"""Build GUNSMOKE.PRG for an unexpanded 4 MB Atari STE (--sim: the Musashi build for the tests)."""
from pathlib import Path
import argparse
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
import gen
from prepare import prepare
from paths import build_dir, ROOT
from toolchain import assemble_link


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sim', action='store_true')
    ap.add_argument('--debug', action='store_true')
    ap.add_argument('--assets', action='store_true', help='regenerate the graphics and palette assets')
    ap.add_argument('--frames', type=int, default=0)
    ap.add_argument('-D', dest='defines', action='append', default=[])
    args = ap.parse_args()
    prepare()
    build = build_dir('gunsmoke')
    try:
        import assets
    except ImportError:
        assets = None
    if assets and (args.assets or not (build / 'spr_code.s').exists()):
        assets.build()
    maincpu = (build / 'maincpu.rom').read_bytes()
    (build / 'fixed.rom').write_bytes(maincpu[:0x8000])
    (build / 'banks.rom').write_bytes(maincpu[0x8000:0x18000])
    text, report, _ = gen.generate()
    (build / 'code_gunsmoke.s').write_text(text)
    print('translation:', {k: v for k, v in report.items() if k != 'unsupported'}, len(report['unsupported']), 'unsupported')
    tag = 'gunsmoke_sim' if args.sim else 'gunsmoke'
    out = ROOT / 'run' / tag / 'GUNSMOKE.PRG'
    out.parent.mkdir(parents=True, exist_ok=True)
    defs = list(args.defines) + (['SIM=1'] if args.sim else []) + (['DEBUG=1'] if args.debug else [])
    if args.frames:
        defs.append(f'FRAMES={args.frames}')
    assemble_link('gunsmoke', 'gunsmoke.s', tag, str(out), defs)
    print(f'built {out}, {out.stat().st_size} bytes')


if __name__ == '__main__':
    main()
