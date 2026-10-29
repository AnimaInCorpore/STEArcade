"""Coverage of the Z80 program in the port's schedule (tools/machine.py PacmanPort.run_frame_port), with scripted play.

    python ref/cover.py <seed> [frames]  ->  build/pacman/cover<seed>.pkl

pcs, jumps (where computed jumps went: jp (hl) / (ix) / (iy)), writes ((pc, address) of the stores to the video and
colour RAM $4000-$47FF, the sprite RAM $4FF0-$4FFF and the I/O $5000-$50FF), io ((pc, address, 'r' / 'w') of the
accesses to $5000-$5FFF and to anything outside ROM and RAM: $4800-$4BFF, the mirrors from $6000), outs ((pc, port,
value) of `out`), halts (pcs).

Seeds: 1-3 attract, coin, start and random 4-way play to the game over, and again; 4-6 infinite lives (MAME cheat
$4E14) and a level finished now and then (MAME's "Finish this Level Now!": $4E0E = $F4), so the play reaches the
intermissions and later levels; 7 two players; 8 the other DIP switches (2 coins 1 credit, 5 lives, bonus 15000, hard,
alternate ghost names); 9 free play, bonus none, 1 life; 10 the rack test switch now and then in play; 11 level 20 on
(and finished often); 12 level 250 on: the levels past 255 (the split screen).  The service mode is left out: its
tests never wait for a frame (the port's schedule has no place to deliver the IRQ there), and the port has no switch
for it.
"""
import collections
import pickle
import random
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'tools'), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import PacmanPort, DSW1_DEFAULT, UP, LEFT, RIGHT, DOWN
from paths import build_dir

LIVES, DOTS, LEVEL = 0x4E14, 0x4E0E, 0x4E13
SEEDS = range(1, 13)


def dsw1(seed):
    if seed == 8:
        return 0x03 | 0x0C | 0x10 | 0x00 | 0x00       # 2C/1C, 5 lives, bonus 15000, hard, alternate names
    if seed == 9:
        return 0x00 | 0x00 | 0x30 | 0x40 | 0x80       # free play, 1 life, no bonus
    return DSW1_DEFAULT


def inputs(frame, rnd, state):
    """-> (joy, coin, start1, start2, service, rack): the joystick bits pressed (active high), the switches"""
    seed = state['seed']
    two = seed == 7
    joy = 0
    coin = start1 = start2 = False
    service = False         # (the service mode's tests never wait for a frame: not in the port)
    rack = seed == 10 and state.get('phase') == 'play' and (frame // 400) % 5 == 4
    if state.setdefault('phase', 'attract') == 'attract' and frame >= state.setdefault('coin_at', 300 + rnd.randrange(1500)):
        state['phase'], state['t0'] = 'coin', frame
    if state['phase'] == 'coin':
        t = frame - state['t0']
        if t < 4 or (two or seed == 8) and 20 <= t < 24 or seed == 8 and 40 <= t < 44:
            coin = True
        elif 80 <= t < 84:
            start2, start1 = two, not two
        elif t >= 84:
            state['phase'], state['t0'] = 'play', frame
    if state['phase'] == 'play':
        if frame >= state.get('next', 0):
            state['next'] = frame + rnd.choice((4, 8, 16, 30, 60, 90))
            state['joy'] = rnd.choice((UP, DOWN, LEFT, RIGHT, UP, DOWN, LEFT, RIGHT, 0, UP | LEFT))
        joy = state['joy']
        if frame - state['t0'] > 3000 and frame % 3000 == 0:
            state['phase'], state['t0'] = 'coin', frame   # (coin and start again: a new game after a game over)
    return joy, coin, start1, start2, service, rack


def apply_inputs(m, frame, rnd, state):
    joy, coin, start1, start2, service, rack = inputs(frame, rnd, state)
    m.set_inputs(joy, coin, start1, start2)
    if rack:
        m.in0 &= ~0x10
    if service:
        m.in1 &= ~0x10


def cheats(seed, frame, m, state):
    """RAM pokes between frames (logic_test.py makes the same on the 68000 side)"""
    ram = m.ram
    if state.get('phase') != 'play':
        return
    t = frame - state['t0']
    if 4 <= seed <= 6 or seed >= 11:
        ram[LIVES - 0x4000] = 6
        ram[LIVES + 1 - 0x4000] = 5
    if seed in (11, 12) and t == 150:
        ram[LEVEL - 0x4000] = 20 if seed == 11 else 250
    period = {4: 2400, 5: 1500, 6: 900, 11: 700, 12: 600}.get(seed)
    if period and t > 300 and t % period == 0:
        ram[DOTS - 0x4000] = 0xF4


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    rnd = random.Random(seed)
    m = PacmanPort(dsw1=dsw1(seed))
    c = m.cpu
    pcs, jumps, writes, io, outs, halts = set(), set(), set(), set(), set(), set()
    site = [0]
    computed = [False]
    step0, rd0, wr0, out0 = c.step, m.rd8, m.wr8, c.io_out

    def step():
        pc = c.pc
        site[0] = pc
        pcs.add(pc)
        if computed[0]:
            jumps.add(pc)
        op = rd0(pc)
        computed[0] = op == 0xE9 or op in (0xDD, 0xFD) and rd0((pc + 1) & 0xFFFF) == 0xE9
        if op == 0x76:
            halts.add(pc)
        return step0()

    def rd(a):
        if 0x4800 <= a < 0x4C00 or a >= 0x5000:
            io.add((site[0], a, 'r'))
        return rd0(a)

    def wr(a, v):
        if 0x4000 <= a < 0x4800 or 0x4FF0 <= a < 0x5100:
            writes.add((site[0], a))
        if a < 0x4000 or 0x4800 <= a < 0x4C00 or a >= 0x5000:
            io.add((site[0], a, 'w'))
        return wr0(a, v)

    def out(port, v):
        outs.add((site[0], port & 0xff, v))
        return out0(port, v)
    c.step, c.rd8, c.wr8, c.io_out = step, rd, wr, out

    levels = collections.Counter()
    state = {'seed': seed}
    for frame in range(frames):
        apply_inputs(m, frame, rnd, state)
        cheats(seed, frame, m, state)
        m.run_frame_port()
        levels[m.ram[LEVEL - 0x4000]] += 1
        if frame % 2000 == 0:
            print(f'seed {seed} frame {frame}: {len(pcs)} pcs, level {m.ram[LEVEL - 0x4000]}', flush=True)
    out = build_dir('pacman') / f'cover{seed}.pkl'
    out.write_bytes(pickle.dumps({'pcs': pcs, 'jumps': jumps, 'writes': writes, 'io': io, 'outs': outs,
                                  'halts': halts, 'levels': levels, 'seed': seed, 'frames': frames}))
    print(out, len(pcs), 'pcs, levels', sorted(levels))


if __name__ == '__main__':
    main()
