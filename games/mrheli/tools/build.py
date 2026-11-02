"""Build MRHELI.PRG (--sim: the Musashi build the tests run).

    venv/bin/python games/mrheli/tools/build.py --sim
"""
from pathlib import Path
import argparse
import subprocess
import sys

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
import gen
from paths import ROOT
from toolchain import assemble_link


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("-D", dest="defines", action="append", default=[])
    args = ap.parse_args()
    if not (ROOT / "assets" / "roms" / "extracted" / "mrheli").is_dir():
        subprocess.run([sys.executable, str(Path(__file__).with_name("prepare.py"))], check=True)
    r = gen.generate()
    print("main: %d instructions, %d entries, %d unsupported, %d missing targets, %s" % (
        r["instructions"], r["entries"], len(r["unsupported"]), len(r["missing"]), r["stats"]))
    for u in r["unsupported"]:
        print("   unsupported", u)
    tag = "mrheli_sim" if args.sim else "mrheli"
    out = ROOT / "run" / tag / "MRHELI.PRG"
    out.parent.mkdir(parents=True, exist_ok=True)
    defs = list(args.defines) + (["SIM=1"] if args.sim else [])
    assemble_link("mrheli", "mrheli.s", tag, str(out), defs)
    print("built %s, %d bytes" % (out, out.stat().st_size))


if __name__ == "__main__":
    main()
