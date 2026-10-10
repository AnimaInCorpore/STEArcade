"""Do tile layers (tile-aligned tiles) and sprites (unaligned tiles) keep a fixed z-order?  For every cell: is an
aligned opaque tile ever drawn after an unaligned one?  python ref/probes/video5.py <frames>"""
import os, sys
import numpy as np
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "engine")]
from machine import Bublbobl, load, decode_tiles
m = Bublbobl()
prom = load("a71-25.41")
tiles = decode_tiles()
opaque = (tiles != 15).any(axis=(1, 2))
N = int(sys.argv[1])
viol = 0; frames = 0; tot_unal = 0; ex = []
for f in range(N):
    m.in0 = 0x03 | (0x04 if 700 <= f < 706 else 0)
    m.in1 = 0xFF & ~(0x40 if 760 <= f < 766 else 0)
    if f > 900:
        m.in1 &= ~(0x02 if (f // 50) % 2 else 0x01)
        if f % 30 < 3: m.in1 &= ~0x20
        if f % 90 < 3: m.in1 &= ~0x10
    m.run_frame_port()
    if f < 650 or f % 5: continue
    frames += 1
    cells = {}
    sx = 0
    oram, vram = m.oram, m.vram
    for offs in range(0, 0x300, 4):
        if oram[offs:offs + 4] == b"\0\0\0\0": continue
        gfx_num, attr = oram[offs + 1], oram[offs + 3]
        pl = 0x80 + ((gfx_num & 0xE0) >> 1)
        go = (gfx_num & 0x1F) * 0x80
        if (gfx_num & 0xA0) == 0xA0: go |= 0x1000
        sy = -oram[offs]
        rows = sum(1 for yc in range(32) if not prom[pl + yc // 2] & 8)
        for yc in range(32):
            p = prom[pl + yc // 2]
            if p & 8: continue
            if not p & 4:
                sx = oram[offs + 2]
                if attr & 0x40: sx -= 256
            for xc in range(2):
                g = go + xc * 0x40 + (yc & 7) * 2 + (p & 3) * 0x10
                code = vram[g] + 256 * (vram[g + 1] & 3) + 1024 * (attr & 15)
                if not opaque[code]: continue
                x = sx + xc * 8; y = (sy + yc * 8) & 0xFF
                al = True
                for cx in {x // 8, (x + 7) // 8}:
                    for cy in {y // 8, (y + 7) // 8}:
                        cells.setdefault((cx, cy), []).append((offs // 4, rows >= 16))
        sx += 16
    v = 0
    for key, lst in cells.items():
        seen_un = False
        for idx, strip in lst:
            if not strip: seen_un = True
            elif seen_un:
                v += 1; break
    tot_unal += sum(1 for l in cells.values() for (_, al) in l if not al)
    if v:
        viol += 1
        if len(ex) < 3: ex.append((f, v))
print("frames checked", frames, "frames with an aligned tile over an unaligned one:", viol, ex, "unaligned tile-cells", tot_unal)
