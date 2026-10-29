"""Coverage of the main Z80 in the port's schedule (tools/machine.py MoonPatrolPort.run_frame_port), with scripted play.

    python games/mpatrol/ref/cover.py <seed> [frames]  ->  build/mpatrol/cover<seed>.pkl

pcs: the pcs executed; jumps: where computed jumps went (jp (hl) / (ix) / (iy)); writes: (pc, address) of the stores
to the text RAM $8000-$87FF, the sprite RAM $C800-$CFFF and the latches $D000-$D7FF (the instruction's start pc);
io: (pc, port, 'r' / 'w'); idle: Counter of the hooks the foreground waited at; sprites: Counter of (code, colour,
flip x, flip y) of the sprites on the screen each frame (they decide the prepared sprite data); courses: Counter of
(course $E510, point $E50E) a frame in play.

Seeds (RAM from MAME's cheats, mpatrol.xml: $E046 the game's state, $E510 the course, $E50E the point, $E511 the time,
$E515 the lives):
  1-2   play as it comes: deaths, the continue, game over, a new game (seed 2: two players, coin twice, start 2);
  3-6   the invulnerability DIP switch and infinite lives, starting the Beginner course (3) or Champion 1-3 (4-6), and
        MAME's "finish current section" every 900 frames of play: every point of the course, the course's end;
  7     the sector selection DIP switch (the game's own: start 1 selects);
  8     the stop mode DIP switch (2 stops, 1 goes on) with plain play;
  9     other DIP switches: 5 lives, no bonus life, 1 coin 2 credits, coin mode 2.
Not covered: the service mode ($3300-$393B, DSW2 bit 7) and the flip screen (cocktail).
"""
import pickle
import random
import sys
from collections import Counter
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools"), str(Path(__file__).resolve().parents[3] / "engine")]
from machine import MoonPatrolPort, DSW1, DSW2
from paths import build_dir

SECTION_END = (0x04, 0x09, 0x0E, 0x13, 0x19, 0x1E, 0x23, 0x28, 0x2D, 0x33)     # (MAME's "finish current section")


def dsw(seed):
    d1, d2 = DSW1, DSW2
    if seed == 9:
        d1 = 0x03 | 0x00 | 0x70                      # 5 lives, no bonus life, 1 coin 2 credits
        d2 &= ~0x04                                  # coin mode 2
    if 3 <= seed <= 6:
        d2 &= ~0x40                                  # invulnerability (cheat)
    if seed == 7:
        d2 &= ~0x20                                  # sector selection (cheat)
    if seed == 8:
        d2 &= ~0x10                                  # stop mode (cheat)
    return d1, d2


def inputs(frame, rnd, state, seed):
    """-> (IN0, IN1), active low.  state: the script's phases (attract, coin, play)."""
    in0, in1 = 0xFF, 0xFF
    phase = state.setdefault("phase", "attract")
    if phase == "attract" and frame >= state.setdefault("coin_at", 300 + rnd.randrange(1500)):
        state["phase"], state["t0"] = "coin", frame
    if state["phase"] == "coin":
        t = frame - state["t0"]
        two = seed == 2
        if t < 20 or two and 40 <= t < 60:
            in0 &= ~0x08                             # coin 1 (held: the game wants it some frames)
        elif 90 <= t < 100:
            in0 &= ~(0x02 if two else 0x01)          # start 2 / start 1
        elif t >= 100:
            state["phase"], state["t0"] = "play", frame
    if state["phase"] == "play":
        if frame >= state.get("next", 0):
            state["next"] = frame + rnd.choice((4, 8, 12, 20, 30, 60))
            state["joy"] = rnd.choice([0, 0x01, 0x01, 0x01, 0x02, 0x01, 0x02])      # right (faster) / left
            state["fire"] = rnd.choice([0, 0x80, 0x20, 0x80, 0x20, 0xA0])          # the two buttons
        in1 ^= state["joy"]
        if frame % 6 < 3:
            in1 ^= state["fire"]
        if frame - state["t0"] > 2000 and frame % 1500 == 0:
            state["phase"], state["t0"] = "coin", frame     # (a coin and start again: the continue, a new game)
            state["games"] = state.get("games", 0) + 1
        if seed == 7 and frame % 53 == 7 and state.setdefault("selects", 0) < 10 + 4 * state.get("games", 0):
            in0 &= ~0x01                                 # (sector selection: start 1 selects, 10 more each game)
            state["selects"] += 1
        if seed == 8:
            t = frame % 700
            if 300 <= t < 304:
                in0 &= ~0x02                             # (stop mode: 2 stops ...)
            elif 400 <= t < 404:
                in0 &= ~0x01                             # (... 1 goes on)
    return in0, in1


