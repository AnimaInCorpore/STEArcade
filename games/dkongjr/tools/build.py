"""Build DKONGJR.PRG:  python build.py [--frames N] [--debug] [--sim] [-D NAME=VALUE] [--out file]
->  run/dkongjr/DKONGJR.PRG (the CPU ROMs are embedded: build/dkongjr/rom_cpu.rom, $0000-$5FFF in address order)"""
import argparse, os, sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import gen, assets, sound_convert
from paths import EXTRACTED, build_dir, run_dir
from toolchain import assemble_link


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=0)
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("--nosprites", action="store_true")
    ap.add_argument("-D", dest="defines", action="append", default=[], help="extra assembler define NAME=VALUE")
    ap.add_argument("--dumpat", type=int, default=0)
    ap.add_argument("--dumptile", type=int, default=0, help="freeze at the Nth frame drawn with tile bank 1 instead")
    ap.add_argument("--out", default=str(run_dir("dkongjr") / "DKONGJR.PRG"))
    a = ap.parse_args()
    text, rep, em = gen.generate()
    (build_dir("dkongjr") / "dkjr_code.s").write_text(text)
    print("translated:", rep["instructions"], "instructions, unsupported:", len(rep["unsupported"]))
    assets.build()
    sound_convert.ensure()             # dkjr_sound.s / dkjr_ym.s: the 8035 clips and the YM patches (MAME recordings)
    (build_dir("dkongjr") / "rom_cpu.rom").write_bytes((EXTRACTED / "dkongjr" / "cpu.rom").read_bytes())
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    defs = list(a.defines)
    if a.frames: defs.append("FRAMES=%d" % a.frames)
    if a.debug: defs.append("DEBUG=1")
    if a.sim: defs.append("SIM=1")
    if a.dumpat: defs.append("DUMPAT=%d" % a.dumpat)
    if a.dumptile: defs += ["DUMPAT=-1", "DUMPTILE=%d" % a.dumptile]
    if a.nosprites: defs.append("NOSPRITES=1")
    assemble_link("dkongjr", "dkongjr.s", "dkongjr", a.out, defs)
    print("built", a.out, os.path.getsize(a.out), "bytes")


if __name__ == "__main__":
    main()
