"""What the MCU does: instructions per frame, loop heads, shared RAM traffic.  python ref/bb_mcu1.py"""
import os, sys
from collections import Counter
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from bublbobl import Bublbobl
m = Bublbobl()
for f in range(400):
    m.run_frame()
h = Counter(); n = [0]
orig = m.mcu.step
def st():
    h[m.mcu.pc] += 1; n[0] += 1
    return orig()
m.mcu.step = st
rd, wr = Counter(), Counter()
op2 = m.mcu_p2_w
def p2(v):
    if not (m.p2_out & 0x10) and (v & 0x10):
        a = m.p4_out | ((v & 0xF) << 8)
        (rd if m.p1_out & 0x80 else wr)[a] += 1
    op2(v)
m.mcu.out[1] = p2
for f in range(5):
    n[0] = 0
    m.run_frame()
    print("frame instrs", n[0], "irq taken?", m.mcu.cc)
print("hot:", ", ".join("%04X:%d" % x for x in h.most_common(20)))
print("reads (addr:count):", sorted(rd.items()))
print("writes:", sorted(wr.items()))
