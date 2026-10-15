"""Kung-Fu Master: the reference board (tools/machine.py) against MAME 0.289.

    python games/kungfum/ref/mame_cmp_kungfum.py [frame ...] [--keep DIR]

One MAME run (engine/mame_frames.lua, PAL=:chr_palette) dumps the main CPU's $D000-$EFFF (tile RAM, RAM) at the
frames and taps the write-only registers: the sprite RAM $C000-$C0FF, the scroll $A000/$B000 and the I/O ports 0
(sound command) and 1 (flip); their state at a frame's end is the tap state plus the frame's logged writes.  A second,
short run takes the sprite palette's pens (PAL=:spr_palette).
(1) render: the reference renderer draws MAME's memory and registers: 0 differing pixels and pens;
(2) logic: the reference machine runs from power-on to the same frames: its RAM, sprite RAM and scroll against
    MAME's, and its sound commands of the frame against MAME's port 0 writes.
"""
import os
from pathlib import Path
import sys

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools"), str(Path(__file__).resolve().parents[3] / "engine")]
from machine import KungFuMaster, Video
import mame_cmp as C

RAM = [(0xD000, 0xEFFF)]
DEFAULT = [60, 120, 300, 600, 900, 1200, 1500, 1800, 2100, 2400, 2700, 2987, 3000, 3300, 3600]   # (2987: sound commands)


def registers(d, f):
    """MAME's sprite RAM, scroll, flip and the frame's sound commands at the frame's end (from the taps)."""
    st = C.load_tap_state(d, f)
    spr = bytearray(0x100)
    reg = {}
    for (tag, o), x in st.items():
        if tag == "maincpu" and 0xC000 <= o < 0xC100:
            spr[o - 0xC000] = x
        else:
            reg[(tag, o)] = x
    sound = []
    for tag, line, o, x in C.load_taps(d, f):
        if tag == "maincpu" and 0xC000 <= o < 0xC100:
            spr[o - 0xC000] = x
        else:
            reg[(tag, o)] = x
            if tag == "maincpu:io" and o == 0:
                sound.append(x)
    scroll = reg.get(("maincpu", 0xA000), 0) | reg.get(("maincpu", 0xB000), 0) << 8
    return spr, scroll, reg.get(("maincpu:io", 1), 0), sound


def main():
    frames, keep = C.parse_args(DEFAULT)
    os.environ["PAL"] = ":spr_palette"
    d0 = C.run_mame("kungfum", [2], ["maincpu:0xd000:0xd0ff"])
    spr_pens = C.load_pens(d0)
    os.environ["PAL"] = ":chr_palette"
    d = C.run_mame("kungfum", frames, ["maincpu:0xd000:0xefff"],
                   ["maincpu:0xa000:0xa000", "maincpu:0xb000:0xb000", "maincpu:0xc000:0xc0ff", "maincpu:io:0x00:0x01"],
                   keep=keep)
    pens = np.vstack((C.load_pens(d), spr_pens))
    v = Video()
    pen_diff = int(np.any(v.raw_pens != pens, axis=1).sum())
    print("pens: %d of %d differ (MAME's pen_color: before the contrast, which the snapshot shows)" % (pen_diff,
                                                                                                    len(pens)))
    worst = pen_diff
    k = KungFuMaster()
    sound_at = 0
    first_ram = None
    for f in frames:
        mem = C.load_dump(d, f, "maincpu", 0xD000)
        spr, scroll, flip, sound = registers(d, f)
        if flip & 1:
            print("frame %d: flip screen written 1" % f)
        rgb = v.render_rgb(mem, spr, scroll)
        shot = C.load_shot(d, f)
        n = C.diff_pixels(rgb, shot)
        worst = max(worst, n)
        C.save_compare(d / ("cmp%d.png" % f), rgb, shot)
        while k.frame < f:
            k.run_frame()
        kr, tot, first = C.ram_diff(k.mem, mem, RAM)
        ks = sum(a != b for a, b in zip(k.sprite_ram, spr))
        mine = [x for fr, x in k.sound_log if fr == f - 1]
        if (kr or ks or k.scroll != scroll or mine != sound) and first_ram is None:
            first_ram = f
        own = C.diff_pixels(k.render_rgb(), shot)
        print("frame %5d: render %5d pixels differ (scroll %04X); logic RAM %4d of %d bytes differ %s, sprite RAM %3d, "
              "scroll %s, sound %s (%d); its own picture %d pixels" % (
                  f, n, scroll, kr, tot, " ".join(first), ks, "ok" if k.scroll == scroll else "%04X" % k.scroll,
                  "ok" if mine == sound else "%s vs %s" % (mine, sound), len(sound), own))
    print("compare pictures (reference | MAME | differences) in", d)
    if first_ram is not None:
        print("logic: first differing frame checked", first_ram)
    return int(worst != 0)


if __name__ == "__main__":
    sys.exit(main())
