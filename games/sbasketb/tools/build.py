"""Build SBASKETB.PRG for a 4 MB Atari STE (--sim: the Musashi build for the tests).

    python tools/build.py [--sim] [--debug] [--assets] [--frames N] [-D NAME=VALUE ...] [--tag T]

The sound is not part of the build yet (NOSOUND=1).
"""
from pathlib import Path
import argparse
import json
import subprocess
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
import gen
from paths import build_dir, ROOT, EXTRACTED
import palette_native as pn
from toolchain import assemble_link


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sim', action='store_true')
    ap.add_argument('--debug', action='store_true')
    ap.add_argument('--assets', action='store_true', help='make the graphics and colours again')
    ap.add_argument('--frames', type=int, default=0)
    ap.add_argument('-D', dest='defines', action='append', default=[])
    ap.add_argument('--tag', help='another run/<tag> folder (default sbasketb / sbasketb_sim)')
    args = ap.parse_args()
    build = build_dir('sbasketb')
    if not (EXTRACTED / 'sbasketb' / gen.ROM_FILES[0][0]).exists():
        subprocess.run([sys.executable, str(Path(__file__).resolve().parent / 'prepare.py')], check=True)
    (build / 'sbasketb.img').write_bytes(gen.image())
    try:
        import assets
    except ImportError:
        assets = None
    if assets and (args.assets or pn.changed('sbasketb') or not (build / 'sb_assets.s').exists()):
        assets.build()
        pn.stamp('sbasketb')
    report = gen.generate()
    (build / 'translation.json').write_text(json.dumps({k: v for k, v in report.items() if k != 'missing'},
                                                       indent=1, default=str) + '\n')
    print('main: instructions %d, unsupported %d' % (report['instructions'], len(report['unsupported'])), report['stats'])
    defs = list(args.defines)
    if not any(d.startswith('NOSOUND') for d in defs):
        defs.append('NOSOUND=1')            # (the sound is not translated yet: README, State)
    tag = args.tag or ('sbasketb_sim' if args.sim else 'sbasketb')
    out = ROOT / 'run' / tag / 'SBASKETB.PRG'
    out.parent.mkdir(parents=True, exist_ok=True)
    defs += (['SIM=1'] if args.sim else []) + (['DEBUG=1'] if args.debug else [])
    if args.frames:
        defs.append('FRAMES=%d' % args.frames)
    assemble_link('sbasketb', 'sbasketb.s', tag, str(out), defs)
    print('built %s, %d bytes' % (out, out.stat().st_size))


if __name__ == '__main__':
    main()
