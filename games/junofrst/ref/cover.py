"""Coverage of the main CPU in the port's schedule (tools/machine.py JunoPort.run_frame_port), with scripted play.

    python ref/cover.py <seed> [frames]  ->  build/junofrst/cover<seed>.pkl

The pickle (engine/m6809cover.py's format, with the 4 KB bank window in virtual pages): exec, acc, targets, wraps, io,
returns keyed by the virtual pc: the window's code ($9000-$9FFF) is page 8 + bank (v = page << 13 | pc & $1FFF, slot 4),
every other pc is itself.  io: the accesses the translation sends through the runtime: $8000-$80FF (palette, I/O, the
latch, the sound and blitter registers), every access of $9000-$9FFF (the window's data), every access of the video RAM (the runtime keeps the picture);
blits: Counter of (source nibble address, copy flag) the blitter ran; pens: pen pixel counts of every 8th picture.

Seeds: 1-4 attract, coin, start, random play (up to 40000 frames each: the game over and a new game); 5-6 the same with
256 lives (DSW2 lives 0); 7 two players; 8 the other DIP switches (cocktail off, difficulty 8, 5 lives, demo sounds off).
"""
import collections
import pickle
import random
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'tools'), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import JunoPort, Video, DSW1, DSW2
from m6809cover import Cover6809
from m6809 import P1
from m6809dis import decode
from paths import build_dir

LEFT, RIGHT, UP, DOWN, FIRE2, FIRE1 = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20


def dsw(seed):
    if seed in (5, 6):
        return DSW1, DSW2 & ~3                    # 256 lives
    if seed == 8:
        return DSW1, 0x02 | 0x08 | 0x00 | 0x80    # 4 lives, difficulty 8, demo sounds off
    return DSW1, DSW2


def inputs(frame, rnd, state):
    """-> (SYSTEM, P1, P2), active low"""
    system, p1, p2 = 0xFF, 0xFF, 0xFF
    two = state.get('two', False)
    if state.setdefault('phase', 'attract') == 'attract' and frame >= state.setdefault('coin_at', 300 + rnd.randrange(1200)):
        state['phase'], state['t0'] = 'coin', frame
    if state['phase'] == 'coin':
        t = frame - state['t0']
        if t < 4 or two and 20 <= t < 24:
            system &= ~0x04                           # coin 1
        elif 60 <= t < 64:
            system &= ~(0x10 if two else 0x08)        # start 2 / start 1
        elif t >= 64:
            state['phase'], state['t0'] = 'play', frame
    if state['phase'] == 'play':
        if frame >= state.get('next', 0):
            state['next'] = frame + rnd.choice((4, 8, 16, 30, 60, 120))
            state['mode'] = rnd.choice(('dir', 'dir', 'dir', 'fire', 'hold', 'idle', 'both'))
            state['bits'] = rnd.choice([LEFT, RIGHT, UP, DOWN, LEFT | UP, RIGHT | UP, LEFT | DOWN, RIGHT | DOWN, 0])
            state['rate'] = rnd.choice((2, 3, 4, 6))
        mode, t = state['mode'], frame - state['t0']
        bits = 0
        if mode in ('dir', 'both', 'hold'):
            bits |= state['bits']
        if mode in ('fire', 'both') and (t // state['rate']) & 1:
            bits |= FIRE1
        if mode == 'hold':
            bits |= FIRE1
        if t % 97 < 2:
            bits |= FIRE2
        p1 ^= bits
        p2 ^= bits if two else 0
        if t > 3000 and frame % 6000 == 0:
            state['phase'], state['t0'] = 'coin', frame   # (coin and start again: a new game after a game over)
    return system, p1, p2


def virtual(pc, bank):
    return ((8 + bank) << 13) | (pc & 0x1FFF) if 0x9000 <= pc < 0xA000 else pc


def io(a, rw):
    """the sites the translation sends through the runtime"""
    return a < 0x8000 or 0x8000 <= a < 0x8100 or 0x9000 <= a < 0xA000


class JunoCover(Cover6809):
    """Cover6809 with the bank window's code in virtual pages"""

    def __init__(self, m):
        super().__init__(m.cpu, io=io)
        self.m = m
        self.bank_in_window = 0

    def step(self):
        c, m = self.c, self.m
        if c.attn:
            n = c._slow()
            if n:
                return n
        pc = c.pc
        bank0 = m.bank
        v = virtual(pc, bank0)
        self.exec[v] += 1
        ent = self._idx.get(pc)
        if ent is None or ent[2] != bank0:
            ins = decode(self._rd0, pc, c.dp, rd_op=c.rd_op)
            x = ins.arg if ins.mode == 'idx' else None
            ent = self._idx[pc] = ((x.reg, x.offset) if x is not None and x.kind in ('off5', 'off8', 'off16') else None,
                                   ins.flow == 'ret', bank0)
        idx, is_ret, _ = ent
        if idx is not None:
            r, o = idx
            if not 0 <= getattr(c, r) + o <= 0xFFFF:
                self.wraps.add(v)
        accs = self._accs
        accs.clear()
        op = c.rd_op(pc)
        c.pc = (pc + 1) & 0xFFFF
        n = P1[op](c)
        c.cycles += n
        prev = None
        acc = self.acc[v]
        for rw, a in accs:
            if pc <= a < pc + 5 and rw == 'r':
                continue                                  # (the instruction's own bytes)
            oddw = prev is not None and prev[0] == rw and a == ((prev[1] + 1) & 0xFFFF) and prev[1] & 1
            acc.add((rw, a >> 13, a >> 13, bool(oddw)))
            if self.is_io(a, rw):
                self.io.add((v, a, rw))
            prev = (rw, a)
        nxt = c.pc
        if m.bank != bank0 and 0x9000 <= pc < 0xA000:
            self.bank_in_window += 1
        if not (pc < nxt <= pc + 5):
            self.targets[v].add(virtual(nxt, m.bank))
        if is_ret:
            self.returns[virtual(nxt, m.bank)] += 1
        return n


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    rnd = random.Random(seed)
    m = JunoPort(*dsw(seed))
    cov = JunoCover(m)
    video = Video()
    pens = collections.Counter()
    blits = collections.Counter()
    state = {'two': seed == 7}
    for frame in range(frames):
        m.frame = frame
        m.system, m.p1, m.p2 = inputs(frame, rnd, state)
        m.run_frame_port()
        for src, dest, copy in m.blits:
            blits[(src, copy)] += 1
        m.blits.clear()
        if frame % 8 == 0:
            cnt = np.bincount(video.render_nibbles(m.mem, m.flip()).ravel(), minlength=16)
            for p in np.nonzero(cnt)[0]:
                pens[int(p)] += int(cnt[p])
        if frame % 2000 == 0:
            print(f'seed {seed} frame {frame}: {len(cov.exec)} pcs, {len(blits)} blit sources', flush=True)
    out = build_dir('junofrst') / f'cover{seed}.pkl'
    d = cov.data()
    d.update({'pens': pens, 'blits': blits, 'seed': seed, 'frames': frames, 'bank_in_window': cov.bank_in_window})
    out.write_bytes(pickle.dumps(d))
    print(out, len(cov.exec), 'pcs,', len(blits), 'blit sources, bank writes inside window code', cov.bank_in_window)


if __name__ == '__main__':
    main()
