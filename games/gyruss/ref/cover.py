"""Coverage of both CPUs in the port's schedule (tools/machine.py GyrussPort.run_frame_port), with scripted play.

    python ref/cover.py <seed> [frames]  ->  build/gyruss/cover<seed>.pkl

main (Z80): pcs, jumps (where computed jumps went: jp (hl) / (ix) / (iy)), writes ((pc, address) of the stores to the
    video RAM $8000-$87FF and the I/O $C000-$C1FF), io ((pc, address, 'r' / 'w') of the accesses to $C000-$C1FF);
sub (KONAMI-1): exec (virtual pc = cpu pc: the program is flat), acc ({pc: set of (r|w, slot, page, odd word)}), targets
    ({pc: set of targets} of computed jumps, returns and calls), wraps (indexed sites whose register + offset crossed
    $FFFF);
pens: the pens' pixel counts of the reference pictures (every 8th frame; tools/assets.py fits the STE's colours);
sprites: Counter of (bank, code, colour, flip x, flip y) entries on screen.

Seeds: 1-3 attract, coin, start and random play to the game over and again; 4-9 the same with infinite lives
(LIVES, poked every frame) so the play reaches later warps and stages; 10-11 two players; 12 the DIP switches' other
bonus, more lives, the hardest difficulty, no demo sounds.
"""
import collections
import pickle
import random
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'tools'), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import GyrussPort, Video, DSW1, DSW2, DSW3
from m6809 import P1
from m6809dis import decode
from paths import build_dir

LIVES = 0x9600                 # (player 1's lives: 3, 2, 1, 0 over a game)


def dsw(seed):
    if seed == 12:
        return DSW1, (DSW2 & ~0x7B) | 0x01 | 0x80, DSW3 | 1   # 5 lives, bonus 40k, hardest, no demo sounds / music
    return DSW1, DSW2, DSW3


def inputs(frame, rnd, state, m=None):
    """-> (SYSTEM, P1), active low"""
    system, p1 = 0xff, 0xff
    two = state.get('two', False)
    if state.setdefault('phase', 'attract') == 'attract' and frame >= state.setdefault('coin_at', 300 + rnd.randrange(900)):
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
            state['next'] = frame + rnd.choice((4, 8, 16, 30, 60))
            state['joy'] = rnd.choice([0, 1, 2, 4, 8, 5, 6, 9, 10, 1, 2])
            state['fire'] = rnd.choice([0, 0x10, 0x10])
        p1 ^= state['joy']
        if frame % 6 < 3:
            p1 ^= state['fire']
        if frame - state['t0'] > 2000 and frame % 1500 == 0:
            state['phase'], state['t0'] = 'coin', frame   # (coin and start again: a new game after a game over)
    return system, p1


def cheats(seed, frame, m, state):
    if 4 <= seed <= 9 and frame > 400:
        m.mem[LIVES] = max(m.mem[LIVES], 3)


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    rnd = random.Random(seed)
    m = GyrussPort(*dsw(seed))
    c = m.main
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
        computed[0] = op == 0xe9 or op in (0xdd, 0xfd) and rd0((pc + 1) & 0xffff) == 0xe9
        return step0()

    def rd(a):
        if 0xC000 <= a < 0xC200:
            io.add((site[0], a, 'r'))
        return rd0(a)

    def wr(a, v):
        if 0x8000 <= a < 0x8800 or 0xC000 <= a < 0xC200:
            writes.add((site[0], a))
        if 0xC000 <= a < 0xC200:
            io.add((site[0], a, 'w'))
        return wr0(a, v)
    c.step, c.rd8, c.wr8 = step, rd, wr

    # the sub CPU
    s = m.sub
    sexec = collections.Counter()
    acc = collections.defaultdict(set)
    targets = collections.defaultdict(set)
    wraps = set()
    idx = {}
    accs = []
    srd0, swr0 = s.rd, s.wr

    def srd(a):
        accs.append(('r', a))
        return srd0(a)

    def swr(a, v):
        accs.append(('w', a))
        swr0(a, v)
    s.rd, s.wr = srd, swr

    def sstep():
        if s.attn:
            n = s._slow()
            if n:
                return n
        pc = s.pc
        sexec[pc] += 1
        if pc not in idx:
            ins = decode(srd0, pc, s.dp, rd_op=s.rd_op)
            x = ins.arg if ins.mode == 'idx' else None
            idx[pc] = (x.reg, x.offset) if x is not None and x.kind in ('off5', 'off8', 'off16') else None
        if idx[pc] is not None:
            r, o = idx[pc]
            if not 0 <= getattr(s, r) + o <= 0xFFFF:
                wraps.add(pc)
        accs.clear()
        op = s.rd_op(pc)
        s.pc = (pc + 1) & 0xFFFF
        n = P1[op](s)
        s.cycles += n
        prev = None
        for rw, a in accs:
            if pc <= a < pc + 5 and rw == 'r':
                continue
            oddw = prev is not None and prev[0] == rw and a == ((prev[1] + 1) & 0xFFFF) and prev[1] & 1
            acc[pc].add((rw, a >> 13, a >> 13, bool(oddw)))
            prev = (rw, a)
        nxt = s.pc
        if not (pc < nxt <= pc + 5):
            targets[pc].add(nxt)
        return n
    s.step = sstep

    video = Video()
    pens = collections.Counter()
    sprites = collections.Counter()
    state = {'two': seed in (10, 11)}
    for frame in range(frames):
        m.system, m.p1 = inputs(frame, rnd, state, m)
        cheats(seed, frame, m, state)
        m.run_frame_port()
        sr = m.sub_mem[0x4040:0x4100]
        for o in range(0, 0xC0, 4):
            a = sr[o + 2]
            sprites[(sr[o + 1] & 1, ((a & 0x20) << 2) | (sr[o + 1] >> 1), a & 15, not a & 0x40, bool(a & 0x80))] += 1
        if frame % 8 == 0:
            raw = video.render_raw(m.mem, bytes(sr))[16:240]
            for p, n in enumerate(__import__('numpy').bincount(raw.ravel(), minlength=320)):
                if n:
                    pens[p] += int(n)
        if frame % 2000 == 0:
            print(f'seed {seed} frame {frame}: {len(pcs)} main pcs, {len(sexec)} sub pcs', flush=True)
    out = build_dir('gyruss') / f'cover{seed}.pkl'
    out.write_bytes(pickle.dumps({'pcs': pcs, 'jumps': jumps, 'writes': writes, 'io': io,
                                  'sub': {'exec': dict(sexec), 'acc': dict(acc), 'targets': dict(targets),
                                          'wraps': wraps},
                                  'pens': pens, 'sprites': sprites, 'seed': seed, 'frames': frames}))
    print(out, len(pcs), 'main pcs,', len(sexec), 'sub pcs')


if __name__ == '__main__':
    main()
