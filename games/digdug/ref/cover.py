"""Dig Dug coverage run for the translator: executed pcs per CPU, the instructions that write the tile RAM ($8000-$83FF)
and the sites of the I/O accesses.  python ref/cover.py <seed> <frames>  ->  digdug_cover_<seed>.pkl

Seeds: 1-3 one player (random joystick and pump button), 4 two players, 5 hardest difficulty, 5 lives, no bonus life, 6 a
cocktail cabinet with two players (the screen flips), 7 a coin-less attract cycle, 9 continue allowed and the other
coinage / bonus DIPs, 10-11 fast input changes (dies earlier: more game overs), 12 the scripted game of tools/schedule_test.py
and render_test.py (the sound CPU's rarer commands only the long runs reach), 13-16 long random play (all four directions,
holds of 5-60 frames), 17 the chasing bot of tools/bot.py (rounds 1-2 and later, several games).  (Seed 8, the service switch, is left out:
the test mode runs inside the main CPU's IRQ handler and does not return.)  ewrites: the instructions that write the
EAROM window ($B800-$B83F), the sites gen.py makes track the address."""
import os, pickle, random, sys
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from paths import build_dir
from machine import DigDug

seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
frames = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
rnd = random.Random(seed)
m = DigDug(skip_tests=True, mcu_events=True)
PLAYERS = 2 if seed in (4, 6) else 1
if seed == 5:
    m.dswa = (m.dswa & 0x07) | 0xC0 | 0x00          # no bonus life, 5 lives
    m.dswb = (m.dswb & ~0x03) | 0x03                # hardest
if seed == 6:
    m.dswb &= ~0x04                                 # cocktail
if seed == 9:
    m.dswa = (m.dswa & ~0x3F) | 0x20 | 0x06         # coinage B 1C_2C, bonus 10K 40K every 40K
    m.dswb = (m.dswb & ~0xCF) | 0x80 | 0x08 | 0x01  # coinage A 1C_2C, no continue, hard
NOCOIN = seed == 7
FAST = seed in (10, 11)

pcs = [set(), set(), set()]
vwrites = [set(), set(), set()]     # the instructions that write the tile RAM
ewrites = [set(), set(), set()]     # the instructions that write the EAROM window: gen.py flags them
cur = [0, 0, 0]
orig = [c.step for c in m.cpus]
for n in range(3):
    def step(n=n, cpu=m.cpus[n], f=orig[n]):
        pcs[n].add(cpu.pc)
        cur[n] = cpu.pc
        return f()
    m.cpus[n].step = step
    def wr8(a, v, n=n, f=m.cpus[n].wr8):
        if 0x8000 <= a < 0x8400:
            vwrites[n].add(cur[n])
        elif 0xB800 <= a < 0xB840:
            ewrites[n].add(cur[n])
        return f(a, v)
    m.cpus[n].wr8 = wr8


def credit_mode():
    """the 51XX is back in credit mode (a game over): its RAM $03 = 0 (2 in a game)"""
    return m.n51.mcu.ram[3] == 0


LONG = seed >= 13
hold = 15
coin_at = 600 + rnd.randrange(600)
state = "attract"
joy = 0
games = 0
t0 = 0
import bot
jit_left, jit = 0, 0
for f in range(frames):
    m.in0 = m.in1 = 0xff
    if seed == 8 and 3000 <= f < 3400:
        m.in1 &= ~0x80                              # the service switch
    if not NOCOIN:
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
            if g % (6 if FAST else hold) == 0:
                joy = rnd.choice([0, 1, 2, 4, 8] if LONG else [0, 1, 2, 4, 8, 8, 4])
                if LONG:
                    hold = rnd.randrange(5, 60)
            if joy:
                m.in0 &= ~joy
                if PLAYERS == 2 and (f // 600) % 2:
                    m.in0 &= ~(joy << 4) if joy else 0xff        # the second player's stick (cocktail)
            if rnd.random() < (0.3 if FAST else 0.12):
                m.in1 &= ~(0x01 | (0x02 if PLAYERS == 2 else 0))
        if state == "play" and g > 600 and credit_mode():        # game over (51XX back in credit mode)
            state, t0 = "over", f
            games += 1
        if state == "over" and g > 1500:
            state = "attract"
            coin_at = f + 200 + rnd.randrange(300)
    if seed >= 17:                                  # the chasing bot of tools/bot.py (it reaches round 2 and further)
        m.in0, m.in1 = bot.decide(m, f)
        if seed >= 18:                              # 18-19: with detours (random directions for 10-40 frames) and pumps
            if jit_left <= 0 and rnd.random() < 0.02:
                jit_left, jit = rnd.randrange(10, 40), rnd.choice([1, 2, 4, 8])
            if jit_left > 0 and f >= 1300:
                jit_left -= 1
                m.in0 = (m.in0 | 0x0F) & ~jit
            if rnd.random() < 0.05:
                m.in1 &= ~0x01
    m.run_frame_port()
    if f % 2000 == 0:
        print(seed, "frame", f, state, "pcs", [len(p) for p in pcs], flush=True)
pickle.dump({"pcs": pcs, "vwrites": vwrites, "ewrites": ewrites, "frames": frames, "seed": seed},
            open(build_dir("digdug") / ("digdug_cover_%d.pkl" % seed), "wb"))
print("done", seed, [len(p) for p in pcs], "tile RAM writers", [len(w) for w in vwrites], "EAROM writers", [len(w) for w in ewrites], "games", games)
