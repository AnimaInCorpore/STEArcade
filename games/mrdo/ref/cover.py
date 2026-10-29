"""Coverage of the Z80 program in the port's schedule (tools/machine.py MrDoPort.run_frame_port), with scripted play.

    python ref/cover.py <seed> [frames]  ->  build/mrdo/cover<seed>.pkl

pcs, jumps (where computed jumps went: jp (hl) / (ix) / (iy)), writes ((pc, address) of the stores to the video RAM
$8000-$8FFF, the sprite RAM $9000-$90FF and the I/O $9800-$FFFF), io ((pc, address, 'r' / 'w') of the accesses
outside ROM and RAM: $9000-$DFFF and $F000-$FFFF), outs / ins ((pc, port) of `out` / `in`), halts (pcs), sprites
(Counter of (code, attr) of the shown entries), scenes (Counter of the scene number $E09B).

Seeds: 1-3 attract, coin, start and random play to the game over, and again; 4-6 infinite lives (MAME cheat $E097)
and random play, seed 6 with fire held often; 7 two players; 8 the other DIP switches (hard, special / extra hard,
5 lives, 2 coins 1 credit); 9 free play, hardest, 2 lives; 10 the rack test switch (DSW1 bit 2) now and then in play:
the scenes go by; 11 / 12 the start scene (MAME cheat $E09B) set to 10 / 21 and infinite lives.  The cocktail cabinet
(flip screen) and the service test (both fire buttons at power on) are left out: the port is upright and has no
switch for them.
"""
import collections
import pickle
import random
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'tools'), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import MrDoPort, DSW1_DEFAULT, DSW2_DEFAULT, UP, LEFT, RIGHT, DOWN
from paths import build_dir

LIVES, SCENE = 0xE097, 0xE09B
SEEDS = range(1, 13)


def dsw(seed):
    if seed == 8:
        return 0x01 | 0x04 | 0x00 | 0x00 | 0x40, 0xA0 | 0x0F       # hard, special / extra hard, 5 lives; 2C/1C
    if seed == 9:
        return 0x00 | 0x04 | 0x18 | 0x00, 0x00                      # hardest, 2 lives; free play
    return DSW1_DEFAULT, DSW2_DEFAULT


def inputs(frame, rnd, state):
    """-> (joy, fire, coin, start1, start2, rack): the joystick bits pressed (active high), the switches"""
    seed = state['seed']
    two = seed == 7
    joy = 0
    fire = coin = start1 = start2 = False
    rack = seed == 10 and state.get('phase') == 'play' and (frame // 300) % 4 == 3
    if state.setdefault('phase', 'attract') == 'attract' and frame >= state.setdefault('coin_at', 300 + rnd.randrange(1500)):
        state['phase'], state['t0'] = 'coin', frame
    if state['phase'] == 'coin':
        t = frame - state['t0']
        if seed != 9 and (t < 4 or (two or seed == 8) and 20 <= t < 24 or seed == 8 and two and 40 <= t < 44):
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
        fire = rnd.random() < (0.5 if seed == 6 else 0.1)
        if frame - state['t0'] > 3000 and frame % 3000 == 0:
            state['phase'], state['t0'] = 'coin', frame   # (coin and start again: a new game after a game over)
    return joy, fire, coin, start1, start2, rack


def apply_inputs(m, frame, rnd, state):
    joy, fire, coin, start1, start2, rack = inputs(frame, rnd, state)
    m.set_inputs(joy, fire, coin, start1, start2)
    d1 = dsw(state['seed'])[0]
    m.dsw1 = d1 & ~0x04 if rack else d1


def cheats(seed, frame, m, state):
    """RAM pokes between frames (logic_test.py makes the same on the 68000 side)"""
    ram = m.ram
    if 4 <= seed <= 6 or seed >= 11:
        ram[LIVES - 0xE000] = 6
    if seed in (11, 12) and ram[SCENE - 0xE000] == 0x01:
        ram[SCENE - 0xE000] = 0x10 if seed == 11 else 0x21


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    rnd = random.Random(seed)
    d1, d2 = dsw(seed)
    m = MrDoPort(dsw1=d1, dsw2=d2)
    c = m.cpu
    pcs, jumps, writes, io, ports, halts = set(), set(), set(), set(), set(), set()
    site = [0]
    computed = [False]
    step0, rd0, wr0 = c.step, m.rd8, m.wr8

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
        if op in (0xD3, 0xDB) or op == 0xED and rd0((pc + 1) & 0xFFFF) & 0xC6 == 0x40:
            ports.add(pc)
        return step0()

    def rd(a):
        if 0x9000 <= a < 0xE000 or a >= 0xF000:
            io.add((site[0], a, 'r'))
        return rd0(a)

    def wr(a, v):
        if 0x8000 <= a < 0x9100 or a >= 0x9800 and not 0xE000 <= a < 0xF000:
            writes.add((site[0], a))
        if a < 0x8000 or 0x9000 <= a < 0xE000 or a >= 0xF000:
            io.add((site[0], a, 'w'))
        return wr0(a, v)
    c.step, c.rd8, c.wr8 = step, rd, wr

    scenes = collections.Counter()
    sprites = collections.Counter()
    state = {'seed': seed}
    for frame in range(frames):
        apply_inputs(m, frame, rnd, state)
        cheats(seed, frame, m, state)
        m.run_frame_port()
        scenes[m.ram[SCENE - 0xE000]] += 1
        sr = m.spriteram
        for o in range(0, 0x100, 4):
            if sr[o + 1]:
                sprites[(sr[o], sr[o + 2])] += 1
        if frame % 2000 == 0:
            print(f'seed {seed} frame {frame}: {len(pcs)} pcs, scene {m.ram[SCENE - 0xE000]:02X}', flush=True)
    out = build_dir('mrdo') / f'cover{seed}.pkl'
    out.write_bytes(pickle.dumps({'pcs': pcs, 'jumps': jumps, 'writes': writes, 'io': io, 'ports': ports,
                                  'halts': halts, 'scenes': scenes, 'sprites': sprites, 'seed': seed,
                                  'frames': frames}))
    print(out, len(pcs), 'pcs, scenes', sorted('%02X' % s for s in scenes))


if __name__ == '__main__':
    main()
