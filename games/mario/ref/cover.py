"""Coverage of the Mario main CPU: the program counters seen executing under random play.

    python ref/cover.py <seed> <frames>      ->  build/mario/cover_<seed>.pkl  (pcs, io events)

Seeds (port.py cover): 1-3 play (random joystick, jump, coins, starts), 4-6 one player with many lives (a RAM poke of the
lives counter, the game's own cheat), 7 two players, 8-9 the DIP switches (lives, coinage, bonus, difficulty), 10 the test
mode (service switch), 11-12 later phases (the POW and the bonus phase by long play with the lives poke).
"""
import sys, os, random, time, pickle
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from machine import *
from paths import build_dir

seed = int(sys.argv[1]); nframes = int(sys.argv[2])
rnd = random.Random(seed)
dsw = DSW_DEFAULT
if seed == 8: dsw = 0x03 | 0x0C | 0x30
if seed == 9: dsw = 0xC0 | 0x08 | 0x01
m = Mario(dsw=dsw)
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
        joy = rnd.choice([0, 0, 1, 2, 16, 17, 18, 1, 2, 0])
        jleft = rnd.randint(3, 40)
    jleft -= 1
    r = rnd.random()
    coin = (seed != 10 and r < 0.004) or (f % 400 == 30 and seed <= 12)
    start1 = f % 500 in (60, 61, 62) and seed != 7
    start2 = seed == 7 and f % 500 in (60, 61, 62)
    if seed in (4, 5, 6, 11, 12):                        # MAME's cheats: free play $6BF0, P1 lives $6116, bonus time $66D4
        m.ram[0x6BF0 - 0x6000] = 1
        m.ram[0x6116 - 0x6000] = 7
        if seed >= 11: m.ram[0x66D4 - 0x6000] = 0x99
    m.set_inputs(p1=joy, p2=joy if seed == 7 else 0, coin=coin, start1=start1, start2=start2, service=(seed == 10 and 30 < f < 50))
    target = cpu.cycles + CYCLES_PER_FRAME
    if m.nmi_mask:
        cpu.nmi()
    while cpu.cycles < target:
        cur[0] = cpu.pc
        pcs.add(cpu.pc)
        cpu.step()
    m.frame += 1
print('frames', nframes, 'pcs', len(pcs), 'time', time.time() - t)
pickle.dump((pcs, ioevents), open(build_dir('mario') / f'cover_{seed}.pkl', 'wb'))
