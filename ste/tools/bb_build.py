"""Build BUBBLE.PRG:  python bb_build.py [--frames N] [--debug] [-D NAME=VALUE] [--out file]
-> ste/run/bublbobl/BUBBLE.PRG (+ the four CPU ROM files)"""
import argparse, os, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bb_gen, bb_assets, m6801x
from build import VASM, VLINK
from bublbobl import ROMDIR

STE = bb_gen.STE
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
        a.out = os.path.join(STE, "run", tag, "BUBBLE.PRG")
    text, reps = bb_gen.generate()
    os.makedirs(os.path.join(STE, "build"), exist_ok=True)
    open(os.path.join(STE, "build", "bb_code.s"), "w").write(text)
    for n, rep in enumerate(reps):
        print("CPU%d: %d instructions, unsupported %d" % (n + 1, rep["instructions"], len(rep["unsupported"])))
        for u in rep["unsupported"][:10]:
            print("   %04X %-24s %s" % u)
    mtext, em, code = m6801x.generate()
    open(os.path.join(STE, "build", "bb_mcu.s"), "w").write(mtext)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    bb_assets.build()
    obj = os.path.join(STE, "build", tag + ".o")
    cmd = [VASM, "-Fvobj", "-quiet", "-nowarn=2047", "-I", os.path.join(STE, "build"), "-o", obj, "bublbobl.s"]
    if a.frames:
        cmd.insert(1, "-DFRAMES=%d" % a.frames)
    if a.debug:
        cmd.insert(1, "-DDEBUG=1")
    if a.sim:
        cmd.insert(1, "-DSIM=1")
    for d in a.defines:
        cmd.insert(1, "-D" + d)
    r = subprocess.run(cmd, cwd=os.path.join(STE, "bublbobl"), capture_output=True, text=True)
    sys.stdout.write(r.stdout + r.stderr)
    if r.returncode:
        sys.exit(r.returncode)
    r = subprocess.run([VLINK, "-b", "ataritos", "-s", "-o", a.out, "-M" + os.path.join(STE, "build", tag + ".map"), obj],
                       capture_output=True, text=True)
    sys.stdout.write(r.stdout + r.stderr)
    if r.returncode:
        sys.exit(r.returncode)
    for f in ROMS:
        shutil.copy(os.path.join(ROMDIR, f), os.path.join(os.path.dirname(a.out), f))
    print("built", a.out, os.path.getsize(a.out), "bytes")


if __name__ == "__main__":
    main()
