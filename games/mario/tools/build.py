"""Build MARIO.PRG for a 4 MB Atari STE (--sim: the Musashi build for the tests).

    python tools/build.py [--sim] [--debug] [--assets] [--frames N] [-D NAME=VALUE ...] [--tag T]

-D NOSOUND=1: without the sound driver (there is none yet: the build always defines it).
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
    ap.add_argument('--tag', help='another run/<tag> folder (default mario / mario_sim)')
    args = ap.parse_args()
    build = build_dir('mario')
    if not (EXTRACTED / 'mario' / 'cpu.rom').exists():
        subprocess.run([sys.executable, str(Path(__file__).resolve().parent / 'prepare.py')], check=True)
    img = gen.load_rom()
    (build / 'mario.rom').write_bytes(img[:0x6000] + bytes(0x2000))        # $0000-$7FFF: the ROM, then RAM
    (build / 'mario_hi.rom').write_bytes(img[0xF000:])                      # $F000-$FFFF
    import assets
    if args.assets or not (build / 'tm_assets.s').exists():
        assets.build()
    text, report, _ = gen.generate()
    (build / 'mario_code.s').write_text(text)
    (build / 'translation.json').write_text(json.dumps(report, indent=1) + '\n')
    print('main:', {k: v for k, v in report.items() if k not in ('unsupported', 'tables', 'io')},
          len(report['unsupported']), 'unsupported')
    defs = list(args.defines)
    if not any(d.startswith('NOSOUND') for d in defs):
        defs.append('NOSOUND=1')
    tag = args.tag or ('mario_sim' if args.sim else 'mario')
    out = ROOT / 'run' / tag / 'MARIO.PRG'
    out.parent.mkdir(parents=True, exist_ok=True)
    defs += (['SIM=1'] if args.sim else []) + (['DEBUG=1'] if args.debug else [])
    if args.frames:
        defs.append('FRAMES=%d' % args.frames)
    assemble_link('mario', 'mario.s', tag, str(out), defs)
    print('built %s, %d bytes' % (out, out.stat().st_size))


if __name__ == '__main__':
    main()
