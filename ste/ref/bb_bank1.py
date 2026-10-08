"""Bank switching pattern of the main CPU: writes to FB40 (frame, pc, value), accesses to the window by bank.
python ref/bb_bank1.py"""
import os, sys
from collections import Counter
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from bublbobl import Bublbobl
m = Bublbobl()
log = []
ow = m.wr_main
def wr(a, v):
    if 0xFB40 <= a < 0xFB80:
        log.append((m.frame, m.main.pc, v))
    ow(a, v)
m.main.wr8 = wr
orr = m.rd_main
rd_by_bank = Counter(); code_by_bank = Counter()
def rd(a):
    if 0x8000 <= a < 0xC000:
        rd_by_bank[(m.bank, "code" if a == m.main.pc or a == m.main.pc + 1 else "data")] += 1
    return orr(a)
m.main.rd8 = rd
def run(n):
    for _ in range(n): m.run_frame()
run(300)
for i in range(6): m.in0 |= 0x04; run(1)
m.in0 &= ~0x04; run(60)
for i in range(6): m.in1 = 0xFF & ~0x40; run(1)
m.in1 = 0xFF; run(200)
for f in range(400):
    m.in1 = 0xFF & ~(0x02 if (f // 50) % 2 else 0x01)
    if f % 30 < 3: m.in1 &= ~0x20
    run(1)
print("writes to FB40:", len(log))
print("values:", Counter(v for _, _, v in log).most_common())
print("by site:", Counter((hex(pc), v) for _, pc, v in log).most_common(30))
print("last 24:", [(f, hex(pc), hex(v)) for f, pc, v in log[-24:]])
print("window reads:", rd_by_bank)
