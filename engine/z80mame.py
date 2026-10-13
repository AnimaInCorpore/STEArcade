"""The Z80 as MAME 0.289 runs it (src/devices/cpu/z80/z80.cpp, z80.lst; BSD-3-Clause, copyright-holders Juergen
Buchmueller, Andrei I. Holub): cycle exact against MAME's scheduler, for boards that must follow MAME instruction for
instruction (engine/m72board.py).  engine/z80.py stays the simple interpreter the other ports use.

MAME's core counts per M-cycle: an access happens, then its cycles come off icount ('3 !! read'), internal cycles
are '+ n' steps; after every step with icount <= 0 the core returns from execute_run() and the rest of the
instruction runs in the next time slice (accesses there see the state of that slice).  The opcode bodies are
generated from z80.lst (engine/z80mame_gen.py -> engine/z80mame_ops.py) as Python generators that yield at those
points; this file holds the registers, MAME's flag representation (m_f: s/z/yx/h/pv values, n, c, q), the helper
functions of z80.cpp and the run loop ("ffff" in z80.lst: the icount check, service attention: NMI, IRQ, EI delay,
HALT; the debugger hook; the opcode fetch).

Interface: run(n) sets icount = n and runs until icount <= 0 at a step (returns n - icount: may overshoot);
executed() = cycles done in this run so far as MAME's machine().time() sees them at an access (n - icount);
abort() = MAME's abort_timeslice (icount -> 0; the caller counts the rest as stolen); set_input("irq"|"nmi", state);
reset() = device_reset; hook: called before each instruction (MAME's debugger_instruction_hook).
"""
from z80mame_ops import OPS, PV, take_nmi, take_interrupt

SA_BUSREQ, SA_NMI_PENDING, SA_IRQ_ON, SA_HALT, SA_AFTER_EI, SA_AFTER_LDAIR = range(6)
F_NMI, F_IRQ, F_HALT, F_EI = 1 << SA_NMI_PENDING, 1 << SA_IRQ_ON, 1 << SA_HALT, 1 << SA_AFTER_EI
OPS0 = OPS[0x00]


