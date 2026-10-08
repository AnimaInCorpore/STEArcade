"""Motorola MC6801 (M6801U4 as used on Bubble Bobble) reference interpreter.

Single chip mode: internal registers $00-$1F, RAM $40-$FF, the 4 KB ROM at $F000.
Just what the protection program needs: the instruction set of the 6801 (6800 plus
ABX ADDD SUBD LDD STD CPX LSRD ASLD MUL PSHX PULX BRN, JSR direct), ports 1-4,
the free running counter with output compare, IRQ1 (level) and OCI.
"""

N, Z, V, C, I, H = 0x08, 0x04, 0x02, 0x01, 0x10, 0x20


class M6801:
    def __init__(self, rom, in_p1=None, in_p3=None, out_p1=None, out_p2=None, out_p3=None, out_p4=None):
        self.rom = rom                       # bytes, mapped at $F000
        self.ram = bytearray(256)            # $40-$FF used
        self.reg = bytearray(0x20)
        self.in_p1, self.in_p3 = in_p1, in_p3
        self.out = [out_p1, out_p2, out_p3, out_p4]
        self.ddr = [0, 0, 0, 0]
        self.data = [0, 0, 0, 0]
        self.a = self.b = 0
        self.x = 0
        self.sp = 0
        self.cc = 0xD0
        self.cycles = 0
        self.counter = 0
        self.ocr = 0xFFFF
        self.tcsr = 0
        self.tcsr_read = False
        self.irq1 = False
        self.p3csr = 0
        self.wai = False
        self.held = False                    # in reset
        self.reset()

    def reset(self):
        self.ddr = [0, 0, 0, 0]
        self.data = [0, 0, 0, 0]
        self.tcsr = 0
        self.counter = 0
        self.ocr = 0xFFFF
        self.p3csr = 0
        self.cc = 0xD0
        self.wai = False
        self.pc = self.rd16(0xFFFE)

    # ---- memory --------------------------------------------------------
    def rd(self, a):
        a &= 0xFFFF
        if a < 0x20:
            return self.rd_reg(a)
        if 0x40 <= a < 0x100:
            return self.ram[a]
        if a >= 0xF000:
            return self.rom[a - 0xF000]
        return 0xFF

    def wr(self, a, v):
        a &= 0xFFFF
        v &= 0xFF
        if a < 0x20:
            self.wr_reg(a, v)
        elif 0x40 <= a < 0x100:
            self.ram[a] = v

    def rd16(self, a):
        return (self.rd(a) << 8) | self.rd(a + 1)

    def wr16(self, a, v):
        self.wr(a, v >> 8)
        self.wr(a + 1, v)

    def port_in(self, p):
        if p == 0 and self.in_p1:
            inp = self.in_p1()
        elif p == 2 and self.in_p3:
            inp = self.in_p3()
        else:
            inp = 0xFF
        return (self.data[p] & self.ddr[p]) | (inp & ~self.ddr[p] & 0xFF)

    def port_out(self, p):
        cb = self.out[p]
        if cb:
            d, dd = self.data[p], self.ddr[p]
            cb(d if dd == 0xFF else ((d & dd) | (dd ^ 0xFF)))

    def rd_reg(self, a):
        if a == 0x02:
            return self.port_in(0)
        if a == 0x03:
            return (self.data[1] & self.ddr[1]) | (0xFF & ~self.ddr[1] & 0xFF)
        if a == 0x06:
            self.p3csr &= 0x3F                      # reading P3 clears IS3
            return self.port_in(2)
        if a == 0x07:
            return (self.data[3] & self.ddr[3]) | (0xFF & ~self.ddr[3] & 0xFF)
        if a == 0x08:
            self.tcsr_read = True
            return self.tcsr
        if a == 0x09:
            return (self.counter >> 8) & 0xFF
        if a == 0x0A:
            return self.counter & 0xFF
        if a == 0x0F:
            return self.p3csr
        return self.reg[a]

    def wr_reg(self, a, v):
        self.reg[a] = v
        if a == 0x00: self.ddr[0] = v
        elif a == 0x01: self.ddr[1] = v
        elif a == 0x04: self.ddr[2] = v
        elif a == 0x05: self.ddr[3] = v
        elif a == 0x02: self.data[0] = v; self.port_out(0)
        elif a == 0x03: self.data[1] = v; self.port_out(1)
        elif a == 0x06: self.data[2] = v; self.port_out(2)
        elif a == 0x07: self.data[3] = v; self.port_out(3)
        elif a == 0x08:
            self.tcsr = (self.tcsr & 0xE0) | (v & 0x1F)
        elif a == 0x0B:
            self.ocr = (self.ocr & 0x00FF) | (v << 8)
            if self.tcsr_read: self.tcsr &= ~0x40
        elif a == 0x0C:
            self.ocr = (self.ocr & 0xFF00) | v
            if self.tcsr_read: self.tcsr &= ~0x40
        elif a == 0x0F:
            self.p3csr = (self.p3csr & 0xC0) | (v & 0x3F)

    def pulse_is3(self):
        self.p3csr |= 0x80

    # ---- stack / flags -------------------------------------------------
    def push(self, v):
        self.wr(self.sp, v)
        self.sp = (self.sp - 1) & 0xFFFF

    def pull(self):
        self.sp = (self.sp + 1) & 0xFFFF
        return self.rd(self.sp)

    def fetch(self):
        v = self.rd(self.pc)
        self.pc = (self.pc + 1) & 0xFFFF
        return v

    def fetch16(self):
        v = self.rd16(self.pc)
        self.pc = (self.pc + 2) & 0xFFFF
        return v

    def setnz8(self, r):
        self.cc = (self.cc & ~(N | Z)) | (N if r & 0x80 else 0) | (Z if (r & 0xFF) == 0 else 0)

    def setnz16(self, r):
        self.cc = (self.cc & ~(N | Z)) | (N if r & 0x8000 else 0) | (Z if (r & 0xFFFF) == 0 else 0)

    def flag(self, f, c):
        self.cc = (self.cc | f) if c else (self.cc & ~f)

    def add8(self, x, y, c=0, sub=False):
        if sub:
            r = x - y - c
            self.flag(C, r < 0)
            self.flag(V, ((x ^ y) & (x ^ r) & 0x80) != 0)
        else:
            r = x + y + c
            self.flag(C, r > 0xFF)
            self.flag(V, (~(x ^ y) & (x ^ r) & 0x80) != 0)
            self.flag(H, ((x & 15) + (y & 15) + c) > 15)
        r &= 0xFF
        self.setnz8(r)
        return r

    def add16(self, x, y, sub=False):
        if sub:
            r = x - y
            self.flag(C, r < 0)
            self.flag(V, ((x ^ y) & (x ^ r) & 0x8000) != 0)
        else:
            r = x + y
            self.flag(C, r > 0xFFFF)
            self.flag(V, (~(x ^ y) & (x ^ r) & 0x8000) != 0)
        r &= 0xFFFF
        self.setnz16(r)
        return r

    def logic(self, r):
        self.setnz8(r)
        self.flag(V, False)
        return r & 0xFF

    # ---- interrupts ----------------------------------------------------
    def take(self, vec):
        for v in (self.pc & 0xFF, self.pc >> 8, self.x & 0xFF, self.x >> 8, self.a, self.b, self.cc):
            self.push(v)
        self.cc |= I
        self.pc = self.rd16(vec)
        self.wai = False
        self.tick(12)

    def tick(self, n):
        self.cycles += n
        old = self.counter
        self.counter = (self.counter + n) & 0xFFFF
        # output compare: match when the counter passes the OCR value
        d = (self.ocr - old) & 0xFFFF
        if 0 < d <= n or (d == 0 and n == 0x10000):
            self.tcsr |= 0x40
        if self.counter < old:
            self.tcsr |= 0x20

    def check_irq(self):
        if self.cc & I:
            return
        if self.irq1:
            self.take(0xFFF8)
        elif (self.tcsr & 0x40) and (self.tcsr & 0x08):
            self.take(0xFFF4)
        elif (self.tcsr & 0x20) and (self.tcsr & 0x04):
            self.take(0xFFF2)

    # ---- execution -----------------------------------------------------
    def ea(self, mode, size=1):
        if mode == 0:                        # immediate: address of operand
            a = self.pc
            self.pc += size
            return a
        if mode == 1:
            return self.fetch()
        if mode == 2:
            return (self.x + self.fetch()) & 0xFFFF
        return self.fetch16()

    def run(self, cycles):
        end = self.cycles + cycles
        while self.cycles < end:
            if self.wai:
                self.tick(4)
                self.check_irq()
                continue
            self.check_irq()
            self.step()

    def step(self):
        op = self.fetch()
        n0 = self.cycles
        self._exec(op)
        if self.cycles == n0:
            self.tick(4)

    def alu8(self, op, v, b):
        """accumulator ops 0x80-0xBF (A) / 0xC0-0xFF (B): returns new register or None"""
        k = op & 0x0F
        r = self.b if b else self.a
        if k == 0: return self.add8(r, v, 0, True)
        if k == 1: self.add8(r, v, 0, True); return None
        if k == 2: return self.add8(r, v, self.cc & C, True)
        if k == 4: return self.logic(r & v)
        if k == 5: self.logic(r & v); return None
        if k == 6: return self.logic(v)
        if k == 8: return self.logic(r ^ v)
        if k == 9: return self.add8(r, v, self.cc & C)
        if k == 0xA: return self.logic(r | v)
        if k == 0xB: return self.add8(r, v)
        raise ValueError(op)

    def unary(self, k, v):
        """0x40-0x4F style read-modify-write; returns new value or None (TST)"""
        if k == 0:                           # NEG
            r = (0 - v) & 0xFF
            self.setnz8(r); self.flag(V, v == 0x80); self.flag(C, v != 0)
        elif k == 3:                         # COM
            r = ~v & 0xFF
            self.setnz8(r); self.flag(V, False); self.flag(C, True)
        elif k == 4:                         # LSR
            r = v >> 1
            self.setnz8(r); self.flag(C, v & 1); self.flag(V, bool(v & 1))     # N = 0: V = C
        elif k == 6:                         # ROR
            r = (v >> 1) | (0x80 if self.cc & C else 0)
            self.setnz8(r); self.flag(C, v & 1); self.flag(V, bool(self.cc & N) != bool(self.cc & C))
        elif k == 7:                         # ASR
            r = (v >> 1) | (v & 0x80)
            self.setnz8(r); self.flag(C, v & 1); self.flag(V, bool(self.cc & N) != bool(self.cc & C))
        elif k == 8:                         # ASL
            r = (v << 1) & 0xFF
            self.setnz8(r); self.flag(C, v & 0x80); self.flag(V, bool(self.cc & N) != bool(self.cc & C))
        elif k == 9:                         # ROL
            r = ((v << 1) | (1 if self.cc & C else 0)) & 0xFF
            self.setnz8(r); self.flag(C, v & 0x80); self.flag(V, bool(self.cc & N) != bool(self.cc & C))
        elif k == 0xA:                       # DEC
            r = (v - 1) & 0xFF
            self.setnz8(r); self.flag(V, v == 0x80)
        elif k == 0xC:                       # INC
            r = (v + 1) & 0xFF
            self.setnz8(r); self.flag(V, v == 0x7F)
        elif k == 0xD:                       # TST
            self.setnz8(v); self.flag(V, False); self.flag(C, False)
            return None
        elif k == 0xF:                       # CLR
            r = 0
            self.cc = (self.cc & ~(N | V | C)) | Z
        else:
            raise ValueError("unary %x" % k)
        return r

    def branch(self, cond):
        d = self.fetch()
        if d & 0x80:
            d -= 256
        if cond:
            self.pc = (self.pc + d) & 0xFFFF
        self.tick(3)

    def cond(self, k):
        c, z, n, v = bool(self.cc & C), bool(self.cc & Z), bool(self.cc & N), bool(self.cc & V)
        return [True, False, not (c or z), c or z, not c, c, not z, z, not v, v, not n, n,
                n == v, n != v, (not z) and n == v, z or n != v][k]

    def _exec(self, op):
        hi = op >> 4
        if op < 0x20:
            self.inherent(op)
        elif hi == 2:
            self.branch(self.cond(op & 15))
        elif hi == 3:
            self.inherent3(op)
        elif hi in (4, 5):
            b = hi == 5
            k = op & 15
            v = self.b if b else self.a
            r = self.unary(k, v)
            if r is not None:
                if b: self.b = r
                else: self.a = r
            self.tick(2)
        elif hi in (6, 7):
            k = op & 15
            if k == 0xE:                     # JMP
                self.pc = self.ea(2 if hi == 6 else 3)
                self.tick(3)
                return
            a = self.ea(2 if hi == 6 else 3)
            r = self.unary(k, self.rd(a))
            if r is not None:
                self.wr(a, r)
            self.tick(6)
        else:
            self.ops8(op)

    def inherent(self, op):
        if op == 0x01: pass
        elif op == 0x04:                     # LSRD
            d = (self.a << 8) | self.b
            self.flag(C, d & 1); d >>= 1
            self.a, self.b = d >> 8, d & 0xFF
            self.setnz16(d); self.flag(V, bool(self.cc & C))
        elif op == 0x05:                     # ASLD
            d = (self.a << 8) | self.b
            self.flag(C, d & 0x8000); d = (d << 1) & 0xFFFF
            self.a, self.b = d >> 8, d & 0xFF
            self.setnz16(d); self.flag(V, bool(self.cc & N) != bool(self.cc & C))
        elif op == 0x06: self.cc = self.a | 0xC0
        elif op == 0x07: self.a = self.cc | 0xC0
        elif op == 0x08: self.x = (self.x + 1) & 0xFFFF; self.flag(Z, self.x == 0)
        elif op == 0x09: self.x = (self.x - 1) & 0xFFFF; self.flag(Z, self.x == 0)
        elif op == 0x0A: self.cc &= ~V
        elif op == 0x0B: self.cc |= V
        elif op == 0x0C: self.cc &= ~C
        elif op == 0x0D: self.cc |= C
        elif op == 0x0E: self.cc &= ~I
        elif op == 0x0F: self.cc |= I
        elif op == 0x10: self.a = self.add8(self.a, self.b, 0, True)
        elif op == 0x11: self.add8(self.a, self.b, 0, True)
        elif op == 0x16: self.b = self.logic(self.a)
        elif op == 0x17: self.a = self.logic(self.b)
        elif op == 0x19:                     # DAA
            a, adj = self.a, 0
            if (self.cc & H) or (a & 0x0F) > 9: adj |= 0x06
            if (self.cc & C) or a > 0x99 or ((a & 0x0F) > 9 and (a >> 4) > 8): adj |= 0x60
            r = a + adj
            self.flag(C, (self.cc & C) or r > 0xFF)
            self.a = r & 0xFF
            self.setnz8(self.a)
        elif op == 0x1B: self.a = self.add8(self.a, self.b)
        else:
            raise ValueError("bad opcode %02x at %04x" % (op, self.pc - 1))
        self.tick(2)

    def inherent3(self, op):
        if op == 0x30: self.x = (self.sp + 1) & 0xFFFF
        elif op == 0x31: self.sp = (self.sp + 1) & 0xFFFF
        elif op == 0x32: self.a = self.pull()
        elif op == 0x33: self.b = self.pull()
        elif op == 0x34: self.sp = (self.sp - 1) & 0xFFFF
        elif op == 0x35: self.sp = (self.x - 1) & 0xFFFF
        elif op == 0x36: self.push(self.a)
        elif op == 0x37: self.push(self.b)
        elif op == 0x38:                     # PULX
            hi = self.pull(); self.x = (hi << 8) | self.pull()
        elif op == 0x39:                     # RTS
            hi = self.pull(); self.pc = (hi << 8) | self.pull()
        elif op == 0x3A: self.x = (self.x + self.b) & 0xFFFF
        elif op == 0x3B:                     # RTI
            self.cc = self.pull() | 0xC0
            self.b = self.pull(); self.a = self.pull()
            hi = self.pull(); self.x = (hi << 8) | self.pull()
            hi = self.pull(); self.pc = (hi << 8) | self.pull()
        elif op == 0x3C:                     # PSHX
            self.push(self.x & 0xFF); self.push(self.x >> 8)
        elif op == 0x3D:                     # MUL
            r = self.a * self.b
            self.a, self.b = r >> 8, r & 0xFF
            self.flag(C, r & 0x80)
        elif op == 0x3E: self.wai = True
        else:
            raise ValueError("bad opcode %02x at %04x" % (op, self.pc - 1))
        self.tick(4)

    def ops8(self, op):
        hi, k = op >> 4, op & 15
        mode = (0, 1, 2, 3)[(hi - 8) & 3]
        b = hi >= 0xC
        if op == 0x8D:                       # BSR
            d = self.fetch()
            if d & 0x80: d -= 256
            self.push(self.pc & 0xFF); self.push(self.pc >> 8)
            self.pc = (self.pc + d) & 0xFFFF
            self.tick(6); return
        if op in (0x9D, 0xAD, 0xBD):         # JSR
            a = self.ea(mode)
            self.push(self.pc & 0xFF); self.push(self.pc >> 8)
            self.pc = a
            self.tick(6); return
        if k == 3 and not b:                 # SUBD
            a = self.ea(mode, 2)
            d = self.add16((self.a << 8) | self.b, self.rd16(a), True)
            self.a, self.b = d >> 8, d & 0xFF
            self.tick(5); return
        if k == 3 and b:
            a = self.ea(mode, 2)
            d = self.add16((self.a << 8) | self.b, self.rd16(a))
            self.a, self.b = d >> 8, d & 0xFF
            self.tick(5); return
        if k == 0xC and not b:               # CPX
            a = self.ea(mode, 2)
            v = self.rd16(a)
            r = (self.x - v) & 0xFFFF
            self.setnz16(r)
            self.flag(V, ((self.x ^ v) & (self.x ^ r) & 0x8000) != 0)
            self.tick(5); return
        if k == 0xC and b:                   # LDD (CC DC EC FC)
            a = self.ea(mode, 2)
            d = self.rd16(a)
            self.a, self.b = d >> 8, d & 0xFF
            self.setnz16(d); self.flag(V, False)
            self.tick(4); return
        if k == 0xD and b:                   # STD (DD ED FD)
            a = self.ea(mode, 2)
            self.wr16(a, (self.a << 8) | self.b)
            self.setnz16((self.a << 8) | self.b); self.flag(V, False)
            self.tick(5); return
        if k == 0xE:                         # LDS / LDX
            a = self.ea(mode, 2)
            v = self.rd16(a)
            self.setnz16(v); self.flag(V, False)
            if b: self.x = v
            else: self.sp = v
            self.tick(4); return
        if k == 0xF and hi >= 9:             # STS / STX
            a = self.ea(mode, 2)
            v = self.x if b else self.sp
            self.wr16(a, v)
            self.setnz16(v); self.flag(V, False)
            self.tick(5); return
        if k == 7 and mode != 0:             # STAA / STAB
            a = self.ea(mode)
            v = self.b if b else self.a
            self.wr(a, v)
            self.logic(v)
            self.tick(4); return
        if k in (3, 7, 0xC, 0xD, 0xE, 0xF):
            raise ValueError("bad opcode %02x at %04x" % (op, self.pc - 1))
        a = self.ea(mode)
        v = self.rd(a)
        r = self.alu8(op, v, b)
        if r is not None:
            if b: self.b = r
            else: self.a = r
        self.tick(3)
