"""Bring-up probe: what the game writes to the sound ports, frame by frame, in attract and random play on every stage.
Prints, per port, the values seen and the runs (value held for n frames)."""
import collections, os, random, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
from machine import DKongJr, CYCLES_PER_FRAME

PORTS = [0x7C00, 0x7C81] + list(range(0x7D00, 0x7D08)) + [0x7D80, 0x7D81]
m = DKongJr()
last = {}
m.wr_orig = m.wr8
def wr(a, v):
    if a in PORTS:
        last[a] = v
    m.wr_orig(a, v)
m.cpu.wr8 = wr
rnd = random.Random(7)
runs = collections.defaultdict(collections.Counter)
cur = {p: (None, 0) for p in PORTS}
joy = 0
for f in range(30000):
    if f % 9 == 0: joy = rnd.choice([0, 1, 2, 4, 8, 16, 17, 18])
    m.in0 = joy
    m.in2 = 0x80 if f % 4000 == 100 else 0x04 if f % 4000 == 200 else 0
    if f % 4000 == 250: m.mem[0x6227] = 1 + (f // 4000) % 4
    if f % 2000 == 1000: m.mem[0x6228] = 3
    last.clear()
    m.run_frame()
    for p in PORTS:
        v = last.get(p, cur[p][0])
        if v == cur[p][0]:
            cur[p] = (v, cur[p][1] + 1)
        else:
            if cur[p][0] is not None: runs[p][(cur[p][0], min(cur[p][1], 99))] += 1
            cur[p] = (v, 1)
for p in PORTS:
    print("%04X" % p, sorted(runs[p].items())[:40])
