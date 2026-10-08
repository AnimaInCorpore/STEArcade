"""Bubble Bobble probes: coin + start via the MCU, instructions per CPU per frame, colours
on screen, banks used.  python ref/probe1.py <outdir>"""
import os, sys
from collections import Counter
import numpy as np
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from machine import Bublbobl, save_png

out = sys.argv[1] if len(sys.argv) > 1 else "."
m = Bublbobl()
cnt = [0, 0, 0]
IDLE = [{0x01ED}, {0x000A}, {0xEF, 0xF0, 0xF1, 0xF2}]
banks = Counter()
orig = [c.step for c in (m.main, m.sub, m.snd)]
for i, c in enumerate((m.main, m.sub, m.snd)):
    def st(i=i, c=c, f=orig[i]):
        if c.pc not in IDLE[i]: cnt[i] += 1
        if i == 0 and 0x8000 <= c.pc < 0xC000:
            banks[(m.bank, c.pc >> 8)] += 1
        return f()
    c.step = st
stats = []
def run(n, tag):
    for f in range(n):
        cnt[:] = [0, 0, 0]
        m.run_frame()
        raw = m.render_raw()
        stats.append((m.frame, tuple(cnt), len(np.unique(raw[raw != 255])), len(np.unique(m.palette_rgb()[raw[raw != 255]], axis=0)) if (raw != 255).any() else 0))
run(300, "boot")
m.in0 &= ~0x04
for i in range(6): m.in0 |= 0x04; run(1, ""); 
m.in0 &= ~0x04
run(60, "coin")
save_png(m.render_rgb(), os.path.join(out, "bb_coin.png"))
for i in range(6): m.in1 = 0xFF & ~0x40; run(1, "")
m.in1 = 0xFF
run(200, "start")
save_png(m.render_rgb(), os.path.join(out, "bb_start.png"))
for f in range(600):
    m.in1 = 0xFF & ~(0x02 if (f // 50) % 2 else 0x01)
    if f % 30 < 3: m.in1 &= ~0x20
    if f % 90 < 3: m.in1 &= ~0x10
    run(1, "")
    if f in (100, 300, 599):
        save_png(m.render_rgb(), os.path.join(out, "bb_play%d.png" % f))
print("frames: instrs main/sub/snd (mean, max); colour indices, rgb colours (max)")
a = np.array([s[1] for s in stats[-600:]])
print("play:", a.mean(0), a.max(0), "indices", max(s[2] for s in stats[-600:]), "rgb", max(s[3] for s in stats[-600:]))
a = np.array([s[1] for s in stats[:300]])
print("boot:", a.mean(0), a.max(0))
print("banks used by main code:", sorted(banks.items())[:40])
print("snd log", m.snd_log[:20], "mcram", m.mcram[:8].hex())
