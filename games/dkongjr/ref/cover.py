"""Coverage of the Donkey Kong Junior main CPU (the PCs the translator is seeded from) and the pens shown (the palette).

    python cover.py SEED FRAMES   -> build/dkongjr/cover_SEED.pkl ((pcs, io events)), pens_SEED.pkl (Counter pen -> pixels)

Random joystick, coins and starts (1 and 2 players).  Seeds 4-9 insert no coin: the whole attract sequence ($600A
steps 0-7: the demo, the title logo in tile bank 1 with its palette cycling at $07CB, ...), which a coin cuts short.
Seeds >= 10 also visit every stage by setting $6227 (stage:
1 springboard, 2 vines (the first), 3 chains, 4 hideout; the same RAM layout as Donkey Kong) and $6229 (level),
refill the lives ($6228) now and then, and seeds >= 20 set a P1 score of 90000+ ($60B2, BCD) so the game over reaches
the high-score name entry.  The pens are counted from the reference renderer every 20 frames.
"""
import collections, os, pickle, random, sys, time
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import numpy as np
from machine import DKongJr, CYCLES_PER_FRAME
from paths import build_dir

seed = int(sys.argv[1]); nframes = int(sys.argv[2])
rnd = random.Random(seed)
m = DKongJr()
cpu = m.cpu
pcs = set()
ioevents = {}   # (pc, addr, kind) -> count
cur = [0]


def rd(a):
    if a >= 0x7800:
        k = (cur[0], a, 'r'); ioevents[k] = ioevents.get(k, 0) + 1
    return m.rd8(a)


def wr(a, v):
    if a >= 0x7800:
        k = (cur[0], a, 'w'); ioevents[k] = ioevents.get(k, 0) + 1
    m.wr8(a, v)


cpu.rd8 = rd; cpu.wr8 = wr
pens = collections.Counter()
t = time.time()
joy = 0; jleft = 0
for f in range(nframes):
    if jleft == 0:
        joy = rnd.choice([0, 0, 1, 2, 4, 8, 16, 17, 18, 20, 24, 5, 9, 6, 10])
        jleft = rnd.randint(3, 40)
    jleft -= 1
    m.in0 = joy
    m.in1 = joy if rnd.random() < 0.5 else 0
    m.in2 = 0
    r = rnd.random()
    if 4 <= seed < 10:
        r = 0.5                     # no coin, no start
    if r < 0.01: m.in2 |= 0x80
    if r > 0.985: m.in2 |= 0x04
    if r > 0.995: m.in2 |= 0x08
    if seed >= 10:
        if f % 1500 == 700 and rnd.random() < 0.8:
            m.mem[0x6227] = rnd.choice([1, 2, 3, 4]); m.mem[0x6229] = rnd.choice([1, 2, 3, 4, 5, 6])
        if f % 2500 == 1200 and (seed < 20 or f < nframes // 2):
            m.mem[0x6228] = 3
    if seed >= 20 and f % 4000 == 3000:
        m.mem[0x60B2:0x60B5] = bytes([rnd.choice([0, 0x50]), rnd.randrange(0x10) * 0x10, rnd.choice([0x09, 0x12, 0x25])])
    target = cpu.cycles + CYCLES_PER_FRAME
    if m.nmi_mask:
        cpu.nmi()
    while cpu.cycles < target:
        cur[0] = cpu.pc
        pcs.add(cpu.pc)
        cpu.step()
    m.frame += 1
    if f % 20 == 0:
        vals, cnts = np.unique(m.render_raw(), return_counts=True)
        for v, c in zip(vals.tolist(), cnts.tolist()):
            pens[v] += c
print('seed', seed, 'frames', nframes, 'pcs', len(pcs), 'pens', len(pens), 'time %.0fs' % (time.time() - t))
out = build_dir('dkongjr')
out.mkdir(parents=True, exist_ok=True)
pickle.dump((pcs, ioevents), open(out / f'cover_{seed}.pkl', 'wb'))
pickle.dump(pens, open(out / f'pens_{seed}.pkl', 'wb'))
