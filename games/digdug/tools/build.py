"""Build DIGDUG.PRG:  python build.py [--frames N] [--debug] [--sim] [-D NAME=VALUE] [--out file]
-> run/digdug/DIGDUG.PRG, run/digdug_sim/DIGDUG.PRG with --sim (the patched CPU ROMs are embedded: build/digdug/rom_cpu*.rom)"""
import argparse, os, sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import gen, assets, sound, mb88x
from machine import load_mcu, load, patch_tests
from paths import build_dir, run_dir
from toolchain import assemble_link

ROMS = (("dd1a.1", "dd1a.2", "dd1a.3", "dd1a.4"), ("dd1a.5", "dd1a.6"), ("dd1.7",))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=0)
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("--full-selftest", action="store_true", help="keep the boot self-tests (~700 frames)")
    ap.add_argument("-D", dest="defines", action="append", default=[])
    ap.add_argument("--out", default=None, help="default: run/digdug/DIGDUG.PRG, run/digdug_sim/DIGDUG.PRG with --sim")
    a = ap.parse_args()
    if a.out is None:
        a.out = str(run_dir("digdug_sim" if a.sim else "digdug") / "DIGDUG.PRG")
    text, reps, ems = gen.generate(skip_tests=not a.full_selftest)
    (build_dir("digdug") / "digdug_code.s").write_text(text)
    for n, rep in enumerate(reps):
        print("CPU%d: %d instructions, unsupported %d" % (n + 1, rep["instructions"], len(rep["unsupported"])))
        for u in rep["unsupported"][:10]:
            print("   %04X %-24s %s" % u)
    n51, _ = mb88x.translate_51xx(load_mcu("51xx.bin"))     # the 51XX's program
    (build_dir("digdug") / "n51_code.s").write_text(n51)
    (build_dir("digdug") / "n51_bss.s").write_text(mb88x.bss("N51"))
    n53, _ = mb88x.translate_53xx(load_mcu("53xx.bin"), "G_IO1")     # the 53XX's program (its K reads the main CPU's latch cells)
    (build_dir("digdug") / "n53_code.s").write_text(n53)
    (build_dir("digdug") / "n53_bss.s").write_text(mb88x.bss("N53"))
    assets.build()
    sound.emit(build_dir("digdug") / "sound_tables.s")
    roms = [b"".join(load(f) for f in files) for files in ROMS]
    if not a.full_selftest:
        roms = list(patch_tests(roms))
    for n, rom in enumerate(roms):
        (build_dir("digdug") / ("rom_cpu%d.rom" % (n + 1))).write_bytes(rom)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    defs = list(a.defines)
    if a.frames: defs.append("FRAMES=%d" % a.frames)
    if a.debug: defs.append("DEBUG=1")
    if a.sim: defs.append("SIM=1")
    assemble_link("digdug", "digdug.s", "digdug", a.out, defs)
    print("built", a.out, os.path.getsize(a.out), "bytes")


if __name__ == "__main__":
    main()
