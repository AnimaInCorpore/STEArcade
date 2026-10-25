"""Time Pilot: the reference board (tools/machine.py) against MAME 0.289.

    python games/timeplt/ref/mame_cmp_timeplt.py [frame ...] [--keep DIR]

One MAME run (engine/mame_frames.lua) dumps the main CPU's $A000-$B7FF at each frame f and f - 1, logs the writes to
$A000-$BFFF with the beam's line, and takes the screen and the pens.  MAME draws the screen line by line
(VIDEO_UPDATE_SCANLINE), and the NMI handler moves the cloud sprites while the beam runs; so the reference renders each
line from the memory at f - 1 plus the writes logged before that line:
(1) render: 0 differing pixels and pens expected;
(2) logic: the reference machine (MAME's schedule, Timeplt.run_frame) from power-on to the same frames: its RAM against
    MAME's (equal bytes count how far the logic follows).
"""
from pathlib import Path
import sys

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools"), str(Path(__file__).resolve().parents[3] / "engine")]
from machine import Timeplt, Video, VISIBLE, VBLANK_LINE
import mame_cmp as C

RAM = [(0xA000, 0xAFFF), (0xB000, 0xB0FF), (0xB400, 0xB4FF)]


def banded(v, prev, writes, before_line=True):
    """The picture [256, 224, 3] drawn line by line: line l from prev plus the writes logged before l (line: the beam;
    >= 240 is the previous VBLANK)."""
    mem = bytearray(prev)
    ws = sorted(((ln if ln < VBLANK_LINE else ln - 256), a, x) for ln, a, x in writes)
    raw = np.zeros((256, 256), np.int16)
    i = 0
    cache = None
    for line in range(VISIBLE[2], VISIBLE[3] + 1):
        changed = False
        while i < len(ws) and (ws[i][0] < line if before_line else ws[i][0] <= line):
            _, a, x = ws[i]
            mem[a] = x
            i += 1
            changed = True
        if cache is None or changed:
            cache = v.render_raw(mem)
        raw[line] = cache[line]
    rgb = v.pens[raw[VISIBLE[2]:VISIBLE[3] + 1]]
    return np.ascontiguousarray(np.rot90(rgb, -1))


def main():
    frames, keep = C.parse_args([60, 300, 600, 900, 1200, 1800, 2400, 3600])
    allf = sorted(set(frames) | {f - 1 for f in frames})
    d = C.run_mame("timeplt", allf, ["maincpu:0xa000:0xb7ff"], ["maincpu:0xa000:0xbfff"], keep=keep)
    v = Video()
    pens = C.load_pens(d)
    pen_diff = int(np.any(v.pens != pens[:len(v.pens)], axis=1).sum())
    print("pens: %d of %d differ (MAME has %d)" % (pen_diff, len(v.pens), len(pens)))
    worst = pen_diff
    g = Timeplt()
    for f in frames:
        mem = C.load_dump(d, f, "maincpu", 0xA000)
        prev = C.load_dump(d, f - 1, "maincpu", 0xA000)
        writes = [(line, 0xB000 | (off & 0x4FF) if off >= 0xB000 else off, x)
                  for tag, line, off, x in C.load_taps(d, f)]
        shot = C.load_shot(d, f)
        n0 = C.diff_pixels(banded(v, prev, writes, True), shot)
        n1 = C.diff_pixels(banded(v, prev, writes, False), shot)
        rgb = banded(v, prev, writes, n0 <= n1)
        n = min(n0, n1)
        worst = max(worst, n)
        C.save_compare(d / ("cmp%d.png" % f), rgb, shot)
        while g.frame < f:
            g.run_frame()
        k, tot, first = C.ram_diff(g.mem, mem, RAM)
        print("frame %5d: render %5d pixels differ (writes before the line %d, up to it %d; %d writes); logic RAM "
              "%4d of %d bytes differ %s" % (f, n, n0, n1, len(writes), k, tot, " ".join(first)))
    print("compare pictures (reference | MAME | differences) in", d)
    return int(worst != 0)


if __name__ == "__main__":
    sys.exit(main())
