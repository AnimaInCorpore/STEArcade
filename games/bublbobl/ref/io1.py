"""I/O accesses of the main CPU: sites of writes to FA00-FBFF and reads of FA00-FA7F; sub CPU: any I/O.
python ref/io1.py"""
import os, sys
from collections import Counter
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from machine import Bublbobl
m = Bublbobl()
w, r = Counter(), Counter()
cur = [0]
step = m.main.step
def st():
    cur[0] = m.main.pc
    return step()
m.main.step = st
ow, orr = m.wr_main, m.rd_main
def wr(a, v):
    if 0xFA00 <= a < 0xFC00: w[(cur[0], a)] += 1
    ow(a, v)
def rd(a):
    if 0xFA00 <= a < 0xFC00 and not (cur[0] <= a < cur[0] + 4): r[(cur[0], a)] += 1
    return orr(a)
m.main.wr8, m.main.rd8 = wr, rd
for f in range(2500):
    m.in0 = 0x03 | (0x04 if 700 <= f < 706 else 0)
    m.in1 = 0xFF & ~(0x40 if 760 <= f < 766 else 0)
    if f > 900:
        m.in1 &= ~(0x02 if (f // 50) % 2 else 0x01)
        if f % 30 < 3: m.in1 &= ~0x20
    m.run_frame_port()
print("writes:", sorted(("%04X" % pc, "%04X" % a, n) for (pc, a), n in w.items()))
print("reads:", sorted(("%04X" % pc, "%04X" % a, n) for (pc, a), n in r.items()))
