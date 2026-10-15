"""Coverage of the main Z80 in the port's schedule (tools/machine.py KungFuPort.run_frame_port), with scripted play.

    python ref/cover.py <seed> [frames]  ->  build/kungfum/cover<seed>.pkl

pcs: the pcs executed; jumps: where computed jumps went (jp (hl) / (ix) / (iy)); writes: (pc, address) of the stores
to the tile RAM D000-DFFF, the sprite RAM C000-C0FF and the scroll A000 / B000 (the instruction's start pc); io:
(pc, port, 'r' / 'w'); idle: Counter of the hooks the foreground waited at; sprites: Counter of (code, flip x, flip y)
cells drawn on the screen each frame (they decide the prepared sprite data, tools/assets.py).

Seeds (MAME's cheats, kungfum.xml): 1-3 play as they come (lives infinite until frame 9000, then not: game over; seed
3 with its score raised to 90000 then: the high-score entry); 4-9 infinite lives and energy, after 400-900 frames of a floor the player put at the boss (MAME's cheat
"proceed to next floor" on the 5th floor: E712 = E102; E000 = $0C if the floor has not ended 3000 frames into it), the
boss killed by one hit (E2E2 = 0), so all five floors, the
bosses, floor 2's pots (dragons, snakes, confetti) and the ending's loop run; 10-11 the invulnerability DIP switch;
12-13 the level selection DIP switch (start 1 selects).
"""
import pickle
import random
import sys
from collections import Counter
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'tools'), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import KungFuPort, DSW1, DSW2
from paths import build_dir

PLAY_STATES = (4,)            # E000 while a floor is played


def dsw(seed):
    d2 = DSW2
    if seed in (10, 11):
        d2 &= ~0x40                                  # invulnerability (cheat)
    if seed in (12, 13):
        d2 &= ~0x20                                  # level selection mode (cheat)
    return DSW1, d2


def inputs(frame, rnd, state, m=None):
    """-> (SYSTEM, P1), active low.  state: the script's phases (attract, coin, play)."""
    system, p1 = 0xff, 0xff
    phase = state.setdefault('phase', 'attract')
    if phase == 'attract' and frame >= state.setdefault('coin_at', 600 + rnd.randrange(900)):
        state['phase'], state['t0'] = 'coin', frame
    if state['phase'] == 'coin':
        t = frame - state['t0']
        if t < 4:
            system &= ~0x08                          # coin 1
        elif 60 <= t < 64:
            system &= ~0x01                          # start 1
        elif t >= 64:
            state['phase'], state['t0'] = 'play', frame
    if state['phase'] == 'play':
        if frame >= state.get('next', 0):
            state['next'] = frame + rnd.choice((4, 8, 12, 20, 30))
            state['joy'] = rnd.choice([0, 0, 1, 1, 1, 2, 4, 8, 5, 6, 9, 10])
            state['fire'] = rnd.choice([0, 0x80, 0x20, 0x80, 0x20, 0xa0])
        p1 ^= state['joy']
        if frame % 4 < 2:
            p1 ^= state['fire']
        if frame - state['t0'] > 3000 and frame % 1200 == 0:
            state['phase'], state['t0'] = 'coin', frame   # (a coin and start again: a new game after a game over)
        if state.get('select') and frame % 97 == 5:
            system &= ~0x01                          # (level selection mode: start 1 selects)
    return system, p1


def cheats(seed, frame, m, state):
    """the pokes of MAME's cheats before the frame"""
    mem = m.mem
    if seed <= 3:
        if frame < 9000:
            mem[0xE084] = 6
        elif seed == 3 and mem[0xE000] == 4 and mem[0xE083] < 0x09:
            mem[0xE083] = 0x09               # (a score of 90000 and more: the game over's high-score entry)
        return
    mem[0xE084] = 6                                  # infinite lives
    if seed <= 9:
        if mem[0xE000] != 0x0C:
            mem[0xE709] = 0x3F                       # infinite energy (not while the floor's end counts it down)
        if frame % 60 == 0:
            mem[0xE2E2] = 0                          # one hit kills the boss
        if mem[0xE000] in PLAY_STATES:
            state['played'] = state.get('played', 0) + 1
            if state['played'] == 900 - 100 * (seed - 4):
                mem[0xE712:0xE714] = mem[0xE102:0xE104]   # to the boss (MAME's "proceed": the 5th floor's way)
            elif state['played'] >= 3000:
                state['played'] = 0
                mem[0xE000] = 0x0C                   # (no end yet: proceed to the next floor)
        else:
            state['played'] = 0


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    rnd = random.Random(seed)
    m = KungFuPort(*dsw(seed))
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
        computed[0] = op == 0xe9 or op in (0xdd, 0xfd) and rd0((pc + 1) & 0xffff) == 0xe9
        return step0()

    def wr(a, v):
        if 0xA000 <= a < 0xE000:
            writes.add((site[0], a))
        return wr0(a, v)

    def io_rd(p):
        io.add((site[0], p & 0xff, 'r'))
        return in0(p)

    def io_wr(p, v):
        io.add((site[0], p & 0xff, 'w'))
        return out0(p, v)

    c.step, c.wr8, c.io_in, c.io_out = step, wr, io_rd, io_wr
    m.wr, m.io_rd, m.io_wr = wr, io_rd, io_wr
    state = {'select': seed in (12, 13)}
    idle = Counter()
    sprites = Counter()
    states = Counter()
    floors = Counter()
    height = None
    for frame in range(frames):
        m.system, m.p1 = inputs(frame, rnd, state, m)
        cheats(seed, frame, m, state)
        m.run_frame_port()
        idle[m.idle_pc] += 1
        states[m.mem[0xE000]] += 1
        floors[m.mem[0xE080]] += 1
        if height is None:
            from machine import load
            height = load('b-5f-.bin')
        sr = m.sprite_ram
        for o in range(0, 256, 8):
            code = sr[o + 4] + ((sr[o + 5] & 7) << 8)
            sx = 256 * (sr[o + 7] & 1) + sr[o + 6]
            sy = 384 - 15 - (256 * (sr[o + 3] & 1) + sr[o + 2])
            h = height[(code >> 5) & 31]
            n = 2 if h == 1 else 4 if h == 2 else h + 1
            if h == 1:
                code &= ~1
            elif h == 2:
                code &= ~3
            if sx + 16 > 128 and sx < 384 and sy + 16 > 0 and sy - 16 * (n - 1) < 256:
                sprites[(code % 1024, n, bool(sr[o + 5] & 0x40), bool(sr[o + 5] & 0x80))] += 1
        if frame % 2000 == 0:
            print(f'seed {seed} frame {frame}: {len(pcs)} pcs, state {m.mem[0xE000]:02x} floor {m.mem[0xE080]:02x}',
                  flush=True)
    out = build_dir('kungfum') / f'cover{seed}.pkl'
    out.write_bytes(pickle.dumps({'pcs': pcs, 'jumps': jumps, 'writes': writes, 'io': io, 'idle': idle,
                                  'sprites': sprites, 'states': states, 'floors': floors, 'seed': seed,
                                  'frames': frames}))
    print(out, len(pcs), 'pcs; states', dict(states), 'floors', dict(floors))


if __name__ == '__main__':
    main()
