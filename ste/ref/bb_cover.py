"""Bubble Bobble coverage for the translator, run in the port's schedule: executed pcs of the main
CPU (window code as virtual pc = pc + 0x4000 * bank entry), the sub CPU and the MCU, and the
instructions that read the banked window as data.
python ref/bb_cover.py <seed> <frames>  ->  bb_cover_<seed>.pkl"""
import os, pickle, random, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from bublbobl import Bublbobl

seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
frames = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
rnd = random.Random(seed)
m = Bublbobl()
pcs = [set(), set(), set()]
wread = set()
main_step, sub_step, mcu_step = m.main.step, m.sub.step, m.mcu.step
cur = [0]

def st_main():
    pc = m.main.pc
    if pc >= 0x8000 and pc < 0xC000:
        pc += ((m.bank ^ 4) & 7) * 0x4000
    pcs[0].add(pc)
    cur[0] = pc
    return main_step()
def st_sub():
    pcs[1].add(m.sub.pc)
    return sub_step()
def st_mcu():
    pcs[2].add(m.mcu.pc)
    return mcu_step()
m.main.step, m.sub.step, m.mcu.step = st_main, st_sub, st_mcu
rd0 = m.main.rd8
def rd(a):
    if 0x8000 <= a < 0xC000:
        pc = cur[0]
        r = pc % 0x4000 + 0x8000 if pc >= 0x8000 else pc
        if not (pc <= a + ((m.bank ^ 4) & 7) * 0x4000 < pc + 4):
            wread.add((pc, (m.bank ^ 4) & 7))
    return rd0(a)
m.main.rd8 = rd

coin_at = 700 + rnd.randrange(300)
state = "attract"
joy = 0
for f in range(frames):
    m.in0 = 0x03
    m.in1 = m.in2 = 0xFF
    if state == "attract" and f >= coin_at:
        state, t0 = "coin", f
    if state == "coin":
        if f < t0 + 4: m.in0 |= 0x04 if rnd.random() < 0.8 else 0x08
        elif f < t0 + 40: pass
        elif f < t0 + 44: m.in1 &= ~0x40
        else: state, t0 = "play", f
    if state == "play":
        g = f - t0
        if g % 20 == 0:
            joy = rnd.choice([0, 0, 1, 2, 3])
        if joy == 1: m.in1 &= ~0x01
        if joy == 2: m.in1 &= ~0x02
        if rnd.random() < 0.15: m.in1 &= ~0x10        # jump
        if rnd.random() < 0.15: m.in1 &= ~0x20        # bubble
        if g > 12000 and rnd.random() < 0.01:         # a second coin and a start now and then
            m.in0 |= 0x04
        if g > 4000 and g % 3000 < 3: m.in1 &= ~0x40
    m.run_frame_port()
    if f % 2000 == 0:
        print(seed, "frame", f, state, "pcs", [len(p) for p in pcs], "window reads", len(wread), flush=True)
pickle.dump({"pcs": pcs, "wread": wread, "frames": frames, "seed": seed},
            open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bb_cover_%d.pkl" % seed), "wb"))
print("done", seed, [len(p) for p in pcs], len(wread))
