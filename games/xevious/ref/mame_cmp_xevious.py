"""Super Xevious: the reference board (tools/machine.py) against MAME (set sxevious).

    python games/xevious/ref/mame_cmp_xevious.py [frame ...] [--keep DIR]

One MAME run (engine/mame_frames.lua) dumps, at each frame, the main CPU's $7800-$CFFF (the shared RAM, the sprite
registers and the four tile RAMs), logs the writes of both CPUs to the scroll / flip latch ($D000-$D07F; the sub CPU writes the scrolls) and takes the screen and the
pens.  (1) render: the reference renderer draws MAME's memory with the latch registers as they stand at the frame's end
(the last values before the frame plus its logged writes): 0 differing pixels and pens;  (2) logic: the reference machine
runs from power-on in MAME's phase (frame_line 224): its RAM against MAME's at the same frames, counted (the three CPUs
are interleaved differently from MAME's scheduler; equal bytes show how far the logic follows).

MAME: WolfMAME 0.248 (F030Arcade/third_party/wolfmame-0248/mame.exe) answers MAME=...; the sets are in assets/roms
(sxevious.zip, namco50.zip, namco51.zip, namco54.zip).  Run it through engine/mamewin.py (mame_cmp does).
"""
from pathlib import Path
import sys

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools"), str(Path(__file__).resolve().parents[3] / "engine")]
import machine
import mame_cmp as C

RAM = [(0x7800, 0x7fff), (0x8000, 0x87ff), (0x9000, 0x97ff), (0xa000, 0xa7ff), (0xb000, 0xcfff)]


def main():
    frames, keep = C.parse_args([700, 1200, 2000, 3000, 4500])
    allf = sorted(set(frames) | {f - 1 for f in frames})        # (a frame's taps cover the interval since the one before)
    d = C.run_mame("sxevious", allf, ["maincpu:0x7800:0xcfff"], ["maincpu:0xd000:0xd07f", "sub:0xd000:0xd07f", "sub2:0xd000:0xd07f"], keep=keep)
    g = machine.Gfx()
    pens = C.load_pens(d)
    ours = np.array(g.palette, np.uint8)
    # MAME's pens: 1152 pens (the indirect palette's 128 + black behind); the display's colours are the 129
    pen_diff = 0
    lut = list(g.bg_lut) + [0] * 0
    seen = pens.shape[0]
    mame_rgb = {}
    for i in range(min(seen, 1152)):
        mame_rgb[i] = tuple(pens[i])
    # every pen the renderer can output (a bg pen, a sprite pen, a foreground pen) must have MAME's colour
    expect = {}
    for i in range(512):
        expect[i] = g.palette[g.bg_lut[i]]
        c = g.sprite_lut[i]
        expect[512 + i] = g.palette[c]
    for i in range(128):
        expect[1024 + i] = g.palette[(i >> 1) if i & 1 else 128]
    for p, rgb in expect.items():
        if p in mame_rgb and tuple(mame_rgb[p]) != tuple(rgb):
            pen_diff += 1
    print("pens: %d of %d differ" % (pen_diff, len(expect)))
    worst = pen_diff
    m = machine.Xevious(skip_tests=False)
    m.gfx = g
    for f in frames:
        mem = C.load_dump(d, f, "maincpu", 0x7800)
        state = {}                                 # per latch register (two addresses reach each): the last write
        for (t, o), x in C.load_tap_state(d, f).items():
            state[(o - 0xd000) >> 4] = (o & 1) << 8 | x
        for t, line, off, x in sorted(C.load_taps(d, f), key=lambda w: w[1]):
            state[(off - 0xd000) >> 4] = (off & 1) << 8 | x
        r = machine.Xevious()
        r.gfx = g
        r.mem[:] = mem
        for reg, x in state.items():
            r.vh_latch(reg << 4, x & 0xff)          # (the register's bit 8 is the address bit A0)
            r.vh_latch((reg << 4) | (x >> 8), x & 0xff)
        rgb = r.render_rgb()
        shot = C.load_shot(d, f)
        n = C.diff_pixels(rgb, shot)
        worst = max(worst, n)
        C.save_compare(d / ("cmp%d.png" % f), rgb, shot)
        while m.frame < f:
            m.run_frame()
        k, tot, first = C.ram_diff(m.mem, mem, RAM)
        own = C.diff_pixels(m.render_rgb(), shot)
        print("frame %5d: render %5d pixels differ (scroll %s flip %d); logic RAM %4d of %d bytes differ %s; its own picture %d pixels"
              % (f, n, r.scroll, r.flip, k, tot, " ".join(first[:4]), own), flush=True)
    print("compare pictures (reference | MAME | differences) in", d)
    return int(worst != 0)


if __name__ == "__main__":
    sys.exit(main())
