"""The port's schedule (run_frame_port) against the interleaved reference: same inputs, screens compared.
python ref/bb_port1.py <frames> [outdir]"""
import os, sys, time
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from bublbobl import Bublbobl, save_png
N = int(sys.argv[1]); out = sys.argv[2] if len(sys.argv) > 2 else "/tmp"
a, b = Bublbobl(), Bublbobl()
def inputs(m, f):
    m.in0 = 0x03 | (0x04 if 700 <= f < 706 else 0)
    m.in1 = 0xFF & ~(0x40 if 760 <= f < 766 else 0)
    if f > 900:
        m.in1 &= ~(0x02 if (f // 50) % 2 else 0x01)
        if f % 30 < 3: m.in1 &= ~0x20
t0 = time.time()
for f in range(N):
    inputs(a, f); inputs(b, f)
    a.run_frame()
    b.run_frame_port()
    if f % 100 == 99:
        ra, rb = a.render_raw(), b.render_raw()
        pa, pb = a.palette_rgb()[np.where(ra == 255, 0, ra)], b.palette_rgb()[np.where(rb == 255, 0, rb)]
        diff = int((ra != rb).sum())
        print("frame", f + 1, "pixels differing", diff, "main pc %04X/%04X" % (a.main.pc, b.main.pc), flush=True)
        if f + 1 in (300, 600, 1000, N):
            save_png(a.render_rgb(), os.path.join(out, "bbA_%d.png" % (f + 1)))
            save_png(b.render_rgb(), os.path.join(out, "bbB_%d.png" % (f + 1)))
print("%.1f s" % (time.time() - t0))
