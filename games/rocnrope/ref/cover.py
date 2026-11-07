"""Coverage of the main CPU in the port's schedule (tools/machine.py RocnRopePort.run_frame_port), with scripted play.

    python ref/cover.py <seed> [frames]  ->  build/rocnrope/cover<seed>.pkl

The pickle: the 6809 coverage (engine/m6809cover.py: exec, acc, targets, wraps, io: the accesses outside the RAM and the
ROM's reads, the video RAM's stores), dps: the DP values each pc ran with; pens: the pens' pixel counts of the reference pictures (every 8th frame);
sprites: Counter of (code, colour, flip x, flip y) entries.

Seeds: 1-3 attract, coin, start, random play to the game over and again (the game ends after 3 lives); 4-9 infinite
lives ($50C0 kept at 2) with random play (4-6) and the same with the stage poked (7-9, STAGE_POKES: see below);
10 two players; 12-15 MAME's cheats (infinite lives $50C0 = 10, invincibility $51C0 = 2 / $51DE = 0, infinite bonus
$509B = $99) with random play for 60000 frames; 11 the DIP switches' other settings (5 lives, difficulty 1 / 16 alternating, bonus 80000, no repeated
bonus, no demo sounds).
"""
import collections
import pickle
import random
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'tools'), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import RocnRopePort, Video, DSW1, DSW2, DSW3
from m6809cover import Cover6809
from paths import build_dir

LIVES1 = 0x50C0
LEFT, RIGHT, UP, DOWN, B1, B2 = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20     # IN0 / IN1 bits (active low)
STAGE_POKES = {7: (0x50C3, 2), 8: (0x50C3, 5), 9: (0x50C3, 7)}    # $50C3 (0-7, changes with the scene): what the exploration found


def dsw(seed):
    if seed == 11:
        return DSW1, 0x01 | 0x78 | 0x80, 0x00           # 5 lives... (bits: lives $01 = 5), easy, demo sounds off, bonus 80000
    return DSW1, DSW2, DSW3


def inputs(frame, rnd, state):
    """-> (SYSTEM, IN0, IN1), active low.  Attract, a coin, start (two players: two coins, start 2), then random play: a
    direction and a button for a random while each, new games after a game over (every 3000 frames: coin and start)."""
    system, in0, in1 = 0xFF, 0xFF, 0xFF
    two = state.get('two', False)
    if state.setdefault('phase', 'attract') == 'attract' and frame >= state.setdefault('coin_at', 600 + rnd.randrange(1500)):
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
            state['next'] = frame + rnd.choice((6, 10, 20, 40, 80, 160))
            state['dir'] = rnd.choice((0, LEFT, RIGHT, UP, DOWN, LEFT, RIGHT, RIGHT, UP, UP | LEFT, UP | RIGHT))
            state['btn'] = rnd.choice((0, 0, 0, B1, B2, B1 | B2))
            state['tap'] = rnd.choice((0, 0, 1, 3, 9))
        bits = state['dir']
        t = frame - state['t0']
        if state['btn'] and (not state['tap'] or t % (state['tap'] * 2 + 2) < state['tap'] + 1):
            bits |= state['btn']
        in0 &= ~bits & 0xFF
        if two:
            in1 &= ~bits & 0xFF
        if t > 3000 and frame % 3000 == 0:
            state['phase'], state['t0'] = 'coin', frame
    return system, in0, in1


def cheats(seed, frame, m, state):
    mem = m.mem
    if seed >= 12 and state.get('phase') == 'play':          # MAME's cheats: infinite lives, invincibility, infinite bonus
        mem[LIVES1] = 0x0A
        mem[0x51C0] = 0x02
        mem[0x51DE] = 0x00
        mem[0x509B] = 0x99
    if 4 <= seed <= 9 and state.get('phase') == 'play':
        if mem[LIVES1] < 2:
            mem[LIVES1] = 2
        poke = STAGE_POKES.get(seed)
        if poke and frame % 2500 == 2400:
            mem[poke[0]] = poke[1]


def io(a, rw):
    """the accesses the translation sends through the runtime: the I/O ($3000-$3FFF, $8000-$81FF), the unmapped space,
    stores to the ROM, and the video and colour RAM ($4800-$4FFF stores: main_io_w lists the changed cells)"""
    if 0x4000 <= a < 0x4800 or 0x5000 <= a < 0x6000:
        return False
    if 0x4800 <= a < 0x5000:
        return rw == 'w'
    return not (a >= 0x6000 and rw == 'r')


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    rnd = random.Random(seed)
    m = RocnRopePort(*dsw(seed))
    cov = Cover6809(m.cpu, io=io)
    dps = collections.defaultdict(set)              # pc -> the DP values it ran with (gen.py dp_sites)
    step0 = m.cpu.step

    def step():
        dps[m.cpu.pc].add(m.cpu.dp)
        return step0()
    m.cpu.step = step
    video = Video()
    pens = collections.Counter()
    sprites = collections.Counter()
    state = {'two': seed == 10}
    mem = m.mem
    for frame in range(frames):
        m.frame = frame
        m.system, m.in0, m.in1 = inputs(frame, rnd, state)
        cheats(seed, frame, m, state)
        m.run_frame_port()
        for o in range(0, 0x30, 2):
            attr = mem[0x4000 + o]
            sprites[(mem[0x4401 + o], attr & 15, bool(attr & 0x40), not attr & 0x80)] += 1
        if frame % 8 == 0:
            raw = video.render_raw(mem)[16:240]
            cnt = np.bincount(raw.ravel(), minlength=512)
            for p in np.nonzero(cnt)[0]:
                pens[int(p)] += int(cnt[p])
        if frame % 2000 == 0:
            print(f'seed {seed} frame {frame}: {len(cov.exec)} pcs, lives {mem[LIVES1]}', flush=True)
    out = build_dir('rocnrope') / f'cover{seed}.pkl'
    d = cov.data()
    d.update({'pens': pens, 'sprites': sprites, 'seed': seed, 'frames': frames, 'dps': dict(dps)})
    out.write_bytes(pickle.dumps(d))
    print(out, len(cov.exec), 'pcs')


if __name__ == '__main__':
    main()
