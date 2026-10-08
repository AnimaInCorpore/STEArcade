"""MCU code coverage through coin / start / play.  python ref/mcu2.py"""
import os, sys
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from machine import Bublbobl
m = Bublbobl()
pcs = set()
orig = m.mcu.step
def st():
    pcs.add(m.mcu.pc); return orig()
m.mcu.step = st
def run(n):
    for _ in range(n): m.run_frame()
run(300)
for i in range(6): m.in0 |= 0x04; run(1)
m.in0 &= ~0x04; run(60)
for i in range(6): m.in1 = 0xFF & ~0x40; run(1)
m.in1 = 0xFF; run(200)
print("after start", len(pcs))
for f in range(900):
    m.in1 = 0xFF & ~(0x02 if (f // 50) % 2 else 0x01)
    if f % 30 < 3: m.in1 &= ~0x20
    run(1)
print("after play", len(pcs), "range", hex(min(pcs)), hex(max(pcs)))
m.in0 |= 0x04; run(5); m.in0 &= ~0x04; run(5)
m.in0 |= 0x08; run(5); m.in0 &= ~0x08; run(5)
m.in0 &= ~0x02; run(5); m.in0 |= 0x02; run(5)
print("after coin2/service", len(pcs))
print(" ".join("%04X" % p for p in sorted(pcs)))
