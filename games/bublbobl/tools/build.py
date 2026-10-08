"""Build BUBBLE.PRG:  python build.py [--frames N] [--debug] [--sim] [-D NAME=VALUE] [--out file]
-> run/bublbobl/BUBBLE.PRG, run/bublbobl_sim/BUBBLE.PRG with --sim (+ the four CPU ROM files, patched)"""
import argparse, os, sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import gen, assets, m6801x
import machine
from paths import build_dir, ROOT
from toolchain import assemble_link

ROMS = ("a78-06-1.51", "a78-05-1.52", "a78-08.37", "a78-01.17")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=0)
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("-D", dest="defines", action="append", default=[])
    ap.add_argument("--out", default=None, help="default: run/bublbobl/BUBBLE.PRG, run/bublbobl_sim/BUBBLE.PRG with --sim")
    a = ap.parse_args()
    tag = "bublbobl_sim" if a.sim else "bublbobl"
    if a.out is None:
        a.out = str(ROOT / "run" / tag / "BUBBLE.PRG")
    build = build_dir("bublbobl")
    text, reps = gen.generate()
    (build / "bb_code.s").write_text(text)
    for n, rep in enumerate(reps):
        print("CPU%d: %d instructions, unsupported %d" % (n + 1, rep["instructions"], len(rep["unsupported"])))
        for u in rep["unsupported"][:10]:
            print("   %04X %-24s %s" % u)
    mtext, em, code = m6801x.generate(native=m6801x.NATIVE)
    (build / "bb_mcu.s").write_text(mtext)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    assets.build()
    defs = list(a.defines)
    if a.frames: defs.append("FRAMES=%d" % a.frames)
    if a.debug: defs.append("DEBUG=1")
    if a.sim: defs.append("SIM=1")
    assemble_link("bublbobl", "bublbobl.s", tag, a.out, defs)
    # the ROM files the runtime loads: the main and sub CPU's with the boot tests patched out (the game
    # checksums part of its ROM while it runs)
    main_rom, sub_rom = machine.skip_tests(machine.load(ROMS[0]), machine.load(ROMS[2]))
    for f in ROMS:
        data = main_rom if f == ROMS[0] else sub_rom if f == ROMS[2] else machine.load(f)
        open(os.path.join(os.path.dirname(a.out), f), "wb").write(data)
    print("built", a.out, os.path.getsize(a.out), "bytes")


if __name__ == "__main__":
    main()
