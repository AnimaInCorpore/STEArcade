"""Coverage of the main CPU in the port's schedule (tools/machine.py JailBreakPort.run_frame_port), with scripted play.

    python ref/cover.py <seed> [frames]  ->  build/jailbrek/cover<seed>.pkl

The pickle: the 6809 coverage (engine/m6809cover.py: exec, acc, targets, wraps, io: the accesses outside the RAM and
the ROM's reads, the video RAM's stores);
pens: the pens' pixel counts of the reference pictures (every 8th frame); sprites: Counter of (code, colour, flip x,
flip y) entries; scrolls: Counter of the visible rows' scroll values.

Seeds (the game has no level select; MAME's cheats, cheat.7z jailbrek.xml: P1 / P2 lives $15CE / $15FE, all weapons
$1598): 1-3 attract, coin, start, random play to the game over and again (2, 3 with the weapons and lives cheats);
4 two players; 5 weapons and lives, slower input changes; 6 the DIP switches' other settings (5 lives, cocktail,
40K bonus, very difficult, no demo sounds, dual controls), two players; 7-12 more play styles (long runs of one
direction, fire held, select), the cheats on in turn.
"""
import collections
import pickle
import random
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'tools'), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import JailBreakPort, Video, DSW1, DSW2, DSW3
from m6809cover import Cover6809
from paths import build_dir

LIVES1, LIVES2, WEAPONS = 0x15CE, 0x15FE, 0x1598
LEFT, RIGHT, UP, DOWN, FIRE, SELECT = 1, 2, 4, 8, 0x10, 0x20


def dsw(seed):
    if seed == 6:
        return DSW1, 0xC4, 0x0D
    return DSW1, DSW2, DSW3


def inputs(frame, rnd, state):
    """-> (SYSTEM, P1, P2), active low.  Play: a mode at a time (a direction held, tapped fire, nothing), each for a
    random while; both players the same when two play."""
    system = 0xFF
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
    bits = 0
    if state['phase'] == 'play':
        if frame >= state.get('next', 0):
            state['next'] = frame + rnd.choice((6, 12, 30, 60, 120, 240))
            state['mode'] = rnd.choice(('left', 'right', 'right', 'up', 'down', 'upright', 'idle', 'fire', 'fire', 'select'))
            state['hold'] = rnd.choice((2, 4, 10, 20))
        mode, t = state['mode'], frame - state['t0']
        bits = {'left': LEFT, 'right': RIGHT, 'up': UP, 'down': DOWN, 'upright': UP | RIGHT}.get(mode, 0)
        if mode == 'fire' and t % (state['hold'] + 4) < state['hold']:
            bits |= FIRE
        if mode != 'fire' and t % 17 < 2:
            bits |= FIRE
        if mode == 'select' and t % 40 < 2:
            bits |= SELECT
        if t > 4000 and frame % 4000 == 0:
            state['phase'], state['t0'] = 'coin', frame   # (coin and start again: a new game after a game over)
    p = 0xFF ^ bits
    return system, p, p if two else 0xFF


def cheats(seed, frame, m, state):
    mem = m.mem
    if seed in (2, 3, 5) or seed >= 7 and seed % 2:
        mem[LIVES1] = 8
        mem[LIVES2] = 8
    if seed in (3, 5) or seed >= 7 and seed % 3 == 0:
        mem[WEAPONS] = 3


def io(a, rw):
    """the accesses the translation sends through the runtime: the control registers, the I/O, the unmapped space,
    stores to the ROM, and the stores to the colour and video RAM ($0000-$0FFF: main_io_w lists the changed cells for
    the renderer); the scroll RAM $2000-$203F is memory"""
    return not (0x1000 <= a < 0x2040 or a < 0x1000 and rw == 'r' or a >= 0x8000 and rw == 'r')


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    rnd = random.Random(seed)
    m = JailBreakPort(*dsw(seed))
    cov = Cover6809(m.cpu, io=io)
    video = Video()
    pens = collections.Counter()
    sprites = collections.Counter()
    scrolls = collections.Counter()
    state = {'two': seed in (4, 6)}
    mem = m.mem
    for frame in range(frames):
        m.frame = frame
        m.system, m.p1, m.p2 = inputs(frame, rnd, state)
        cheats(seed, frame, m, state)
        m.run_frame_port()
        for o in range(0, 0xC0, 4):
            attr = mem[0x1001 + o]
            sprites[(mem[0x1000 + o] | (attr & 0x40) << 2, attr & 15, bool(attr & 0x10), bool(attr & 0x20))] += 1
        for r in range(2, 30):
            scrolls[mem[0x2000 + r] + 256 * (mem[0x2020 + r] & 1)] += 1
        if frame % 8 == 0 and not m.ctrl[4] & 8:
            raw = video.render_raw(mem)[16:240, 8:248]
            cnt = np.bincount(raw.ravel(), minlength=512)
            for p in np.nonzero(cnt)[0]:
                pens[int(p)] += int(cnt[p])
        if frame % 2000 == 0:
            print(f'seed {seed} frame {frame}: {len(cov.exec)} pcs', flush=True)
    out = build_dir('jailbrek') / f'cover{seed}.pkl'
    d = cov.data()
    d.update({'pens': pens, 'sprites': sprites, 'scrolls': scrolls, 'seed': seed, 'frames': frames})
    out.write_bytes(pickle.dumps(d))
    print(out, len(cov.exec), 'pcs')


if __name__ == '__main__':
    main()
