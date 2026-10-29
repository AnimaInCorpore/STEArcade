"""Coverage of a flat MC6809 / KONAMI-1 program for engine/m6809x.py (Track & Field, Hyper Sports; Gyruss's sub CPU
does the same inline in its ref/cover.py).

    cov = Cover6809(cpu, io=lambda a, rw: 0x1000 <= a < 0x1800)   # wraps cpu.step / cpu.rd / cpu.wr; cpu.run steps
    ... run the machine ...
    cov.data()  -> {'exec': {pc: count}, 'acc': {pc: {(r|w, slot, page, odd word)}}, 'targets': {pc: {next pc}},
                    'wraps': {pc}, 'io': {(pc, address, r|w)}, 'returns': {return point: count}}

exec: the instructions run; acc: each site's data accesses (slot = page = address >> 13: the program is flat; odd
word: the second byte of a 16 bit access whose first byte was at an odd address); targets: where control went other
than to the next instruction (branches taken, jumps, calls, returns, interrupts' entries are not counted: the vector
is a root); wraps: indexed sites whose register + constant offset left $0000-$FFFF; io: the accesses `io(address, r|w)`
names; returns: how often RTS / PULS PC went to each address (engine/m6809x.py Program.ret_weights).
"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from m6809 import P1
from m6809dis import decode


class Cover6809:
    def __init__(self, cpu, io=lambda a, rw: False):
        self.c = c = cpu
        self.exec = collections.Counter()
        self.acc = collections.defaultdict(set)
        self.targets = collections.defaultdict(set)
        self.wraps = set()
        self.io = set()
        self.returns = collections.Counter()
        self.is_io = io
        self._idx = {}
        accs = self._accs = []
        rd0, wr0 = c.rd, c.wr

        def rd(a):
            accs.append(('r', a))
            return rd0(a)

        def wr(a, v):
            accs.append(('w', a))
            wr0(a, v)
        c.rd, c.wr = rd, wr
        self._rd0 = rd0
        c.step = self.step

        def run(n):
            start = c.cycles
            end = start + n
            c.end = end
            while c.cycles < c.end:
                if c.attn and c.wait and not c.can_wake():
                    c.cycles = c.end
                    break
                self.step()
            return c.cycles - start
        c.run = run

    def step(self):
        c = self.c
        if c.attn:
            n = c._slow()
            if n:
                return n
        pc = c.pc
        self.exec[pc] += 1
        ent = self._idx.get(pc)
        if ent is None:
            ins = decode(self._rd0, pc, c.dp, rd_op=c.rd_op)
            x = ins.arg if ins.mode == 'idx' else None
            ent = self._idx[pc] = ((x.reg, x.offset) if x is not None and x.kind in ('off5', 'off8', 'off16') else None,
                                   ins.flow == 'ret')
        idx, is_ret = ent
        if idx is not None:
            r, o = idx
            if not 0 <= getattr(c, r) + o <= 0xFFFF:
                self.wraps.add(pc)
        accs = self._accs
        accs.clear()
        op = c.rd_op(pc)
        c.pc = (pc + 1) & 0xFFFF
        n = P1[op](c)
        c.cycles += n
        prev = None
        acc = self.acc[pc]
        for rw, a in accs:
            if pc <= a < pc + 5 and rw == 'r':
                continue                                  # (the instruction's own bytes)
            oddw = prev is not None and prev[0] == rw and a == ((prev[1] + 1) & 0xFFFF) and prev[1] & 1
            acc.add((rw, a >> 13, a >> 13, bool(oddw)))
            if self.is_io(a, rw):
                self.io.add((pc, a, rw))
            prev = (rw, a)
        nxt = c.pc
        if not (pc < nxt <= pc + 5):
            self.targets[pc].add(nxt)
        if is_ret:
            self.returns[nxt] += 1
        return n

    def data(self):
        return {'exec': dict(self.exec), 'acc': dict(self.acc), 'targets': dict(self.targets), 'wraps': set(self.wraps),
                'io': set(self.io), 'returns': dict(self.returns)}
