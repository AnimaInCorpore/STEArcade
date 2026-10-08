"""Build GALAGA.PRG:  python galaga_build.py [--frames N] [--debug] [-D NAME=VALUE] [--out file]
-> ste/run/galaga/GALAGA.PRG (+ the six CPU ROM files)"""
import argparse, os, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import galaga_gen, galaga_assets
from build import VASM, VLINK
from galaga import ROMDIR

STE = galaga_gen.STE


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=0)
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("--full-selftest", action="store_true", help="keep the boot RAM test (~700 frames)")
    ap.add_argument("-D", dest="defines", action="append", default=[])
    ap.add_argument("--out", default=os.path.join(STE, "run", "galaga", "GALAGA.PRG"))
    a = ap.parse_args()
    text, reps, ems = galaga_gen.generate(skip_tests=not a.full_selftest)
    os.makedirs(os.path.join(STE, "build"), exist_ok=True)
    open(os.path.join(STE, "build", "galaga_code.s"), "w").write(text)
    for n, rep in enumerate(reps):
        print("CPU%d: %d instructions, unsupported %d" % (n + 1, rep["instructions"], len(rep["unsupported"])))
        for u in rep["unsupported"][:10]:
            print("   %04X %-24s %s" % u)
    galaga_assets.build()
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    obj = os.path.join(STE, "build", "galaga.o")
    cmd = [VASM, "-Fvobj", "-quiet", "-nowarn=2047", "-I", os.path.join(STE, "build"), "-o", obj, "galaga.s"]
    if a.frames:
        cmd.insert(1, "-DFRAMES=%d" % a.frames)
    if a.debug:
        cmd.insert(1, "-DDEBUG=1")
    if a.sim:
        cmd.insert(1, "-DSIM=1")
    for d in a.defines:
        cmd.insert(1, "-D" + d)
    r = subprocess.run(cmd, cwd=os.path.join(STE, "galaga"), capture_output=True, text=True)
    sys.stdout.write(r.stdout + r.stderr)
    if r.returncode:
        sys.exit(r.returncode)
    r = subprocess.run([VLINK, "-b", "ataritos", "-s", "-o", a.out, "-M" + os.path.join(STE, "build", "galaga.map"), obj],
                       capture_output=True, text=True)
    sys.stdout.write(r.stdout + r.stderr)
    if r.returncode:
        sys.exit(r.returncode)
    for f in ("gg1_1b.3p", "gg1_2b.3m", "gg1_3.2m", "gg1_4b.2l", "gg1_5b.3f", "gg1_7b.2c"):
        shutil.copy(os.path.join(ROMDIR, f), os.path.join(os.path.dirname(a.out), f))
    print("built", a.out, os.path.getsize(a.out), "bytes")


if __name__ == "__main__":
    main()
