"""Build YIEAR.PRG for a 4 MB Atari STE (--sim: the Musashi build for the tests).

    python tools/build.py [--sim] [--debug] [--assets] [--frames N] [-D NAME=VALUE ...] [--tag T]

"""
from pathlib import Path
import argparse
import json
import subprocess
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
import gen
from paths import build_dir, ROOT, EXTRACTED
from toolchain import assemble_link


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sim', action='store_true')
    ap.add_argument('--debug', action='store_true')
    ap.add_argument('--assets', action='store_true', help='make the graphics and colours again')
    ap.add_argument('--frames', type=int, default=0)
    ap.add_argument('-D', dest='defines', action='append', default=[])
    ap.add_argument('--tag', help='another run/<tag> folder (default yiear / yiear_sim)')
    args = ap.parse_args()
    build = build_dir('yiear')
    if not (EXTRACTED / 'yiear' / gen.ROM_FILES[0]).exists():
        subprocess.run([sys.executable, str(Path(__file__).resolve().parent / 'prepare.py')], check=True)
    (build / 'yiear.img').write_bytes(gen.image()[0])
    try:
        import assets
    except ImportError:
        assets = None
    if assets and (args.assets or not (build / 'ya_assets.s').exists()):
        assets.build()
    report = gen.generate()
    (build / 'translation.json').write_text(json.dumps({k: v for k, v in report.items() if k != 'missing'},
                                                       indent=1, default=str) + '\n')
    print('main: instructions %d, unsupported %d' % (report['instructions'], len(report['unsupported'])), report['stats'])
    defs = list(args.defines)
    tag = args.tag or ('yiear_sim' if args.sim else 'yiear')
    out = ROOT / 'run' / tag / 'YIEAR.PRG'
    out.parent.mkdir(parents=True, exist_ok=True)
    defs += (['SIM=1'] if args.sim else []) + (['DEBUG=1'] if args.debug else [])
    if args.frames:
        defs.append('FRAMES=%d' % args.frames)
    assemble_link('yiear', 'yiear.s', tag, str(out), defs)
    print('built %s, %d bytes' % (out, out.stat().st_size))


if __name__ == '__main__':
    main()
