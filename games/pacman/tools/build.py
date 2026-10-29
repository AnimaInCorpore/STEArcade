"""Build PACMAN.PRG for a 4 MB Atari STE (--sim: the Musashi build for the tests).

    python tools/build.py [--sim] [--debug] [--assets] [--frames N] [--out FILE] [-D NAME=VALUE ...] [--tag T]

No sound yet.  The graphics (tools/assets.py) are made when missing or with --assets.
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
    ap.add_argument('--debug', action='store_true', help='COUNTERS.BIN at the quit (VBLs, frames, pictures)')
    ap.add_argument('--assets', action='store_true', help='make the graphics and colours again')
    ap.add_argument('--out', help='the program file (default run/<tag>/PACMAN.PRG)')
    ap.add_argument('-D', dest='defines', action='append', default=[])
    ap.add_argument('--tag', help='another run/<tag> folder (default pacman / pacman_sim)')
    args = ap.parse_args()
    build = build_dir('pacman')
    if not (EXTRACTED / 'pacman' / 'pacman.6e').exists():
        subprocess.run([sys.executable, str(Path(__file__).resolve().parent / 'prepare.py')], check=True)
    (build / 'pacman.rom').write_bytes(gen.image()[:0x4000])
    import assets
    if args.assets or not (build / 'pm_assets.s').exists():
        assets.build()
    text, report, _ = gen.generate()
    (build / 'code_main.s').write_text(text)
    (build / 'translation.json').write_text(json.dumps(report, indent=1) + '\n')
    print('main:', {k: v for k, v in report.items() if k not in ('unsupported', 'tables', 'io')},
          len(report['unsupported']), 'unsupported')
    defs = list(args.defines) + (['SIM=1'] if args.sim else []) + (['DEBUG=1'] if args.debug else [])
    if args.frames:
        defs.append('FRAMES=%d' % args.frames)
    tag = args.tag or ('pacman_sim' if args.sim else 'pacman')
    out = Path(args.out) if args.out else ROOT / 'run' / tag / 'PACMAN.PRG'
    out.parent.mkdir(parents=True, exist_ok=True)
    assemble_link('pacman', 'pacman.s', tag, str(out), defs)
    print('built %s, %d bytes' % (out, out.stat().st_size))


if __name__ == '__main__':
    main()
