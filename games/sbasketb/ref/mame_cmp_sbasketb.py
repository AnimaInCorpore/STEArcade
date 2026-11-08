"""Super Basketball: the reference board (tools/machine.py) against MAME (WolfMAME 0.248 of the F030Arcade checkout
unless MAME names another executable; MAME runs minimized, engine/mamewin.py).

    python games/sbasketb/ref/mame_cmp_sbasketb.py [frame ...] [--keep DIR]

One MAME run (engine/mame_frames.lua) dumps the main CPU's $2000-$3BFF, the screen and the pens at the frames; the
write-only registers (palette bank $3C20, scroll $3F80, the LS259 $3C80-$3C87) come from the write taps.
(1) render: the reference renderer draws MAME's memory: 0 differing pixels and pens;
(2) logic: the reference machine runs from power-on to the same frames; its RAM against MAME's (the CPU is alone on
    its bus: everything but the bytes the interrupt pushes on the stack matches).
"""
import os
from pathlib import Path
import sys

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools"), str(Path(__file__).resolve().parents[3] / "engine")]
os.environ.setdefault("MAME", r"C:\Arbeit\F030Arcade\third_party\wolfmame-0248\mame.exe")
from machine import SBasket, Video
import mame_cmp as M

# WolfMAME 0.248 has this board's CPU at 1.4 MHz; the authoritative 0.286 source says 18.432 MHz / 12 = 1.536 MHz
# (the reference and the port use 1.536 MHz; the logic comparison runs the reference at the binary's clock)
MAME_HZ = 1400000
# and its DSW2 default has "Starting Score" 70-78 ($08) where the 0.286 source has 100-115 (DSW2 $60)
MAME_DSW2 = 0x68
FRAMES = [60, 300, 600, 900, 1200, 1800, 2400, 3600]
TAPS = ["maincpu:0x3c20:0x3c20", "maincpu:0x3f80:0x3f80", "maincpu:0x3c80:0x3c87"]


def regs(d, f, last):
    """the write-only registers at frame f's end: the state before the frame's writes plus the frame's writes"""
    st = dict(last)
    for k, v in M.load_tap_state(d, f).items():
        st[k[1]] = v
    for tag, line, off, data in M.load_taps(d, f):
        st[off] = data
    return st


def main():
    frames, keep = M.parse_args(FRAMES)
    d = M.run_mame("sbasketb", frames, ["maincpu:0x2000:0x3bff"], taps=TAPS, keep=keep)
    video = Video()
    pens = M.load_pens(d)
    n = min(len(pens), len(video.pens))
    pen_diff = int(np.any(video.pens[:n] != pens[:n], axis=1).sum())
    print("pens: %d of %d differ (MAME has %d)" % (pen_diff, n, len(pens)))
    worst = pen_diff
    m = SBasket(dsw2=MAME_DSW2, hz=MAME_HZ)
    st = {}
    for f in frames:
        mem = M.load_dump(d, f, "maincpu", 0x2000)
        st = regs(d, f, st)
        mem[0x3C20], mem[0x3F80] = st.get(0x3C20, 0), st.get(0x3F80, 0)
        select = st.get(0x3C85, 0) & 1
        rgb = video.render_rgb(mem, bool(st.get(0x3C80, 0) & 1), select=select)
        shot = M.load_shot(d, f)
        k = M.diff_pixels(rgb, shot)
        worst = max(worst, k)
        M.save_compare(d / ("cmp%d.png" % f), rgb, shot)
        while m.frame < f:
            m.run_frame()
        c, tot, first = M.ram_diff(m.mem, mem, [(0x2000, 0x3BFF)])
        print("frame %5d: render %5d pixels differ; logic RAM %4d of %d bytes differ %s; regs pb %02X scroll %02X "
              "(machine %02X %02X)" % (f, k, c, tot, " ".join(first), mem[0x3C20], mem[0x3F80], m.mem[0x3C20],
                                       m.mem[0x3F80]))
    print("compare pictures (reference | MAME | differences) in", d)
    return int(worst != 0)


if __name__ == "__main__":
    sys.exit(main())
