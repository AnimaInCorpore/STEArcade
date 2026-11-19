"""Coverage of the main CPU on the reference board (tools/machine.py, MAME's schedule), with scripted play.

    python ref/cover.py <seed> [frames]  ->  build/defender/cover<seed>.pkl

The pickle (engine/m6809cover.py's format, the banked window in virtual pages): exec, acc, targets, wraps, io, returns
keyed by the virtual pc: code in $C000-$CFFF while view k (1-7) shows a ROM bank is page 8 + k (v = page << 13 |
pc & $1FFF); every other pc is itself.  io: the accesses the translation sends through the runtime: $C000-$CFFF (the
I/O in view 0, the bank's data otherwise), writes to $D000-$DFFF (the view select), every access of the video RAM
$0000-$97FF (the runtime keeps the picture).  views: Counter of (virtual pc, view) at every window access.

Seeds (MAME's cheat addresses: P1 lives $A1C9, smart bombs $A1CB, start wave $A1CA; P2 $A206, $A208, $A207):
  1-4   the factory CMOS: attract, coin, start, random play to the game over, again (a new game every 6000 frames)
  5-6   the same with lives and smart bombs held at 5
  7     two players (P2's lives held too in half the games)
  8-11  lives held, the first wave set to 5, 12, 25, 60 (later waves' enemies and speeds)
  12    a blank CMOS: the bookkeeping menu, every item stepped up and down, values changed, then left; then play
  13-16 random play like 1-4 with other timings (deaths, hyperspace, smart bombs used more)
  17-18 like 1-4 with the score set to 20,000 / 300,000 at the start of each game: the game over enters initials
        (P1 score: BCD $A1C2-$A1C5)
"""
import collections
import pickle
import random
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'tools'), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import Defender, factory_cmos
from m6809cover import Cover6809
from m6809 import P1
from m6809dis import decode
from paths import build_dir

# IN0 (PIA 0 A), IN1 (PIA 0 B), IN2 (PIA 1 A); active high
FIRE, THRUST, SMART, HYPER, START2, START1, REVERSE, DOWN = 1, 2, 4, 8, 0x10, 0x20, 0x40, 0x80
UP = 1
AUTO_UP, ADVANCE, HS_RESET, COIN1 = 1, 2, 8, 0x10

P1_LIVES, P1_SMART, P1_WAVE = 0xA1C9, 0xA1CB, 0xA1CA
P2_LIVES, P2_SMART, P2_WAVE = 0xA206, 0xA208, 0xA207
P1_SCORE = 0xA1C2                                   # 4 bytes BCD, the most significant first


def virtual(pc, view):
    return ((8 + view) << 13) | (pc & 0x1FFF) if 0xC000 <= pc < 0xD000 and view else pc


def io(a, rw):
    return 0xC000 <= a < 0xD000 or (rw == 'w' and 0xD000 <= a < 0xE000) or a < 0x9800


class DefCover(Cover6809):
    """Cover6809 with the banked window's code in virtual pages"""

    def __init__(self, m):
        super().__init__(m.cpu, io=io)
        self.m = m
        self.view_in_window = 0
        self.views = collections.Counter()

    def step(self):
        c, m = self.c, self.m
        if c.attn:
            n = c._slow()
            if n:
                return n
        pc = c.pc
        view0 = m.view
        v = virtual(pc, view0)
        self.exec[v] += 1
        key = v
        ent = self._idx.get(key)
        if ent is None:
            ins = decode(self._rd0, pc, c.dp, rd_op=c.rd_op)
            x = ins.arg if ins.mode == 'idx' else None
            ent = self._idx[key] = ((x.reg, x.offset) if x is not None and x.kind in ('off5', 'off8', 'off16') else None,
                                    ins.flow == 'ret')
        idx, is_ret = ent
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
            if io(a, rw):
                self.io.add((v, a, rw))
                if 0xC000 <= a < 0xD000:
                    self.views[(v, view0)] += 1
            prev = (rw, a)
        nxt = c.pc
        if m.view != view0 and 0xC000 <= pc < 0xD000:
            self.view_in_window += 1
        if not (pc < nxt <= pc + 5):
            self.targets[v].add(virtual(nxt, m.view))
        if is_ret:
            self.returns[virtual(nxt, m.view)] += 1
        return n


