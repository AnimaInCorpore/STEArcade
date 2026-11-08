"""Coverage of the Donkey Kong 3 main CPU: the program counters seen executing under random play.

    python ref/cover.py <seed> <frames>      ->  build/dkong3/cover_<seed>.pkl  (pcs, io events)

Seeds (port.py cover): 1-6 and 11 play (random joystick, fire, coins, starts), 7 two players, 8-9 the DIP switches (lives,
coinage, bonus, difficulty), 10 the test mode (service DIP), 12 the service button, 13-18 stages poked at the start, 19-24 with infinite lives too.
"""
import sys, os, random, time, pickle
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from machine import *
from paths import build_dir

seed = int(sys.argv[1]); nframes = int(sys.argv[2])
rnd = random.Random(seed)
dsw0, dsw1 = DSW0_DEFAULT, DSW1_DEFAULT
if seed == 8: dsw1 = 0x03 | 0x0C | 0x30 | 0xC0
if seed == 10: dsw0 = 0x40                                   # the service DIP: the test mode
if seed == 9: dsw0, dsw1 = 0x07 | 0x80, 0x01 | 0x08 | 0x10
m = DK3(dsw0=dsw0, dsw1=dsw1)
cpu = m.cpu
pcs = set()
ioevents = {}   # (pc, addr, kind) -> count
cur = [0]
orig_rd, orig_wr = m.rd8, m.wr8
def rd(a):
    if a >= 0x7800: ioevents[(cur[0], a, 'r')] = ioevents.get((cur[0], a, 'r'), 0) + 1
    return orig_rd(a)
def wr(a, v):
    if a >= 0x7800: ioevents[(cur[0], a, 'w')] = ioevents.get((cur[0], a, 'w'), 0) + 1
    orig_wr(a, v)
cpu.rd8 = rd; cpu.wr8 = wr
m.dma.rd = rd; m.dma.wr = wr
t = time.time()
joy = 0; jleft = 0
for f in range(nframes):
    if jleft == 0:
        joy = rnd.choice([0, 0, 1, 2, 4, 8, 16, 17, 18, 5, 9, 1, 2, 0])
        jleft = rnd.randint(3, 40)
    jleft -= 1
    r = rnd.random()
    coin = (seed != 10 and r < 0.004) or (f % 400 == 30 and seed <= 12)
    start1 = f % 500 in (60, 61, 62) and seed != 7
    start2 = seed == 7 and f % 500 in (60, 61, 62)
    if seed >= 13:                                      # MAME's cheats (credits $6BF1, lives $601A) and the stage ($601B, found by poking: 0 and 1 the
        m.ram[0x6BF1 - 0x6000] = 0x63                   # greenhouse, 2 the roof stage; values above 2 are not stages), poked while the game starts
        if seed >= 19:
            m.ram[0x601A - 0x6000] = 6
        if f % 500 in range(63, 200):
            m.ram[0x601B - 0x6000] = (seed + f // 500) % 3
    m.set_inputs(p1=joy, p2=joy if seed == 7 else 0, coin=coin, start1=start1, start2=start2, service=(seed == 10 and 30 < f < 50) or (seed == 12 and f % 700 in range(300, 330)))
    target = cpu.cycles + CYCLES_PER_FRAME
    if m.nmi_mask:
        cpu.nmi()
    while cpu.cycles < target:
        cur[0] = cpu.pc
        pcs.add(cpu.pc)
        cpu.step()
    m.frame += 1
print('frames', nframes, 'pcs', len(pcs), 'time', time.time() - t)
pickle.dump((pcs, ioevents), open(build_dir('dkong3') / f'cover_{seed}.pkl', 'wb'))
