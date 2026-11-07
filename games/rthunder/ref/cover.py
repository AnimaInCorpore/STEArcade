"""Coverage of Rolling Thunder's two 6809 programs (tools/machine.py): what the translation needs to know.

    python games/rthunder/ref/cover.py SEED FRAMES [--port]    -> build/rthunder/cover_SEED.pkl (cover_p_SEED.pkl with --port)

By default the board runs on MAME's schedule (Rthunder.run_frame); --port runs the port's schedule
(RthunderPort.run_frame_port: the CPUs one after the other, yielding at the spin waits in machine.SPIN).

Virtual addresses for engine/m6809x.py: page = address >> 13 (8 KB) for the fixed slots (cpu1: 0 tile RAM 0, 1 tile
RAM 1, 2 CUS30 / shared / sprite RAM; cpu2: 0 shared RAM and sprite RAM, 1, 2 the tile RAMs; both 4-7 the ROM at $8000),
the banked ROM window of slot 3 ($6000-$7FFF) in pages 8 + bank (cpu1: bank = $6800's low 5 bits, 32 banks; cpu2: the
$D803 value & 3).

Seeds: 0 the attract mode only; 1-9 random play (coin, start, then the controls changing every few frames; a coin and
start again later); 11-19 the same with a DIP switch setting that gives the stage select.  Records per CPU (0 cpu1,
1 cpu2):
  exec     Counter of (virtual pc, slot) executed
  acc      {(virtual pc, slot): set of (r|w, address slot, virtual page, odd word start?)} data accesses
  ioacc    {(virtual pc, slot): set of (r|w, address)} the accesses to the registers ($8000-$FFFF stores, $6000 window
           stores) and the shared RAM's semaphore bytes
  targets  {(virtual pc, slot): set of virtual targets} of computed jumps, returns and calls
  dp       {(virtual pc, slot): set of DP values}
  wrap     set of (virtual pc, slot) whose indexed operand (register + constant offset) crossed $FFFF / $0000
  semw     {cpu: set of the virtual pcs that wrote a semaphore byte (RthunderPort.SEM)}
  spin     {cpu: set of virtual pcs of the backward branches that closed a spin wait: the same registers and no write
           between two taken passes}
"""
import collections
import pickle
import random
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools"), str(Path(__file__).resolve().parents[3] / "engine")]
from machine import Rthunder, RthunderPort
from m6809 import P1
from m6809dis import decode
from paths import build_dir


def schedule(seed):
    """-> (DSWA, DSWB, inputs(f) -> (IN0, IN1, IN2)): the seed's inputs frame by frame (active low)"""
    rng = random.Random(seed)
    play = seed > 0
    dswb = 0xD7 if seed >= 11 else 0xD7          # (the driver's default has the level select cheat on)
    coin_at = 400 if play else 10 ** 9
    st = dict(hold=0, bits=0)

    def inputs(f):
        in0 = in1 = in2 = 0xFF
        if not play or f < coin_at:
            return in0, in1, in2
        k = (f - coin_at) % 3000
        if k < 6:
            in0 &= ~0x20                         # coin 1
        if 100 <= k < 106:
            in0 &= ~0x40                         # start 1
        if k >= 150:
            if st["hold"] <= 0:
                st["bits"] = rng.choice([0, 1, 2, 4, 8, 0x10, 0x20, 0x11, 0x12, 0x21, 0x22, 0x01, 0x01, 0x01, 0x40, 0x80])
                st["hold"] = rng.randint(2, 40)
            st["hold"] -= 1
            b = st["bits"]
            if b & 1:
                in2 &= ~0x10                     # left
            if b & 2:
                in2 &= ~0x20                     # right
            if b & 4:
                in1 &= ~0x04                     # up
            if b & 8:
                in0 &= ~0x04                     # down
            if b & 0x10:
                in2 &= ~0x08                     # button 1 (fire)
            if b & 0x20:
                in0 &= ~0x02                     # button 2 (bomb)
            if b & 0x40:
                in0 &= ~0x40                     # start (continue)
            if b & 0x80:
                in0 &= ~0x20                     # coin
        return in0, in1, in2
    return 0xFF, dswb, inputs


