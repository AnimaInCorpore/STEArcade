"""Build RTHUNDER.PRG (--sim: the Musashi build the logic test runs).

    python games/rthunder/tools/build.py [--sim] [-D NAME=VALUE ...]

Only the sim build exists: the translated CPUs (tools/gen.py) and the runtime (src/core.s).
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
    ap.add_argument("--sim", action="store_true", default=True)
    ap.add_argument("-D", dest="defines", action="append", default=[])
    args = ap.parse_args()
    if not (ROOT / "assets" / "roms" / "extracted" / "rthunder").is_dir():
        subprocess.run([sys.executable, str(Path(__file__).with_name("prepare.py"))], check=True)
    import assets
    assets.build()
    report = gen.generate()
    for name in ("main", "sub"):
        r = report[name]
        print("%s: %d instructions, %d unsupported, %d missing targets, %s" % (
            name, r["instructions"], len(r["unsupported"]), len(r["missing"]), r["stats"]))
    out = ROOT / "run" / "rthunder_sim" / "RTHUNDER.PRG"
    out.parent.mkdir(parents=True, exist_ok=True)
    assemble_link("rthunder", "rthunder.s", "rthunder_sim", str(out), list(args.defines) + ["SIM=1"])
    print("built %s, %d bytes" % (out, out.stat().st_size))


if __name__ == "__main__":
    main()
