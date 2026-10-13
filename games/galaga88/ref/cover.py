"""Coverage of Galaga '88's main and sub CPU programs on the reference board (engine/namcos1.py).

    venv/bin/python games/galaga88/ref/cover.py SEED FRAMES      -> build/galaga88/cover_SEED.pkl

Random play (coin, start, then left / right / fire changing every few frames from the seed; seeds 1-3 only the attract
mode with a coin late).  Records per CPU
(0 main, 1 sub, 2 sound):
  exec[cpu]   Counter of (virtual pc, bank slot) executed
  acc[cpu]    {(virtual pc, slot): set of (r|w, address bank slot, virtual page, odd word start?)} for every data
              access an instruction made (the instruction's own fetches excluded)
  ioacc[cpu]  {(virtual pc, slot): set of (r|w, virtual address)} the accesses to the I/O pages ($170-$17F)
  shared      {(region, offset): [writer cpus, reader cpus]} for TRIRAM, the CUS30 sound RAM and work RAM
  targets     {(virtual pc, slot): set of virtual targets} of computed jumps, returns and calls (where the pc went next
              when it was not the next instruction)
  dp, sslot   per CPU a Counter of DP and of S's slot, sampled once a frame
  dpsite      {(virtual pc, slot): set of DP values} from frame DP_FROM on (after the boot: $40, the main IRQ's
              routine at $C12A 0)
"""
import collections
import os
import pickle
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from namcos1 import NamcoS1
from m6809 import P1
from paths import build_dir

DP_FROM = 250                 # (DP per site from this frame on: the boot runs code with DP 0 that later runs with $40)


