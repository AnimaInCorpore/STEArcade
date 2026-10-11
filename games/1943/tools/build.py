"""Build the 1943 STE runtime (--sim for the Musashi checks)."""
from pathlib import Path
import argparse
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
import gen
from paths import build_dir, ROOT
from toolchain import assemble_link


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sim', action='store_true')
    ap.add_argument('--debug', action='store_true')
    ap.add_argument('--frames', type=int, default=0)
    ap.add_argument('--sound', action='store_true', help='record the sound driver again (tools/sound.py, ~15 min)')
    ap.add_argument('-D', dest='defines', action='append', default=[])
    args = ap.parse_args()
    build = build_dir('1943')
    if not (build / 'maincpu.rom').exists():
        sys.exit('error: no prepared ROMs in %s: python port.py prepare 1943' % build)
    if True:                                    # (from the recordings, build/1943/fx.pkl and music.pkl; before assets,
        import sound                            # which puts 1942's tools, and their sound.py, first in the path)
        import capsnd
        d = sound.driver()
        if args.sound:
            capsnd.all_effects(d, again=True)
            capsnd.all_tunes(d, again=True)
        print('cs_data.s: %d bytes' % capsnd.emit(d, build / 'cs_data.s'))
    try:
        import assets
        assets.build()
    except ImportError:
        pass
    maincpu = (build / 'maincpu.rom').read_bytes()
    (build / 'fixed.rom').write_bytes(maincpu[:0x8000])
    (build / 'banks.rom').write_bytes(maincpu[0x10000:0x30000])
    import mcux
    mtext, n = mcux.generate()
    (build / 'mcu_code.s').write_text(mtext)
    text, report, _ = gen.generate()
    (build / 'code_1943.s').write_text(text)
    print('translation:', report)
    if report['unsupported']:
        raise RuntimeError('Unsupported translated instructions')
    tag = '1943_sim' if args.sim else '1943'
    out = ROOT / 'run' / tag / '1943.PRG'
    out.parent.mkdir(parents=True, exist_ok=True)
    defs = list(args.defines)
    if args.sim:
        defs.append('SIM=1')
    if args.debug:
        defs.append('DEBUG=1')
    if args.frames:
        defs.append(f'FRAMES={args.frames}')
    assemble_link('1943', '1943.s', tag, str(out), defs)
    print(f'built {out}, {out.stat().st_size} bytes')


if __name__ == '__main__':
    main()
