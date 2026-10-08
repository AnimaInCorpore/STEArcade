"""Compare tools/machine.py render_raw() with MAME (see ref/mame_cmp_dkong.py, README "Checking a
reference against MAME").  MAME runs the bublbobl set itself (the MCU ROM is in the set); the main CPU's
C000-F9FF (video RAM, object RAM, shared RAM, palette RAM) is dumped at frame N and rendered with the
reference.

    python ref/mame_cmp_bublbobl.py [frames...]       # default 700 1500 2500
"""
import os
import subprocess
import sys
import tempfile
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "..", "tools"), os.path.join(HERE, "..", "..", "..", "engine")]
import machine

from paths import ROMS, ENGINE
frames = [int(a) for a in sys.argv[1:]] or [700, 1500, 2500]
for f in frames:
    out = tempfile.mkdtemp()
    env = dict(os.environ, FRAME=str(f), OUT=out, START="0xc000", END="0xf9ff")
    subprocess.run(["mame", "bublbobl", "-window", "-rompath", ROMS, "-sound", "none", "-nothrottle",
                    "-seconds_to_run", "250", "-skip_gameinfo", "-autoboot_script",
                    str(ENGINE / "mame_dump.lua"), "-snapshot_directory", out, "-snapname", "shot"],
                   env=env, cwd=out, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    shot = np.array(Image.open(os.path.join(out, "shot.png")).convert("RGB"))
    mem = open(os.path.join(out, "mem.bin"), "rb").read()
    m = machine.Bublbobl()
    m.vram[:] = mem[0:0xDD00 - 0xC000]
    m.oram[:] = mem[0xDD00 - 0xC000:0xE000 - 0xC000]
    m.pal[:] = mem[0xF800 - 0xC000:0xFA00 - 0xC000]
    m.video_enable = True
    rgb = m.render_rgb()
    d = (rgb != shot[:rgb.shape[0], :rgb.shape[1]]).any(axis=2)
    nspr = sum(1 for o in range(0, 0x300, 4) if any(m.oram[o:o + 4]))
    print("frame %d: %d objects, shot %s, ref %s: %d pixels differ" % (f, nspr, shot.shape[:2], rgb.shape[:2], d.sum()))
    Image.fromarray(np.hstack([rgb, shot[:rgb.shape[0], :rgb.shape[1]]])).save(os.path.join(out, "cmp.png"))
    print("  side by side:", os.path.join(out, "cmp.png"))
