"""Build GYRUSS.PRG for a 4 MB Atari STE (--sim: the Musashi build for the tests).

    python tools/build.py [--sim] [--debug] [--assets] [--frames N] [-D NAME=VALUE ...]
"""
from pathlib import Path
import argparse
import json
import subprocess
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
import gen
import gen_sub
from machine import load
from paths import build_dir, ROOT, EXTRACTED
from toolchain import assemble_link


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sim', action='store_true')
    ap.add_argument('--debug', action='store_true')
    ap.add_argument('--assets', action='store_true', help='make the graphics and colours again')
    ap.add_argument('--frames', type=int, default=0)
    ap.add_argument('-D', dest='defines', action='append', default=[])
    ap.add_argument('--tag', help='another run/<tag> folder (default gyruss / gyruss_sim)')
    args = ap.parse_args()
    build = build_dir('gyruss')
    if not (EXTRACTED / 'gyruss' / 'gyrussk.1').exists():
        subprocess.run([sys.executable, str(Path(__file__).resolve().parent / 'prepare.py')], check=True)
    (build / 'gyruss.rom').write_bytes(gen.image()[:0x8000])
    (build / 'sub.rom').write_bytes(load('gyrussk.9'))
    import assets
    if args.assets or not (build / 'gy_assets.s').exists():
        assets.build()
    text, report, _ = gen.generate()
    (build / 'code_main.s').write_text(text)
    (build / 'translation.json').write_text(json.dumps(report, indent=1) + '\n')
    print('main:', {k: v for k, v in report.items() if k not in ('unsupported', 'tables', 'io')},
          len(report['unsupported']), 'unsupported')
    srep = gen_sub.generate()
    print('sub: instructions', srep['instructions'], 'unsupported', len(srep['unsupported']), 'missing',
          len(srep['missing']))
    defs = list(args.defines)
    if not any(d.startswith('NOSOUND') for d in defs):
        import sndgen
        (build / 'snd.rom').write_bytes(sndgen.image()[:0x4000])
        stext, srep2 = sndgen.generate()
        if args.assets or not (build / 'snd_dac.s').exists():
            subprocess.run([sys.executable, str(Path(__file__).resolve().parent / 'i8039.py'), '--rate', '6258',
                            '--cap', '7'], check=True)
        (build / 'snd_code.s').write_text(stext)
        print('sound: instructions', srep2['instructions'], 'unsupported', len(srep2['unsupported']), 'missing',
              len(srep2['missing']))
    tag = args.tag or ('gyruss_sim' if args.sim else 'gyruss')
    out = ROOT / 'run' / tag / 'GYRUSS.PRG'
    out.parent.mkdir(parents=True, exist_ok=True)
    defs += (['SIM=1'] if args.sim else []) + (['DEBUG=1'] if args.debug else [])
    if args.frames:
        defs.append('FRAMES=%d' % args.frames)
    assemble_link('gyruss', 'gyruss.s', tag, str(out), defs)
    print('built %s, %d bytes' % (out, out.stat().st_size))


if __name__ == '__main__':
    main()
