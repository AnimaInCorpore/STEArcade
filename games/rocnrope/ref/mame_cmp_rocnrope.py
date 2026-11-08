"""Roc'n Rope: the reference board (tools/machine.py) against MAME (set MAME to a binary that knows rocnrope, e.g.
C:/Arbeit/F030Arcade/third_party/wolfmame-0248/mame.exe).

    python games/rocnrope/ref/mame_cmp_rocnrope.py [frame ...] [--keep DIR]

One MAME run (engine/mame_frames.lua) dumps the main CPU's $4000-$5FFF, the screen and the pens at the frames.
(1) render: the reference renderer draws MAME's memory: 0 differing pixels and pens;
(2) logic: the reference machine runs from power-on to the same frames; its RAM against MAME's (the CPU is alone on
    its bus: everything but the bytes the interrupt pushes on the stack matches).
"""
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools"), str(Path(__file__).resolve().parents[3] / "engine")]
from machine import RocnRope, Video
import mame_cmp

if __name__ == "__main__":
    sys.exit(mame_cmp.single_cpu("rocnrope", RocnRope, Video(), (0x4000, 0x5FFF), [(0x4000, 0x5FFF)],
                                 [60, 300, 600, 900, 1200, 1800, 2400, 3600]))
