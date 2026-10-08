"""Build DKONG.PRG:  python build.py [--frames N]  ->  ste/run/DKONG.PRG (+ ROM files)"""
import argparse, os, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen, assets, sprites

STE = gen.STE
VLINK = r"C:/Arbeit/F030Arcade/third_party/vlink/vlink.exe"
VASM = r"C:\Arbeit\F030Arcade\third_party\vasm\vasmm68k_mot.exe"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=0)
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("--sprites", action="store_true", help="regenerate the sprite routines")
    ap.add_argument("--out", default=os.path.join(STE, "run", "DKONG.PRG"))
    a = ap.parse_args()
    text, rep, em = gen.generate()
    os.makedirs(os.path.join(STE, "build"), exist_ok=True)
    open(os.path.join(STE, "build", "dk_code.s"), "w").write(text)
    print("translated:", rep["instructions"], "instructions, unsupported:", len(rep["unsupported"]))
    assets.build()
    sprite_source = os.path.join(STE, 'build', 'dk_sprites.s')
    sprite_generator = os.path.join(STE, 'tools', 'sprites.py')
    sprite_observed = os.path.join(STE, 'tools', 'sprite_observed.json')
    if (not os.path.exists(sprite_source) or a.sprites or
            max(os.path.getmtime(sprite_generator), os.path.getmtime(sprite_observed)) >
            os.path.getmtime(sprite_source)):
        print('sprites:', sprites.build(verify=True))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    obj = os.path.join(STE, "build", "dkong.o")
    cmd = [VASM, "-Fvobj", "-quiet", "-nowarn=2047", "-I", os.path.join(STE, "build"), "-o", obj, "dkong.s"]
    if a.frames:
        cmd.insert(1, "-DFRAMES=%d" % a.frames)
    if a.debug:
        cmd.insert(1, "-DDEBUG=1")
    if a.sim:
        cmd.insert(1, "-DSIM=1")
    r = subprocess.run(cmd, cwd=os.path.join(STE, "rt"), capture_output=True, text=True)
    sys.stdout.write(r.stdout + r.stderr)
    if r.returncode:
        sys.exit(r.returncode)
    r = subprocess.run([VLINK, "-b", "ataritos", "-s", "-o", a.out, "-M" + os.path.join(STE, "build", "dkong.map"), obj],
                       capture_output=True, text=True)
    sys.stdout.write(r.stdout + r.stderr)
    if r.returncode:
        sys.exit(r.returncode)
    romdir = os.path.join(STE, "..", "assets", "roms", "extracted")
    for f in ("c_5et_g.bin", "c_5ct_g.bin", "c_5bt_g.bin", "c_5at_g.bin"):
        shutil.copy(os.path.join(romdir, f), os.path.join(os.path.dirname(a.out), f))
    print("built", a.out, os.path.getsize(a.out), "bytes")


if __name__ == "__main__":
    main()
