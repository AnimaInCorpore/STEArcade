"""Build BUBBLE.PRG:  python build.py [--frames N] [--debug] [--sim] [-D NAME=VALUE] [--out file]
-> run/bublbobl/BUBBLE.PRG, run/bublbobl_sim/BUBBLE.PRG with --sim (the CPU ROMs are embedded, patched)"""
import argparse, os, sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import gen, assets, m6801x
import machine
import sound
from paths import build_dir, ROOT
from toolchain import assemble_link

ROMS = ("a78-06-1.51", "a78-05-1.52", "a78-08.37", "a78-01.17")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=0)
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("-D", dest="defines", action="append", default=[])
    ap.add_argument("--sound", action="store_true", help="record the sound driver again (tools/sound.py, ~15 min)")
    ap.add_argument("--out", default=None, help="default: run/bublbobl/BUBBLE.PRG, run/bublbobl_sim/BUBBLE.PRG with --sim")
    a = ap.parse_args()
    tag = "bublbobl_sim" if a.sim else "bublbobl"
    if a.out is None:
        a.out = str(ROOT / "run" / tag / "BUBBLE.PRG")
    build = build_dir("bublbobl")
    if a.sound:
        sound.all_sounds(True)
    print("bb_sound.s: %d bytes" % sound.emit(build / "bb_sound.s"))     # (from build/bublbobl/sound.pkl)
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
    # the embedded ROMs (bublbobl.s rom_table): the main and sub CPU's with the boot tests patched out (the
    # game checksums part of its ROM while it runs)
    main_rom, sub_rom = machine.skip_tests(machine.load(ROMS[0]), machine.load(ROMS[2]))
    for name, data in (("rom_main", main_rom), ("rom_banks", machine.load(ROMS[1])), ("rom_sub", sub_rom),
                       ("rom_mcu", machine.load(ROMS[3]))):
        (build / (name + ".rom")).write_bytes(data)
    defs = list(a.defines)
    if a.frames: defs.append("FRAMES=%d" % a.frames)
    if a.debug: defs.append("DEBUG=1")
    if a.sim: defs.append("SIM=1")
    if os.environ.get("BB_NO_NATIVES"): defs.append("MCU_XLATE=1")      # (gen.py: the translation alone)
    assemble_link("bublbobl", "bublbobl.s", tag, a.out, defs)
    print("built", a.out, os.path.getsize(a.out), "bytes")


if __name__ == "__main__":
    main()
