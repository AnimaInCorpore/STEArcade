"""Coverage of the main CPU in the port's schedule (tools/machine.py TimepltPort.run_frame_port), with scripted play.

    python ref/cover.py <seed> [frames]  ->  build/timeplt/cover<seed>.pkl

pcs, jumps (where computed jumps went: jp (hl) / (ix) / (iy)), writes ((pc, address) of the stores to the video RAM
$A000-$A7FF, the sprite RAMs $B000-$BFFF and the I/O $C000-$CFFF), io ((pc, address, 'r' / 'w') of the accesses to
$C000-$CFFF); pens: the pens' pixel counts of the reference pictures (every 8th frame), per era too (eras: Counter per
[$AD14]); sprites: Counter of (code, colour, flip x, flip y) entries; clouds: reused cloud instances seen.

Seeds: 1-3 attract, coin, start and random play to the game over and again; 4-8 infinite lives (MAME cheat $AD10)
from stage 1-5 ($AD11 / $AD14) with the guardian called now and then ($AD02), so the play reaches every era and the
stage changes; 9 invincible ($A800) with the guardian called often: many stages, the later loops; 10-11 two players;
12 the DIP switches' other bonus, 5 lives, the hardest difficulty, no demo sounds.
"""
import collections
import pickle
import random
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'tools'), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import TimepltPort, Video, DSW0, DSW1
from paths import build_dir

LIVES, STAGE, ERA, GUARDIAN, INVINCIBLE = 0xAD10, 0xAD11, 0xAD14, 0xAD02, 0xA800


def dsw(seed):
    if seed == 12:
        return DSW0, (DSW1 & ~0xFB) | 0x01 | 0x00 | 0x00 | 0x80   # 5 lives, bonus 20000 60000, hardest, no demo sounds
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
            state['joy'] = rnd.choice([0, 1, 2, 4, 8, 5, 6, 9, 10, 1, 2, 4, 8])
            state['fire'] = rnd.choice([0, 0x10, 0x10, 0x10])
        p1 ^= state['joy']
        if frame % 6 < 3:
            p1 ^= state['fire']
        if frame - state['t0'] > 3000 and frame % 2500 == 0:
            state['phase'], state['t0'] = 'coin', frame   # (coin and start again: a new game after a game over)
    return system, p1, p1 if two else 0xFF


def cheats(seed, frame, m, state):
    mem = m.mem
    if 4 <= seed <= 9 and frame > 300:
        mem[LIVES] = 7
    if 4 <= seed <= 8 and mem[0xAD30] == 0xFF and mem[STAGE] == 1:
        mem[STAGE] = seed - 3
        mem[ERA] = (seed - 4) % 5
    if seed == 9:
        mem[INVINCIBLE] = 0xFF
    if (4 <= seed <= 8 and frame % 3000 == 2999) or (seed == 9 and frame % 900 == 899):
        mem[GUARDIAN] = 0


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    rnd = random.Random(seed)
    m = TimepltPort(*dsw(seed))
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
        if 0xC000 <= a < 0xD000:
            io.add((site[0], a, 'r'))
        elif 0x6000 <= a < 0xA000 or a >= 0xD000:
            io.add((site[0], a, 'r'))               # (unmapped: reads $FF on the board)
        return rd0(a)

    def wr(a, v):
        if 0xA000 <= a < 0xA800 or 0xB000 <= a < 0xD000:
            writes.add((site[0], a))
        if 0xC000 <= a < 0xD000 or a < 0xA000 or a >= 0xD000:
            io.add((site[0], a, 'w'))
        return wr0(a, v)
    c.step, c.rd8, c.wr8 = step, rd, wr

    video = Video()
    pens = collections.Counter()
    eras = collections.defaultdict(collections.Counter)
    sprites = collections.Counter()
    clouds = collections.Counter()
    state = {'two': seed in (10, 11)}
    for frame in range(frames):
        m.system, m.p1, m.p2 = inputs(frame, rnd, state)
        cheats(seed, frame, m, state)
        m.run_frame_port()
        mem = m.mem
        for o in range(0x10, 0x40, 2):
            a = mem[0xB400 + o]
            sprites[(mem[0xB001 + o], a & 0x3F, not a & 0x40, bool(a & 0x80))] += 1
        for e in m.extra:
            clouds[e[0]] += 1
            sprites[(e[2], e[3] & 0x3F, not e[3] & 0x40, bool(e[3] & 0x80))] += 1
        if frame % 8 == 0:
            raw = video.render_raw(mem, m.extra)[16:240]
            cnt = np.bincount(raw.ravel(), minlength=384)
            era = mem[ERA]
            for p in np.nonzero(cnt)[0]:
                pens[int(p)] += int(cnt[p])
                eras[era][int(p)] += int(cnt[p])
        if frame % 2000 == 0:
            print(f'seed {seed} frame {frame}: {len(pcs)} pcs, stage {mem[STAGE]} era {mem[ERA]}', flush=True)
    out = build_dir('timeplt') / f'cover{seed}.pkl'
    out.write_bytes(pickle.dumps({'pcs': pcs, 'jumps': jumps, 'writes': writes, 'io': io, 'pens': pens,
                                  'eras': dict(eras), 'sprites': sprites, 'clouds': clouds, 'seed': seed,
                                  'frames': frames}))
    print(out, len(pcs), 'pcs,', sum(clouds.values()), 'clouds reused')


if __name__ == '__main__':
    main()
