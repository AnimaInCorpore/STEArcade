"""Super Xevious coverage run for the translator: executed pcs per CPU, the instructions that write the tile RAMs, the
sites of the I/O accesses and the 50XX's commands, in the STE schedule (run_frame_port, the boot self-test skipped).
    python ref/cover.py <seed> <frames>  ->  build/xevious/xevious_cover_<seed>.pkl

Seeds: 1-3 random play (1 player); 4-5 two players; 6 no coin (the whole attract mode); 7-9 more play with lives
(DIP) variants; the 11-14 infinite lives (MAME's cheat), 60000 frames; 31-34 invincible (the cheat's `ret` at $1492 in the reference's ROM image), 60000 frames: the later areas.
"""
import os, pickle, random, sys
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from paths import build_dir
from machine import Xevious

seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
frames = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
rnd = random.Random(seed)
INVINCIBLE = seed >= 31                  # MAME's invincibility cheat (a ROM patch of the reference: the translation is not patched)
m = Xevious(skip_tests=True, invincible=INVINCIBLE)
PLAYERS = 2 if seed in (4, 5) else 1
NOCOIN = seed == 6
INFINITE = 11 <= seed < 31                    # infinite lives: the later areas (random play dies in the first ones)
if seed in (7, 8):
    m.dswa = 0xff & ~0x60 | (0x40 if seed == 7 else 0x00)      # 1 life / 5 lives
if seed == 9:
    m.dswb = m.dswb & ~0x60 | 0x00                              # hardest

pcs = [set(), set(), set()]
vwrites = [set(), set(), set()]       # the instructions that write the tile RAMs ($B000-$CFFF)
sites = {"bb_read": [set(), set(), set()], "latch": [set(), set(), set()], "bs": [set(), set(), set()],
         "latch06": [set(), set(), set()]}
cur = [0, 0, 0]
orig = [c.step for c in m.cpus]
for n in range(3):
    def step(n=n, cpu=m.cpus[n], f=orig[n]):
        pcs[n].add(cpu.pc)
        cur[n] = cpu.pc
        return f()
    m.cpus[n].step = step
    def wr8(a, v, n=n, f=m.cpus[n].wr8):
        if 0xb000 <= a < 0xd000:
            vwrites[n].add(cur[n])
        elif 0xd000 <= a < 0xd080:
            sites["latch"][n].add(cur[n])
        elif 0x6820 <= a <= 0x6827:
            sites["latch06"][n].add(cur[n])
        elif a >= 0xf000:
            sites["bs"][n].add(cur[n])
        return f(a, v)
    m.cpus[n].wr8 = wr8
    def rd8(a, n=n, f=m.cpus[n].rd8):
        if a >= 0xf000:
            sites["bb_read"][n].add(cur[n])
        return f(a)
    m.cpus[n].rd8 = rd8


def credit_mode():
    """the 51XX is back in credit mode (a game over): RAM $03 = 0 (2 in a game)"""
    return m.n51.mcu.ram[3] == 0


coin_at = 300 + rnd.randrange(600)
state = "attract"
joy = 0
games = 0
t0 = 0
for f in range(frames):
    m.in0 = m.in1 = 0xff
    m.dswb |= 1
    if INFINITE:
        m.mem[0x8183] = 9                                   # MAME's Infinite Lives cheat ($8183)
    if state == "attract" and f >= coin_at and not NOCOIN:
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
        if g % 12 == 0:
            joy = rnd.choice([0, 1, 2, 3, 4, 5, 6, 7, 8])
        bits = {1: 0x01, 2: 0x03, 3: 0x02, 4: 0x06, 5: 0x04, 6: 0x0c, 7: 0x08, 8: 0x09}.get(joy, 0)
        m.in0 &= ~bits
        if rnd.random() < 0.15: m.in1 &= ~0x01
        if rnd.random() < 0.05: m.dswb &= ~1               # button 2 (the bomb) reads through the switch bank
    if state == "play":
        if credit_mode() and g > 600:                       # game over (the 51XX back in credit mode)
            state, t0 = "over", f
            games += 1
    if state == "over" and f - t0 > 300:
        state = "attract"
        coin_at = f + 300
    m.run_frame_port()
    if f % 2000 == 0:
        print(seed, "frame", f, state, "pcs", [len(p) for p in pcs], flush=True)
pickle.dump({"pcs": pcs, "vwrites": vwrites, "sites": sites, "frames": frames, "seed": seed, "n50": m.n50.log[:200], "n50_cmds": sorted({v for k, f, v in m.n50.log if k == "w"}), "n50_reads": sum(1 for e in m.n50.log if e[0] == "r"), "n54_cmds": sorted(set(m.n54.log_cmds))},
            open(build_dir("xevious") / ("xevious_cover_%d.pkl" % seed), "wb"))
print("done", seed, [len(p) for p in pcs], "tile RAM writers", [len(w) for w in vwrites], "games", games,
      "bb read sites", [sorted(s) for s in sites["bb_read"]])
