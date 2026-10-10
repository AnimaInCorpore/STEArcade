"""Object list statistics: active objects, tile-aligned ones, how many change per frame, tiles drawn.
python ref/probes/video1.py <frames>"""
import os, sys
from collections import Counter
import numpy as np
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "engine")]
from machine import Bublbobl, load
m = Bublbobl()
prom = load("a71-25.41")
N = int(sys.argv[1])
prev_o = None; prev_v = None
stats = []
order_viol = 0
for f in range(N):
    m.in0 = 0x03 | (0x04 if 700 <= f < 706 else 0)
    m.in1 = 0xFF & ~(0x40 if 760 <= f < 766 else 0)
    if f > 900:
        m.in1 &= ~(0x02 if (f // 50) % 2 else 0x01)
        if f % 30 < 3: m.in1 &= ~0x20
        if f % 90 < 3: m.in1 &= ~0x10
    m.run_frame_port()
    if f < 900 or f % 3: continue
    o = bytes(m.oram); v = bytes(m.vram)
    objs = []
    for i in range(0, 0x300, 4):
        if o[i:i+4] == b"\0\0\0\0": continue
        gfx_num, attr = o[i+1], o[i+3]
        x = o[i+2] - (256 if attr & 0x40 else 0); y = (-o[i]) & 0xFF
        page = ((gfx_num & 0x1f) * 0x80) | (0x1000 if (gfx_num & 0xa0) == 0xa0 else 0)
        pl = 0x80 + ((gfx_num & 0xE0) >> 1)
        rows = sum(1 for yc in range(32) if not prom[pl + yc // 2] & 8)
        objs.append((i // 4, x, y, page, gfx_num >> 5, rows))
    n = len(objs)
    al = sum(1 for (_, x, y, *_r) in objs if x % 8 == 0 and y % 8 == 0)
    chg_o = sum(1 for i in range(0, 0x300, 4) if prev_o and o[i:i+4] != prev_o[i:i+4])
    chg_v = sum(1 for p in range(0, len(v), 0x80) if prev_v and v[p:p+0x80] != prev_v[p:p+0x80])
    # order: unaligned object followed (later in the list) by an aligned one
    first_un = next((k for k, (_, x, y, *_r) in enumerate(objs) if not (x % 8 == 0 and y % 8 == 0)), None)
    viol = first_un is not None and any(x % 8 == 0 and y % 8 == 0 for (_, x, y, *_r) in objs[first_un:])
    tiles = sum(r * 2 for (*_a, r) in objs)
    stats.append((f, n, al, chg_o, chg_v, tiles, viol))
    prev_o, prev_v = o, v
a = np.array([s[1:6] for s in stats])
print("active objects mean/max", a[:,0].mean(), a[:,0].max(), "aligned mean", a[:,1].mean(), "objects changed/frame mean", a[:,2].mean(), "max", a[:,2].max(),
      "vram pages changed mean", a[:,3].mean(), "max", a[:,3].max(), "tile slots mean", a[:,4].mean(), a[:,4].max())
print("frames where an aligned object comes after an unaligned one:", sum(1 for s in stats if s[6]), "of", len(stats))
print(stats[:12])
