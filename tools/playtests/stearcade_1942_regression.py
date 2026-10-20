"""Replay retained assisted inputs against a fixed translation, then continue.

Uses the retained instrumented source and relocates TEXT-relative RAM writes.
Unlike reproducibility replay, records both program hashes and permits a fix.
"""
import gzip
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import stearcade_replay_support as play


def symbols(path):
    return {name: int(addr, 16) for addr, name in
            re.findall(r'^\s*0x([0-9a-f]+) (\w+):', path.read_text(), re.M)}


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source', type=Path)
    ap.add_argument('out', type=Path)
    ap.add_argument('--continue-ticks', type=int, default=1200)
    args = ap.parse_args()
    source, out = args.source.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    work = out / 'program'; work.mkdir()
    for f in (source / 'program').glob('*.s'):
        shutil.copy2(f, work / f.name)
    with (out / 'build.log').open('w') as log:
        for cmd in ([play.VASM, '-Fvobj', '-quiet', '-nowarn=2047',
                     '-I', str(play.STE/'build/1942'), '-I', str(play.RT_INCLUDE),
                     '-o', str(work/'game.o'), '1942.s'],
                    [play.VLINK, '-b', 'ataritos', '-s', '-o', str(work/'GAME.PRG'),
                     '-M'+str(work/'game.map'), str(work/'game.o')]):
            subprocess.run(cmd, cwd=work, stdout=log, stderr=log, check=True)
    old = symbols(source/'program/game.map'); sym = symbols(work/'game.map')
    manifest = json.loads((source/'manifest.json').read_text())
    assert play.sha(source/'program/GAME.PRG') == manifest['program_sha256']
    assert play.sha(play.HATARI) == manifest['hatari_sha256']
    assert play.sha(play.TOS) == manifest['tos_sha256']
    assert 'Z70F2' in sym
    delta = sym['g_block'] - old['g_block']
    def relocate(command):
        match = re.fullmatch(r"w 'TEXT\+\$([0-9a-f]+)' (\$[0-9a-f]+)", command)
        if not match:
            raise ValueError('Unexpected retained command: '+command)
        address = int(match[1],16)
        assert old['g_block']+0x6000 <= address < old['g_block']+0x7000
        return f"w 'TEXT+${address+delta:x}' {match[2]}"
    with gzip.open(source/'states.jsonl.gz','rt') as f:
        expected = {row['tick']: bytes.fromhex(row['ram']) for row in map(json.loads,f)}
    report = dict(source=str(source), original_program_sha256=manifest['program_sha256'],
                  fixed_program_sha256=play.sha(work/'GAME.PRG'), ram_relocation=delta,
                  checked=0, ticks=0, continuation_ticks=0, mismatch=None, failure=None)
    (out/'manifest.json').write_text(json.dumps(report,indent=2))
    h = play.Live(out/'hatari', work, sym, '1942')
    try:
        h.step()
        with gzip.open(source/'timeline.jsonl.gz','rt') as f:
            for tick, system, player, extra in map(json.loads,f):
                commands = [relocate(c) for c in extra if not c.startswith(('screenshot ','savebin '))]
                capture = h.step([f"w 'TEXT+${sym['dream_system']:x}' ${system:x}",
                                  f"w 'TEXT+${sym['dream_player']:x}' ${player:x}", *commands])
                report['ticks'] = tick+1
                assert capture[1] == bytes([system,player])
                if tick+1 in expected:
                    assert capture[0] == expected[tick+1], f'RAM mismatch at {tick+1}'
                    report['checked'] += 1
                if (tick+1)%6000 == 0:
                    print('replayed',tick+1,'checkpoints',report['checked'],flush=True)
        report['retained_timeline_completed'] = True
        for i in range(args.continue_ticks):
            capture = h.step()
            assert capture[1] == bytes([system,player])
            report['continuation_ticks'] = i+1
        report['final_stage_byte'] = capture[0][0x103]
    except Exception as exc:
        report['failure'] = repr(exc)
    finally:
        h.close()
    report['crash'] = (work/'CRASH.TXT').read_text() if (work/'CRASH.TXT').exists() else None
    report['passed'] = (report['failure'] is None and report['crash'] is None
                        and report['checked'] == len(expected)
                        and report['continuation_ticks'] == args.continue_ticks)
    (out/'regression.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report),flush=True)
    return not report['passed']


if __name__ == '__main__':
    raise SystemExit(main())
