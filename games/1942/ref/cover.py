"""1942 coverage run for the translator, in the port's schedule: the executed pcs of the main CPU and the instructions that
read the banked ROM window ($8000-$BFFF) as data, and the stores to the latches C800-C806.
python ref/cover.py <seed> <frames>  ->  build/1942/cover_<seed>.pkl

Scripted play: attract mode, a coin and the start button now and then, random joystick, fire and loop (bomb) buttons.
Service mode (DSWB bit 3, code in bank 2) is not exercised: the DIP switch stays off.
"""
import os, pickle, random, sys
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from paths import build_dir
from machine import Machine1942

seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
frames = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
rnd = random.Random(seed)
m = Machine1942()
c = m.cpu
pcs = set()
wread = set()
video_writes = set()                    # (pc, 'fg' | 'bg') of the stores to the character / background RAM (dirty flags for the renderer)
io_writes = set()                       # (pc, address) of the stores to C800-C806 (the bank latch needs hooks)
cur = [0]
step0 = c.step
rd0 = c.rd8


def step():
    cur[0] = c.pc
    pcs.add(c.pc)
    return step0()


def rd(a):
    if 0x8000 <= a < 0xC000:
        pc = cur[0]
        if not (pc <= a < pc + 4):                      # not the instruction fetch itself
            wread.add((pc, m.bank))
    return rd0(a)


wr0 = c.wr8


def wr(a, v):
    if 0xC800 <= a <= 0xC806:
        io_writes.add((cur[0], a))
    elif 0xD000 <= a < 0xDC00:
        video_writes.add((cur[0], 'fg' if a < 0xD800 else 'bg'))
    return wr0(a, v)


c.step = step
c.rd8 = rd
c.wr8 = wr

coin_at = 700 + rnd.randrange(300)
state = "attract"
joy = 0xFF
t0 = 0
for f in range(frames):
    m.sys_in = 0xFF
    m.p1 = 0xFF
    m.p2 = 0xFF
    if state == "attract" and f >= coin_at:
        state, t0 = "coin", f
    if state == "coin":
        if f < t0 + 4:
            m.sys_in &= 0x7F                          # coin 1
        elif 30 <= f - t0 < 34:
            m.sys_in &= 0xFE                          # start 1
        elif f - t0 >= 34:
            state, t0 = "play", f
    if state == "play":
        g = f - t0
        if g % 25 == 0:
            joy = rnd.choice([0xFF, 0xFF, 0xFE, 0xFD, 0xFB, 0xF7, 0xFA, 0xF6, 0xF9, 0xF5])
        m.p1 = joy
        if rnd.random() < 0.3:
            m.p1 &= ~0x10
        if rnd.random() < 0.02:
            m.p1 &= ~0x20                              # loop
        if g % 2500 < 3 and g > 5000:
            m.sys_in &= 0x7F                          # more coins
        if g > 1500 and g % 700 < 3:
            m.sys_in &= 0xFE
        if g > 30000:
            state, coin_at = "attract", f + 200
    m.run_frame_port()
    if f % 2000 == 0:
        print(seed, "frame", f, state, "pcs", len(pcs), "window reads", len(wread), flush=True)
pickle.dump({"pcs": pcs, "wread": wread, "io_writes": io_writes, "video_writes": video_writes, "frames": frames, "seed": seed},
            open(build_dir("1942") / ("cover_%d.pkl" % seed), "wb"))
print("done", seed, len(pcs), len(wread))
