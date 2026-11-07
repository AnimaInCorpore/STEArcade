"""Build XEVIOUS.PRG:  python build.py [--frames N] [--debug] [--sim] [-D NAME=VALUE] [--out file] [--tag name]
-> run/xevious/XEVIOUS.PRG, run/xevious_sim/XEVIOUS.PRG with --sim (the CPU ROMs are embedded: build/xevious/rom_*.rom)"""
import argparse, os, sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import gen, assets, mb88x
from machine import load_mcu, load, ste_rom
from paths import build_dir, run_dir
from toolchain import assemble_link

ROMS = gen.ROMS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=0)
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("--full-selftest", action="store_true", help="keep the main CPU's boot self-test (~630 frames)")
    ap.add_argument("-D", dest="defines", action="append", default=[])
    ap.add_argument("--out", default=None, help="default: run/xevious/XEVIOUS.PRG, run/xevious_sim/XEVIOUS.PRG with --sim")
    ap.add_argument("--tag", default=None)
    ap.add_argument("--invincible", action="store_true", help="MAME's invincibility cheat (a ROM patch; the test builds of seeds 31+)")
    a = ap.parse_args()
    tag = a.tag or ("xevious_sim" if a.sim else "xevious")
    if a.out is None:
        a.out = str(run_dir(tag) / "XEVIOUS.PRG")
    text, reps, ems = gen.generate(skip_tests=not a.full_selftest, invincible=a.invincible)
    (build_dir("xevious") / "xevious_code.s").write_text(text)
    for n, rep in enumerate(reps):
        print("CPU%d: %d instructions, unsupported %d" % (n + 1, rep["instructions"], len(rep["unsupported"])))
        for u in rep["unsupported"][:10]:
            print("   %04X %-24s %s" % u)
    n51, _ = mb88x.translate_51xx(load_mcu("namco51.zip", "51xx.bin", 0xc2f57ef8))     # the 51XX's program
    (build_dir("xevious") / "n51_code.s").write_text(n51)
    (build_dir("xevious") / "n51_bss.s").write_text(mb88x.bss("N51"))
    assets.build()
    roms = [b"".join(load(f) for f in files) for files in ROMS]
    roms[0] = ste_rom(roms[0], not a.full_selftest, a.invincible)
    for n, rom in enumerate(roms):
        (build_dir("xevious") / ("rom_cpu%d.rom" % (n + 1))).write_bytes(rom)
    bb = bytearray(0x4000)
    bb[0:0x1000] = load("xvi_9.2a")
    bb[0x1000:0x3000] = load("xvi_10.2b")
    bb[0x3000:0x4000] = load("xvi_11.2c")
    (build_dir("xevious") / "rom_bb.rom").write_bytes(bytes(bb))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    defs = list(a.defines)
    if a.frames: defs.append("FRAMES=%d" % a.frames)
    if a.debug: defs.append("DEBUG=1")
    if a.sim: defs.append("SIM=1")
    assemble_link("xevious", "xevious.s", tag, a.out, defs)
    print("built", a.out, os.path.getsize(a.out), "bytes")


if __name__ == "__main__":
    main()
