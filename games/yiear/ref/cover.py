"""Coverage of the main CPU in the port's schedule (tools/machine.py YieArPort.run_frame_port), with scripted play.

    python ref/cover.py <seed> [frames]  ->  build/yiear/cover<seed>.pkl

The pickle: the 6809 coverage (engine/m6809cover.py: exec, acc, targets, wraps, io: the accesses outside the RAM and the
ROM's reads; the boot self-test is not covered: the port starts at $8000);
pens: the pens' pixel counts of the reference pictures (every 8th frame); sprites: Counter of (code, flip x, flip y)
entries; phrases: Counter of the VLM5030 phrases started (data bytes); frames, seed.

Seeds: 1-4 attract, coin, start, random play (moves and kicks / punches in changing modes) to the game over and
again; 5-8 the same with 5 lives and the easy setting (further opponents); 9 two players; 10 the other DIP switches
(2 lives, bonus 40000 90000, very difficult, demo sounds off, dual controls: player 2's inputs are read);
11 the service mode (DSW3 bit 2 = 0).
"""
import collections
import pickle
import random
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'tools'), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import YieArPort, Video, DSW1, DSW2, DSW3
from m6809cover import Cover6809
from paths import build_dir

LEFT, RIGHT, UP, DOWN, KICK, PUNCH, B3 = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40


def dsws(seed):
    """(DSW1, DSW2, DSW3) of a seed: 5-8 five lives, easy ($78); 10 two lives, bonus 40000 90000, very difficult, demo
    sounds off, dual controls ($C2, DSW3 bit 1 clear); 11 the service mode (DSW3 bit 2 clear)"""
    if 5 <= seed <= 8:
        return DSW1, 0x78, DSW3
    if seed == 10:
        return DSW1, 0xC2, DSW3 & ~0x02
    if seed == 11:
        return DSW1, DSW2, DSW3 & ~0x04
    return DSW1, DSW2, DSW3


def inputs(frame, rnd, state):
    """-> (SYSTEM, IN1, IN2), active low.  Play: a mode at a time (walking, jumping, ducking, kicking, punching,
    nothing), each for a random while."""
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
            state['next'] = frame + rnd.choice((4, 8, 16, 30, 60, 120))
            state['mode'] = rnd.choice(('walk', 'walk', 'jump', 'duck', 'kick', 'punch', 'mix', 'mix', 'idle', 'b3'))
            state['dir'] = rnd.choice((LEFT, RIGHT, RIGHT, 0))
            state['rate'] = rnd.choice((1, 2, 3, 5))
        mode, t = state['mode'], frame - state['t0']
        d = state['dir']
        if mode == 'walk':
            bits = d
        elif mode == 'jump':
            bits = UP | d
        elif mode == 'duck':
            bits = DOWN | d | (KICK if t % 6 < 2 else 0)
        elif mode == 'kick':
            bits = (KICK if t % 8 < 3 else 0) | d | (UP if rnd.random() < 0.2 else 0)
        elif mode == 'punch':
            bits = (PUNCH if t % 8 < 3 else 0) | d | (DOWN if rnd.random() < 0.2 else 0)
        elif mode == 'mix':
            bits = rnd.choice((0, LEFT, RIGHT, UP, DOWN, KICK, PUNCH, UP | KICK, DOWN | PUNCH, RIGHT | KICK, LEFT | PUNCH))
        elif mode == 'b3':
            bits = B3 | d | (UP if t % 10 < 3 else 0)
        if t > 2500 and frame % 2500 == 0:
            state['phase'], state['t0'] = 'coin', frame   # (coin and start again: a new game after a game over)
    in1 = (~bits) & 0xFF
    return system, in1, (in1 if two else 0xFF)


def io(a, rw):
    """the accesses the translation sends through the runtime: the I/O ($0000, $4000-$4FFF), the unmapped space and
    stores to the ROM; RAM ($5000-$5FFF, the video RAM too: render.s compares it with what it drew) and the ROM's
    reads are plain memory"""
    return not (0x5000 <= a < 0x6000 or a >= 0x8000 and rw == 'r')


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    rnd = random.Random(seed)
    m = YieArPort(*dsws(seed))
    m.boot()                                         # (the self-test is not covered)
    cov = Cover6809(m.cpu, io=io)
    m.run_to_idle()                                  # (the init from $8000 is)
    m.booted = True
    video = Video()
    pens = collections.Counter()
    sprites = collections.Counter()
    state = {'two': seed == 9}
    mem = m.mem
    for frame in range(frames):
        m.system, m.in1, m.in2 = inputs(frame, rnd, state)
        m.run_frame_port()
        for o in range(0, 0x30, 2):
            attr = mem[0x5000 + o]
            sprites[(mem[0x5401 + o] | (attr & 1) << 8, not attr & 0x40, bool(attr & 0x80))] += 1
        if frame % 8 == 0:
            raw = video.render_raw(mem)[16:240]
            cnt = np.bincount(raw.ravel(), minlength=32)
            for p in np.nonzero(cnt)[0]:
                pens[int(p)] += int(cnt[p])
        if frame % 2000 == 0:
            print(f'seed {seed} frame {frame}: {len(cov.exec)} pcs', flush=True)
    out = build_dir('yiear') / f'cover{seed}.pkl'
    d = cov.data()
    phrases = collections.Counter()               # the VLM5030's phrases started (the data byte latched when ST falls)
    st = data = 0
    for _, kind, v in m.sound_log:
        if kind == 'vd':
            data = v
        elif kind == 'vc':
            if st and not v & 2:
                phrases[data] += 1
            st = v >> 1 & 1
    d.update({'pens': pens, 'sprites': sprites, 'phrases': phrases, 'seed': seed, 'frames': frames})
    out.write_bytes(pickle.dumps(d))
    print(out, len(cov.exec), 'pcs')


if __name__ == '__main__':
    main()
