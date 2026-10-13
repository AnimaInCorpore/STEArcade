"""R-Type: the M72 board (engine/m72board.py) from power-on against MAME 0.289's memory at the frames.

    python games/rtype/ref/logic_rtype.py [frame ...] [--keep DIR]
"""
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools"), str(Path(__file__).resolve().parents[3] / "engine")]
import mame_cmp
import m72_mame
import prepare

FRAMES = [30, 60, 120, 200, 300, 400, 700, 1000]

if __name__ == "__main__":
    frames, keep = mame_cmp.parse_args(FRAMES)
    sys.exit(m72_mame.logic("rtype", frames, prepare.MAME_ROMS, keep))
