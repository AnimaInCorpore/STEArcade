"""Compare tools/machine.py render_raw() with MAME pixel by pixel (the check every reference gets, docs/porting-guide.md).

    python port.py mame mario [frames...] [--keep DIR]       # default 700 1500 2500

One MAME run (engine/mame_frames.lua through engine/mame_cmp.py; MAME in the MAME environment variable, default the
wolfmame-0248 of the F030Arcade checkout; ROM zips in assets/roms) dumps $6000-$77FF and the screenshot at each frame
and logs the writes to the scroll register ($7D00) and the LS259 latch ($7E80-$7E87): the reference renders the dumped
memory with the latches' values at the frame's end and the number of differing pixels is printed (0 = equal to MAME).
"""
import os
import sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "..", "tools"), os.path.join(HERE, "..", "..", "..", "engine")]
os.environ.setdefault("MAME", r"C:\Arbeit\F030Arcade\third_party\wolfmame-0248\mame.exe")
import mame_cmp
import machine
from mario_pens import PENS

frames, keep = mame_cmp.parse_args([700, 1500, 2500])
d = mame_cmp.run_mame("mario", frames, ["maincpu:0x6000:0x77ff"],
                      taps=["maincpu:0x7d00:0x7d00", "maincpu:0x7e80:0x7e87"], keep=keep)
pal = np.array([[(c >> 16) & 255, (c >> 8) & 255, c & 255] for c in PENS], np.uint8)
assert (mame_cmp.load_pens(d)[:256] == pal).all(), "tools/mario_pens.py differs from this MAME's palette"
for f in frames:
    shot = mame_cmp.load_shot(d, f)
    m = machine.Mario()
    m.gfx = machine.Gfx()
    mem = mame_cmp.load_dump(d, f, "maincpu", 0x6000)
    m.ram[:] = mem[0x6000:0x7800]
    state = mame_cmp.load_tap_state(d, f)
    reg = {a: state.get(("maincpu", a), 0) for a in [0x7d00] + list(range(0x7e80, 0x7e88))}
    for tag, line, off, data in mame_cmp.load_taps(d, f):
        reg[off] = data
    m.scroll = reg[0x7d00]
    m.latch = [reg[0x7e80 + i] & 1 for i in range(8)]
    rgb = pal[m.render_raw()][16:240]
    n = mame_cmp.diff_pixels(rgb, shot)
    print("frame %d: scroll $%02X latch %s: %d of %d pixels differ" % (f, m.scroll, "".join(map(str, m.latch)), n, shot.shape[0] * shot.shape[1]))
    if n:
        mame_cmp.save_compare(os.path.join(str(d), "cmp%d.png" % f), rgb, shot)
