"""Build GALAGA.PRG:  python build.py [--frames N] [--debug] [--sim] [-D NAME=VALUE] [--out file]
-> run/galaga/GALAGA.PRG, run/galaga_sim/GALAGA.PRG with --sim (the CPU ROMs are embedded: build/galaga/rom_cpu*.rom)"""
import argparse, os, sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import gen, assets, sound
from paths import build_dir, run_dir
from toolchain import assemble_link
from machine import ROMDIR

ROMS = ("gg1_1b.3p", "gg1_2b.3m", "gg1_3.2m", "gg1_4b.2l", "gg1_5b.3f", "gg1_7b.2c")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=0)
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("--full-selftest", action="store_true", help="keep the boot RAM test (~700 frames)")
    ap.add_argument("-D", dest="defines", action="append", default=[])
    ap.add_argument("--out", default=None, help="default: run/galaga/GALAGA.PRG, run/galaga_sim/GALAGA.PRG with --sim")
    a = ap.parse_args()
    if a.out is None:
        a.out = str(run_dir("galaga_sim" if a.sim else "galaga") / "GALAGA.PRG")
    text, reps, ems = gen.generate(skip_tests=not a.full_selftest)
    (build_dir("galaga") / "galaga_code.s").write_text(text)
    for n, rep in enumerate(reps):
        print("CPU%d: %d instructions, unsupported %d" % (n + 1, rep["instructions"], len(rep["unsupported"])))
        for u in rep["unsupported"][:10]:
            print("   %04X %-24s %s" % u)
    assets.build()
    sound.emit(build_dir("galaga") / "sound_tables.s")
    rd = lambda f: open(os.path.join(ROMDIR, f), "rb").read()
    for name, files in (("rom_cpu1", ROMS[:4]), ("rom_cpu2", ROMS[4:5]), ("rom_cpu3", ROMS[5:6])):
        (build_dir("galaga") / (name + ".rom")).write_bytes(b"".join(rd(f) for f in files))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    defs = list(a.defines)
    if a.frames: defs.append("FRAMES=%d" % a.frames)
    if a.debug: defs.append("DEBUG=1")
    if a.sim: defs.append("SIM=1")
    assemble_link("galaga", "galaga.s", "galaga", a.out, defs)
    print("built", a.out, os.path.getsize(a.out), "bytes")


if __name__ == "__main__":
    main()
