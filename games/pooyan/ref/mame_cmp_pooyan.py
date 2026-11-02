"""Pooyan: the reference board (tools/machine.py) against MAME 0.289.

    python games/pooyan/ref/mame_cmp_pooyan.py [frame ...] [--keep DIR]

One MAME run (engine/mame_frames.lua) dumps the main CPU's $8000-$94FF (colour and video RAM, RAM, the two sprite
RAMs), the screen and the pens at the frames.
(1) render: the reference renderer draws MAME's memory: 0 differing pixels and pens;
(2) logic: the reference machine (MAME's schedule, Pooyan.run_frame) from power-on to the same frames: its RAM against
    MAME's, without the stack ($8FC0-$8FFF: the bytes the NMI pushes differ, the CPU is alone on its bus).
Result (2026-11-01, MAME 0.289): pens 0 of 512, every frame's picture 0 pixels, RAM equal.
ref/mame_avi_cmp.py is the Windows variant (WolfMAME 0.162's AVI, every frame of the attract mode).
"""
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools"), str(Path(__file__).resolve().parents[3] / "engine")]
from machine import Pooyan, Video
import mame_cmp

if __name__ == "__main__":
    sys.exit(mame_cmp.single_cpu("pooyan", Pooyan, Video(), (0x8000, 0x94FF),
                                 [(0x8000, 0x8FBF), (0x9010, 0x903F), (0x9410, 0x943F)],
                                 [60, 300, 600, 900, 1200, 1800, 2400, 3600]))
