"""Build 1942.PRG:  python build.py [--frames N] [--debug] [--sim] [-D NAME=VALUE] [--out file]
-> run/1942/1942.PRG, run/1942_sim/1942.PRG with --sim (the CPU ROMs are embedded: build/1942/rom_*.rom)"""
import argparse, os, sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import gen, assets
from machine import ROMDIR
from paths import build_dir, ROOT
from toolchain import assemble_link

ROMS = ("srb-03.m3", "srb-04.m4", "srb-05.m5", "srb-06.m6", "srb-07.m7")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=0)
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("-D", dest="defines", action="append", default=[])
    ap.add_argument("--sound", action="store_true", help="record the sound programs again (sound_data.s, from the sound driver)")
    ap.add_argument("--out", default=None, help="default: run/1942/1942.PRG, run/1942_sim/1942.PRG with --sim")
    a = ap.parse_args()
    tag = "1942_sim" if a.sim else "1942"
    if a.out is None:
        a.out = str(ROOT / "run" / tag / "1942.PRG")
    build = build_dir("1942")
    assets.build()
    text, rep, em, code = gen.generate()
    (build / "code_1942.s").write_text(text)
    print("translated: %d instructions, unsupported %d, window sites %d" % (rep["instructions"], len(rep["unsupported"]), rep["window_sites"]))
    for u in rep["unsupported"][:10]:
        print("   %04X %-24s %s" % u)
    if a.sound:
        (build / "sound_rec.pkl").unlink(missing_ok=True)
    if a.sound or not (build / "sound_data.s").exists():
        import sound
        print("sound_data.s: %d bytes" % sound.emit(build / "sound_data.s"))
    rd = lambda f: open(os.path.join(ROMDIR, f), "rb").read()
    (build / "rom_fixed.rom").write_bytes(rd(ROMS[0]) + rd(ROMS[1]))                     # $0000-$7FFF
    (build / "rom_banks.rom").write_bytes(rd(ROMS[2]) + rd(ROMS[3]) + b"\xff" * 0x2000 + rd(ROMS[4]))   # banks 0-2
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    defs = list(a.defines)
    if a.frames: defs.append("FRAMES=%d" % a.frames)
    if a.debug: defs.append("DEBUG=1")
    if a.sim: defs.append("SIM=1")
    assemble_link("1942", "1942.s", tag, a.out, defs)
    print("built", a.out, os.path.getsize(a.out), "bytes")


if __name__ == "__main__":
    main()
