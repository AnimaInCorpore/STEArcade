"""Build RTYPE.PRG (--sim: the Musashi build the tests run).

    venv/bin/python games/rtype/tools/build.py --sim
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
    ap.add_argument("--legacy-renderer", action="store_true", help="Use the older shared M72 renderer")
    ap.add_argument("-D", dest="defines", action="append", default=[])
    args = ap.parse_args()
    if args.legacy_renderer and any(d.split('=')[0] == 'STAGE' for d in args.defines):
        ap.error('--legacy-renderer cannot be combined with -D STAGE')
    if not (ROOT / "assets" / "roms" / "extracted" / "rtype").is_dir():
        subprocess.run([sys.executable, str(Path(__file__).with_name("prepare.py"))], check=True)
    r = gen.generate()
    stage = not args.legacy_renderer and (not args.sim or any(d.split('=')[0] == 'STAGE' for d in args.defines))
    if stage:
        import stage_assets
        stage_assets.ensure()
    elif not args.sim or not all((ROOT / 'build/rtype' / f'm72_{name}.bin').exists()
                                 for name in ('tf', 'uf', 'tb', 'ub', 'bs', 'sp', 'su', 'lab', 'q4', 'pal')):
        import assets
        assets.build()
    if not args.sim:
        import snapshot
        snapshot.write()
    print("main: %d instructions, %d entries, %d unsupported, %d missing targets, %s" % (
        r["instructions"], r["entries"], len(r["unsupported"]), len(r["missing"]), r["stats"]))
    tag = "rtype_sim" if args.sim else "rtype"
    out = ROOT / "run" / tag / "RTYPE.PRG"
    out.parent.mkdir(parents=True, exist_ok=True)
    defs = list(args.defines) + (["SIM=1"] if args.sim else [])
    if stage and not any(d.split('=')[0] == 'STAGE' for d in defs):
        defs.append('STAGE=1')
    assemble_link("rtype", "rtype.s", tag, str(out), defs)
    print("built %s, %d bytes" % (out, out.stat().st_size))


if __name__ == "__main__":
    main()
