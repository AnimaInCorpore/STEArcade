"""Coverage of the main CPU in the port's schedule (tools/machine.py TrackFieldPort.run_frame_port), with scripted play.

    python ref/cover.py <seed> [frames]  ->  build/trackfld/cover<seed>.pkl

The pickle: the 6809 coverage (engine/m6809cover.py: exec, acc, targets, wraps, io: the accesses outside the RAM and the ROM's reads, the
video RAM's stores);
pens: the pens' pixel counts of the reference pictures (every 8th frame); sprites: Counter of (code, colour, flip x,
flip y) entries; scrolls: Counter of the visible rows' scroll values.

Seeds (MAME's cheats, cheat.7z trackfld.xml): 1-3 attract, coin, start, the name entry, random play to the game over
and again; 4-9 the start event 0-5 ($2884: 100 m dash, long jump, javelin, 110 m hurdles, hammer throw, high jump),
always qualify ($287F), infinite lives ($2B81): every event and the rounds after; 10-11 two players (11: always
qualify); 12 the DIP switches' other settings (2 lives, game over after the last event, bonus 100000, records erased,
difficult, no demo sounds), always qualify.
"""
import collections
import pickle
import random
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'tools'), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import TrackFieldPort, Video, DSW1, DSW2
from m6809cover import Cover6809
from paths import build_dir

EVENT, QUALIFY, LIVES1 = 0x2884, 0x287F, 0x2B81
RUN1, JUMP, RUN3 = 0x04, 0x02, 0x01             # IN0 bits of player 1 (player 2: << 4)


def dsw(seed):
    if seed == 12:
        return DSW1, DSW2 & ~0xFF | 0x00 | 0x02 | 0x00 | 0x00 | 0x00 | 0x00 | 0x80
    return DSW1, DSW2


def inputs(frame, rnd, state):
    """-> (SYSTEM, IN0, IN1), active low.  Play: a mode at a time (running at a rate, the action button tapped or held,
    nothing), each for a random while; both players the same when two play."""
    system, in0 = 0xFF, 0xFF
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
            state['mode'] = rnd.choice(('run', 'run', 'run', 'tap', 'hold', 'idle', 'runjump'))
            state['rate'] = rnd.choice((1, 2, 2, 3, 4, 6))
            state['hold'] = rnd.choice((4, 10, 20, 40))
        mode, rate, t = state['mode'], state['rate'], frame - state['t0']
        bits = 0
        if mode in ('run', 'runjump'):
            bits |= RUN1 if (t // rate) & 1 else RUN3
        if mode == 'tap' and t % 12 < 2 or mode == 'runjump' and t % 50 < 2:
            bits |= JUMP
        if mode == 'hold' and t % (state['hold'] + 30) < state['hold']:
            bits |= JUMP
        in0 ^= bits | (bits << 4 if two else 0)
        if t > 3000 and frame % 3000 == 0:
            state['phase'], state['t0'] = 'coin', frame   # (coin and start again: a new game after a game over)
    return system, in0, 0xFF


def cheats(seed, frame, m, state):
    mem = m.mem
    if 4 <= seed <= 9:
        if mem[EVENT] == 0:
            mem[EVENT] = seed - 4
        mem[LIVES1] = 2
    if 4 <= seed <= 9 or seed in (11, 12):
        mem[QUALIFY] = 1


def io(a, rw):
    """the accesses the translation sends through the runtime: the I/O, the unmapped space, stores to the ROM, and the
    stores to the video and colour RAM ($3000-$3FFF: main_io_w lists the changed cells for the renderer)"""
    return not (0x1800 <= a < 0x2000 or 0x2800 <= a < 0x3000 or 0x3000 <= a < 0x4000 and rw == 'r' or
                a >= 0x6000 and rw == 'r')


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    rnd = random.Random(seed)
    m = TrackFieldPort(*dsw(seed))
    cov = Cover6809(m.cpu, io=io)
    video = Video()
    pens = collections.Counter()
    sprites = collections.Counter()
    scrolls = collections.Counter()
    events = collections.Counter()
    state = {'two': seed in (10, 11)}
    mem = m.mem
    for frame in range(frames):
        m.frame = frame
        m.system, m.in0, m.in1 = inputs(frame, rnd, state)
        cheats(seed, frame, m, state)
        m.run_frame_port()
        for o in range(0, 0x40, 2):
            attr = mem[0x1800 + o]
            sprites[(mem[0x1C01 + o] | (attr & 1) << 8, attr & 15, not attr & 0x40, bool(attr & 0x80))] += 1
        for r in range(2, 30):
            scrolls[mem[0x1840 + r] + 256 * (mem[0x1C40 + r] & 1)] += 1
        events[mem[EVENT]] += 1
        if frame % 8 == 0:
            raw = video.render_raw(mem)[16:240]
            cnt = np.bincount(raw.ravel(), minlength=512)
            for p in np.nonzero(cnt)[0]:
                pens[int(p)] += int(cnt[p])
        if frame % 2000 == 0:
            print(f'seed {seed} frame {frame}: {len(cov.exec)} pcs, event {mem[EVENT]}', flush=True)
    out = build_dir('trackfld') / f'cover{seed}.pkl'
    d = cov.data()
    d.update({'pens': pens, 'sprites': sprites, 'scrolls': scrolls, 'events': events, 'seed': seed, 'frames': frames})
    out.write_bytes(pickle.dumps(d))
    print(out, len(cov.exec), 'pcs, events', dict(events))


if __name__ == '__main__':
    main()