def play_bits(frame, rnd, state, heavy):
    """random play: (IN0, IN1) bits"""
    if frame >= state.get('next', 0):
        state['next'] = frame + rnd.choice((4, 8, 16, 30, 60, 120))
        state['vert'] = rnd.choice((0, 0, DOWN, UP << 8))
        state['thrust'] = rnd.random() < 0.6
        state['rev'] = rnd.random() < (0.15 if heavy else 0.05)
        state['rate'] = rnd.choice((2, 3, 4, 6, 0))
    t = frame - state['t0']
    in0 = in1 = 0
    if state['vert'] == DOWN:
        in0 |= DOWN
    elif state['vert']:
        in1 |= UP
    if state['thrust']:
        in0 |= THRUST
    if state['rev']:
        in0 |= REVERSE
    if state['rate'] and (t // state['rate']) & 1:
        in0 |= FIRE
    if t % (331 if heavy else 997) < 3:
        in0 |= SMART
    if t % (577 if heavy else 2111) < 3:
        in0 |= HYPER
    return in0, in1


def inputs(seed, frame, rnd, state):
    """-> (IN0, IN1, IN2)"""
    in0 = in1 = 0
    in2 = state.get('auto', 0)
    two = state.get('two', False)
    ph = state.setdefault('phase', 'menu' if seed == 12 else 'attract')
    if ph == 'menu':
        # the bookkeeping menu of a blank CMOS (from ~frame 1200): 30 steps up, values changed on the way, 30 down,
        # then up to item 28 and past it
        t = frame - 1300
        if t >= 0:
            k, r = divmod(t, 40)
            if k < 30:
                state['auto'] = AUTO_UP
                in2 = AUTO_UP | (ADVANCE if r < 2 else 0) | (HS_RESET if k % 3 == 1 and 20 <= r < 22 else 0)
            elif k < 60:
                state['auto'] = 0
                in2 = (ADVANCE if r < 2 else 0) | (HS_RESET if k % 4 == 1 and 20 <= r < 22 else 0)
            elif k < 120:
                state['auto'] = AUTO_UP
                in2 = AUTO_UP | (ADVANCE if r < 2 else 0)
            else:
                state['phase'] = 'attract'
                state['coin_at'] = frame + 600
    elif ph == 'attract' and frame >= state.setdefault('coin_at', 1300 + rnd.randrange(1200)):
        state['phase'], state['t0'] = 'coin', frame
    if state['phase'] == 'coin':
        t = frame - state['t0']
        if t < 4 or two and 20 <= t < 24:
            in2 |= COIN1
        elif 60 <= t < 64:
            in0 |= START2 if two else START1
        elif t >= 64:
            state['phase'], state['t0'] = 'play', frame
    if state['phase'] == 'play':
        b0, b1 = play_bits(frame, rnd, state, seed >= 13)
        in0 |= b0
        in1 |= b1
        t = frame - state['t0']
        if t > 3000 and frame % 6000 == 0:
            state['phase'], state['t0'] = 'coin', frame   # (coin and start again: a new game after a game over)
    return in0, in1, in2


def cheats(seed, state, mem):
    if state.get('phase') != 'play':
        return
    if seed in (17, 18) and state.get('scored') != state['t0'] and mem[P1_SCORE + 3] | mem[P1_SCORE + 2]:
        state['scored'] = state['t0']                 # (once a game, after its first points)
        mem[P1_SCORE + 1] = 0x02 if seed == 17 else 0x30
    if 5 <= seed <= 11:
        mem[P1_LIVES] = 5
        mem[P1_SMART] = 5
        if seed == 7 and (state['t0'] // 6000) & 1:
            mem[P2_LIVES] = 5
    if 8 <= seed <= 11 and mem[P1_WAVE] == 1:
        mem[P1_WAVE] = (5, 12, 25, 60)[seed - 8]


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 30000
    rnd = random.Random(seed)
    m = Defender(None if seed == 12 else factory_cmos())
    cov = DefCover(m)
    state = {'two': seed == 7}
    for frame in range(frames):
        m.in0, m.in1, m.in2 = inputs(seed, frame, rnd, state)
        cheats(seed, state, m.mem)
        m.run_frame()
        if frame % 2000 == 0:
            print(f'seed {seed} frame {frame}: {len(cov.exec)} pcs, phase {state.get("phase")}', flush=True)
    out = build_dir('defender') / f'cover{seed}.pkl'
    out.parent.mkdir(parents=True, exist_ok=True)
    d = cov.data()
    d.update({'seed': seed, 'frames': frames, 'views': cov.views, 'view_in_window': cov.view_in_window,
              'sound': m.sound_log})
    out.write_bytes(pickle.dumps(d))
    print(out, len(cov.exec), 'pcs, view changes inside window code', cov.view_in_window)


if __name__ == '__main__':
    main()
