"""Screenshots of run/mpatrol/MPATROL.PRG in the pinned Hatari (F030Arcade's build), out of the user's way.

    python games/mpatrol/tools/shots.py [vbl ...] [--prg PATH] [--out DIR]   -> DIR/mpatrol_<vbl>.png

Hatari runs fast-forward on a desktop of its own (engine/mamewin.py: no window, no focus); a debugger script
(--parse) sets a breakpoint at each VBL whose script takes Hatari's own screenshot (the emulated screen, borders
included), the last one quits.  CRASH.TXT, if the program wrote one, is printed.
"""
from pathlib import Path
import argparse
import os
import shutil
import sys
import tempfile
sys.path[:0] = [str(Path(__file__).resolve().parents[3] / "engine")]
import mamewin
from paths import ROOT

ARCADE = Path(os.environ.get("F030ARCADE", r"C:\Arbeit\F030Arcade"))
HATARI = ARCADE / "third_party" / "hatari" / "build-ucrt64" / "src" / "hatari.exe"
TOS = ARCADE / "third_party" / "tos" / "tos206de.img"
MSYS = Path(os.environ.get("MSYS2", r"C:\msys64"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vbls", nargs="*", type=int, default=[250, 500, 1000])
    ap.add_argument("--prg", type=Path, default=ROOT / "run" / "mpatrol" / "MPATROL.PRG")
    ap.add_argument("--out", type=Path, default=ROOT / "build" / "mpatrol" / "shots")
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="mpatrol_hatari_"))
    disk = work / "disk"
    disk.mkdir()
    shutil.copy(args.prg, disk / args.prg.name)
    vbls = sorted(args.vbls)
    init = []
    for i, v in enumerate(vbls):
        shot = args.out / ("mpatrol_%d.png" % v)
        if shot.exists():
            shot.unlink()
        script = work / ("shot%d.ini" % i)
        script.write_text("screenshot %s\n" % shot.as_posix() + ("quit\n" if v == vbls[-1] else ""))
        init.append("b VBL = %d :once :quiet :trace :file %s" % (v, script.as_posix()))
    (work / "init.ini").write_text("\n".join(init) + "\n")
    env = dict(os.environ, PATH="%s;%s;%s" % (MSYS / "ucrt64" / "bin", MSYS / "usr" / "bin", os.environ["PATH"]))
    cmd = [str(HATARI), "--machine", "ste", "--memsize", "4", "--tos", str(TOS), "--fast-boot", "true",
           "--cpu-exact", "true", "--compatible", "true", "--sound", "off", "--confirm-quit", "off",
           "--statusbar", "false", "--borders", "true", "--fast-forward", "true", "--log-file", str(work / "hatari.log"),
           "--parse", str(work / "init.ini"), "-d", str(disk), "--auto", "C:\\" + args.prg.name]
    r = mamewin.run(cmd, mame=False, cwd=work, env=env, timeout=args.timeout, capture_output=True, text=True)
    for v in vbls:
        shot = args.out / ("mpatrol_%d.png" % v)
        print("%s %s" % (shot, "ok" if shot.exists() else "missing"))
    crash = disk / "CRASH.TXT"
    if crash.exists():
        print("--- CRASH.TXT\n" + crash.read_text())
    if r.returncode:
        print("hatari exit %d; log: %s" % (r.returncode, work / "hatari.log"))


if __name__ == "__main__":
    main()
