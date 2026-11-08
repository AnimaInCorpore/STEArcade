#!/usr/bin/env python3
"""Compare the complete existing play recording at Mega STE 8/16 MHz.

Run build.py first. This makes a separate, unattended replay executable with
PLAYBACK's existing lives cheat; it does not alter the playable release.
"""
import argparse
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'engine'))
from toolchain import assemble_link


def benchmark(mode, work, hatari, tos):
    work.mkdir(parents=True, exist_ok=True)
    source = (ROOT / 'games/gunsmoke/src/gunsmoke.s').read_text()
    # CPU instructions perform the mode changes. Debugger I/O pokes bypass
    # Hatari's register handlers and must not select the benchmark speed.
    source = source.replace('\tlea\tfixed_rom,a0', f'''
\tmove.b $ffff8e21.w,bench_old
\tmove.b bench_old,d0
\tand.b #$fc,d0
\tor.b #{mode},d0
\tmove.b d0,$ffff8e21.w
\tmove.b $ffff8e21.w,bench_mode
\tlea\tfixed_rom,a0''', 1)
    source = source.replace('quit:\n\tmove\t#$2700,sr',
                            'quit:\n\tmove\t#$2700,sr\n\tbsr bench_save', 1)
    source = source.replace('\tbsr\trestore_hardware',
                            '\tbsr\trestore_hardware\n\tmove.b bench_old,$ffff8e21.w')
    source += '''
\tsection text,code
bench_save:
\tmove.b $ffff8e21.w,bench_mode+1
\tclr.w -(sp)
\tpea bench_filename
\tmove.w #$3c,-(sp)
\ttrap #1
\taddq.l #8,sp
\tmove.w d0,d6
\tpea bench_mode
\tmove.l #2,-(sp)
\tmove.w d6,-(sp)
\tmove.w #$40,-(sp)
\ttrap #1
\tlea 12(sp),sp
\tmove.w d6,-(sp)
\tmove.w #$3e,-(sp)
\ttrap #1
\taddq.l #4,sp
\trts
\tsection data,data
bench_filename: dc.b 'MODE.BIN',0
\teven
\tsection bss,bss
bench_old: ds.b 1
bench_mode: ds.b 2
\teven
'''
    fixture = work / 'fixture.s'
    fixture.write_text(source)
    program = work / 'GUNSMOKE.TOS'
    assemble_link('gunsmoke', str(fixture), f'mste_bench{mode}', str(program),
                  ['DEBUG=1', 'FRAMES=0', 'PLAYBACK=1'])
    for name in ['COUNTERS.BIN', 'CRASH.TXT', 'RATE.BIN', 'MODE.BIN', 'result.json', 'pulses.json']:
        (work / name).unlink(missing_ok=True)
    fifo = work / 'commands.fifo'
    fifo.unlink(missing_ok=True)
    cmd = [str(hatari), '--machine', 'megaste', '--memsize', '4', '--tos', str(tos),
           '--fast-boot', 'true', '--cpu-exact', 'true', '--compatible', 'true',
           '--sound', 'off', '--fast-forward', 'true', '--confirm-quit', 'off',
           '--cmd-fifo', str(fifo), '--trace', 'video_sync,video_border_v',
           '--trace-file', str(work / 'trace.log'), '--log-file', str(work / 'hatari.log'),
           str(program)]
    env = dict(os.environ, SDL_VIDEO_DRIVER='dummy', SDL_AUDIO_DRIVER='dummy')
    with (work / 'host.log').open('w') as log:
        proc = subprocess.Popen(cmd, env=env, stdout=log, stderr=log)
        start = time.monotonic()
        shot = False
        try:
            while time.monotonic() - start < 240:
                if (work / 'CRASH.TXT').exists():
                    raise RuntimeError((work / 'CRASH.TXT').read_text())
                if (work / 'COUNTERS.BIN').exists():
                    break
                if not shot and time.monotonic() - start > 8 and fifo.exists():
                    with fifo.open('w') as f:
                        f.write('hatari-debug screenshot ' + str(work / 'picture.png') + '\n')
                    shot = True
                if proc.poll() is not None:
                    raise RuntimeError('Hatari exited; see ' + str(work))
                time.sleep(.1)
            else:
                raise RuntimeError('timeout: ' + str(work))
        finally:
            proc.terminate()
            proc.wait(timeout=10)

    control = list((work / 'MODE.BIN').read_bytes())
    assert [v & 3 for v in control] == [mode, mode], control
    vbls, pictures, ticks, fallbacks, *late = struct.unpack(
        '>8H', (work / 'COUNTERS.BIN').read_bytes()[:16])
    points = list(struct.iter_unpack('>2H', (work / 'RATE.BIN').read_bytes()))
    # RATE records every 100 VBLs. Rates use nominal 50 Hz, not host wall time.
    rows = [dict(from_tick=a[0], ticks_s=((b[0] - a[0]) & 65535) / 2,
                 pictures_s=((b[1] - a[1]) & 65535) / 2)
            for a, b in zip(points, points[1:]) if a[0] >= 900]
    assert vbls >= 3000 and pictures > 0 and ticks == 9001
    assert late == [0] * 4, late
    result = dict(mode=mode, vbls=vbls, pictures=pictures, logic_frames=ticks,
                  average_logic_fps=ticks / vbls * 50,
                  average_picture_fps=pictures / vbls * 50,
                  border_fallbacks=fallbacks, late=late, play_windows=rows,
                  play_mean_logic_fps=statistics.mean(x['ticks_s'] for x in rows),
                  play_mean_picture_fps=statistics.mean(x['pictures_s'] for x in rows),
                  play_min_picture_fps=min(x['pictures_s'] for x in rows), control=control,
                  hatari_sha256=hashlib.sha256(hatari.read_bytes()).hexdigest(),
                  program_sha256=hashlib.sha256(program.read_bytes()).hexdigest(),
                  recording_sha256=hashlib.sha256((ROOT / 'build/gunsmoke/play_inputs.bin').read_bytes()).hexdigest())
    (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    check_pulses(work, mode)
    print(json.dumps({k: v for k, v in result.items() if k != 'play_windows'}, indent=2))


def check_pulses(work, mode):
    trace = work / 'trace.log'
    raw = []
    for line in trace.read_text().splitlines():
        m = re.match(r'sync=(0x\w+) video_cyc_w=(\d+).*pc=([0-9a-f]+)', line)
        if m:
            raw.append((int(m[1], 16), int(m[2]) / (2 if mode else 1), int(m[3], 16)))
    pulses = [(int(a[1] // 512), a[1] % 512, b[1] % 512)
              for a, b in zip(raw, raw[1:])
              if a[0] == 0 and b[0] == 2 and 25 * 512 < a[1] < 270 * 512][8:]
    top = [p for p in pulses if p[0] < 100]
    bottom = [p for p in pulses if p[0] > 200]
    assert len(top) > 7900 and len(bottom) > 7900, (len(top), len(bottom))
    assert all(line == 33 and 376 <= start < 500 and end < 36 for line, start, end in top)
    assert all(line == 262 and 376 <= start < 500 and end < 36 for line, start, end in bottom)
    data = dict(mode=mode, top_count=len(top), bottom_count=len(bottom),
                top_histogram=[[list(k), v] for k, v in Counter(top).items()],
                bottom_histogram=[[list(k), v] for k, v in Counter(bottom).items()])
    (work / 'pulses.json').write_text(json.dumps(data, indent=2) + '\n')
    with gzip.open(trace.with_suffix('.log.gz'), 'wb') as f:
        f.write(trace.read_bytes())
    trace.unlink()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mode', type=int, choices=[0, 3], required=True,
                    help='0: 8 MHz/cache off; 3: 16 MHz/cache on')
    ap.add_argument('--out', type=Path)
    ap.add_argument('--hatari', type=Path, default=Path(os.environ.get(
        'HATARI', '/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari')))
    ap.add_argument('--tos', type=Path, default=Path(os.environ.get(
        'TOS', '/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img')))
    args = ap.parse_args()
    out = args.out or ROOT / 'build/gunsmoke-megaste' / f'full-mode{args.mode}'
    benchmark(args.mode, out.resolve(), args.hatari.resolve(), args.tos.resolve())


if __name__ == '__main__':
    main()
