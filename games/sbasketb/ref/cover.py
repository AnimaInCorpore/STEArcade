"""Coverage of the main CPU in the port's schedule (tools/machine.py SBasketPort.run_frame_port), with scripted play.

    python ref/cover.py <seed> [frames]  ->  build/sbasketb/cover<seed>.pkl

The pickle: the 6809 coverage (engine/m6809cover.py: exec, acc, targets, wraps, io: the accesses outside the RAM and the
ROM's reads, the video RAM's stores) and dp: {pc: the direct page values it ran with}; pens: the pens' pixel counts of the reference pictures (every 8th frame);
sprites: Counter of (code, colour set, flip x, flip y) entries; scrolls: Counter of the scroll values.

Seeds: 1-3 attract, coin, start, random play (the game's clock runs out, the name entry, again); 4-5 two players
(coin, coin, start 2); 6-9 the game time 30 / 40 / 50 s and other DIP switches; 10-11 more random play with faster
input changes; 12 the service mode (start 1 + start 2 held through the boot's input read); 13 no coin (the whole attract
cycle: title, the demo game, the high scores); 14 the coin after 6000 frames; 15-20 fixed stick and button patterns; 21 the runtime's AUTOPLAY script itself.
"""
import collections
import pickle
import random
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'tools'), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import SBasketPort, Video, DSW1, DSW2
from m6809cover import Cover6809
from paths import build_dir

# P1 / P2 bits (active low): left, right, up, down, button 1 (shoot / pass), 2, 3
L, R, U, D, B1, B2, B3 = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40
COIN1, COIN2, START1, START2 = 0x01, 0x02, 0x08, 0x10


def dsw(seed):
    if seed == 6:
        return DSW1, DSW2 | 0x03              # 30 s
    if seed == 7:
        return DSW1, (DSW2 & ~0x03) | 0x01     # 40 s
    if seed == 8:
        return 0xFE, (DSW2 & ~0x63) | 0x02 | 0x08 | 0x10    # 2 coins ..., 50 s, 70-78, data initialized, hardest
    if seed == 9:
        return DSW1, (DSW2 & ~0x60) | 0x20 | 0x04 | 0x80    # hard, cocktail, demo sounds off
    return DSW1, DSW2


