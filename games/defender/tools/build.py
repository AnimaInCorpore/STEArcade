"""Build DEFENDER.PRG for the Atari STE (--sim: the Musashi build for tools/logic_test.py).

    python tools/build.py [--sim] [--frames N] [-D NAME=VALUE ...] [--tag T] [--play SEED]
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


def write_tape(path, seed, frames):
    """ref/cover.py's inputs of a seed, 4 bytes an arcade frame: IN0, IN1, IN2, flags (bit 0: lives and smart bombs
    held at 5, as cover.cheats does for seeds 5-11; bit 1: in play)"""
    import random
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ref'))
    import cover
    rnd, state, out = random.Random(seed), {'two': seed == 7}, bytearray()
    for f in range(frames):
        i0, i1, i2 = cover.inputs(seed, f, rnd, state)
        play = state.get('phase') == 'play'
        out += bytes((i0, i1, i2, (1 if play and 5 <= seed <= 11 else 0) | (2 if play else 0)))
    path.write_bytes(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sim', action='store_true')
    ap.add_argument('-D', dest='defines', action='append', default=[])
    ap.add_argument('--frames', type=int, default=0, help='quit after this many VBLs')
    ap.add_argument('--play', type=int, metavar='SEED', help='replay the inputs of ref/cover.py seed SEED (-D PLAY=1)')
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
    if args.play is not None:
        write_tape(build / 'df_tape.bin', args.play, 20000)
        args.defines.append('PLAY=1')
    defs = list(args.defines) + (['SIM=1'] if args.sim else []) + (['FRAMES=%d' % args.frames] if args.frames else [])
    assemble_link('defender', 'defender.s', tag, str(out), defs)
    print('built %s, %d bytes' % (out, out.stat().st_size))


if __name__ == '__main__':
    main()
