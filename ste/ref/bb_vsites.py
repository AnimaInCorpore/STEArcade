"""Sites of the main CPU that write the video RAM (C000-DCFF) or the object RAM (DD00-DFFF), in the port's
schedule with random play: pc -> (count, lowest, highest address).  python ref/bb_vsites.py <seed> <frames>
-> bb_vsites_<seed>.pkl"""
import os, pickle, random, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from bublbobl import Bublbobl
seed = int(sys.argv[1]); frames = int(sys.argv[2])
rnd = random.Random(seed)
m = Bublbobl()
sites = {}
cur = [0]
step = m.main.step
def st():
    pc = m.main.pc
    if 0x8000 <= pc < 0xC000:
        pc += ((m.bank ^ 4) & 7) * 0x4000
    cur[0] = pc
    return step()
m.main.step = st
ow = m.wr_main
def wr(a, v):
    if 0xC000 <= a < 0xE000:
        k = sites.setdefault(cur[0], [0, a, a])
        k[0] += 1; k[1] = min(k[1], a); k[2] = max(k[2], a)
    ow(a, v)
m.main.wr8 = wr
coin_at = 700 + rnd.randrange(300)
state = "attract"; joy = 0
for f in range(frames):
    m.in0 = 0x03; m.in1 = m.in2 = 0xFF
    if state == "attract" and f >= coin_at: state, t0 = "coin", f
    if state == "coin":
        if f < t0 + 4: m.in0 |= 0x04
        elif f < t0 + 44 and f >= t0 + 40: m.in1 &= ~0x40
        elif f >= t0 + 44: state, t0 = "play", f
    if state == "play":
        g = f - t0
        if g % 20 == 0: joy = rnd.choice([0, 0, 1, 2, 3])
        if joy == 1: m.in1 &= ~0x01
        if joy == 2: m.in1 &= ~0x02
        if rnd.random() < 0.15: m.in1 &= ~0x10
        if rnd.random() < 0.15: m.in1 &= ~0x20
        if g > 4000 and g % 3000 < 3: m.in1 &= ~0x40
    m.run_frame_port()
pickle.dump(sites, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bb_vsites_%d.pkl" % seed), "wb"))
print(seed, len(sites), "sites")
for pc, (n, lo, hi) in sorted(sites.items(), key=lambda kv: -kv[1][0])[:25]:
    print("  %05X  %8d writes  %04X-%04X" % (pc, n, lo, hi))
