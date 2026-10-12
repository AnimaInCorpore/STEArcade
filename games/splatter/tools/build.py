"""Build SPLATTER.PRG (--sim: the Musashi build the tests run; the only build so far).

    venv/bin/python games/splatter/tools/build.py --sim
"""
from pathlib import Path
import argparse
import subprocess
import sys

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
import gen
from paths import ROOT, build_dir
from toolchain import assemble_link


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("-D", dest="defines", action="append", default=[])
    args = ap.parse_args()
    if not (ROOT / "assets" / "roms" / "extracted" / "splatter").is_dir():
        subprocess.run([sys.executable, str(Path(__file__).with_name("prepare.py"))], check=True)
    report = gen.generate()
    if not args.sim:
        import snapshot
        snapshot.write()
    for name, r in report.items():
        print("%s: %d instructions, %d unsupported, %d missing targets, %s" % (
            name, r["instructions"], len(r["unsupported"]), len(r["missing"]), r["stats"]))
    tag = "splatter_sim" if args.sim else "splatter"
    out = ROOT / "run" / tag / "SPLATTER.PRG"
    out.parent.mkdir(parents=True, exist_ok=True)
    defs = list(args.defines) + (["SIM=1"] if args.sim else [])
    assemble_link("splatter", "splatter.s", tag, str(out), defs)
    print("built %s, %d bytes" % (out, out.stat().st_size))


if __name__ == "__main__":
    main()
