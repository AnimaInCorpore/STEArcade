"""Coverage of the main CPU in the port's schedule (tools/machine.py HyperSportsPort.run_frame_port), with scripted
play.

    python ref/cover.py <seed> [frames]  ->  build/hyperspt/cover<seed>.pkl

The pickle: the 6809 coverage (engine/m6809cover.py: exec, acc, targets, wraps, io: the accesses outside the RAM and
the ROM's reads, the video RAM's stores); pens: the pens' pixel counts of the reference pictures (every 8th frame);
sprites: Counter of (code, colour, flip x, flip y) entries; scrolls: Counter of the visible rows' scroll values.

Seeds (MAME's cheats, cheat.7z hyperspt.xml): 1-3 attract, coin, start, the name entry, random play to the game over
and again; 4-10 the start event 0-6 ($3068: free style, skeet shooting, long horse, archery, triple jump,
weightlifting, pole vault) with player 1 always on the first try ($3502) and no false starts ($3503): every event and
the rounds after; 11 two players (no cheats); 12 the DIP switches' other settings (the game continues after the last
event, records erased, no demo sounds, the hardest difficulty), first try.
"""
import collections
import pickle
import random
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'tools'), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import HyperSportsPort, Video, DSW1, DSW2
from m6809cover import Cover6809
from paths import build_dir

EVENT, FIRST_TRY, FALSE_START = 0x3068, 0x3502, 0x3503
RUN1, ACT, RUN3 = 0x04, 0x02, 0x01             # P1_P2 bits of player 1 (player 2: << 4)


def dsw(seed):
    if seed == 12:
        return DSW1, 0x00 | 0x00 | 0x04 | 0x00 | 0x00    # continues, upright, no demo sounds, erase, difficult 4
    return DSW1, DSW2


def inputs(frame, rnd, state):
    """-> (SYSTEM, P1_P2, P3_P4), active low.  Play: a mode at a time (running at a rate, the action button tapped or
    held, nothing), each for a random while; both players the same when two play."""
    system, p12 = 0xFF, 0xFF
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
            state['next'] = frame + rnd.choice((8, 16, 30, 60, 120, 240))
            state['mode'] = rnd.choice(('run', 'run', 'run', 'tap', 'tap', 'hold', 'idle', 'runjump', 'left', 'right'))
            state['rate'] = rnd.choice((1, 2, 2, 3, 4, 6))
            state['hold'] = rnd.choice((4, 10, 20, 40))
        mode, rate, t = state['mode'], state['rate'], frame - state['t0']
        bits = 0
        if mode in ('run', 'runjump'):
            bits |= RUN1 if (t // rate) & 1 else RUN3
        if mode == 'left' and (t // rate) & 1:
            bits |= RUN1                             # (skeet shooting, archery: the buttons fire left / right)
        if mode == 'right' and (t // rate) & 1:
            bits |= RUN3
        if mode == 'tap' and t % 12 < 2 or mode == 'runjump' and t % 50 < 2:
            bits |= ACT
        if mode == 'hold' and t % (state['hold'] + 30) < state['hold']:
            bits |= ACT
        p12 ^= bits | (bits << 4 if two else 0)
        if t > 3000 and frame % 3000 == 0:
            state['phase'], state['t0'] = 'coin', frame   # (coin and start again: a new game after a game over)
    return system, p12, 0xFF


def cheats(seed, frame, m, state):
    mem = m.mem
    if 4 <= seed <= 10:
        if mem[EVENT] == 0:
            mem[EVENT] = seed - 4
    if 4 <= seed <= 10 or seed == 12:
        mem[FIRST_TRY] = 0
        mem[FALSE_START] = 0


def io(a, rw):
    """the accesses the translation sends through the runtime: the I/O, the unmapped space, stores to the ROM, and the
    stores to the video and colour RAM ($2000-$2FFF: main_io_w lists the changed cells for the renderer)"""
    return not (0x1000 <= a < 0x1100 or 0x3000 <= a < 0x4000 or 0x2000 <= a < 0x3000 and rw == 'r' or
                a >= 0x4000 and rw == 'r')


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    rnd = random.Random(seed)
    m = HyperSportsPort(*dsw(seed))
    cov = Cover6809(m.cpu, io=io)
    video = Video()
    pens = collections.Counter()
    sprites = collections.Counter()
    scrolls = collections.Counter()
    events = collections.Counter()
    state = {'two': seed == 11}
    mem = m.mem
    for frame in range(frames):
        m.frame = frame
        m.system, m.p1_p2, m.p3_p4 = inputs(frame, rnd, state)
        cheats(seed, frame, m, state)
        m.run_frame_port()
        for o in range(0, 0xC0, 4):
            attr = mem[0x1000 + o]
            sprites[(mem[0x1002 + o] + 8 * (attr & 0x20), attr & 15, not attr & 0x40, bool(attr & 0x80))] += 1
        for r in range(2, 30):
            scrolls[mem[0x10C0 + 2 * r] + 256 * (mem[0x10C1 + 2 * r] & 1)] += 1
        events[mem[EVENT]] += 1
        if frame % 8 == 0:
            raw = video.render_raw(mem)[16:240]
            cnt = np.bincount(raw.ravel(), minlength=512)
            for p in np.nonzero(cnt)[0]:
                pens[int(p)] += int(cnt[p])
        if frame % 2000 == 0:
            print(f'seed {seed} frame {frame}: {len(cov.exec)} pcs, event {mem[EVENT]}', flush=True)
    out = build_dir('hyperspt') / f'cover{seed}.pkl'
    d = cov.data()
    d.update({'pens': pens, 'sprites': sprites, 'scrolls': scrolls, 'events': events, 'seed': seed, 'frames': frames})
    out.write_bytes(pickle.dumps(d))
    print(out, len(cov.exec), 'pcs, events', dict(events))


if __name__ == '__main__':
    main()