class Z80Mame:
    def __init__(self, rd8, wr8, io_in, io_out, irq_ack=None):
        self._rd = rd8
        self._wr = wr8
        self._in = io_in
        self._out = io_out
        self.irq_ack_cb = irq_ack or (lambda: 0xFF)
        self.hook = None
        self.icount = 0
        self.n = 0
        self.total = 0                  # cycles of finished runs (MAME's totalcycles without the running slice)
        # device_start
        self.PRVPC = self.PC = self.SP = 0
        self.A = self.F = self.B = self.C = self.D = self.E = self.H = self.L = 0
        self.IX = self.IY = 0xFFFF
        self.WZ = 0
        self.af2 = self.bc2 = self.de2 = self.hl2 = 0
        self.TL = self.TH = 0
        self.TDAT2 = 0
        self.ea = 0
        self.R = self.R2 = self.I = 0
        self.iff1 = self.iff2 = 0
        self.halt_ = 0
        self.im = 0
        self.nmi_state = self.irq_state = 0
        self.busreq = self.busack = 0
        self.sa = 0
        self.tmp_vec = 0
        self.q = self.qt = 0
        self.set_f(0)
        self.fz = 0                      # (Z set)
        self.loop = self._loop()
        self.reset()

    # ---- device_reset / lines ------------------------------------------------------------------------------
    def reset(self):
        self.leave_halt()
        self.PC = 0
        self.WZ = 0
        self.I = self.R = self.R2 = 0
        self.iff1 = self.iff2 = 0
        self.sa &= ~(F_NMI | F_EI | (1 << SA_AFTER_LDAIR))
        self.loop = self._loop()          # m_ref = 0xffff00: an interrupted instruction is dropped

    def set_input(self, line, state, total_cycles=1):
        """execute_set_input; total_cycles: the device's total_cycles() (an NMI edge at 0, the reset's moment, is
        not taken)"""
        if line == "nmi":
            if not self.nmi_state and state and total_cycles:
                self.sa |= F_NMI
            self.nmi_state = 1 if state else 0
        elif line == "irq":
            self.irq_state = 1 if state else 0
            if state:
                self.sa |= F_IRQ
            else:
                self.sa &= ~F_IRQ

    # ---- the scheduler's protocol --------------------------------------------------------------------------
    def run(self, n):
        self.icount = n
        self.n = n
        next(self.loop)
        return self.n - self.icount

    def executed(self):
        return self.n - self.icount

    def abort(self):
        """abort_timeslice: the remaining cycles are swallowed (returns them: MAME's cycles_stolen)"""
        k = self.icount
        if k > 0:
            self.n -= k
            self.icount = 0
            return k
        return 0

    # ---- buses ---------------------------------------------------------------------------------------------
    def rd(self, a):
        return self._rd(a & 0xFFFF)

    def rd_pc(self):
        return self._rd(self.PC)

    def wr(self, a, v):
        self._wr(a & 0xFFFF, v & 0xFF)

    def io_in(self, p):
        return self._in(p & 0xFFFF)

    def io_out(self, p, v):
        self._out(p & 0xFFFF, v & 0xFF)

    def irq_ack(self):
        return self.irq_ack_cb()

    def sa_set(self, bit, v):
        if v:
            self.sa |= 1 << bit
        else:
            self.sa &= ~(1 << bit)

    def sa_get(self, bit):
        return (self.sa >> bit) & 1

    # ---- the run loop: z80.lst's "ffff" ---------------------------------------------------------------------
    def _loop(s):
        while True:
            while s.icount <= 0:
                yield
            if s.sa:
                if s.busreq:
                    raise NotImplementedError("BUSREQ")
                s.sa &= ~(1 << SA_BUSREQ)
                if s.sa & F_NMI:
                    yield from take_nmi(s)
                elif s.irq_state and s.iff1 and not s.sa & F_EI:
                    yield from take_interrupt(s)
                s.sa &= ~F_EI
                if s.halt_:
                    s.TL = s._rd(s.PC)              # rop, PC-- (the halted CPU fetches its next byte)
                    s.icount -= 2
                    if s.icount <= 0:
                        yield
                    s.icount -= 2
                    if s.icount <= 0:
                        yield
                    s.R = (s.R + 1) & 0xFF
                    s.q = s.qt
                    s.qt = 0x28
                    continue
            s.PRVPC = s.PC
            if s.hook is not None:
                s.hook()
            s.TL = s._rd(s.PC)
            s.icount -= 2
            if s.icount <= 0:
                yield
            s.icount -= 2
            if s.icount <= 0:
                yield
            s.PC = (s.PC + 1) & 0xFFFF
            s.R = (s.R + 1) & 0xFF
            s.q = s.qt
            s.qt = 0x28
            r = OPS0[s.TL](s)
            if r is not None:
                yield from r

    # ---- registers as MAME's state shows them ----------------------------------------------------------------
    def get_f(self):
        return ((self.fs & 0x80) | (0 if self.fz else 0x40) | (self.fyx & 0x28) | (self.fh & 0x10) | PV[self.fpv]
                | (2 if self.fn else 0) | (1 if self.fc else 0))

    def set_f(self, f):
        self.fs = f & 0xFF
        self.fz = 0 if f & 0x40 else 1
        self.fyx = f & 0xFF
        self.fh = f & 0xFF
        self.fpv = 0 if f & 0x04 else 1
        self.fn = 1 if f & 2 else 0
        self.fc = 1 if f & 1 else 0

    def regs(self):
        """(pc, af, bc, de, hl, ix, iy, sp, af2, bc2, de2, hl2, r, i, im, iff1, iff2, halt)"""
        return (self.PC, (self.A << 8) | self.get_f(), (self.B << 8) | self.C, (self.D << 8) | self.E,
                (self.H << 8) | self.L, self.IX, self.IY, self.SP, self.af2, self.bc2, self.de2, self.hl2,
                (self.R & 0x7F) | (self.R2 & 0x80), self.I, self.im, self.iff1, self.iff2, self.halt_)

    # ---- z80.cpp's helpers ----------------------------------------------------------------------------------
    def halt(self):
        if not self.halt_:
            self.halt_ = 1
            self.sa |= F_HALT

    def leave_halt(self):
        if self.halt_:
            self.halt_ = 0
            self.sa &= ~F_HALT

    def inc(self, r):
        r = (r + 1) & 0xFF
        self.qt = 0
        self.fs = self.fz = self.fyx = r
        self.fpv = 1 if r != 0x80 else 0
        self.fh = 0x10 if (r & 0x0F) == 0 else 0
        self.fn = 0
        return r

    def dec(self, r):
        r = (r - 1) & 0xFF
        self.qt = 0
        self.fs = self.fz = self.fyx = r
        self.fpv = 1 if r != 0x7F else 0
        self.fh = 0x10 if (r & 0x0F) == 0x0F else 0
        self.fn = 1
        return r

    def rlca(self):
        a = self.A
        self.A = ((a << 1) | (a >> 7)) & 0xFF
        self.qt = 0
        self.fyx = self.A
        self.fh = self.fn = 0
        self.fc = self.A & 1

    def rrca(self):
        a0 = self.A
        self.A = ((a0 >> 1) | (a0 << 7)) & 0xFF
        self.qt = 0
        self.fyx = self.A
        self.fh = self.fn = 0
        self.fc = a0 & 1

    def rla(self):
        res = ((self.A << 1) + self.fc) & 0xFF
        self.qt = 0
        self.fyx = res
        self.fh = self.fn = 0
        self.fc = 1 if self.A & 0x80 else 0
        self.A = res

    def rra(self):
        res = ((self.fc << 7) | (self.A >> 1)) & 0xFF
        self.qt = 0
        self.fyx = res
        self.fh = self.fn = 0
        self.fc = self.A & 1
        self.A = res

    def add_a(self, value):
        a = self.A
        res = (a + value) & 0xFFFF
        self.qt = 0
        self.fs = self.fz = self.fyx = res & 0xFF
        self.fc = 1 if res & 0x100 else 0
        self.fh = ((a & 0x0F) + (value & 0x0F)) & 0xFF
        self.fpv = 0 if ((a ^ res) & (value ^ res) & 0x80) else 1
        self.fn = 0
        self.A = res & 0xFF

    def adc_a(self, value):
        a = self.A
        c = self.fc
        res = (a + value + c) & 0xFFFF
        self.qt = 0
        self.fs = self.fz = self.fyx = res & 0xFF
        self.fc = 1 if res & 0x100 else 0
        self.fh = ((a & 0x0F) + (value & 0x0F) + c) & 0xFF
        self.fpv = 0 if ((a ^ res) & (value ^ res) & 0x80) else 1
        self.fn = 0
        self.A = res & 0xFF

    def sub_a(self, value):
        a = self.A
        res = (a - value) & 0xFFFF
        self.qt = 0
        self.fs = self.fz = self.fyx = res & 0xFF
        self.fc = 1 if res & 0x100 else 0
        self.fh = ((a & 0x0F) - (value & 0x0F)) & 0xFF
        self.fpv = 0 if ((a ^ value) & (a ^ res) & 0x80) else 1
        self.fn = 1
        self.A = res & 0xFF

    def sbc_a(self, value):
        a = self.A
        c = self.fc
        res = (a - value - c) & 0xFFFF
        self.qt = 0
        self.fs = self.fz = self.fyx = res & 0xFF
        self.fc = 1 if res & 0x100 else 0
        self.fh = ((a & 0x0F) - (value & 0x0F) - c) & 0xFF
        self.fpv = 0 if ((a ^ value) & (a ^ res) & 0x80) else 1
        self.fn = 1
        self.A = res & 0xFF

    def neg(self):
        v = self.A
        self.A = 0
        self.sub_a(v)

    def daa(self):
        A = self.A
        a = A
        h = self.fh & 0x10
        if self.fn:
            if h or (A & 0xF) > 9:
                a -= 6
            if self.fc or A > 0x99:
                a -= 0x60
        else:
            if h or (A & 0xF) > 9:
                a += 6
            if self.fc or A > 0x99:
                a += 0x60
        a &= 0xFF
        self.qt = 0
        self.fs = self.fz = self.fpv = self.fyx = a
        self.fh = (A ^ a) & 0xFF
        self.fc = 1 if (self.fc or A > 0x99) else 0
        self.A = a

    def and_a(self, value):
        self.A &= value
        self.qt = 0
        self.fs = self.fz = self.fpv = self.fyx = self.A
        self.fn = self.fc = 0
        self.fh = 0x10

    def or_a(self, value):
        self.A = (self.A | value) & 0xFF
        self.qt = 0
        self.fs = self.fz = self.fpv = self.fyx = self.A
        self.fh = self.fn = self.fc = 0

    def xor_a(self, value):
        self.A = (self.A ^ value) & 0xFF
        self.qt = 0
        self.fs = self.fz = self.fpv = self.fyx = self.A
        self.fh = self.fn = self.fc = 0

    def cp(self, value):
        a = self.A
        res = (a - value) & 0xFFFF
        self.qt = 0
        self.fs = self.fz = res & 0xFF
        self.fyx = value
        self.fc = 1 if res & 0x100 else 0
        self.fh = ((a & 0x0F) - (value & 0x0F)) & 0xFF
        self.fpv = 0 if ((a ^ value) & (a ^ res) & 0x80) else 1
        self.fn = 1

    def exx(self):
        bc, de, hl = (self.B << 8) | self.C, (self.D << 8) | self.E, (self.H << 8) | self.L
        self.B, self.C = self.bc2 >> 8, self.bc2 & 0xFF
        self.D, self.E = self.de2 >> 8, self.de2 & 0xFF
        self.H, self.L = self.hl2 >> 8, self.hl2 & 0xFF
        self.bc2, self.de2, self.hl2 = bc, de, hl

    def _shift_flags(self, res, c):
        self.qt = 0
        self.fs = self.fz = self.fpv = self.fyx = res
        self.fh = self.fn = 0
        self.fc = c
        return res

    def rlc(self, v):
        return self._shift_flags(((v << 1) | (v >> 7)) & 0xFF, v >> 7)

    def rrc(self, v):
        return self._shift_flags(((v >> 1) | (v << 7)) & 0xFF, v & 1)

    def rl(self, v):
        return self._shift_flags(((v << 1) + self.fc) & 0xFF, v >> 7)

    def rr(self, v):
        return self._shift_flags(((v >> 1) | (self.fc << 7)) & 0xFF, v & 1)

    def sla(self, v):
        return self._shift_flags((v << 1) & 0xFF, v >> 7)

    def sra(self, v):
        return self._shift_flags((v >> 1) | (v & 0x80), v & 1)

    def sll(self, v):
        return self._shift_flags(((v << 1) | 1) & 0xFF, v >> 7)

    def srl(self, v):
        return self._shift_flags(v >> 1, v & 1)

    def bit(self, b, v):
        self.qt = 0
        self.fs = self.fz = self.fpv = v & (1 << b)
        self.fh = 0x10
        self.fn = 0
        self.fyx = v

    def bit_hl(self, b, v):
        self.bit(b, v)
        self.fyx = self.WZ >> 8

    def bit_xy(self, b, v):
        self.bit(b, v)
        self.fyx = self.ea >> 8

    def res(self, b, v):
        return v & ~(1 << b) & 0xFF

    def set(self, b, v):
        return v | (1 << b)

    def block_io_interrupted_flags(self):
        self.fyx = self.PC >> 8
        pv_old = PV[self.fpv]
        B = self.B
        if self.fc:
            self.fh = 0
            if self.TL & 0x80:
                self.fpv = ((B - 1) & 0x07)
                if (B & 0x0F) == 0:
                    self.fh = 0x10
            else:
                self.fpv = ((B + 1) & 0x07)
                if (B & 0x0F) == 0x0F:
                    self.fh = 0x10
        else:
            self.fpv = B & 0x07
        self.fpv = (pv_old ^ PV[self.fpv]) & 0x04

    def ei(self):
        self.iff1 = self.iff2 = 1
        self.sa |= F_EI
