"""Compare tools/machine.py render_raw() with MAME (see ref/mame_cmp_dkong.py, README "Checking a
reference against MAME").

The RAM image of the reference machine is written into MAME's RAM (engine/mame_dump.lua, INJECT) and
MAME's own video code draws it: this checks the renderer (tiles, sprites, palette), not the game.  It
was written when the Namco 51xx / 54xx MCU ROMs were missing (blank stand-ins kept MAME in its test
screen); the real namco51.zip / namco54.zip are used now when assets/roms has them (the game against
MAME: ref/mame_cmp_51xx.py).  The starfield is left out of the reference (its phase depends on
the exact frame), so a pixel where MAME has a star and the reference the black background is
expected and counted separately; any other difference is an error.

    python ref/mame_cmp_galaga.py [frames...]       # default 900 1500 2100
"""
import os
import subprocess
import sys
import tempfile
import zipfile
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "..", "tools"), os.path.join(HERE, "..", "..", "..", "engine")]
import mamewin                       # (MAME runs minimized)
import machine

from paths import ROMS, ENGINE
frames = [int(a) for a in sys.argv[1:]] or [900, 1500, 2100]

rompath = tempfile.mkdtemp()
os.symlink(os.path.join(ROMS, "galaga.zip"), os.path.join(rompath, "galaga.zip"))
for n, f in (("namco51", "51xx.bin"), ("namco54", "54xx.bin")):
    if os.path.exists(os.path.join(ROMS, n + ".zip")):
        os.symlink(os.path.join(ROMS, n + ".zip"), os.path.join(rompath, n + ".zip"))
    else:                                   # (the renderer check only: never for game play)
        with zipfile.ZipFile(os.path.join(rompath, n + ".zip"), "w") as z:
            z.writestr(f, bytes(1024))

m = machine.Galaga(skip_tests=True)
m.gfx = g = machine.Gfx()
imgs = {}
cache = lambda f: os.path.join(tempfile.gettempdir(), "galaga_ram_%d.bin" % f)     # the run takes a minute
for f in frames:
    if os.path.exists(cache(f)):
        imgs[f] = open(cache(f), "rb").read()
for f in range(1, max(frames) + 1):
    if len(imgs) == len(frames):
        break
    m.run_frame()
    if f in frames and f not in imgs:
        imgs[f] = bytes(m.ram)
        open(cache(f), "wb").write(imgs[f])
for f in frames:
    out = tempfile.mkdtemp()
    open(os.path.join(out, "ram.bin"), "wb").write(imgs[f])
    env = dict(os.environ, FRAME="400", OUT=out, START="0x8000", END="0x9fff",
               INJECT=os.path.join(out, "ram.bin"))
    mamewin.run(["mame", "galaga", "-window", "-rompath", rompath, "-sound", "none", "-nothrottle",
                    "-seconds_to_run", "250", "-skip_gameinfo", "-autoboot_script",
                    str(ENGINE / "mame_dump.lua"), "-snapshot_directory", out, "-snapname", "shot"],
                   env=env, cwd=out, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    shot = np.array(Image.open(os.path.join(out, "shot.png")).convert("RGB"))
    pens = [tuple(int(l.split()[1][i:i + 2], 16) for i in (0, 2, 4)) for l in open(os.path.join(out, "pens.txt"))]
    mm = open(os.path.join(out, "mem.bin"), "rb").read()
    kept = sum(a == b for a, b in zip(mm, imgs[f]))
    # pen table: characters 0-255, sprites 256-511, stars 512-575
    bad = [i for i in range(256) if tuple(g.rgb[g.char_lut[i]]) != pens[i]]
    bad += [256 + i for i in range(256) if tuple(g.rgb[g.sprite_lut[i]]) != pens[256 + i]]
    bad += [512 + i for i in range(64) if tuple(g.rgb[32 + i]) != pens[512 + i]]
    m.ram[:] = imgs[f]
    m.stars.stars = []
    rgb = m.render_rgb()
    h, w = rgb.shape[:2]
    d = (rgb != shot[:h, :w]).any(axis=2)
    star = d & (rgb == g.rgb[96]).all(axis=2)
    print("frame %d: %d sprites, game rewrote %d of %d RAM bytes, shot %s, %d of %d pens differ, "
          "%d pixels differ (+%d where MAME has a star)" %
          (f, sum(1 for o in range(0, 0x80, 2) if imgs[f][0x1380 + o]), len(mm) - kept, len(mm), shot.shape[:2],
           len(bad), len(pens), (d & ~star).sum(), star.sum()))
    if bad:
        print("  first pens:", [(i, pens[i]) for i in bad[:6]])
    Image.fromarray(np.hstack([rgb, shot[:h, :w]])).save(os.path.join(out, "cmp.png"))
    print("  side by side:", os.path.join(out, "cmp.png"))