def cheats(seed, frame, m, state):
    """the pokes of MAME's cheats before the frame"""
    if not 3 <= seed <= 6:
        return
    mem = m.mem
    mem[0xE515] = 0x0A                                   # infinite lives
    if mem[0xE046] in (0x80, 0x90) and mem[0xE510] == 0 and seed > 3:
        mem[0xE510] = seed - 3                           # the starting course (MAME's "select starting course")
        if mem[0xE50E] == 0:
            mem[0xE50E] = 0x1A
    if mem[0xE046] & 0x89 == 0x81:                       # player 1 in play
        state["played"] = state.get("played", 0) + 1
        if state["played"] % 900 == 0:                   # MAME's "finish current section now"
            p = mem[0xE50E]
            end = next((e for e in SECTION_END if p <= e), 0x33)
            mem[0xE50B] = 0x3C
            mem[0xE511], mem[0xE512] = 0x21, 0x01
            mem[0xE50E] = end
            mem[0xE1DC] = 0x01


def sprites_on_screen(m, out):
    sr = m.sprite_ram
    for o in range(0, 0x100, 4):
        sy, attr, code, sx = 257 - sr[o], sr[o + 1], sr[o + 2], sr[o + 3] + 129
        if sx + 16 > 136 and sx <= 375 and sy + 16 > 22 and sy <= 273:
            out[(code, attr & 0x0F, bool(attr & 0x40), bool(attr & 0x80))] += 1


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    rnd = random.Random(seed)
    m = MoonPatrolPort(*dsw(seed))
    c = m.cpu
    pcs, jumps, writes, io = set(), set(), set(), set()
    site = [0]
    computed = [False]
    step0, rd0, wr0, in0, out0 = c.step, m.rd, m.wr, m.io_rd, m.io_wr

    def step():
        pc = c.pc
        site[0] = pc
        pcs.add(pc)
        if computed[0]:
            jumps.add(pc)
        op = rd0(pc)
        computed[0] = op == 0xE9 or op in (0xDD, 0xFD) and rd0((pc + 1) & 0xFFFF) == 0xE9
        return step0()

    def wr(a, v):
        if 0x8000 <= a < 0x8800 or 0xC800 <= a < 0xD800:
            writes.add((site[0], a))
        return wr0(a, v)

    def io_rd(p):
        io.add((site[0], p & 0xFF, "r"))
        return in0(p)

    def io_wr(p, v):
        io.add((site[0], p & 0xFF, "w"))
        return out0(p, v)

    c.step, c.wr8, c.io_in, c.io_out = step, wr, io_rd, io_wr
    m.wr, m.io_rd, m.io_wr = wr, io_rd, io_wr
    state = {}
    idle, sprites, states, courses = Counter(), Counter(), Counter(), Counter()
    for frame in range(frames):
        m.in0, m.in1 = inputs(frame, rnd, state, seed)
        cheats(seed, frame, m, state)
        m.run_frame_port()
        idle[m.idle_pc] += 1
        states[m.mem[0xE046]] += 1
        if m.mem[0xE046] & 0x81 == 0x81:
            courses[(m.mem[0xE510], m.mem[0xE50E])] += 1
        sprites_on_screen(m, sprites)
        if frame % 2000 == 0:
            print("seed %d frame %d: %d pcs, state %02X course %d point %02X" % (
                seed, frame, len(pcs), m.mem[0xE046], m.mem[0xE510], m.mem[0xE50E]), flush=True)
    out = build_dir("mpatrol") / ("cover%d.pkl" % seed)
    out.write_bytes(pickle.dumps({"pcs": pcs, "jumps": jumps, "writes": writes, "io": io, "idle": idle,
                                  "sprites": sprites, "states": states, "courses": courses, "seed": seed,
                                  "frames": frames}))
    print(out, len(pcs), "pcs; states", {"%02X" % k: v for k, v in states.items()},
          "; courses", sorted({k[0] for k in courses}), "points", len(courses))


if __name__ == "__main__":
    main()
