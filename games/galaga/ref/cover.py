"""Galaga coverage run for the translator: executed pcs per CPU and the sites of the
I/O accesses.  python ref/cover.py <seed> <frames>  ->  galaga_cover_<seed>.pkl"""
import os, pickle, random, sys
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from paths import build_dir
from machine import Galaga

seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
frames = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
rnd = random.Random(seed)
m = Galaga()
pcs = [set(), set(), set()]
orig = [c.step for c in m.cpus]
for n in range(3):
    def step(n=n, cpu=m.cpus[n], f=orig[n]):
        pcs[n].add(cpu.pc)
        return f()
    m.cpus[n].step = step

coin_at = 1500 + rnd.randrange(600)
state = "attract"
joy = 0
for f in range(frames):
    m.in0 = m.in1 = 0xff
    if state == "attract" and f >= coin_at:
        state, t0 = "coin", f
    if state == "coin":
        if f < t0 + 5: m.in1 &= ~0x10
        elif f < t0 + 40: pass
        elif f < t0 + 45: m.in1 &= ~0x04
        else: state, t0 = "play", f
    if state == "play":
        g = f - t0
        if g % 15 == 0:
            joy = rnd.choice([0, 0, 1, 2])
        if joy == 1: m.in0 &= ~0x02
        if joy == 2: m.in0 &= ~0x08
        if rnd.random() < 0.08: m.in1 &= ~0x01
        if g > 9000 and m.n51.mode == 1:         # game over: insert another coin
            state = "attract"
            coin_at = f + 300
    m.run_frame()
    if f % 2000 == 0:
        print(seed, "frame", f, state, "pcs", [len(p) for p in pcs], flush=True)
pickle.dump({"pcs": pcs, "frames": frames, "seed": seed},
            open(build_dir("galaga") / ("galaga_cover_%d.pkl" % seed), "wb"))
print("done", seed, [len(p) for p in pcs])
