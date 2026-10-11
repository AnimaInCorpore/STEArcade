"""Build the Black Tiger STE runtime (--sim for the Musashi checks)."""
from pathlib import Path
import argparse
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
import sound                    # (first: assets may put other games' tools in the path)
import gen
import assets
from prepare import prepare
from paths import build_dir, ROOT
from toolchain import assemble_link


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sim', action='store_true')
    ap.add_argument('--debug', action='store_true')
    ap.add_argument('--frames', type=int, default=0)
    ap.add_argument('--sound', action='store_true', help='record the sound driver again (tools/sound.py, ~6 min)')
    ap.add_argument('-D', dest='defines', action='append', default=[])
    args = ap.parse_args()
    prepare()
    assets.build()
    build = build_dir('blktiger')
    if args.sound:
        sound.all_effects(True)
        sound.all_tunes(True)
    print('bt_sound.s: %d bytes' % sound.emit(build / 'bt_sound.s'))     # (from build/blktiger/fx.pkl, music.pkl)
    maincpu = (build / 'maincpu.rom').read_bytes()
    (build / 'fixed.rom').write_bytes(maincpu[:0x8000])
    (build / 'banks.rom').write_bytes(maincpu[0x10000:])
    text, report, _ = gen.generate()
    (build / 'code_blktiger.s').write_text(text)
    print('translation:', report)
    if report['unsupported']:
        raise RuntimeError('Unsupported translated instructions')
    tag = 'blktiger_sim' if args.sim else 'blktiger'
    out = ROOT / 'run' / tag / 'BLKTIGER.PRG'
    out.parent.mkdir(parents=True, exist_ok=True)
    defs = list(args.defines)
    if args.sim:
        defs.append('SIM=1')
    if args.debug:
        defs.append('DEBUG=1')
    if args.frames:
        defs.append(f'FRAMES={args.frames}')
    assemble_link('blktiger', 'blktiger.s', tag, str(out), defs)
    print(f'built {out}, {out.stat().st_size} bytes')


if __name__ == '__main__':
    main()