def inputs(frame, rnd, state):
    """-> (SYSTEM, P1, P2), active low.  Play: a mode at a time (the stick held in a direction, shooting taps and holds,
    nothing), each for a random while; both players when two play."""
    system, p1, p2 = 0xFF, 0xFF, 0xFF
    two = state.get('two', False)
    fast = state.get('fast', False)
    if state.setdefault('phase', 'attract') == 'attract' and frame >= state.setdefault('coin_at', state.get('late', 300 + rnd.randrange(1200))):
        state['phase'], state['t0'] = 'coin', frame
    if state['phase'] == 'coin':
        t = frame - state['t0']
        if t < 4 or two and 20 <= t < 24:
            system &= ~COIN1
        elif 60 <= t < 64:
            system &= ~(START2 if two else START1)
        elif t >= 64:
            state['phase'], state['t0'] = 'play', frame
    if state['phase'] == 'play' and state.get('pattern'):
        # a fixed pattern (the runtime's AUTOPLAY, more of its kind): a direction for 2^k frames in turn, button 1 for 3 of
        # every `period` frames, the other buttons now and then
        t = frame - state['t0']
        k, period = state['pattern']
        dirs = (L, U, R, D, L | U, R | D)[(t >> k) % (6 if k > 3 else 4)]
        bits = dirs
        if t % period < 3:
            bits |= B1
        if t % (period * 5) < 2:
            bits |= B2
        if t % (period * 9) < 2:
            bits |= B3
        p1 ^= bits
        p2 ^= bits if two else 0
        if t > 3600 and frame % 3600 == 0:
            state['phase'], state['t0'] = 'coin', frame
    elif state['phase'] == 'play':
        if frame >= state.get('next', 0):
            state['next'] = frame + rnd.choice((4, 8, 16, 30, 60) if fast else (8, 16, 30, 60, 120, 240))
            state['mode'] = rnd.choice(('dir', 'dir', 'dir', 'tap', 'hold', 'idle', 'dirshoot', 'pass'))
            state['dir'] = rnd.choice((L, R, U, D, L | U, L | D, R | U, R | D))
            state['rate'] = rnd.choice((2, 3, 5, 8, 12))
            state['hold'] = rnd.choice((4, 10, 20, 40))
        mode, rate, t = state['mode'], state['rate'], frame - state['t0']
        bits = 0
        if mode in ('dir', 'dirshoot', 'pass'):
            bits |= state['dir']
        if mode in ('tap', 'dirshoot') and t % rate < 2:
            bits |= B1
        if mode == 'hold' and t % (state['hold'] + 20) < state['hold']:
            bits |= B1 | state['dir']
        if mode == 'pass' and t % (rate + 6) < 2:
            bits |= B2
        if t % 97 < 2:
            bits |= B3
        p1 ^= bits
        p2 ^= bits if two else 0
        if t > 3000 and frame % 3000 == 0:
            state['phase'], state['t0'] = 'coin', frame   # (coin and start again: a new game after a game over)
    if state.get('service'):
        if frame < 4:
            system &= ~(START1 | START2)          # (held at the power-on: the boot reads SYSTEM at once)
        elif frame % 90 < 4:
            system &= ~START1                     # (start 1 changes the test's modes)
        if frame % 700 < 30:
            p1 ^= (L, R, U, D, B1, B2, B3)[frame // 30 % 7]
        return system, p1, p2
    return system, p1, p2


def autoplay(frame):
    """the runtime's AUTOPLAY script (src/sbasketb.s; period 4000): coin 1 at 700-703, start 1 at 760-763, then a direction
    for 32 frames (left, up, right, down) and button 1 for 3 of every 16 frames -> (SYSTEM, P1, P2)"""
    t = frame % 4000
    system, p1 = 0xFF, 0xFF
    if 700 <= t < 704:
        system = 0xFE
    if 760 <= t < 764:
        system = 0xF7
    if t >= 840:
        p1 = (0xFE, 0xFB, 0xFD, 0xF7)[(t >> 5) & 3]
        if t & 15 < 3:
            p1 &= 0xEF
    return system, p1, 0xFF


def io(a, rw):
    """the accesses the translation sends through the runtime: the I/O, the unmapped space, stores to the ROM, and the
    stores to the video and colour RAM ($3000-$37FF: the renderer's changed cells)"""
    return not (0x2000 <= a < 0x3000 or 0x3800 <= a < 0x3C00 or 0x3000 <= a < 0x3800 and rw == 'r' or
                a >= 0x6000 and rw == 'r')


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    rnd = random.Random(seed)
    m = SBasketPort(*dsw(seed))
    cov = Cover6809(m.cpu, io=io)
    dps = collections.defaultdict(set)         # the direct page register at each instruction: TFR A,DP moves it ($20 / $24)
    step0 = m.cpu.step

    def step():
        dps[m.cpu.pc].add(m.cpu.dp)
        return step0()
    m.cpu.step = step
    video = Video()
    pens = collections.Counter()
    sprites = collections.Counter()
    scrolls = collections.Counter()
    state = {'two': seed in (4, 5), 'fast': seed in (10, 11), 'service': seed == 12,
             'late': 10 ** 9 if seed == 13 else 6000 if seed == 14 else None}
    if 15 <= seed <= 21:
        state['pattern'] = {15: (5, 16), 16: (4, 12), 17: (6, 20), 18: (3, 10), 19: (5, 24), 20: (4, 16), 21: None}[seed]
        state['coin_at'] = 400 + 50 * seed
    if state['late'] is None:
        del state['late']
    mem = m.mem
    for frame in range(frames):
        m.frame = frame
        m.system, m.p1, m.p2 = autoplay(frame) if seed == 21 else inputs(frame, rnd, state)
        m.run_frame_port()
        base = 0x3900 if m.latch[5] else 0x3800
        for o in range(0, 0x100, 4):
            if mem[base + o + 2] or mem[base + o + 3]:
                at = mem[base + o + 1]
                sprites[(mem[base + o] | (at & 0x20) << 3, (at & 15) + 16 * mem[0x3C20], bool(at & 0x40),
                         bool(at & 0x80))] += 1
        scrolls[mem[0x3F80]] += 1
        if frame % 8 == 0:
            raw = video.render_raw(mem, select=m.latch[5])[16:240]
            cnt = np.bincount(raw.ravel(), minlength=4352)
            for p in np.nonzero(cnt)[0]:
                pens[int(p)] += int(cnt[p])
        if frame % 2000 == 0:
            print(f'seed {seed} frame {frame}: {len(cov.exec)} pcs', flush=True)
    out = build_dir('sbasketb') / f'cover{seed}.pkl'
    d = cov.data()
    d.update({'dp': dict(dps), 'pens': pens, 'sprites': sprites, 'scrolls': scrolls, 'seed': seed, 'frames': frames})
    out.write_bytes(pickle.dumps(d))
    print(out, len(cov.exec), 'pcs')


if __name__ == '__main__':
    main()
