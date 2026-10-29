"""Coverage of the main CPU in the port's schedule (tools/machine.py PooyanPort.run_frame_port), with scripted play.

    python ref/cover.py <seed> [frames]  ->  build/pooyan/cover<seed>.pkl

pcs, jumps (where computed jumps went: jp (hl) / (ix) / (iy)), writes ((pc, address) of the stores to the video RAM
$8000-$87FF, the sprite RAMs $9000-$9FFF and the I/O $A000-$FFFF), io ((pc, address, 'r' / 'w') of the accesses to
$A000-$FFFF and of stores into the ROM); pens: the pens' pixel counts of the reference pictures (every 8th frame), per
round too (rounds: Counter per [$8907]); sprites: Counter of (code, colour, flip x, flip y) entries.

Seeds: 1-3 attract, coin, start and random play to the game over and again; 4-8 infinite lives (MAME cheat $8908)
with "1 wolf left" ($8901) every 400-1200 frames, so the play goes through the rounds, the bonus stages and the later
loops; 9 a score of 50,000+ ($88A2-$88A3, BCD hundreds) before the game ends: the high-score entry; 10-11 two players; 12 the
DIP switches' other bonus, 5 lives, the hardest difficulty, no demo sounds; 13 no coin: the whole attract cycle
(its second half, state 18 at $71B9, a demo that starts ~95 s after power-on, frame 5781).
"""
import collections
import pickle
import random
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'tools'), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import PooyanPort, Video, DSW0, DSW1
from paths import build_dir

LIVES, WOLVES, ROUND, SCORE = 0x8908, 0x8901, 0x8907, 0x88A2


def dsw(seed):
    if seed == 12:
        return DSW0, 0x01 | 0x00 | 0x00 | 0x80   # 5 lives, upright, bonus 30K 70K+, hardest, no demo sounds
    return DSW0, DSW1


def inputs(frame, rnd, state):
    """-> (SYSTEM, P1, P2), active low"""
    system, p1 = 0xFF, 0xFF
    two = state.get('two', False)
    if state.setdefault('phase', 'attract') == 'attract' and frame >= state.setdefault('coin_at', 300 + rnd.randrange(1500)):
        state['phase'], state['t0'] = 'coin', frame
    if state['phase'] == 'coin':
        t = frame - state['t0']
        if t < 4 or two and 20 <= t < 24:
            system &= ~0x01                          # coin 1
        elif 60 <= t < 64:
            system &= ~(0x10 if two else 0x08)       # start 2 / start 1
        elif t >= 64:
            state['phase'], state['t0'] = 'play', frame
    if state['phase'] == 'play':
        if frame >= state.get('next', 0):
            state['next'] = frame + rnd.choice((4, 8, 16, 30, 60, 120))
            state['joy'] = rnd.choice([0, 0, 4, 8, 4, 8, 12])
            state['fire'] = rnd.choice([0, 0x10, 0x10, 0x10])
        p1 ^= state['joy']
        if frame % 6 < 3:
            p1 ^= state['fire']
        if frame - state['t0'] > 3000 and frame % 2500 == 0:
            state['phase'], state['t0'] = 'coin', frame   # (coin and start again: a new game after a game over)
    return system, p1, p1 if two else 0xFF


def cheats(seed, frame, m, state):
    mem = m.mem
    if 4 <= seed <= 8 and frame > 300:
        mem[LIVES] = 5
        if frame % (400 + 200 * (seed - 4)) == 0:
            mem[WOLVES] = 1
    if seed == 9 and state.get('phase') == 'play' and mem[SCORE] == 0 and frame - state['t0'] > 200:
        mem[SCORE] = 0x05


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    rnd = random.Random(seed)
    m = PooyanPort(*dsw(seed))
    c = m.cpu
    pcs, jumps, writes, io = set(), set(), set(), set()
    site = [0]
    computed = [False]
    step0, rd0, wr0 = c.step, m.rd, m.wr

    def step():
        pc = c.pc
        site[0] = pc
        pcs.add(pc)
        if computed[0]:
            jumps.add(pc)
        op = rd0(pc)
        computed[0] = op == 0xE9 or op in (0xDD, 0xFD) and rd0((pc + 1) & 0xFFFF) == 0xE9
        return step0()

    def rd(a):
        if a >= 0xA000:
            io.add((site[0], a, 'r'))
        return rd0(a)

    def wr(a, v):
        if 0x8000 <= a < 0x8800 or 0x9000 <= a:
            writes.add((site[0], a))
        if a >= 0xA000 or a < 0x8000:
            io.add((site[0], a, 'w'))
        return wr0(a, v)
    c.step, c.rd8, c.wr8 = step, rd, wr

    video = Video()
    pens = collections.Counter()
    rounds = collections.defaultdict(collections.Counter)
    sprites = collections.Counter()
    state = {'two': seed in (10, 11)}
    if seed == 13:
        state['coin_at'] = frames          # (never: attract mode only)
    for frame in range(frames):
        m.system, m.p1, m.p2 = inputs(frame, rnd, state)
        cheats(seed, frame, m, state)
        m.run_frame_port()
        mem = m.mem
        for o in range(0x10, 0x40, 2):
            a = mem[0x9400 + o]
            sprites[(mem[0x9001 + o] & 63, a & 15, not a & 0x40, bool(a & 0x80))] += 1
        if frame % 8 == 0:
            raw = video.render_raw(mem)[16:240]
            cnt = np.bincount(raw.ravel(), minlength=512)
            rnd_no = mem[ROUND]
            for p in np.nonzero(cnt)[0]:
                pens[int(p)] += int(cnt[p])
                rounds[rnd_no][int(p)] += int(cnt[p])
        if frame % 2000 == 0:
            print(f'seed {seed} frame {frame}: {len(pcs)} pcs, round {mem[ROUND] + 1}, score '
                  f'{mem[SCORE]:02X}{mem[SCORE + 1]:02X}{mem[SCORE + 2]:02X}', flush=True)
    out = build_dir('pooyan') / f'cover{seed}.pkl'
    out.write_bytes(pickle.dumps({'pcs': pcs, 'jumps': jumps, 'writes': writes, 'io': io, 'pens': pens,
                                  'rounds': dict(rounds), 'sprites': sprites, 'seed': seed, 'frames': frames}))
    print(out, len(pcs), 'pcs')


if __name__ == '__main__':
    main()
