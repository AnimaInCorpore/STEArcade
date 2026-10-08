"""ISR cost per frame on the simulator (68000 cycles at 8 MHz, no wait states for the blitter bus share)."""
import os, sys, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sim import Sim, RUN, STE
frames = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
s = Sim(RUN / sys.argv[2] if len(sys.argv) > 2 else RUN / "DKSIM.PRG")
syms = s.symbols(STE / "build" / "dkong.map")
base = s.base; blk = base + syms["z80_block"]
rnd = random.Random(3); joy = 0
costs = []
nspr = []
heavy = []
def sprite_counts():
    rects = base + syms['spr_prev_rect']
    return tuple(sum(s.mem.r16(rects + bank * 192 + slot * 2) != 0xFFFF
                     for slot in range(96)) for bank in range(2))

while s.frames < frames:
    f = s.frames
    s.mem.w8(base + syms["in2_kbd"], 0x80 if 40 <= f < 50 else (0x04 if 80 <= f < 90 else 0))
    if f % 12 == 0: joy = rnd.choice([0, 0, 1, 2, 4, 8, 16, 17, 18])
    s.mem.w8(base + syms["in0_kbd"], joy)
    if f > 300 and f % 1500 == 800:
        s.mem.w8(blk + 0x6227, rnd.choice([1, 2, 3, 4])); s.mem.w8(blk + 0x6229, rnd.choice([1, 2, 3, 4]))
    s.run_frames(1)
    t0 = s._total
    r = s.cpu.execute(60)
    s._total += r.cycles
    guard = 0
    while s.mem.r8(base + syms["vbl_busy"]) and guard < 20000:
        r = s.cpu.execute(200)
        s._total += r.cycles + s.blitter.cycles
        s.blitter.cycles = 0
        guard += 1
    costs.append(s._total - t0)
    counts = sprite_counts()
    nspr.append(max(counts))
    if costs[-1] > 160000 and len(heavy) < 40 and s.frames > 600:
        heavy.append((s.frames, costs[-1], *counts, s.mem.r8(blk + 0x600A)))
import numpy as np
c = np.array(costs[50:])
print("frames", len(c), "ISR cycles: mean %.0f  p95 %.0f  max %.0f  (frame = 160000)" % (c.mean(), np.percentile(c, 95), c.max()))
print("frames over 160000:", int((c > 160000).sum()), " over 120000:", int((c > 120000).sum()))

for h in heavy: print('frame %d cost %d sprites %d/%d mode %d' % h)

import collections
g = collections.defaultdict(list)
for c, n in zip(costs, nspr): g[min(n // 4 * 4, 40)].append(c)
for k in sorted(g): print("sprites %2d-%2d: frames %4d mean cost %7.0f" % (k, k + 3, len(g[k]), sum(g[k]) / len(g[k])))
