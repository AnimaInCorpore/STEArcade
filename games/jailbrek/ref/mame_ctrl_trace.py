"""Runs MAME's jailbrek with ref/mame_ctrl_trace.lua: the control-register writes with their time in CPU cycles.

    python games/jailbrek/ref/mame_ctrl_trace.py OUTFILE [LAST_FRAME]
"""
from pathlib import Path
import os
import sys
import tempfile

sys.path[:0] = [str(Path(__file__).resolve().parents[3] / "engine")]
import mamewin
from paths import ROMS

exe = os.environ.get("MAME") or r"C:\Arbeit\F030Arcade\third_party\wolfmame-0248\mame.exe"
out = Path(sys.argv[1]).resolve()
d = Path(tempfile.mkdtemp(prefix="mame_jb_"))
env = dict(os.environ, OUT=str(out), LAST=sys.argv[2] if len(sys.argv) > 2 else "1560")
with (d / "mame.log").open("w") as log:
    r = mamewin.run([exe, "jailbrek", "-rompath", str(ROMS), "-window", "-sound", "none", "-nothrottle", "-frameskip", "0",
                     "-seconds_to_run", "250", "-skip_gameinfo", "-autoboot_script",
                     str(Path(__file__).with_suffix(".lua"))], cwd=d, env=env, stdout=log, stderr=log, timeout=600)
print("exit", r.returncode, out.exists() and out.stat().st_size)
