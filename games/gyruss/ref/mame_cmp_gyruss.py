"""Gyruss: the reference board (tools/machine.py) against MAME 0.289.

    python games/gyruss/ref/mame_cmp_gyruss.py [frame ...] [--keep DIR]

One MAME run (engine/mame_frames.lua) dumps, at each frame f and f - 1, the main CPU's $8000-$A7FF and the sub CPU's
$4000-$47FF, logs the sprite RAM writes with the beam's line, and takes the screen and the pens.
(1) render: the reference renderer draws MAME's memory; the sprites per band of lines as MAME's partial updates
    drew them (the sprite RAM at f - 1 plus the logged writes): 0 differing pixels and pens;
(2) logic: the reference machine runs from power-on to the same frames; its RAM against MAME's (two CPUs on a shared
    RAM, interleaved differently from MAME: equal bytes count how far the logic follows).
"""
from pathlib import Path
import sys

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools"), str(Path(__file__).resolve().parents[3] / "engine")]
from machine import Gyruss, Video, sprite_bands
import mame_cmp as C

MAIN_RAM = [(0x8000, 0x87FF), (0x9000, 0xA7FF)]
SUB_RAM = [(0x4000, 0x47FF)]


def main():
    frames, keep = C.parse_args([60, 300, 600, 900, 1200, 1800, 2400, 3600])
    allf = sorted(set(frames) | {f - 1 for f in frames})
    d = C.run_mame("gyruss", allf, ["maincpu:0x8000:0xa7ff", "sub:0x4000:0x47ff"], ["sub:0x4040:0x40ff"], keep=keep)
    v = Video()
    pens = C.load_pens(d)
    pen_diff = int(np.any(v.pens != pens, axis=1).sum())
    print("pens: %d of %d differ" % (pen_diff, len(pens)))
    worst = pen_diff
    g = Gyruss()
    for f in frames:
        mem = C.load_dump(d, f, "maincpu", 0x8000)
        sub = C.load_dump(d, f, "sub", 0x4000)
        prev = C.load_dump(d, f - 1, "sub", 0x4000)
        writes = [(line, off - 0x4040, x) for tag, line, off, x in C.load_taps(d, f)]
        bands = sprite_bands(prev[0x4040:0x4100], writes)
        rgb = v.render_rgb(mem, bands)
        shot = C.load_shot(d, f)
        n = C.diff_pixels(rgb, shot)
        worst = max(worst, n)
        C.save_compare(d / ("cmp%d.png" % f), rgb, shot)
        while g.frame < f:
            g.run_frame()
        k1, t1, f1 = C.ram_diff(g.mem, mem, MAIN_RAM)
        k2, t2, f2 = C.ram_diff(g.sub_mem, sub, SUB_RAM)
        own = C.diff_pixels(g.render_rgb(), shot)
        print("frame %5d: render %5d pixels differ (%d sprite bands); logic RAM main %4d of %d, sub %4d of %d bytes "
              "differ %s; its own picture %d pixels" % (f, n, len(bands), k1, t1, k2, t2, " ".join(f1[:4] + f2[:4]), own))
    print("compare pictures (reference | MAME | differences) in", d)
    return int(worst != 0)


if __name__ == "__main__":
    sys.exit(main())
