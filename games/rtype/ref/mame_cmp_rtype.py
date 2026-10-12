"""R-Type: the M72 reference renderer (engine/m72.py) against MAME 0.289.

    python games/rtype/ref/mame_cmp_rtype.py [frame ...] [--keep DIR]

Needs games/rtype/tools/prepare.py first (build/rtype/mame_roms).  One MAME run (engine/m72_mame.py) captures the
frames (title, demo play in stages 1 and 2, the high score table) and the frame before each; the renderer draws
MAME's memory per raster band: 0 differing pixels and pens.  (Before frame ~200 MAME's pens differ from the palette
RAM: pens the game has not written yet keep MAME's default pattern, red/green/blue = pen bits 0/1/2.)
"""
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools"), str(Path(__file__).resolve().parents[3] / "engine")]
from machine import Video
import mame_cmp
import m72_mame
import prepare

FRAMES = [400, 700, 1000, 1300, 1600, 1900, 2200, 2450, 2700, 3000, 3300, 3600, 3900, 4200, 4500, 4800,
          5100, 5400, 5700]

if __name__ == "__main__":
    frames, keep = mame_cmp.parse_args(FRAMES)
    sys.exit(m72_mame.compare("rtype", Video(), frames, prepare.MAME_ROMS, keep))