def run(seed, frames, port=False, out=None):
    dswa, dswb, inputs = schedule(seed)
    m = RthunderPort() if port else Rthunder()
    m.dsw = [dswa, dswb]
    exec_ = {0: collections.Counter(), 1: collections.Counter()}
    acc = {0: collections.defaultdict(set), 1: collections.defaultdict(set)}
    ioacc = {0: collections.defaultdict(set), 1: collections.defaultdict(set)}
    targets = {0: collections.defaultdict(set), 1: collections.defaultdict(set)}
    dps = {0: collections.defaultdict(set), 1: collections.defaultdict(set)}
    wraps = {0: set(), 1: set()}
    spin = {0: set(), 1: set()}
    semw = {0: set(), 1: set()}
    idx = {0: {}, 1: {}}
    accs = [[], []]
    writes = [0, 0]
    last = [{}, {}]                              # per cpu: branch pc -> (registers, writes) of its last taken pass
    rds = (m.rd1, m.rd2)
    wrs = (m.wr1, m.wr2)

    def virt(i, a):
        s = a >> 13
        if s == 3:
            return ((8 + (m.bank1 if i == 0 else m.bank2)) << 13) | (a & 0x1FFF)
        return a

    def make(i):
        c = m.cpus[i]
        ord_, owr = rds[i], wrs[i]

        def rd(a):
            accs[i].append(("r", a))
            return ord_(a)

        def wr(a, v):
            accs[i].append(("w", a))
            writes[i] += 1
            owr(a, v)
        c.rd, c.wr, c.rd_op = rd, wr, rd

        def step():
            if c.attn:
                n = c._slow()
                if n:
                    return n
            pc = c.pc
            key = (virt(i, pc), pc >> 13)
            exec_[i][key] += 1
            dps[i][key].add(c.dp)
            v = key[0]
            if v not in idx[i]:
                ins = decode(lambda a: ord_(a & 0xFFFF), pc, c.dp)
                x = ins.arg if ins.mode == "idx" else None
                back = ins.flow == "jcc" and ins.target is not None and ins.target < pc
                idx[i][v] = ((x.reg, x.offset) if x is not None and x.kind in ("off5", "off8", "off16") and x.reg in "xyus"
                             else None, back, ins.target)
            ix, back, tgt = idx[i][v]
            if ix is not None:
                r, o = ix
                if not 0 <= getattr(c, r) + o <= 0xFFFF:
                    wraps[i].add(key)
            accs[i].clear()
            regs = (c.a, c.b, c.x, c.y, c.u, c.s, c.dp, c.cc)
            op = rd(pc)
            c.pc = (pc + 1) & 0xFFFF
            n = P1[op](c)
            c.cycles += n
            prev = None
            for rw, a in accs[i][1:]:
                if pc <= a < pc + 5 and rw == "r":
                    continue
                oddw = prev is not None and prev[0] == rw and a == ((prev[1] + 1) & 0xFFFF) and prev[1] & 1
                acc[i][key].add((rw, a >> 13, virt(i, a) >> 13, bool(oddw)))
                if (rw == "w" and (a >= 0x6000 or 0x5600 <= a < 0x5700 and i == 0)) or \
                        (i == 1 and 0x1600 <= a < 0x1700) or (rw == "r" and a >= 0x4000 and a < 0x4400 and i == 0):
                    if len(ioacc[i][key]) < 64:
                        ioacc[i][key].add((rw, a))
                if rw == "w" and (i == 0 and 0x4400 <= a < 0x5800 and a - 0x4000 in m.SEMO or
                                  i == 1 and a < 0x1800 and a in m.SEMO):
                    semw[i].add(v)
                prev = (rw, a)
            nxt = c.pc
            if not (pc < nxt <= pc + 5):
                targets[i][key].add(virt(i, nxt))
                if back and nxt == tgt:
                    # a taken backward conditional branch: the same registers and no write since its last pass = a wait
                    st = (regs, writes[i])
                    if last[i].get(v) == st:
                        spin[i].add(v)
                    last[i][v] = (regs, writes[i])
            return n

        def run_(n):
            start = c.cycles
            c.end = start + n
            while c.cycles < c.end:
                if c.attn and c.wait and not c.can_wake():
                    c.cycles = c.end
                    break
                step()
            return c.cycles - start
        c.step = step
        c.run = run_

    for i in (0, 1):
        make(i)
    if port:
        m.boot()
    for f in range(frames):
        m.in0, m.in1, m.in2 = inputs(f)
        if port:
            m.run_frame_port()
        else:
            m.run_frame()
    if port:
        for i, pc in m.learned:
            spin[i].add(pc)
        for i in (0, 1):
            spin[i] |= m.SPIN[i]
        print("learned spin waits %s, semaphore bytes %s" % (sorted((i, "%X" % v) for i, v in m.learned),
                                                           sorted("%X" % a for a in m.learned_sem)))
    data = dict(exec=exec_, semw=semw, acc={i: dict(v) for i, v in acc.items()}, ioacc={i: dict(v) for i, v in ioacc.items()},
                targets={i: dict(v) for i, v in targets.items()}, semo=set(m.SEMO) if port else set(),
                dp={i: {k: s for k, s in v.items() if s != {0}} for i, v in dps.items()}, wrap=wraps, spin=spin,
                frames=frames, seed=seed, port=port)
    out = out or build_dir("rthunder") / ("cover_%s%d.pkl" % ("p_" if port else "", seed))
    with open(out, "wb") as f:
        pickle.dump(data, f)
    return m, data


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    seed = int(args[0]) if args else 0
    frames = int(args[1]) if len(args) > 1 else 3000
    m, data = run(seed, frames, port="--port" in sys.argv)
    print("seed %d: %d frames, distinct pcs cpu1 %d cpu2 %d, spin sites %s" % (
        seed, frames, len(data["exec"][0]), len(data["exec"][1]),
        {i: sorted("%X" % v for v in s) for i, s in data["spin"].items()}))
