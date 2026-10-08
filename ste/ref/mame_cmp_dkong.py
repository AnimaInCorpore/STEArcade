"""Compare tools/dkong.py render_raw() with MAME pixel by pixel (the check that found the sprite
position off by one and the wrong palette, 2026-10-08).

    python ref/mame_cmp_dkong.py [frames...]       # default 700 1500 2500

Runs MAME (ref/mame_dump.lua, needs `mame` in the PATH and the ROM zip in assets/roms) once per frame,
renders the dumped memory with the reference and prints the number of differing pixels for every
palette bank / sprite bank.  The right bank gives 0 (the memory is dumped after the frame is drawn,
so a fast moving sprite can leave a few pixels).
"""
import os
import subprocess
import sys
import tempfile
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import dkong

ROMS = os.path.join(HERE, "..", "..", "assets", "roms")
frames = [int(a) for a in sys.argv[1:]] or [700, 1500, 2500]
pal = np.array([[(c >> 16) & 255, (c >> 8) & 255, c & 255] for c in dkong.PENS], np.uint8)
for f in frames:
    out = tempfile.mkdtemp()
    env = dict(os.environ, FRAME=str(f), OUT=out, START="0x6000", END="0x7fff")
    subprocess.run(["mame", "dkong", "-window", "-rompath", ROMS, "-sound", "none", "-nothrottle",
                    "-seconds_to_run", "600", "-skip_gameinfo", "-autoboot_script",
                    os.path.join(HERE, "mame_dump.lua"), "-snapshot_directory", out, "-snapname", "shot"],
                   env=env, cwd=out, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ref = np.array(Image.open(os.path.join(out, "shot.png")).convert("RGB"))
    mp = [tuple(int(x, 16) for x in (l.split()[1][0:2], l.split()[1][2:4], l.split()[1][4:6]))
          for l in open(os.path.join(out, "pens.txt"))]
    assert [tuple(int(v) for v in p) for p in pal] == mp[:256], \
        "tools/dkong_pens.py differs from this MAME's palette (%d pens)" % len(mp)
    d = dkong.DKong()
    d.gfx = dkong.Gfx()
    d.mem[0x6000:0x8000] = open(os.path.join(out, "mem.bin"), "rb").read()
    d.flip = 1          # the upright game keeps $7D82 at 1: the picture is MAME's, not rotated back
    res = []
    for pb in range(4):
        for sb in range(2):
            d.palette_bank, d.sprite_bank = pb, sb
            rgb = pal[d.render_raw()][16:240].transpose(1, 0, 2)[::-1][::-1, ::-1]
            res.append(((rgb != ref).any(axis=2).sum(), pb, sb))
    best = min(res)
    print("frame %d: best palette bank %d sprite bank %d: %d of %d pixels differ" %
          (f, best[1], best[2], best[0], ref.shape[0] * ref.shape[1]))
