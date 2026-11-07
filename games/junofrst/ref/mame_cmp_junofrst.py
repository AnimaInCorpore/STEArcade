"""Juno First: the reference board (tools/machine.py) against MAME (WolfMAME 0.248: set MAME=...\\wolfmame-0248\\mame.exe).

    python games/junofrst/ref/mame_cmp_junofrst.py [frame ...] [--keep DIR]

One MAME run (engine/mame_frames.lua) dumps the main CPU's $0000-$8FFF (the video RAM, the palette RAM, the RAM), the
screen (ROT90, 224 x 768) and the pens at the frames.
(1) render: the reference renderer draws MAME's memory: 0 differing pixels and pens;
(2) logic: the reference machine runs from power-on to the same frames; its RAM against MAME's (the CPU is alone on
    its bus: everything but the bytes the interrupt pushes on the stack matches).
"""
from pathlib import Path
import os
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools"), str(Path(__file__).resolve().parents[3] / "engine")]
from machine import Juno, Video, pens
import mame_cmp
import numpy as np

def main():
    frames, keep = mame_cmp.parse_args([60, 300, 600, 900, 1200, 1800, 2400, 3600])
    d = mame_cmp.run_mame("junofrst", frames, ["maincpu:0x0:0x8fff"], keep=os.path.abspath(keep) if keep else None,
                          pens_every=True)
    v = Video()
    worst = 0
    m = Juno()
    for f in frames:
        mem = mame_cmp.load_dump(d, f, "maincpu", 0)
        mp = mame_cmp.load_pens(d, f)
        pen_diff = int(np.any(pens(mem[0x8000:0x8010]) != mp, axis=1).sum())
        rgb = v.render_rgb(mem)
        shot = mame_cmp.load_shot(d, f)
        n = mame_cmp.diff_pixels(rgb, shot)
        worst = max(worst, n, pen_diff)
        mame_cmp.save_compare(d / ("cmp%d.png" % f), rgb, shot)
        while m.frame < f:
            m.run_frame()
        k, tot, first = mame_cmp.ram_diff(m.mem, mem, [(0x0000, 0x800F), (0x8100, 0x8FFF)])
        own = mame_cmp.diff_pixels(m.render_rgb(), shot)
        print("frame %5d: %d of 16 pens differ; render %5d pixels differ; logic RAM %5d of %d bytes differ %s; its own "
              "picture %d pixels" % (f, pen_diff, n, k, tot, " ".join(first), own))
    print("compare pictures (reference | MAME | differences) in", d)
    return int(worst != 0)


if __name__ == "__main__":
    sys.exit(main())
