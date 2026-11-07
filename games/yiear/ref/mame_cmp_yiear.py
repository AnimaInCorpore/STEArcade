"""Yie Ar Kung-Fu: the reference board (tools/machine.py) against MAME.

    python games/yiear/ref/mame_cmp_yiear.py [frame ...] [--keep DIR]

One MAME run (engine/mame_frames.lua; MAME in the MAME environment variable, default the wolfmame-0248 of the
F030Arcade checkout, started minimized through engine/mamewin.py) dumps the main CPU's $5000-$5FFF, the screen and the
pens at the frames.
(1) render: the reference renderer draws MAME's memory: 0 differing pixels and pens;
(2) logic: the reference machine runs from power-on to the same frames; its RAM against MAME's (the CPU is alone on
    its bus: everything but the bytes the interrupt pushes on the stack matches).
Palette: the 0.286 source (the authority, AGENTS.md) weighs the blue PROM bits 0x52 / 0xAD, the wolfmame-0248 binary
0x47 / 0x97 (red and green agree); the port uses the source's, and this check compares with the binary's blue.
"""
import os
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools"), str(Path(__file__).resolve().parents[3] / "engine")]
os.environ.setdefault("MAME", r"C:\Arbeit\F030Arcade\third_party\wolfmame-0248\mame.exe")
from machine import YieAr, Video
import mame_cmp

if __name__ == "__main__":
    sys.exit(mame_cmp.single_cpu("yiear", YieAr, Video(blue=(0x47, 0x97)), (0x5000, 0x5FFF), [(0x5000, 0x5FFF)],
                                 [60, 300, 600, 900, 1200, 1800, 2400, 3600]))
