"""Coverage of the main CPU in the port's schedule (tools/machine.py MikiePort.run_frame_port), with scripted play.

    python ref/cover.py <seed> [frames]  ->  build/mikie/cover<seed>.pkl

The pickle: the 6809 coverage (engine/m6809cover.py: exec, acc, targets, wraps, io: the accesses outside the RAM and
the ROM's reads, the video RAM's stores); pens: the pens' pixel counts of the reference pictures (every 8th frame);
sprites: Counter of (code, gfx bank, palette-bank colour, flip x, flip y) entries.

Seeds: 1-3 attract, coin, start, random play (to the game over and again); 4-6 the same with player 1's lives kept at
$2970 (the game runs on: every stage reached by play); 7-8 two players; 9 the other DIP switches (7 lives, bonus 40k,
hardest, no demo sounds), 10 the service-less variants: start button held at the start.
"""
import collections
import pickle
import random
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'tools'), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import MikiePort, Video, DSW1, DSW2, DSW3
from m6809cover import Cover6809
from paths import build_dir

LIVES1 = 0x2970
LEFT, RIGHT, UP, DOWN, B1, B2 = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20     # P1 / P2 bits (active low)


def dsw(seed):
    if seed == 9:
        return DSW1, 0x80 & 0, DSW3                       # 7 lives, bonus 40k only, hardest, demo sounds on
    return DSW1, DSW2, DSW3


def inputs(frame, rnd, state):
    """-> (SYSTEM, P1, P2), active low.  Play: a mode at a time (walking in one direction, hitting, idle), each for a
    random while; both players the same when two play."""
    system, p1 = 0xFF, 0xFF
    two = state.get('two', False)
    if state.setdefault('phase', 'attract') == 'attract' and frame >= state.setdefault('coin_at', 300 + rnd.randrange(1200)):
        state['phase'], state['t0'] = 'coin', frame
    if state['phase'] == 'coin':
        t = frame - state['t0']
        if t < 4 or two and 20 <= t < 24:
            system &= ~0x01
        elif 60 <= t < 64:
            system &= ~(0x10 if two else 0x08)
        elif t >= 64:
            state['phase'], state['t0'] = 'play', frame
    if state['phase'] == 'play':
        if frame >= state.get('next', 0):
            state['next'] = frame + rnd.choice((8, 16, 30, 60, 120, 240))
            state['dir'] = rnd.choice((0, LEFT, RIGHT, UP, DOWN, LEFT | UP, RIGHT | UP, LEFT | DOWN, RIGHT | DOWN))
            state['btn'] = rnd.choice((0, 0, B1, B2, B1 | B2))
            state['rate'] = rnd.choice((0, 0, 2, 4, 8))
        t = frame - state['t0']
        bits = state['dir']
        btn = state['btn']
        if state['rate'] and (t // state['rate']) & 1:
            btn = 0
        bits |= btn
        p1 ^= bits
        if t > 3000 and frame % 3000 == 0:
            state['phase'], state['t0'] = 'coin', frame
    return system, p1, p1 if two else 0xFF


def cheats(seed, frame, m, state):
    if 4 <= seed <= 6 and m.mem[LIVES1] < 2:
        m.mem[LIVES1] = 2


def io(a, rw):
    """the accesses the translation sends through the runtime: the I/O, the unmapped space, stores to the ROM and the
    stores to the video and colour RAM ($3800-$3FFF: main_io_w lists the changed cells for the renderer)"""
    return not (a < 0x100 or 0x2800 <= a < 0x3800 or 0x3800 <= a < 0x4000 and rw == 'r' or a >= 0x6000 and rw == 'r')


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    rnd = random.Random(seed)
    m = MikiePort(*dsw(seed))
    cov = Cover6809(m.cpu, io=io)
    video = Video()
    pens = collections.Counter()
    sprites = collections.Counter()
    state = {'two': seed in (7, 8)}
    mem = m.mem
    for frame in range(frames):
        m.frame = frame
        m.system, m.in0, m.in1 = inputs(frame, rnd, state)
        cheats(seed, frame, m, state)
        m.run_frame_port()
        for o in range(0, 0x90, 4):
            a0, a2 = mem[0x2800 + o], mem[0x2802 + o]
            sprites[((a2 & 0x3F) + ((a2 & 0x80) >> 1) + ((a0 & 0x40) << 1), a2 >> 6 & 1, a0 & 15,
                     not a0 & 0x10, bool(a0 & 0x20))] += 1
        if frame % 8 == 0:
            raw = video.render_raw(mem, m.palbank)[16:240]
            cnt = np.bincount(raw.ravel(), minlength=4096)
            for p in np.nonzero(cnt)[0]:
                pens[int(p)] += int(cnt[p])
        if frame % 2000 == 0:
            print(f'seed {seed} frame {frame}: {len(cov.exec)} pcs, state {mem[0x2902]}, lives {mem[LIVES1]}', flush=True)
    out = build_dir('mikie') / f'cover{seed}.pkl'
    d = cov.data()
    d.update({'pens': pens, 'sprites': sprites, 'seed': seed, 'frames': frames})
    out.write_bytes(pickle.dumps(d))
    print(out, len(cov.exec), 'pcs')


if __name__ == '__main__':
    main()
