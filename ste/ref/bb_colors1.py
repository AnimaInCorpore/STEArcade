"""Colours on screen per frame: distinct palette indices and distinct RGB values (whole screen,
top 16 lines, the rest).  python ref/bb_colors1.py <frames>  (coin + start after 1500 frames)"""
import os, sys
from collections import Counter
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from bublbobl import Bublbobl, save_png
m = Bublbobl()
N = int(sys.argv[1])
hist = Counter(); worst = (0, 0)
for f in range(N):
    m.in0 = 0x03 | (0x04 if 1500 <= f < 1506 else 0)
    m.in1 = 0xFF & ~(0x40 if 1560 <= f < 1566 else 0)
    if f > 1700:
        m.in1 &= ~(0x02 if (f // 50) % 2 else 0x01)
        if f % 30 < 3: m.in1 &= ~0x20
    m.run_frame()
    raw = m.render_raw()
    rgb = m.palette_rgb()
    vis = raw != 255
    n_all = len({tuple(rgb[i]) for i in np.unique(raw[vis])}) if vis.any() else 0
    top = raw[:16]; rest = raw[16:]
    n_top = len({tuple(rgb[i]) for i in np.unique(top[top != 255])}) if (top != 255).any() else 0
    n_rest = len({tuple(rgb[i]) for i in np.unique(rest[rest != 255])}) if (rest != 255).any() else 0
    hist[(n_all, n_top, n_rest)] += 1
    if n_all > worst[0]:
        worst = (n_all, f); save_png(m.render_rgb(), "/tmp/bb_worst.png")
print("worst", worst)
tot = Counter()
for (a, t, r), c in hist.items(): tot[a] += c
print("distinct RGB per frame (all):", sorted(tot.items()))
tot = Counter()
for (a, t, r), c in hist.items(): tot[r] += c
print("distinct RGB per frame below the top 16 lines:", sorted(tot.items()))
