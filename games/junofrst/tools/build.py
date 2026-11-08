"""Build JUNOFRST.PRG for a 4 MB Atari STE (--sim: the Musashi build for the tests).

    python tools/build.py [--sim] [--debug] [--assets] [--frames N] [-D NAME=VALUE ...] [--tag T]

-D NOSOUND=1 builds without the sound.
"""
from pathlib import Path
import argparse
import json
import os
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
    ap.add_argument('--nobg', action='store_true', help='leave the background dots out (faster; the picture is not exact)')
    ap.add_argument('--frames', type=int, default=0)
    ap.add_argument('-D', dest='defines', action='append', default=[])
    ap.add_argument('--tag', help='another run/<tag> folder (default junofrst / junofrst_sim)')
    args = ap.parse_args()
    build = build_dir('junofrst')
    if not (EXTRACTED / 'junofrst' / gen.PROGRAM[0][0]).exists():
        subprocess.run([sys.executable, str(Path(__file__).resolve().parent / 'prepare.py')], check=True)
    if args.nobg:
        os.environ["JF_NOBG"] = "1"
    mem, banks = gen.rom_image()
    (build / 'junofrst.img').write_bytes(bytes(mem))
    (build / 'banks.rom').write_bytes(banks)
    import assets
    assets.build()
    report = gen.generate()
    (build / 'translation.json').write_text(json.dumps({k: v for k, v in report.items() if k != 'missing'},
                                                       indent=1, default=str) + '\n')
    print('main: instructions %d, unsupported %d' % (report['instructions'], len(report['unsupported'])), report['stats'])
    defs = list(args.defines)
    if not any(d.startswith('NOSOUND') for d in defs):
        import sndgen
        (build / 'snd.rom').write_bytes(sndgen.image()[:0x1000])
        stext, srep2 = sndgen.generate()
        if args.assets or not (build / 'snd_dac.s').exists():
            subprocess.run([sys.executable, str(Path(__file__).resolve().parent / 'i8039.py'), '--rate', '6258',
                            '--cap', '7'], check=True)
        (build / 'snd_code.s').write_text(stext)
        print('sound: instructions', srep2['instructions'], 'unsupported', len(srep2['unsupported']), 'missing',
              len(srep2['missing']))
    tag = args.tag or ('junofrst_sim' if args.sim else 'junofrst')
    out = ROOT / 'run' / tag / 'JUNOFRST.PRG'
    out.parent.mkdir(parents=True, exist_ok=True)
    defs += (['SIM=1'] if args.sim else []) + (['DEBUG=1'] if args.debug else [])
    if args.frames:
        defs.append('FRAMES=%d' % args.frames)
    assemble_link('junofrst', 'junofrst.s', tag, str(out), defs)
    print('built %s, %d bytes' % (out, out.stat().st_size))


if __name__ == '__main__':
    main()
