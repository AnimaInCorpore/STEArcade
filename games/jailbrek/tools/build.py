"""Build JAILBREK.PRG for a 4 MB Atari STE (--sim: the Musashi build for the tests).

    python tools/build.py [--sim] [--debug] [--assets] [--frames N] [-D NAME=VALUE ...] [--tag T]

The sound is not built yet (NOSOUND=1 always).
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
    ap.add_argument('--tag', help='another run/<tag> folder (default jailbrek / jailbrek_sim)')
    args = ap.parse_args()
    build = build_dir('jailbrek')
    if not (EXTRACTED / 'jailbrek' / gen.ROM_FILES[0]).exists():
        subprocess.run([sys.executable, str(Path(__file__).resolve().parent / 'prepare.py')], check=True)
    (build / 'jailbrek.img').write_bytes(gen.image())
    try:
        import assets
    except ImportError:
        assets = None
    if assets and (args.assets or pn.changed('jailbrek') or not (build / 'jb_assets.s').exists()):
        assets.build()
        pn.stamp('jailbrek')
    report = gen.generate()
    (build / 'translation.json').write_text(json.dumps({k: v for k, v in report.items() if k != 'missing'},
                                                       indent=1, default=str) + '\n')
    print('main: instructions %d, unsupported %d' % (report['instructions'], len(report['unsupported'])), report['stats'])
    defs = list(args.defines)
    tag = args.tag or ('jailbrek_sim' if args.sim else 'jailbrek')
    out = ROOT / 'run' / tag / 'JAILBREK.PRG'
    out.parent.mkdir(parents=True, exist_ok=True)
    defs += (['SIM=1'] if args.sim else []) + (['DEBUG=1'] if args.debug else [])
    if args.frames:
        defs.append('FRAMES=%d' % args.frames)
    assemble_link('jailbrek', 'jailbrek.s', tag, str(out), defs)
    print('built %s, %d bytes' % (out, out.stat().st_size))


if __name__ == '__main__':
    main()
