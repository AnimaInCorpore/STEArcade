"""Build DKONG.PRG:  python build.py [--frames N] [--debug] [--sim] [-D NAME=VALUE] [--out file]
->  run/dkong/DKONG.PRG (+ the four CPU ROM files)"""
import argparse, os, shutil, sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import gen, assets
from paths import EXTRACTED, build_dir, run_dir
from toolchain import assemble_link

ROMS = ("c_5et_g.bin", "c_5ct_g.bin", "c_5bt_g.bin", "c_5at_g.bin")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=0)
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("--nosprites", action="store_true")
    ap.add_argument("-D", dest="defines", action="append", default=[], help="extra assembler define NAME=VALUE")
    ap.add_argument("--dumpat", type=int, default=0)
    ap.add_argument("--dumpbank", type=int, default=0, help="dump and freeze at the Nth palette bank change instead")
    ap.add_argument("--out", default=str(run_dir("dkong") / "DKONG.PRG"))
    a = ap.parse_args()
    text, rep, em = gen.generate()
    (build_dir("dkong") / "dk_code.s").write_text(text)
    print("translated:", rep["instructions"], "instructions, unsupported:", len(rep["unsupported"]))
    assets.build()
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    defs = list(a.defines)
    if a.frames: defs.append("FRAMES=%d" % a.frames)
    if a.debug: defs.append("DEBUG=1")
    if a.sim: defs.append("SIM=1")
    if a.dumpat: defs.append("DUMPAT=%d" % a.dumpat)
    if a.dumpbank: defs += ["DUMPAT=-1", "DUMPBANK=%d" % a.dumpbank]
    if a.nosprites: defs.append("NOSPRITES=1")
    assemble_link("dkong", "dkong.s", "dkong", a.out, defs)
    for f in ROMS:
        shutil.copy(EXTRACTED / "dkong" / f, os.path.join(os.path.dirname(a.out), f))
    print("built", a.out, os.path.getsize(a.out), "bytes")


if __name__ == "__main__":
    main()
