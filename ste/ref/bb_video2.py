"""Changed 8x8 cells per frame (pixel compare of consecutive frames) in play.  python ref/bb_video2.py"""
import os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from bublbobl import Bublbobl
m = Bublbobl()
prev = None; res = []
for f in range(1500):
    m.in0 = 0x03 | (0x04 if 700 <= f < 706 else 0)
    m.in1 = 0xFF & ~(0x40 if 760 <= f < 766 else 0)
    if f > 900:
        m.in1 &= ~(0x02 if (f // 50) % 2 else 0x01)
        if f % 30 < 3: m.in1 &= ~0x20
        if f % 90 < 3: m.in1 &= ~0x10
    m.run_frame_port()
    if f >= 1100:
        raw = m.render_raw()
        pal = m.palette_rgb()
        rgb = pal[np.where(raw == 255, 0, raw)]
        if prev is not None:
            d = (rgb != prev).any(axis=2)
            cells = d.reshape(28, 8, 32, 8).any(axis=(1, 3))
            res.append(int(cells.sum()))
        prev = rgb
print("changed cells per frame: mean %.1f max %d min %d" % (np.mean(res), max(res), min(res)))
print(res[:60])
