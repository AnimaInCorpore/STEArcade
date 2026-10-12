"""Mr. HELI: the M72 reference renderer (engine/m72.py) against MAME 0.289.

    python games/mrheli/ref/mame_cmp_mrheli.py [frame ...] [--keep DIR]

Needs games/mrheli/tools/prepare.py first (with the MCU program: build/mrheli/mame_roms).  One MAME run
(engine/m72_mame.py) captures the frames (title, demo play in the first stages: sky, cave with two raster splits,
castle) and the frame before each; the renderer draws MAME's memory per raster band: 0 differing pixels and pens.
"""
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools"), str(Path(__file__).resolve().parents[3] / "engine")]
from machine import Video
import mame_cmp
import m72_mame
import prepare

FRAMES = [600, 1200, 1500, 2100, 2700, 3300, 3900, 4500, 4800, 5100, 5400, 6300, 6900, 7200, 7800, 8100, 8700]

if __name__ == "__main__":
    frames, keep = mame_cmp.parse_args(FRAMES)
    sys.exit(m72_mame.compare("mrheli", Video(), frames, prepare.MAME_ROMS, keep))
