"""Build MPATROL.PRG (so far only --sim: the Musashi build for the tests; the STE build comes with the renderer).

    python tools/build.py --sim [-D NAME=VALUE ...]
"""
from pathlib import Path
import argparse
import json
import subprocess
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
import gen
from paths import build_dir, ROOT, EXTRACTED
from toolchain import assemble_link


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true")
    ap.add_argument("-D", dest="defines", action="append", default=[])
    args = ap.parse_args()
    if not args.sim:
        sys.exit("Moon Patrol: only the simulator build (--sim) so far")
    build = build_dir("mpatrol")
    if not (EXTRACTED / "mpatrol" / "mpa-1.3m").exists():
        subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "prepare.py")], check=True)
    (build / "mpatrol.rom").write_bytes(gen.image()[:0x8000])
    text, report, _ = gen.generate()
    (build / "code_mpatrol.s").write_text(text)
    (build / "translation.json").write_text(json.dumps(report, indent=1) + "\n")
    print("translation:", {k: v for k, v in report.items() if k not in ("unsupported", "tables", "io")},
          len(report["unsupported"]), "unsupported")
    tag = "mpatrol_sim"
    out = ROOT / "run" / tag / "MPATROL.PRG"
    out.parent.mkdir(parents=True, exist_ok=True)
    assemble_link("mpatrol", "mpatrol.s", tag, str(out), list(args.defines) + ["SIM=1"])
    print("built %s, %d bytes" % (out, out.stat().st_size))


if __name__ == "__main__":
    main()
