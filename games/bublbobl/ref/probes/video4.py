"""Who writes video RAM (C000-DCFF) and object RAM (DD00-DFFF): sites, counts per frame.  python ref/probes/video4.py"""
import os, sys
from collections import Counter
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "engine")]
from machine import Bublbobl
m = Bublbobl()
sites = Counter(); osites = Counter(); per_frame = []
cnt = [0]
ow = m.wr_main
cur = [0]
step = m.main.step
def st():
    cur[0] = m.main.pc | (((m.bank ^ 4) & 7) << 16 if 0x8000 <= m.main.pc < 0xC000 else 0)
    return step()
m.main.step = st
def wr(a, v):
    if 0xC000 <= a < 0xDD00:
        sites[cur[0]] += 1; cnt[0] += 1
    elif 0xDD00 <= a < 0xE000:
        osites[cur[0]] += 1
    ow(a, v)
m.main.wr8 = wr
for f in range(1500):
    m.in0 = 0x03 | (0x04 if 700 <= f < 706 else 0)
    m.in1 = 0xFF & ~(0x40 if 760 <= f < 766 else 0)
    if f > 900:
        m.in1 &= ~(0x02 if (f // 50) % 2 else 0x01)
        if f % 30 < 3: m.in1 &= ~0x20
    if f == 1000: sites.clear(); osites.clear(); cnt[0] = 0
    m.run_frame_port()
    if f >= 1000: per_frame.append(cnt[0]); cnt[0] = 0
print("vram byte writes per frame: mean %.0f max %d" % (sum(per_frame) / len(per_frame), max(per_frame)))
print("vram sites:", [("%05X" % pc, n) for pc, n in sites.most_common(12)])
print("oram sites:", [("%05X" % pc, n) for pc, n in osites.most_common(6)])
