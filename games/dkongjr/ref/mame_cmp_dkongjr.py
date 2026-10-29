"""The reference renderer (tools/machine.py render_raw() through tools/dkongjr_pens.py) against MAME's own picture.

    python mame_cmp_dkongjr.py [frames...]       # default 300 700 1200 1700 2100 2400 2800 5000 (the last two: the title)

The authoritative MAME is the 0.286 source (AGENTS.md); no 0.286 binary with the Donkey Kong driver is installed, so
this runs WolfMAME 0.184 ($MAME, default F030Arcade-private's mamearcade64.exe), whose dkongjr code is the same where it
makes the picture: dkong2b_palette, the resistor nets, compute_res_net, palette_t::normalize_range, the tile info,
draw_sprites, screen_update_dkong and the ROM set differ only in syntax (checked 2026-10-29).  ref/mame184_dump.lua
(0.184's Lua API) writes $6000-$7FFF and a snapshot at each frame; the latches ($7D82-$7D87, $7C80) can not be read
back, so the palette bank, the sprite bank and the tile bank are searched (the best of the 16).  The memory is read
after the frame was drawn, so a moving sprite can be a step ahead: the frames are the attract mode (no coin), where
MAME and the reference agree on what is shown.  The colours are compared as RGB: the check covers dkongjr_pens.py too.
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
import mamewin                       # (MAME on its own desktop: never a window or the focus)
from paths import ROMS

MAME = os.environ.get("MAME", r"C:\Arbeit\F030Arcade-private\third_party\wolfmame-0184\mamearcade64.exe")


def run_mame(frames, out):
    env = dict(os.environ, FRAMES=",".join(str(f) for f in frames), OUT=out)
    kw = {}
    mamewin.run([MAME, "dkongjr", "-window", "-rompath", str(ROMS), "-sound", "none", "-nothrottle",
                    "-seconds_to_run", "250", "-skip_gameinfo", "-autoboot_script", os.path.join(HERE, "mame184_dump.lua"),
                    "-snapshot_directory", out, "-snapname", "%i", "-nvram_directory", os.path.join(out, "nv"),
                    "-cfg_directory", os.path.join(out, "cfg")],
                   env=env, cwd=out, check=True, capture_output=True, timeout=600, **kw)


def main():
    frames = sorted(int(a) for a in sys.argv[1:]) or [300, 700, 1200, 1700, 2100, 2400, 2800, 5000]
    out = tempfile.mkdtemp(prefix="dkjr_mame_")
    run_mame(frames, out)
    d = machine.DKongJr()
    d.gfx = machine.Gfx()
    pal = np.array(d.gfx.pens, np.uint8)
    d.flip = 1                  # the upright game keeps $7D82 at 1: MAME's picture, not rotated back
    bad = 0
    for i, f in enumerate(frames):
        shot = np.array(Image.open(os.path.join(out, "%04d.png" % i)).convert("RGB"))
        d.mem[0x6000:0x8000] = open(os.path.join(out, "mem_%d.bin" % f), "rb").read()
        res = []
        for tb in range(2):
            for pb in range(4):
                for sb in range(2):
                    d.gfx_bank, d.palette_bank, d.sprite_bank = tb, pb, sb
                    rgb = pal[d.render_raw()][16:240].transpose(1, 0, 2)[::-1][::-1, ::-1]
                    if rgb.shape != shot.shape:
                        raise SystemExit("MAME's snapshot is %s, the reference %s" % (shot.shape, rgb.shape))
                    res.append((int((rgb != shot).any(axis=2).sum()), tb, pb, sb))
        best = min(res)
        bad += best[0] > 0
        print("frame %d: %d of %d pixels differ (tile bank %d, palette bank %d, sprite bank %d)" %
              (f, best[0], shot.shape[0] * shot.shape[1], best[1], best[2], best[3]))
        if best[0]:
            d.gfx_bank, d.palette_bank, d.sprite_bank = best[1:]
            rgb = pal[d.render_raw()][16:240].transpose(1, 0, 2)[::-1][::-1, ::-1]
            diff = np.where((rgb != shot).any(axis=2)[..., None], np.uint8([255, 0, 255]), shot)
            Image.fromarray(np.concatenate([shot, rgb, diff], axis=1)).save(os.path.join(out, "diff_%d.png" % f))
            print("   %s" % os.path.join(out, "diff_%d.png" % f))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
