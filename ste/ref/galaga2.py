"""Galaga reference probe: what the sound CPU writes while booting, and whether the game
runs the same when it is stopped after its boot.  python ref/galaga2.py"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import numpy as np
from galaga import Galaga

IDLE3 = 0x00B9


def script(m, f):
    """the same inputs for both machines: coin at 1500, start, then play"""
    m.in0 = m.in1 = 0xff
    if 1500 <= f < 1506: m.in1 &= ~0x10
    if 1540 <= f < 1546: m.in1 &= ~0x04
    if f >= 1560:
        g = f - 1560
        if (g // 40) % 2: m.in0 &= ~0x02
        else: m.in0 &= ~0x08
        if g % 20 < 3: m.in1 &= ~0x01


full = Galaga()
cut = Galaga()
writes3 = []
orig = cut.writer(2)
cut.cpus[2].wr8 = lambda a, v: (writes3.append((cut.frame, a, v)), orig(a, v))
stopped = None
first_diff = None
for f in range(2400):
    script(full, f)
    script(cut, f)
    full.run_frame()
    cut.run_frame()
    if stopped is None and not cut.held[2] and cut.cpus[2].pc == IDLE3:
        stopped = f
        cut.held[2] = True
        w = sorted(set(a for _, a, _ in writes3 if a >= 0x8000))
        print("CPU3 reached its idle loop in frame", f, "after writing", len(writes3), "bytes to",
              "%04X-%04X" % (w[0], w[-1]) if w else "nothing", "(%d addresses)" % len(w))
        print("  shared RAM outside its own area:", ["%04X=%02X" % (a, v) for _, a, v in writes3 if 0x8000 <= a and not (0x9c00 <= a) and a not in range(0x9000, 0x9020)][:20])
    if f in (1300, 1480, 1700, 2000, 2399):
        a, b = full.render_raw(), cut.render_raw()
        same = np.array_equal(a, b)
        print("frame %d: screens %s, main pcs %04X/%04X" % (f, "same" if same else "DIFFER (%d px)" % int((a != b).sum()), full.cpus[0].pc, cut.cpus[0].pc))
print("full run: credits", full.n51.credits, "mode", full.n51.mode)
