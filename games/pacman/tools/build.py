"""Build PACMAN.PRG for a 4 MB Atari STE (--sim: the Musashi build for the tests).

    python tools/build.py [--sim] [--frames N] [-D NAME=VALUE ...] [--tag T]

No picture and no sound yet (src/render.s is a stub): the build runs the game logic.
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
    ap.add_argument('--frames', type=int, default=0)
    ap.add_argument('-D', dest='defines', action='append', default=[])
    ap.add_argument('--tag', help='another run/<tag> folder (default pacman / pacman_sim)')
    args = ap.parse_args()
    build = build_dir('pacman')
    if not (EXTRACTED / 'pacman' / 'pacman.6e').exists():
        subprocess.run([sys.executable, str(Path(__file__).resolve().parent / 'prepare.py')], check=True)
    (build / 'pacman.rom').write_bytes(gen.image()[:0x4000])
    text, report, _ = gen.generate()
    (build / 'code_main.s').write_text(text)
    (build / 'translation.json').write_text(json.dumps(report, indent=1) + '\n')
    print('main:', {k: v for k, v in report.items() if k not in ('unsupported', 'tables', 'io')},
          len(report['unsupported']), 'unsupported')
    defs = list(args.defines) + (['SIM=1'] if args.sim else [])
    if args.frames:
        defs.append('FRAMES=%d' % args.frames)
    tag = args.tag or ('pacman_sim' if args.sim else 'pacman')
    out = ROOT / 'run' / tag / 'PACMAN.PRG'
    out.parent.mkdir(parents=True, exist_ok=True)
    assemble_link('pacman', 'pacman.s', tag, str(out), defs)
    print('built %s, %d bytes' % (out, out.stat().st_size))


if __name__ == '__main__':
    main()
