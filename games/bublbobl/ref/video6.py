"""Model of the renderer's work: dirty cells (object diff + vram page diff, both buffers), overlap closure,
tile draws.  Counts per frame.  python ref/video6.py <frames> [dbl]"""
import os, sys
import numpy as np
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from machine import Bublbobl, load, decode_tiles
m = Bublbobl()
prom = load("a71-25.41")
tiles = decode_tiles()
opaque = (tiles != 15).any(axis=(1, 2))
fullopaque = (tiles != 15).all(axis=(1, 2))
N = int(sys.argv[1]); DBL = len(sys.argv) > 2

def slots(rec):
    """list of (x, y, voff) for an object record (xin, ynum, num, xraw, attr)"""
    xin, y0, num, xr, attr = rec
    pl = 0x80 + ((num & 0xE0) >> 1)
    go = (num & 0x1F) * 0x80
    if (num & 0xA0) == 0xA0: go |= 0x1000
    sy = -y0
    sx = xin
    out = []
    for yc in range(32):
        p = prom[pl + yc // 2]
        if p & 8: continue
        if not p & 4:
            sx = xr - (256 if attr & 0x40 else 0)
        for xc in range(2):
            out.append((sx + xc * 8, (sy + yc * 8) & 0xFF, go + xc * 0x40 + (yc & 7) * 2 + (p & 3) * 0x10))
    return out, sx

def cells(x, y):
    cs = set()
    for cx in {x >> 3, (x + 7) >> 3}:
        for cy in {y >> 3, (y + 7) >> 3}:
            if 0 <= cx < 32 and 2 <= cy < 30: cs.add((cx, cy))
    return cs

prev_rec = {}; prev_sl = {}; prev_vram = None
dirty_prev = set()
res = []
for f in range(N):
    m.in0 = 0x03 | (0x04 if 700 <= f < 706 else 0)
    m.in1 = 0xFF & ~(0x40 if 760 <= f < 766 else 0)
    if f > 900:
        m.in1 &= ~(0x02 if (f // 50) % 2 else 0x01)
        if f % 30 < 3: m.in1 &= ~0x20
        if f % 90 < 3: m.in1 &= ~0x10
    m.run_frame_port()
    if f < 900: continue
    oram, vram = bytes(m.oram), bytes(m.vram)
    recs = {}; sl = {}
    sx = 0
    for i in range(192):
        e = oram[i * 4:i * 4 + 4]
        if e == b"\0\0\0\0": continue
        rec = (sx, e[0], e[1], e[2], e[3])
        s, sx_end = slots(rec)
        recs[i] = rec; sl[i] = s
        sx = sx_end + 16
    dirty = set()
    for i in set(recs) | set(prev_rec):
        if recs.get(i) != prev_rec.get(i):
            for (x, y, v) in prev_sl.get(i, []): dirty |= cells(x, y)
            for (x, y, v) in sl.get(i, []): dirty |= cells(x, y)
    if prev_vram is not None:
        pages = [p for p in range(0, len(vram), 0x80) if vram[p:p + 0x80] != prev_vram[p:p + 0x80]]
        for i, s in sl.items():
            for (x, y, v) in s:
                if (v & ~0x7F) in pages and vram[v:v + 2] != prev_vram[v:v + 2]:
                    dirty |= cells(x, y)
    cur = set(dirty)
    if DBL: dirty |= dirty_prev
    # closure over unaligned tiles
    un = []
    for i, s in sl.items():
        for (x, y, v) in s:
            if x % 8 or y % 8:
                cs = cells(x, y)
                if cs: un.append(cs)
    changed = True; rounds = 0
    while changed:
        changed = False; rounds += 1
        for cs in un:
            if cs & dirty and not cs <= dirty:
                dirty |= cs; changed = True
    # draws
    aligned_draws = unal_draws = 0
    for i, s in sl.items():
        for (x, y, v) in s:
            cs = cells(x, y)
            if cs & dirty:
                code = vram[v] + 256 * (vram[v + 1] & 3) + 1024 * (recs[i][4] & 15)
                if not opaque[code]: continue
                if x % 8 or y % 8: unal_draws += 1
                else: aligned_draws += 1
    res.append((len(cur), len(dirty), aligned_draws, unal_draws, rounds))
    prev_rec, prev_sl, prev_vram = recs, sl, vram
    dirty_prev = cur
a = np.array(res)
print("frames", len(a), "cur dirty mean %.0f, dirty (with prev) mean %.0f max %d, aligned draws mean %.0f max %d, unaligned draws mean %.0f max %d, rounds mean %.1f" % (
    a[:,0].mean(), a[:,1].mean(), a[:,1].max(), a[:,2].mean(), a[:,2].max(), a[:,3].mean(), a[:,3].max(), a[:,4].mean()))
print("percentiles of dirty:", np.percentile(a[:,1], [50, 75, 90, 99]))
