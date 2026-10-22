"""Galaga coverage run for the translator: executed pcs per CPU, the instructions that write the video RAM and the
sites of the I/O accesses.  python ref/cover.py <seed> <frames>  ->  galaga_cover_<seed>.pkl"""
import os, pickle, random, sys
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from paths import build_dir
from machine import Galaga

seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
frames = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
rnd = random.Random(seed)
MCU = seed >= 7                     # 7: random play with the real 51XX (event-driven: the STE build's), as seed 1 otherwise
m = Galaga(skip_tests=True, mcu=True, mcu_events=True) if MCU else Galaga()


def credit_mode():
    """the 51XX is back in credit mode (a game over): the simulation's mode 1, the real chip's RAM $03 = 0 (2 in a game)"""
    return m.n51.mcu.ram[3] == 0 if MCU else m.n51.mode == 1
pcs = [set(), set(), set()]
vwrites = [set(), set(), set()]     # the instructions that write the video RAM (8000-87FF): gen.py flags them
cur = [0, 0, 0]
orig = [c.step for c in m.cpus]
for n in range(3):
    def step(n=n, cpu=m.cpus[n], f=orig[n]):
        pcs[n].add(cpu.pc)
        cur[n] = cpu.pc
        return f()
    m.cpus[n].step = step
    def wr8(a, v, n=n, f=m.cpus[n].wr8):
        if 0x8000 <= a < 0x8800:
            vwrites[n].add(cur[n])
        return f(a, v)
    m.cpus[n].wr8 = wr8

# Seeds 4-6 force a high score (the score is six digits in the video RAM, 83F8 up, 24 = blank; the table's fifth
# entry is 20000): the name entry after the game over (3000: the ranks' jump table at 31A6, the letter wheel), played
# with the random inputs (4: one player, 5: two players, both ranking; 6: no input, it times out).
HIGH = 4 <= seed <= 6
PLAYERS = 2 if seed == 5 else 1
SCORES = [30000, 25000, 21000, 123450, 20010]


def poke_score(digits_at, value):
    for i in range(6):
        m.ram[digits_at - 0x8000 + i] = (value // 10 ** i) % 10 if value >= 10 ** i or i == 0 else 0x24


coin_at = 1500 + rnd.randrange(600)
state = "attract"
joy = 0
games = 0
for f in range(frames):
    m.in0 = m.in1 = 0xff
    if state == "attract" and f >= coin_at:
        state, t0 = "coin", f
    if state == "coin":
        if f < t0 + 5: m.in1 &= ~0x10
        elif f < t0 + 40: pass
        elif PLAYERS == 2 and f < t0 + 45: m.in1 &= ~0x10
        elif PLAYERS == 2 and f < t0 + 80: pass
        elif f < t0 + 85: m.in1 &= ~(0x08 if PLAYERS == 2 else 0x04)
        else: state, t0 = "play", f
    if state in ("play", "over"):
        g = f - t0
        if g % 15 == 0:
            joy = rnd.choice([0, 0, 1, 2])
        if not (seed == 6 and state == "over"):
            if joy == 1: m.in0 &= ~0x02
            if joy == 2: m.in0 &= ~0x08
            if rnd.random() < 0.08: m.in1 &= ~0x01
    if state == "play":
        if HIGH and g == 600:
            poke_score(0x83F8, SCORES[games % len(SCORES)])
            if PLAYERS == 2:
                poke_score(0x83E3, SCORES[(games + 2) % len(SCORES)])
        if credit_mode() and (g > 9000 or HIGH and g > 600):    # game over (51xx back in credit mode)
            state, t0 = "over", f
            games += 1
    if state == "over" and g > (4000 if HIGH else 0):     # (the name entry: a minute at most, then the attract)
        state = "attract"
        coin_at = f + 300
    m.run_frame()
    if f % 2000 == 0:
        print(seed, "frame", f, state, "pcs", [len(p) for p in pcs], flush=True)
pickle.dump({"pcs": pcs, "vwrites": vwrites, "frames": frames, "seed": seed},
            open(build_dir("galaga") / ("galaga_cover_%d.pkl" % seed), "wb"))
print("done", seed, [len(p) for p in pcs], "video RAM writers", [len(w) for w in vwrites])
