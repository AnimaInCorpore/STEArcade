"""Default palette A/B in the pinned cycle-exact 14 MB Hatari.

Baseline assets/source are retained privately in palette_default_audit/baseline.
Each variant gets private snapshots, inputs, source and executable; production
files and a user's running emulator are untouched.
"""
import gzip
import json
import os
import pickle
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

import play_inputs
import toolchain

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'build/rtype/palette_default_audit'
PINNED = Path.home() / 'Work/F030Arcade/third_party'


def snapshot(checkpoint, target):
    state = pickle.loads(gzip.decompress(checkpoint.read_bytes()))
    ctx = state['symbols']['ctx_main']
    words = [int.from_bytes(ctx[i:i + 2], 'big') for i in range(0, 8, 2)] + list(ctx[8:12])
    words += [int.from_bytes(ctx[i:i + 4], 'big') & 65535 for i in range(16, 44, 4)]
    words += [(int.from_bytes(ctx[56:60], 'big') - int.from_bytes(ctx[52:56], 'big')) & 65535,
              int.from_bytes(ctx[60:62], 'big')]
    data = b''.join(state['memory'][str(base)] for base in
                    (0x40000, 0xC0000, 0xC8000, 0xCC000, 0xD0000, 0xD8000))
    data += state['symbols']['m72_spritebuf'] + struct.pack(f'>{len(words)}H', *words)
    data += state['symbols']['m72_scroll'] + state['symbols']['m72_raster'] + state['symbols']['m72_port02']
    assert len(data) == 57390
    target.write_bytes(data)


def run(seed, start, variant, frames=600):
    work = OUT / f'hatari_{seed}_{start}_{variant}'
    assets, source = work / 'assets', work / 'src'
    assets.mkdir(parents=True, exist_ok=True); source.mkdir(exist_ok=True)
    for p in (ROOT / 'build/rtype').iterdir():
        if p.is_file() and not (assets / p.name).exists():
            (assets / p.name).symlink_to(p)
    for p in (ROOT / 'games/rtype/src').glob('*.s'):
        shutil.copy2(p, source / p.name)
    if variant == 'base':
        shutil.copy2(OUT / 'baseline/stage.s', source / 'stage.s')
        for name in ('stage_scenes.bin', 'stage_sprites.s', 'stage_sstream.bin', 'stage_precol.bin'):
            (assets / name).unlink(missing_ok=True)
            shutil.copy2(OUT / 'baseline' / name, assets / name)
    for name in ('snapshot.bin', 'play_inputs.bin'):
        (assets / name).unlink(missing_ok=True)
    snapshot(ROOT / f'build/rtype/native_structure_audit/seed{seed}_frame{start}.pkl.gz', assets / 'snapshot.bin')
    play_inputs.build_dir = lambda game: assets
    sys.argv = ['play_inputs.py', '--seed', str(seed), '--start', str(start), '--frames', str(start + frames)]
    play_inputs.main()
    toolchain.build_dir = lambda game: assets
    toolchain.src_dir = lambda game: source
    defines = ['STAGE=1', 'DEBUG=1', 'PLAYBACK=1'] + (['INVULN=1'] if seed >= 8 else [])
    executable = work / 'RTYPE.PRG'
    toolchain.assemble_link('rtype', 'rtype.s', 'palette_hw', str(executable), defines)
    for name in ('COUNTERS.BIN', 'BORDERS.BIN', 'CRASH.TXT', 'cmd.fifo'):
        (work / name).unlink(missing_ok=True)
    command = [str(PINNED / 'hatari/build/src/hatari'), '--machine', 'ste', '--memsize', '14',
               '--tos', str(PINNED / 'tos/tos206de.img'), '--fast-boot', 'true', '--cpu-exact', 'true',
               '--compatible', 'true', '--sound', 'off', '--fast-forward', 'true', '--confirm-quit', 'off',
               '--statusbar', 'false', '--cmd-fifo', 'cmd.fifo', '--log-file', 'hatari.log', 'RTYPE.PRG']
    with (work / 'hatari.out').open('w') as log:
        proc = subprocess.Popen(command, cwd=work, stdout=log, stderr=subprocess.STDOUT,
                                env=dict(os.environ, SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy'))
        try:
            deadline = time.monotonic() + 300
            while proc.poll() is None and not (work / 'COUNTERS.BIN').exists() and not (work / 'CRASH.TXT').exists():
                if time.monotonic() > deadline:
                    raise RuntimeError('Hatari timeout')
                time.sleep(.2)
        finally:
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=15)
    assert not (work / 'CRASH.TXT').exists(), (work / 'CRASH.TXT').read_text()
    vbl, logic, pictures, dropped, skipped, late = struct.unpack('>6I', (work / 'COUNTERS.BIN').read_bytes()[:24])
    borders = struct.unpack('>5H', (work / 'BORDERS.BIN').read_bytes()[:10])
    assert logic == frames + 1 and borders[1:] == (0, 0, 0, 0), (logic, borders)
    report = dict(vbl=vbl, logic=logic, pictures=pictures, dropped=dropped, skipped=skipped, late=late,
                  borders=list(borders), logic_per_s=logic * 50 / vbl, pictures_per_s=pictures * 50 / vbl)
    (work / 'snapshot.bin.gz').write_bytes(gzip.compress((assets / 'snapshot.bin').read_bytes(), mtime=0))
    shutil.copy2(assets / 'play_inputs.bin', work / 'play_inputs.bin')
    executable.unlink()
    shutil.rmtree(assets)
    shutil.rmtree(source)
    return report


def main():
    # A legacy renderer must never be timed with packed-pair tables.
    data = (OUT / 'baseline/stage_scenes.bin').read_bytes()
    count = int.from_bytes(data[:2], 'big')
    size = (len(data) - 2) // count
    for k in range(count):
        assert max(data[2 + k * size + 80:2 + k * size + 80 + 3 * 4096]) < 16, 'Baseline is not a flat palette'
    report = {}
    for seed, start in [(1, 12600), (10, 65000)]:
        for variant in ('base', 'default'):
            key = f'{seed}_{start}_{variant}'
            report[key] = run(seed, start, variant)
            print(key, report[key], flush=True)
            (OUT / 'hatari_results.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
