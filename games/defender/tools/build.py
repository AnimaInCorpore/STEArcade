"""Build DEFENDER.PRG for the Atari STE (--sim: the Musashi build for tools/logic_test.py).

    python tools/build.py [--sim] [--frames N] [-D NAME=VALUE ...] [--tag T]
"""
from pathlib import Path
import argparse
import json
import subprocess
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
import gen
from machine import factory_cmos
from paths import build_dir, ROOT, EXTRACTED
from toolchain import assemble_link


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sim', action='store_true')
    ap.add_argument('-D', dest='defines', action='append', default=[])
    ap.add_argument('--frames', type=int, default=0, help='quit after this many VBLs')
    ap.add_argument('--tag', help='another run/<tag> folder (default defender / defender_sim)')
    args = ap.parse_args()
    build = build_dir('defender')
    if not (EXTRACTED / 'defender' / gen.PROGRAM[0][0]).exists():
        subprocess.run([sys.executable, str(Path(__file__).resolve().parent / 'prepare.py')], check=True)
    mem, banks = gen.rom_image()
    (build / 'defender.img').write_bytes(bytes(mem))
    (build / 'banks.rom').write_bytes(banks)
    (build / 'cmos.bin').write_bytes(factory_cmos())
    import assets
    assets.build()
    report = gen.generate()
    (build / 'translation.json').write_text(json.dumps({k: v for k, v in report.items() if k != 'missing'},
                                                       indent=1, default=str) + '\n')
    print('main: instructions %d, unsupported %d' % (report['instructions'], len(report['unsupported'])), report['stats'])
    tag = args.tag or ('defender_sim' if args.sim else 'defender')
    out = ROOT / 'run' / tag / 'DEFENDER.PRG'
    out.parent.mkdir(parents=True, exist_ok=True)
    defs = list(args.defines) + (['SIM=1'] if args.sim else []) + (['FRAMES=%d' % args.frames] if args.frames else [])
    assemble_link('defender', 'defender.s', tag, str(out), defs)
    print('built %s, %d bytes' % (out, out.stat().st_size))


if __name__ == '__main__':
    main()
