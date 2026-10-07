"""Reference Z80 interpreter (documented + common undocumented behaviour).

Used as ground truth for the Donkey Kong STE port: the machine model in
dkong.py drives it, and the recompiled 68000 code is compared against it.

Memory access goes through rd8/wr8 callbacks supplied by the machine.
"""

S, Z, Y, H, X, PV, N, C = 0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01

PARITY = [0] * 256
for _i in range(256):
    PARITY[_i] = PV if bin(_i).count("1") % 2 == 0 else 0
SZ = [(S if i & 0x80 else 0) | (Z if i == 0 else 0) | (i & (Y | X)) for i in range(256)]
SZP = [SZ[i] | PARITY[i] for i in range(256)]


class Z80:
    def __init__(self, rd8, wr8, io_in=None, io_out=None):
        self.rd8 = rd8
        self.wr8 = wr8
        self.io_in = io_in or (lambda port: 0xFF)
        self.io_out = io_out or (lambda port, v: None)
        self.reset()

    def reset(self):
        self.a = self.f = self.b = self.c = self.d = self.e = self.h = self.l = 0
        self.a_ = self.f_ = self.b_ = self.c_ = self.d_ = self.e_ = self.h_ = self.l_ = 0
        self.ix = self.iy = 0
        self.sp = 0xFFFF
        self.pc = 0
        self.i = self.r = 0
        self.iff1 = self.iff2 = 0
        self.im = 0
        self.halted = False
        self.cycles = 0
        self.ei_delay = False
        self.afmask = 0xFF       # flags kept by push af / pop af (the port tracks S Z C only)

    # ---- helpers -------------------------------------------------------
    def rd16(self, a):
        return self.rd8(a & 0xFFFF) | (self.rd8((a + 1) & 0xFFFF) << 8)

    def wr16(self, a, v):
        self.wr8(a & 0xFFFF, v & 0xFF)
        self.wr8((a + 1) & 0xFFFF, (v >> 8) & 0xFF)

    def fetch8(self):
        v = self.rd8(self.pc)
        self.pc = (self.pc + 1) & 0xFFFF
        return v

    def fetch16(self):
        lo = self.fetch8()
        return lo | (self.fetch8() << 8)

    def push(self, v):
        self.sp = (self.sp - 1) & 0xFFFF
        self.wr8(self.sp, (v >> 8) & 0xFF)
        self.sp = (self.sp - 1) & 0xFFFF
        self.wr8(self.sp, v & 0xFF)

    def pop(self):
        lo = self.rd8(self.sp)
        self.sp = (self.sp + 1) & 0xFFFF
        hi = self.rd8(self.sp)
        self.sp = (self.sp + 1) & 0xFFFF
        return lo | (hi << 8)

    @property
    def bc(self): return (self.b << 8) | self.c
    @bc.setter
    def bc(self, v): self.b = (v >> 8) & 0xFF; self.c = v & 0xFF
    @property
    def de(self): return (self.d << 8) | self.e
    @de.setter
    def de(self, v): self.d = (v >> 8) & 0xFF; self.e = v & 0xFF
    @property
    def hl(self): return (self.h << 8) | self.l
    @hl.setter
    def hl(self, v): self.h = (v >> 8) & 0xFF; self.l = v & 0xFF
    @property
    def af(self): return (self.a << 8) | self.f
    @af.setter
    def af(self, v): self.a = (v >> 8) & 0xFF; self.f = v & 0xFF

    # ---- register access by index (B C D E H L (HL) A) -------------------
    def get_r(self, idx, ixm=None, disp_addr=None):
        if idx == 0: return self.b
        if idx == 1: return self.c
        if idx == 2: return self.d
        if idx == 3: return self.e
        if idx == 4: return self.h if ixm is None else ((self.ix if ixm == 'x' else self.iy) >> 8)
        if idx == 5: return self.l if ixm is None else ((self.ix if ixm == 'x' else self.iy) & 0xFF)
        if idx == 6: return self.rd8(disp_addr)
        return self.a

    def set_r(self, idx, v, ixm=None, disp_addr=None):
        v &= 0xFF
        if idx == 0: self.b = v
        elif idx == 1: self.c = v
        elif idx == 2: self.d = v
        elif idx == 3: self.e = v
        elif idx == 4:
            if ixm is None: self.h = v
            elif ixm == 'x': self.ix = (self.ix & 0x00FF) | (v << 8)
            else: self.iy = (self.iy & 0x00FF) | (v << 8)
        elif idx == 5:
            if ixm is None: self.l = v
            elif ixm == 'x': self.ix = (self.ix & 0xFF00) | v
            else: self.iy = (self.iy & 0xFF00) | v
        elif idx == 6: self.wr8(disp_addr, v)
        else: self.a = v

    def get_rp(self, p, ixm=None):
        if p == 0: return self.bc
        if p == 1: return self.de
        if p == 2: return self.hl if ixm is None else (self.ix if ixm == 'x' else self.iy)
        return self.sp

    def set_rp(self, p, v, ixm=None):
        v &= 0xFFFF
        if p == 0: self.bc = v
        elif p == 1: self.de = v
        elif p == 2:
            if ixm is None: self.hl = v
            elif ixm == 'x': self.ix = v
            else: self.iy = v
        else: self.sp = v

    def get_rp2(self, p, ixm=None):
        if p == 3: return self.af & (0xFF00 | self.afmask)
        return self.get_rp(p, ixm)

    def set_rp2(self, p, v, ixm=None):
        if p == 3: self.af = v & (0xFF00 | self.afmask)
        else: self.set_rp(p, v, ixm)

    def cond(self, cc):
        f = self.f
        if cc == 0: return not (f & Z)
        if cc == 1: return bool(f & Z)
        if cc == 2: return not (f & C)
        if cc == 3: return bool(f & C)
        if cc == 4: return not (f & PV)
        if cc == 5: return bool(f & PV)
        if cc == 6: return not (f & S)
        return bool(f & S)

    # ---- ALU -----------------------------------------------------------
    def alu(self, op, v):
        a = self.a
        if op == 0 or op == 1:  # ADD / ADC
            c = (self.f & C) if op == 1 else 0
            r = a + v + c
            res = r & 0xFF
            f = SZ[res]
            if ((a & 0xF) + (v & 0xF) + c) > 0xF: f |= H
            if (~(a ^ v) & (a ^ res) & 0x80): f |= PV
            if r > 0xFF: f |= C
            self.a = res
            self.f = f
        elif op == 2 or op == 3 or op == 7:  # SUB / SBC / CP
            c = (self.f & C) if op == 3 else 0
            r = a - v - c
            res = r & 0xFF
            f = SZ[res] | N
            if ((a & 0xF) - (v & 0xF) - c) < 0: f |= H
            if ((a ^ v) & (a ^ res) & 0x80): f |= PV
            if r < 0: f |= C
            if op == 7:
                f = (f & ~(Y | X)) | (v & (Y | X))
            else:
                self.a = res
            self.f = f
        elif op == 4:  # AND
            self.a = a & v
            self.f = SZP[self.a] | H
        elif op == 5:  # XOR
            self.a = a ^ v
            self.f = SZP[self.a]
        else:  # OR
            self.a = a | v
            self.f = SZP[self.a]

    def inc8(self, v):
        r = (v + 1) & 0xFF
        f = (self.f & C) | SZ[r]
        if (v & 0xF) == 0xF: f |= H
        if v == 0x7F: f |= PV
        self.f = f
        return r

    def dec8(self, v):
        r = (v - 1) & 0xFF
        f = (self.f & C) | SZ[r] | N
        if (v & 0xF) == 0: f |= H
        if v == 0x80: f |= PV
        self.f = f
        return r

    def add16(self, a, b):
        r = a + b
        f = self.f & (S | Z | PV)
        if ((a & 0xFFF) + (b & 0xFFF)) > 0xFFF: f |= H
        if r > 0xFFFF: f |= C
        f |= (r >> 8) & (Y | X)
        self.f = f
        return r & 0xFFFF

    def adc16(self, a, b):
        c = self.f & C
        r = a + b + c
        res = r & 0xFFFF
        f = (res >> 8) & (S | Y | X)
        if res == 0: f |= Z
        if ((a & 0xFFF) + (b & 0xFFF) + c) > 0xFFF: f |= H
        if (~(a ^ b) & (a ^ res) & 0x8000): f |= PV
        if r > 0xFFFF: f |= C
        self.f = f
        return res

    def sbc16(self, a, b):
        c = self.f & C
        r = a - b - c
        res = r & 0xFFFF
        f = ((res >> 8) & (S | Y | X)) | N
        if res == 0: f |= Z
        if ((a & 0xFFF) - (b & 0xFFF) - c) < 0: f |= H
        if ((a ^ b) & (a ^ res) & 0x8000): f |= PV
        if r < 0: f |= C
        self.f = f
        return res

    def daa(self):
        a = self.a
        f = self.f
        adj = 0
        cy = f & C
        if (f & H) or (a & 0xF) > 9: adj |= 0x06
        if cy or a > 0x99:
            adj |= 0x60
            cy = C
        if f & N:
            res = (a - adj) & 0xFF
            hf = H if (f & H) and (a & 0xF) < 6 else 0
        else:
            res = (a + adj) & 0xFF
            hf = H if (a & 0xF) > 9 else 0
        self.a = res
        self.f = SZP[res] | (f & N) | hf | cy

    def rot(self, op, v):
        """CB-prefix rotate/shift. op: 0 RLC 1 RRC 2 RL 3 RR 4 SLA 5 SRA 6 SLL 7 SRL"""
        c_in = self.f & C
        if op == 0:
            c = v >> 7; r = ((v << 1) | c) & 0xFF
        elif op == 1:
            c = v & 1; r = (v >> 1) | (c << 7)
        elif op == 2:
            c = v >> 7; r = ((v << 1) | c_in) & 0xFF
        elif op == 3:
            c = v & 1; r = (v >> 1) | (c_in << 7)
        elif op == 4:
            c = v >> 7; r = (v << 1) & 0xFF
        elif op == 5:
            c = v & 1; r = (v >> 1) | (v & 0x80)
        elif op == 6:
            c = v >> 7; r = ((v << 1) | 1) & 0xFF
        else:
            c = v & 1; r = v >> 1
        self.f = SZP[r] | c
        return r

    # ---- interrupts ----------------------------------------------------
    def nmi(self):
        self.halted = False
        self.iff2 = self.iff1
        self.iff1 = 0
        self.push(self.pc)
        self.pc = 0x66
        self.cycles += 11

    def irq(self, vec=0xFF):
        if not self.iff1:
            return False
        self.halted = False
        self.iff1 = self.iff2 = 0
        if self.im == 2:
            self.push(self.pc)
            self.pc = self.rd16((self.i << 8) | vec)
            self.cycles += 19
        else:
            self.push(self.pc)
            self.pc = 0x38
            self.cycles += 13
        return True

    # ---- execution -----------------------------------------------------
    def step(self):
        """Execute one instruction; returns T-states."""
        if self.halted:
            self.cycles += 4
            return 4
        c0 = self.cycles
        ixm = None
        self.cycles += self._exec(ixm)
        return self.cycles - c0

    def _exec(self, ixm):
        op = self.fetch8()
        self.r = (self.r & 0x80) | ((self.r + 1) & 0x7F)
        if op == 0xDD:
            return 4 + self._exec_ix('x')
        if op == 0xFD:
            return 4 + self._exec_ix('y')
        if op == 0xCB:
            return self._exec_cb()
        if op == 0xED:
            return self._exec_ed()
        return self._exec_main(op, None, 0)

    def _exec_ix(self, ixm):
        op = self.fetch8()
        self.r = (self.r & 0x80) | ((self.r + 1) & 0x7F)
        if op == 0xDD:
            return 4 + self._exec_ix('x')
        if op == 0xFD:
            return 4 + self._exec_ix('y')
        if op == 0xED:
            return self._exec_ed()
        if op == 0xCB:
            d = self.fetch8()
            d = d - 256 if d >= 128 else d
            addr = ((self.ix if ixm == 'x' else self.iy) + d) & 0xFFFF
            return self._exec_cb(addr)
        return self._exec_main(op, ixm, 0)

    def _exec_cb(self, ixaddr=None):
        op = self.fetch8()
        if ixaddr is None:
            self.r = (self.r & 0x80) | ((self.r + 1) & 0x7F)
        x = op >> 6
        y = (op >> 3) & 7
        z = op & 7
        if ixaddr is not None:
            v = self.rd8(ixaddr)
            cyc = 20 if x == 1 else 23
        else:
            v = self.get_r(z, None, self.hl)
            cyc = (12 if x == 1 else 15) if z == 6 else 8
        if x == 0:
            r = self.rot(y, v)
        elif x == 1:
            bit = v & (1 << y)
            f = (self.f & C) | H | (Z | PV if bit == 0 else 0) | (S if (y == 7 and bit) else 0)
            if ixaddr is not None:
                f |= (ixaddr >> 8) & (Y | X)
            else:
                f |= v & (Y | X)
            self.f = f
            return cyc
        elif x == 2:
            r = v & ~(1 << y)
        else:
            r = v | (1 << y)
        if ixaddr is not None:
            self.wr8(ixaddr, r)
            if z != 6:
                self.set_r(z, r)
        else:
            self.set_r(z, r, None, self.hl)
        return cyc

    def _exec_ed(self):
        op = self.fetch8()
        self.r = (self.r & 0x80) | ((self.r + 1) & 0x7F)
        x = op >> 6
        y = (op >> 3) & 7
        z = op & 7
        p = y >> 1
        q = y & 1
        if x == 1:
            if z == 0:
                v = self.io_in(self.bc)
                if y != 6:
                    self.set_r(y, v)
                self.f = (self.f & C) | SZP[v]
                return 12
            if z == 1:
                self.io_out(self.bc, 0 if y == 6 else self.get_r(y))
                return 12
            if z == 2:
                hl = self.hl
                rp = self.get_rp(p)
                self.hl = self.sbc16(hl, rp) if q == 0 else self.adc16(hl, rp)
                return 15
            if z == 3:
                nn = self.fetch16()
                if q == 0:
                    self.wr16(nn, self.get_rp(p))
                else:
                    self.set_rp(p, self.rd16(nn))
                return 20
            if z == 4:  # NEG
                a = self.a
                self.a = 0
                self.alu(2, a)
                return 8
            if z == 5:  # RETN / RETI
                self.iff1 = self.iff2
                self.pc = self.pop()
                return 14
            if z == 6:
                self.im = (0, 0, 1, 2)[y & 3]
                return 8
            if z == 7:
                if y == 0: self.i = self.a; return 9
                if y == 1: self.r = self.a; return 9
                if y == 2:
                    self.a = self.i
                    self.f = (self.f & C) | SZ[self.a] | (PV if self.iff2 else 0)
                    return 9
                if y == 3:
                    self.a = self.r
                    self.f = (self.f & C) | SZ[self.a] | (PV if self.iff2 else 0)
                    return 9
                if y == 4:  # RRD
                    m = self.rd8(self.hl)
                    self.wr8(self.hl, ((self.a << 4) | (m >> 4)) & 0xFF)
                    self.a = (self.a & 0xF0) | (m & 0x0F)
                    self.f = (self.f & C) | SZP[self.a]
                    return 18
                if y == 5:  # RLD
                    m = self.rd8(self.hl)
                    self.wr8(self.hl, ((m << 4) | (self.a & 0x0F)) & 0xFF)
                    self.a = (self.a & 0xF0) | (m >> 4)
                    self.f = (self.f & C) | SZP[self.a]
                    return 18
                return 8
        if x == 2 and z <= 3 and y >= 4:
            return self._block(y, z)
        return 8  # NOP

    def _block(self, y, z):
        inc = y in (4, 6)
        rep = y >= 6
        step = 1 if inc else -1
        if z == 0:  # LDI/LDD/LDIR/LDDR
            v = self.rd8(self.hl)
            self.wr8(self.de, v)
            self.hl = (self.hl + step) & 0xFFFF
            self.de = (self.de + step) & 0xFFFF
            self.bc = (self.bc - 1) & 0xFFFF
            n = (self.a + v) & 0xFF
            f = (self.f & (S | Z | C)) | (n & X) | ((n << 4) & Y)
            if self.bc: f |= PV
            self.f = f
            if rep and self.bc:
                self.pc = (self.pc - 2) & 0xFFFF
                return 21
            return 16
        if z == 1:  # CPI/CPD/CPIR/CPDR
            v = self.rd8(self.hl)
            r = (self.a - v) & 0xFF
            hf = H if ((self.a & 0xF) - (v & 0xF)) < 0 else 0
            self.hl = (self.hl + step) & 0xFFFF
            self.bc = (self.bc - 1) & 0xFFFF
            f = (self.f & C) | (r & S) | (Z if r == 0 else 0) | hf | N
            n = r - (1 if hf else 0)
            f |= (n & X) | ((n << 4) & Y)
            if self.bc: f |= PV
            self.f = f
            if rep and self.bc and r != 0:
                self.pc = (self.pc - 2) & 0xFFFF
                return 21
            return 16
        if z == 2:  # INI/IND/INIR/INDR
            v = self.io_in(self.bc)
            self.wr8(self.hl, v)
            self.hl = (self.hl + step) & 0xFFFF
            self.b = (self.b - 1) & 0xFF
            self.f = (self.f & C) | SZ[self.b] | N
            if rep and self.b:
                self.pc = (self.pc - 2) & 0xFFFF
                return 21
            return 16
        v = self.rd8(self.hl)  # OUTI/OUTD/OTIR/OTDR
        self.b = (self.b - 1) & 0xFF
        self.io_out(self.bc, v)
        self.hl = (self.hl + step) & 0xFFFF
        self.f = (self.f & C) | SZ[self.b] | N
        if rep and self.b:
            self.pc = (self.pc - 2) & 0xFFFF
            return 21
        return 16

    def _exec_main(self, op, ixm, extra):
        x = op >> 6
        y = (op >> 3) & 7
        z = op & 7
        p = y >> 1
        q = y & 1
        # address of the memory operand for (HL) / (IX+d)
        def mem_addr():
            if ixm is None:
                return self.hl
            d = self.fetch8()
            d = d - 256 if d >= 128 else d
            return ((self.ix if ixm == 'x' else self.iy) + d) & 0xFFFF
        xtra = 8 if ixm is not None else 0

        if x == 1:
            if op == 0x76:
                self.halted = True
                self.pc = (self.pc - 1) & 0xFFFF
                return 4
            if z == 6:  # LD r,(HL)/(IX+d)
                a = mem_addr()
                self.set_r(y, self.rd8(a))
                return 7 + (12 if ixm else 0)
            if y == 6:  # LD (HL),r
                a = mem_addr()
                self.wr8(a, self.get_r(z))
                return 7 + (12 if ixm else 0)
            self.set_r(y, self.get_r(z, ixm), ixm)
            return 4
        if x == 2:
            if z == 6:
                a = mem_addr()
                self.alu(y, self.rd8(a))
                return 7 + (12 if ixm else 0)
            self.alu(y, self.get_r(z, ixm))
            return 4
        if x == 0:
            if z == 0:
                if y == 0: return 4
                if y == 1:
                    self.a, self.a_ = self.a_, self.a
                    self.f, self.f_ = self.f_, self.f
                    return 4
                d = self.fetch8()
                d = d - 256 if d >= 128 else d
                if y == 2:
                    self.b = (self.b - 1) & 0xFF
                    if self.b:
                        self.pc = (self.pc + d) & 0xFFFF
                        return 13
                    return 8
                if y == 3:
                    self.pc = (self.pc + d) & 0xFFFF
                    return 12
                if self.cond(y - 4):
                    self.pc = (self.pc + d) & 0xFFFF
                    return 12
                return 7
            if z == 1:
                if q == 0:
                    self.set_rp(p, self.fetch16(), ixm)
                    return 10
                self.set_rp(2, self.add16(self.get_rp(2, ixm), self.get_rp(p, ixm)), ixm)
                return 11
            if z == 2:
                if q == 0:
                    if p == 0: self.wr8(self.bc, self.a); return 7
                    if p == 1: self.wr8(self.de, self.a); return 7
                    nn = self.fetch16()
                    if p == 2:
                        self.wr16(nn, self.get_rp(2, ixm)); return 16
                    self.wr8(nn, self.a); return 13
                if p == 0: self.a = self.rd8(self.bc); return 7
                if p == 1: self.a = self.rd8(self.de); return 7
                nn = self.fetch16()
                if p == 2:
                    self.set_rp(2, self.rd16(nn), ixm); return 16
                self.a = self.rd8(nn); return 13
            if z == 3:
                v = self.get_rp(p, ixm)
                self.set_rp(p, v + 1 if q == 0 else v - 1, ixm)
                return 6
            if z == 4 or z == 5:
                if y == 6:
                    a = mem_addr()
                    v = self.rd8(a)
                    self.wr8(a, self.inc8(v) if z == 4 else self.dec8(v))
                    return 11 + (12 if ixm else 0)
                v = self.get_r(y, ixm)
                self.set_r(y, self.inc8(v) if z == 4 else self.dec8(v), ixm)
                return 4
            if z == 6:
                if y == 6:
                    a = mem_addr()
                    self.wr8(a, self.fetch8())
                    return 10 + (9 if ixm else 0)
                self.set_r(y, self.fetch8(), ixm)
                return 7
            # z == 7
            a = self.a
            if y == 0:
                c = a >> 7; self.a = ((a << 1) | c) & 0xFF
                self.f = (self.f & (S | Z | PV)) | c | (self.a & (Y | X))
            elif y == 1:
                c = a & 1; self.a = (a >> 1) | (c << 7)
                self.f = (self.f & (S | Z | PV)) | c | (self.a & (Y | X))
            elif y == 2:
                c = a >> 7; self.a = ((a << 1) | (self.f & C)) & 0xFF
                self.f = (self.f & (S | Z | PV)) | c | (self.a & (Y | X))
            elif y == 3:
                c = a & 1; self.a = (a >> 1) | ((self.f & C) << 7)
                self.f = (self.f & (S | Z | PV)) | c | (self.a & (Y | X))
            elif y == 4:
                self.daa()
            elif y == 5:
                self.a = a ^ 0xFF
                self.f = (self.f & (S | Z | PV | C)) | H | N | (self.a & (Y | X))
            elif y == 6:
                self.f = (self.f & (S | Z | PV)) | C | (a & (Y | X))
            else:
                c = self.f & C
                self.f = (self.f & (S | Z | PV)) | (H if c else C) | (a & (Y | X))
            return 4
        # x == 3
        if z == 0:
            if self.cond(y):
                self.pc = self.pop()
                return 11
            return 5
        if z == 1:
            if q == 0:
                self.set_rp2(p, self.pop(), ixm)
                return 10
            if p == 0:
                self.pc = self.pop(); return 10
            if p == 1:
                self.b, self.b_ = self.b_, self.b
                self.c, self.c_ = self.c_, self.c
                self.d, self.d_ = self.d_, self.d
                self.e, self.e_ = self.e_, self.e
                self.h, self.h_ = self.h_, self.h
                self.l, self.l_ = self.l_, self.l
                return 4
            if p == 2:
                self.pc = self.get_rp(2, ixm); return 4
            self.sp = self.get_rp(2, ixm); return 6
        if z == 2:
            nn = self.fetch16()
            if self.cond(y):
                self.pc = nn
            return 10
        if z == 3:
            if y == 0:
                self.pc = self.fetch16(); return 10
            if y == 2:
                n = self.fetch8()
                self.io_out((self.a << 8) | n, self.a); return 11
            if y == 3:
                n = self.fetch8()
                self.a = self.io_in((self.a << 8) | n); return 11
            if y == 4:
                lo = self.rd8(self.sp)
                hi = self.rd8((self.sp + 1) & 0xFFFF)
                v = self.get_rp(2, ixm)
                self.wr8(self.sp, v & 0xFF)
                self.wr8((self.sp + 1) & 0xFFFF, v >> 8)
                self.set_rp(2, lo | (hi << 8), ixm)
                return 19
            if y == 5:
                d, e, h, l = self.d, self.e, self.h, self.l
                self.d, self.e, self.h, self.l = h, l, d, e
                return 4
            if y == 6:
                self.iff1 = self.iff2 = 0; return 4
            self.iff1 = self.iff2 = 1
            self.ei_delay = True
            return 4
        if z == 4:
            nn = self.fetch16()
            if self.cond(y):
                self.push(self.pc)
                self.pc = nn
                return 17
            return 10
        if z == 5:
            if q == 0:
                self.push(self.get_rp2(p, ixm)); return 11
            nn = self.fetch16()
            self.push(self.pc)
            self.pc = nn
            return 17
        if z == 6:
            self.alu(y, self.fetch8())
            return 7
        self.push(self.pc)
        self.pc = y * 8
        return 11
