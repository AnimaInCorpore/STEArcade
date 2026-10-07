import sys, os, random, time, pickle
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
from dkong import *
seed = int(sys.argv[1]); nframes = int(sys.argv[2])
rnd = random.Random(seed)
m = DKong()
cpu = m.cpu
pcs = set()
ioevents = {}   # (pc, addr, kind) -> count
orig_rd = cpu.rd8; orig_wr = cpu.wr8
cur = [0]
def rd(a):
    if a >= 0x7000 and a < 0x8000 and a >= 0x7800: ioevents[(cur[0], a, 'r')] = ioevents.get((cur[0], a, 'r'), 0) + 1
    return m.rd8(a)
def wr(a, v):
    if a >= 0x7800: ioevents[(cur[0], a, 'w')] = ioevents.get((cur[0], a, 'w'), 0) + 1
    m.wr8(a, v)
cpu.rd8 = rd; cpu.wr8 = wr
t = time.time()
joy = 0; jleft = 0
for f in range(nframes):
    if jleft == 0:
        joy = rnd.choice([0,0,1,2,4,8,16,17,18,20,24,5,9,6,10])
        jleft = rnd.randint(3, 40)
    jleft -= 1
    m.in0 = joy
    m.in2 = 0
    r = rnd.random()
    if r < 0.01: m.in2 |= 0x80
    if r > 0.985: m.in2 |= 0x04
    if r > 0.995: m.in2 |= 0x08
    if f % 5000 == 4000:
        pass
    target = cpu.cycles + CYCLES_PER_FRAME
    if m.nmi_mask:
        cpu.nmi()
    while cpu.cycles < target:
        cur[0] = cpu.pc
        pcs.add(cpu.pc)
        cpu.step()
    m.frame += 1
print('frames', nframes, 'pcs', len(pcs), 'time', time.time() - t)
pickle.dump((pcs, ioevents), open(f'cover_{seed}.pkl', 'wb'))
