"""Build TROJAN.PRG (run/trojan/) for a 4 MB STE, or the simulator variant (--sim: run/trojan_sim/)."""
from pathlib import Path
import argparse
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
import gen
from machine import load
from paths import build_dir, ROOT, EXTRACTED
from toolchain import assemble_link


def prepare():
    if not (EXTRACTED / 'trojan' / 'tb04.bin').exists():
        import subprocess
        subprocess.run([sys.executable, str(Path(__file__).resolve().parent / 'prepare.py')], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sim', action='store_true')
    ap.add_argument('--debug', action='store_true')
    ap.add_argument('--frames', type=int, default=0)
    ap.add_argument('--sound', action='store_true', help='record the sound driver again (tools/sound.py, ~15 min)')
    ap.add_argument('-D', dest='defines', action='append', default=[])
    args = ap.parse_args()
    prepare()
    build = build_dir('trojan')
    try:
        import assets
        assets.build()
    except ImportError:
        pass
    import sound
    import capsnd
    d = sound.driver()
    if args.sound:
        capsnd.all_effects(d, again=True)
        capsnd.all_tunes(d, again=True)
    print('cs_data.s: %d bytes' % capsnd.emit(d, build / 'cs_data.s'))     # (records first when nothing is recorded)
    (build / 'fixed.rom').write_bytes(load('tb04.bin'))
    (build / 'banks.rom').write_bytes(load('tb06.bin') + load('tb05.bin'))
    text, report, _ = gen.generate()
    (build / 'code_trojan.s').write_text(text)
    print('translation:', report)
    if report['unsupported']:
        raise RuntimeError('unsupported translated instructions')
    tag = 'trojan_sim' if args.sim else 'trojan'
    out = ROOT / 'run' / tag / 'TROJAN.PRG'
    out.parent.mkdir(parents=True, exist_ok=True)
    defs = list(args.defines)
    if args.sim:
        defs.append('SIM=1')
    if args.debug:
        defs.append('DEBUG=1')
    if args.frames:
        defs.append('FRAMES=%d' % args.frames)
    assemble_link('trojan', 'trojan.s', tag, str(out), defs)
    print('built %s, %d bytes' % (out, out.stat().st_size))


if __name__ == '__main__':
    main()
