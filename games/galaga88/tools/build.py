"""Build GALAGA88.PRG (--sim: the Musashi build the tests run).

    venv/bin/python games/galaga88/tools/build.py --sim
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
    if not (ROOT / "assets" / "roms" / "extracted" / "galaga88").is_dir():
        subprocess.run([sys.executable, str(Path(__file__).with_name("prepare.py"))], check=True)
    report = gen.generate()
    if not args.sim:
        import snapshot
        import assets
        sys.path.append(str(ROOT / "games" / "splatter" / "tools"))
        import mcu                                  # (the CUS64 model: Splatterhouse's, the same program)
        from namcos1 import load_regions
        r = load_regions("galaga88")
        mcu.write_tables(build_dir("galaga88") / "mcu_samples.s", r["voice"], r["mcu"])
        snapshot.write()
        assets.build()
    for name, r in report.items():
        print("%s: %d instructions, %d unsupported, %d missing targets, %s" % (
            name, r["instructions"], len(r["unsupported"]), len(r["missing"]), r["stats"]))
    tag = "galaga88_sim" if args.sim else "galaga88"
    out = ROOT / "run" / tag / "GALAGA88.PRG"
    out.parent.mkdir(parents=True, exist_ok=True)
    defs = list(args.defines) + (["SIM=1"] if args.sim else [])
    assemble_link("galaga88", "galaga88.s", tag, str(out), defs)
    print("built %s, %d bytes" % (out, out.stat().st_size))


if __name__ == "__main__":
    main()