def run(seed, frames, out=None):
    m = NamcoS1("galaga88")
    exec_ = {i: collections.Counter() for i in (0, 1, 2)}
    acc = {i: collections.defaultdict(set) for i in (0, 1, 2)}
    ioacc = {i: collections.defaultdict(set) for i in (0, 1, 2)}
    targets = {i: collections.defaultdict(set) for i in (0, 1, 2)}
    dpsite = {i: collections.defaultdict(set) for i in (0, 1, 2)}
    rec_dp = [False]
    shared = collections.defaultdict(lambda: [set(), set()])
    cur = [None, None, None]                 # (virtual pc, slot) of the instruction each CPU executes
    fetch = [set(), set(), set()]            # addresses of the current instruction's own bytes
    accs = [[], [], []]                      # (r/w, cpu address) of the current instruction

    def virt(i, a):
        return (m.offsets[i][a >> 13] | (a & 0x1FFF)) if i < 2 else a

    def make_run(i):
        c = m.cpus[i]

        def run_(n):
            start = c.cycles
            c.end = start + n
            while c.cycles < c.end:
                if c.attn:
                    if c.wait and not c.can_wake():
                        c.cycles = c.end
                        break
                    if c._slow():
                        continue
                pc = c.pc
                key = (virt(i, pc), pc >> 13)
                cur[i] = key
                exec_[i][key] += 1
                if rec_dp[0]:
                    dpsite[i][key].add(c.dp)
                accs[i] = []
                op = c.rd(pc)
                c.pc = (pc + 1) & 0xFFFF
                c.cycles += P1[op](c)
                ln = None
                # data accesses: everything the instruction touched beyond its own bytes (pc .. pc + 4)
                prev = None
                for rw, a in accs[i]:
                    if pc <= a < pc + 5 and rw == "r":
                        continue
                    oddw = prev is not None and prev[0] == rw and a == ((prev[1] + 1) & 0xFFFF) and prev[1] & 1
                    acc[i][key].add((rw, a >> 13, virt(i, a) >> 13, bool(oddw)))
                    va = virt(i, a)
                    if i < 2 and 0x170 <= va >> 13 <= 0x17F and len(ioacc[i][key]) < 64:
                        ioacc[i][key].add((rw, va))
                    prev = (rw, a)
                nxt = c.pc
                if not (pc < nxt <= pc + 5):
                    targets[i][key].add(virt(i, nxt))
            return c.cycles - start
        return run_

    for i in (0, 1, 2):
        m.cpus[i].run = make_run(i)
    ord_, owr = m.mmu_rd, m.mmu_wr

    def note(i, a, rw):
        v = virt(i, a)
        if 0x2FF000 <= v < 0x300000:
            shared[("tri", v & 0x7FF)][rw == "r"].add(i)
        elif 0x2FE000 <= v < 0x2FF000:
            shared[("snd", v & 0x3FF)][rw == "r"].add(i)

    def rd(i, a):
        accs[i].append(("r", a))
        note(i, a, "r")
        return ord_(i, a)

    def wr(i, a, v):
        accs[i].append(("w", a))
        note(i, a, "w")
        owr(i, a, v)
    m.mmu_rd, m.mmu_wr = rd, wr
    # (the closures in make_cpus call self.mmu_rd / mmu_wr by name: rebind)
    m.main.rd = lambda a: m.mmu_rd(0, a)
    m.main.wr = lambda a, v: m.mmu_wr(0, a, v)
    m.sub.rd = lambda a: m.mmu_rd(1, a)
    m.sub.wr = lambda a, v: m.mmu_wr(1, a, v)
    osr, osw = m.snd_rd, m.snd_wr

    def srd(a):
        accs[2].append(("r", a))
        if 0x7000 <= a < 0x8000:
            shared[("tri", a & 0x7FF)][1].add(2)
        elif 0x5000 <= a < 0x6000:
            shared[("snd", a & 0x3FF)][1].add(2)
        return osr(a)

    def swr(a, v):
        accs[2].append(("w", a))
        if 0x7000 <= a < 0x8000:
            shared[("tri", a & 0x7FF)][0].add(2)
        elif 0x5000 <= a < 0x6000:
            shared[("snd", a & 0x3FF)][0].add(2)
        osw(a, v)
    m.snd.rd, m.snd.wr = srd, swr
    omr, omw = m.mcu.ext_rd, m.mcu.ext_wr

    def mrd(a):
        if 0xC000 <= a < 0xC800:
            shared[("tri", a & 0x7FF)][1].add(3)
        return omr(a)

    def mwr(a, v):
        if 0xC000 <= a < 0xC800:
            shared[("tri", a & 0x7FF)][0].add(3)
        omw(a, v)
    m.mcu.ext_rd, m.mcu.ext_wr = mrd, mwr

    dps = [collections.Counter(), collections.Counter()]
    sslot = [collections.Counter(), collections.Counter()]
    rng = random.Random(seed)
    play = seed > 3
    coin_at = 300 if play else 2400
    hold = 0
    for f in range(frames):
        if f == coin_at:
            m.coin_in &= ~0x10
        if f == coin_at + 6:
            m.coin_in |= 0x10
        if play and f == coin_at + 100:
            m.control_in[0] &= ~0x80
        if play and f == coin_at + 106:
            m.control_in[0] |= 0x80
        if play and f > coin_at + 150:
            if hold <= 0:
                # (right, left, fire; the fighter moves left and right only)
                bits = rng.choice([0, 1, 2, 0x10, 0x11, 0x12, 0x10, 0x10, 1, 2])
                m.control_in[0] = (0xFF & ~bits) | 0x80
                hold = rng.randint(2, 30)
            hold -= 1
            if f % 1500 == 0:                 # coin and start again after a game over
                m.coin_in &= ~0x10
            elif f % 1500 == 6:
                m.coin_in |= 0x10
            elif f % 1500 == 100:
                m.control_in[0] &= ~0x80
        rec_dp[0] = f >= DP_FROM
        dps[0][m.main.dp] += 1
        dps[1][m.sub.dp] += 1
        sslot[0][m.main.s >> 13] += 1
        sslot[1][m.sub.s >> 13] += 1
        m.run_frame()
    data = dict(exec=exec_, acc={i: dict(v) for i, v in acc.items()}, ioacc={i: dict(v) for i, v in ioacc.items()}, targets={i: dict(v) for i, v in targets.items()},
                shared={k: [sorted(w), sorted(r)] for k, (w, r) in shared.items()}, frames=frames, seed=seed,
                dp=dps, sslot=sslot, dpsite={i: dict(dpsite[i]) for i in (0, 1)})
    out = out or build_dir("galaga88") / ("cover_%d.pkl" % seed)
    with open(out, "wb") as f:
        pickle.dump(data, f)
    return m, data


if __name__ == "__main__":
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
    m, data = run(seed, frames)
    print("seed %d: %s frames (main / sub / sound distinct pcs %s), DP %s, S slots %s" % (
        seed, frames, [len(data["exec"][i]) for i in (0, 1, 2)], data["dp"], data["sslot"]))
