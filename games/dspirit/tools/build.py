"""Build DSPIRIT.PRG (--sim: the Musashi build the logic tests run).

    venv/bin/python games/dspirit/tools/build.py [--sim] [-D NAME=VALUE ...]

The program: the translated CPUs (tools/gen.py), the snapshot (tools/snapshot.py), the turned graphics
(tools/assets.py), the MCU model's tables (games/splatter/tools/mcu.py: the same CUS64 program) and src/render.s
(tools/make_render.py: Dragon Spirit's renderer with the routines it shares with Galaga '88's).
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
    if not (ROOT / "assets" / "roms" / "extracted" / "dspirit").is_dir():
        subprocess.run([sys.executable, str(Path(__file__).with_name("prepare.py"))], check=True)
    report = gen.generate()
    if not args.sim:
        import snapshot
        import assets
        import make_render         # (writes src/render.s)
        sys.path.append(str(ROOT / "games" / "splatter" / "tools"))
        import mcu
        from namcos1 import load_regions
        r = load_regions("dspirit")
        mcu.write_tables(build_dir("dspirit") / "mcu_samples.s", r["voice"], r["mcu"])
        snapshot.write()
        assets.build()
    for name, r in report.items():
        print("%s: %d instructions, %d unsupported, %d missing targets, %s" % (
            name, r["instructions"], len(r["unsupported"]), len(r["missing"]), r["stats"]))
    tag = "dspirit_sim" if args.sim else "dspirit"
    out = ROOT / "run" / tag / "DSPIRIT.PRG"
    out.parent.mkdir(parents=True, exist_ok=True)
    defs = list(args.defines) + (["SIM=1"] if args.sim else [])
    assemble_link("dspirit", "dspirit.s", tag, str(out), defs)
    print("built %s, %d bytes" % (out, out.stat().st_size))


if __name__ == "__main__":
    main()
