"""Audit native Hatari playback against MAME and the port reference schedule.

    venv/bin/python games/kungfum/tools/ppo_hatari.py build/kungfum/ppo/ppo_1.bin

Builds in its own output directory; never rebuilds/replaces the normal program.
MAME states must be the adjacent .states.jsonl produced by play_ppo.py record.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[2]/'engine')]
from paths import ROOT, VASM, VLINK, RT_INCLUDE, build_dir, src_dir
import playbot
from play_search import Game

SIZE = 8 + 0x2000 + 0x100


def compare(want, got, frame):
    changes = []
    for key, base in [('ram', 0xd000), ('sprites', 0xc000)]:
        a, b = want[key], got[key]
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        if diff:
            changes.append(dict(region=key, count=len(diff), first=[dict(address=f'{base+i:04x}',
                                expected=a[i], actual=b[i]) for i in diff[:12]]))
    if want['scroll'] != got['scroll']:
        changes.append(dict(region='scroll', expected=want['scroll'], actual=got['scroll']))
    return dict(frame=frame, changes=changes) if changes else None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('recording', type=Path)
    ap.add_argument('--out', type=Path)
    ap.add_argument('--timeout', type=int, default=600)
    args = ap.parse_args()
    recording = args.recording.resolve()
    ticks = playbot.load(recording)
    if len(ticks) <= 900 or len(ticks) % 12 or len(ticks) > 65520:
        ap.error('recording must have >900 frames, divisible by 12, and <=65520')
    sidecar = json.loads(recording.with_suffix('.json').read_text())
    replay_hash = hashlib.sha256(recording.read_bytes()).hexdigest()
    if sidecar['replay_sha256'] != replay_hash or sidecar['frames'] != len(ticks):
        ap.error('recording does not match its MAME metadata')
    statefile = recording.with_suffix('.states.jsonl')
    state_bytes = statefile.read_bytes() if statefile.exists() else gzip.decompress(statefile.with_suffix('.jsonl.gz').read_bytes())
    if 'states_sha256' in sidecar and hashlib.sha256(state_bytes).hexdigest() != sidecar['states_sha256']:
        ap.error('MAME checkpoint file does not match its metadata')
    out = (args.out or recording.parent / (recording.stem+'_hatari')).resolve()
    out.mkdir(parents=True, exist_ok=True)
    # An interrupted/repeated audit must not accept stale success markers.
    for name in ('AUDIT.OK', 'AUDIT.BIN', 'CRASH.TXT'):
        (out/name).unlink(missing_ok=True)
    (out/'play_inputs.bin').write_bytes(recording.read_bytes())
    prg, obj, mapfile = [out/name for name in ('KUNGFUM.PRG','replay.o','replay.map')]
    subprocess.run([VASM, '-Fvobj', '-quiet', '-nowarn=2047', '-DPLAYBACK=1', '-DREPLAY_AUDIT=1',
                    f'-DREPLAY_AUDIT_FRAMES={len(ticks)}', '-I', str(out), '-I', str(build_dir('kungfum')),
                    '-I', str(RT_INCLUDE), '-o', str(obj), 'kungfum.s'], cwd=src_dir('kungfum'), check=True)
    subprocess.run([VLINK, '-b', 'ataritos', '-s', '-o', str(prg), '-M'+str(mapfile), str(obj)], check=True)
    hatari = os.environ.get('HATARI', '/Users/saschaspringer/Work/F030Arcade/third_party/hatari/build/src/hatari')
    tos = os.environ.get('TOS', '/Users/saschaspringer/Work/F030Arcade/third_party/tos/tos206de.img')
    command = [hatari, '--machine','ste','--memsize','4','--tos',tos,'--fast-boot','true',
               '--cpu-exact','true','--compatible','true','--sound','off','--confirm-quit','off',
               '--statusbar','false','--fast-forward','true','--log-file',str(out/'hatari.log'), str(prg)]
    start = time.monotonic()
    with (out/'console.log').open('w') as log:
        process = subprocess.Popen(command, cwd=out, stdout=log, stderr=log)
        try:
            while not (out/'AUDIT.OK').exists():
                if (out/'CRASH.TXT').exists():
                    raise RuntimeError('Hatari port crashed: '+(out/'CRASH.TXT').read_text())
                if process.poll() is not None or time.monotonic()-start > args.timeout:
                    raise RuntimeError(f'Hatari stopped/timed out; see {out}/hatari.log')
                time.sleep(.2)
        finally:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
    hatari_seconds = time.monotonic()-start
    data = (out/'AUDIT.BIN').read_bytes()
    expected = list(range(900, len(ticks)+1, 12))
    if len(data) != len(expected)*SIZE:
        raise RuntimeError(f'incomplete audit: {len(data)} bytes, expected {len(expected)*SIZE}')
    samples = {}
    for i, offset in enumerate(range(0,len(data),SIZE)):
        packet = data[offset:offset+SIZE]
        frame, pc, rng, scroll = struct.unpack('>4H',packet[:8])
        if frame != expected[i]: raise RuntimeError('audit frame sequence differs')
        samples[frame] = dict(pc=pc, rng=rng, scroll=scroll, ram=packet[8:8+0x2000], sprites=packet[8+0x2000:])
    mame = [json.loads(line) for line in state_bytes.decode().splitlines()]
    if [s['frame'] for s in mame] != expected:
        raise RuntimeError('MAME checkpoint frames differ from recording/audit')
    first_mame = None
    mame_differences = 0
    for s in mame:
        s['ram'], s['sprites'] = bytes.fromhex(s['ram']), bytes.fromhex(s['sprites'])
        diff = compare(s,samples[s['frame']],s['frame'])
        if diff:
            mame_differences += 1
            if first_mame is None: first_mame = dict(diff, mame_pc=f"{s['pc']:04x}",hatari_hook_pc=f"{samples[s['frame']]['pc']:04x}")
    # Dead stack bytes are deliberately different after translated merged PUSH/POP.
    # Track the exact exclusions used by logic_test.py, rather than masking RAM.
    import re
    merged = {int(h[1],16) for line in (build_dir('kungfum')/'code_kungfum.s').read_text().splitlines()
              if (h := re.match(r'^Z([0-9A-F]{4}):\t\t; push .* \(merged\)',line))}
    game = Game(); machine = game.machine(); dead=set(); site=[0]
    step, write = machine.cpu.step, machine.cpu.wr8
    def traced():
        site[0]=machine.cpu.pc
        return step()
    def stored(a,v):
        (dead.add if site[0] in merged else dead.discard)(a)
        return write(a,v)
    machine.cpu.step, machine.cpu.wr8 = traced, stored
    first_reference = None
    reference_differences = 0
    for tick,(system,p1) in enumerate(ticks):
        game.tick(machine,tick,system,p1)
        frame=tick+1
        if frame not in samples: continue
        want=dict(ram=bytes(machine.mem[0xd000:0xf000]),sprites=bytes(machine.sprite_ram),scroll=machine.scroll)
        got=dict(samples[frame])
        ram=bytearray(got['ram'])
        for a in dead:
            if 0xd000 <= a < 0xf000: ram[a-0xd000]=want['ram'][a-0xd000]
        got['ram']=bytes(ram)
        diff=compare(want,got,frame)
        if machine.rnd_state != got['rng']:
            diff=diff or dict(frame=frame,changes=[])
            diff['changes'].append(dict(region='rng',expected=machine.rnd_state,actual=got['rng']))
        if diff:
            reference_differences += 1
            if first_reference is None: first_reference=diff
    report=dict(recording=str(recording.relative_to(ROOT)) if recording.is_relative_to(ROOT) else str(recording),
                recording_sha256=hashlib.sha256(recording.read_bytes()).hexdigest(),
                frames=len(ticks), checkpoint_stride=12, checkpoints=len(samples),
                hatari_seconds=hatari_seconds, comparison_seconds=time.monotonic()-start-hatari_seconds,
                native_mame=dict(differing_checkpoints=mame_differences,first_difference=first_mame,
                                 interpretation='Native board timing and refresh-register RNG differ. MAME checkpoints also include the next-frame lives poke; Hatari checkpoints precede it. These differences alone do not establish a port bug.'),
                port_reference=dict(differing_checkpoints=reference_differences,first_difference=first_reference),
                hatari_sha256=hashlib.sha256(Path(hatari).read_bytes()).hexdigest(),
                tos_sha256=hashlib.sha256(Path(tos).read_bytes()).hexdigest(),
                program_sha256=hashlib.sha256(prg.read_bytes()).hexdigest())
    (out/'divergences.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return int(reference_differences != 0)


if __name__=='__main__':
    sys.exit(main())
