"""Mikie: the reference board (tools/machine.py) against MAME.

    python games/mikie/ref/mame_cmp_mikie.py [frame ...] [--keep DIR]

One MAME run (engine/mame_frames.lua) dumps the main CPU's $0000-$00FF and $2800-$3FFF, the screen and the pens at the
frames.  The palette bank latch ($2200) is write-only: it is read from the reference machine's run, which sets it from
the same program, and the render check tries every bank and reports the best (a bank mismatch shows as wrong colours).
(1) render: the reference renderer draws MAME's memory: 0 differing pixels and pens;
(2) logic: the reference machine runs from power-on to the same frames; its RAM against MAME's.
The MAME binary is the one of the MAME environment variable (WolfMAME 0.248 under F030Arcade/third_party/wolfmame-0248;
the ROM set is assets/roms/mikie.zip).
"""
from pathlib import Path
import sys

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools"), str(Path(__file__).resolve().parents[3] / "engine")]
from machine import Mikie, Video
import mame_cmp

DUMP = (0x2800, 0x3FFF)
RAM = [(0x2800, 0x3FFF)]


def main():
    frames, keep = mame_cmp.parse_args([60, 300, 600, 900, 1200, 1800, 2400, 3600])
    d = mame_cmp.run_mame("mikie", frames, ["maincpu:0x%x:0x%x" % DUMP, "maincpu:0x0:0xff"], keep=keep)
    video = Video()
    pens = mame_cmp.load_pens(d)
    pen_diff = int(np.any(video.pens != pens, axis=1).sum())
    print("pens: %d of %d differ" % (pen_diff, len(pens)))
    worst = pen_diff
    m = Mikie()
    for f in frames:
        mem = mame_cmp.load_dump(d, f, "maincpu", DUMP[0], space="program")
        mem = mame_cmp.load_dump(d, f, "maincpu", 0, into=mem)
        shot = mame_cmp.load_shot(d, f)
        while m.frame < f:
            m.run_frame()
        counts = {b: mame_cmp.diff_pixels(video.render_rgb(mem, b), shot) for b in range(8)}
        best = min(counts, key=counts.get)
        n = counts[m.palbank]
        worst = max(worst, n)
        mame_cmp.save_compare(d / ("cmp%d.png" % f), video.render_rgb(mem, m.palbank), shot)
        k, tot, first = mame_cmp.ram_diff(m.mem, mem, RAM + [(0, 0xFF)])
        own = mame_cmp.diff_pixels(m.render_rgb(), shot)
        print("frame %5d: render %5d pixels differ (bank %d; best bank %d: %d); logic RAM %4d of %d bytes differ %s; "
              "its own picture %d pixels" % (f, n, m.palbank, best, counts[best], k, tot, " ".join(first), own))
    print("compare pictures (reference | MAME | differences) in", d)
    return int(worst != 0)


if __name__ == "__main__":
    sys.exit(main())
