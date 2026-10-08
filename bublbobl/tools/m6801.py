"""Motorola MC6801 core + disassembler (reference model for the Bubble Bobble MCU).

The 6801 is a 6800 superset (16-bit D/ADDD/SUBD/LDD/STD, MUL, ABX, PSHX/PULX,
LSRD/ASLD, BRN) with on-chip ports 1-4, a free-running counter + output
compare timer and an SCI.  Only what a78-01.17 needs is modelled; accesses to
anything else are recorded in `unhandled` so gaps are visible rather than silent.

Memory model: the machine supplies rd8/wr8 for the *whole* 64 KiB space;
registers 0x00-0x1F are intercepted here.
"""

# ---- opcode tables -------------------------------------------------------
# mode: inh imm8 imm16 dir ext idx rel
ALU_A = {0x0: "suba", 0x1: "cmpa", 0x2: "sbca", 0x4: "anda", 0x5: "bita", 0x6: "ldaa",
         0x7: "staa", 0x8: "eora", 0x9: "adca", 0xA: "oraa", 0xB: "adda"}
ALU_B = {0x0: "subb", 0x1: "cmpb", 0x2: "sbcb", 0x4: "andb", 0x5: "bitb", 0x6: "ldab",
         0x7: "stab", 0x8: "eorb", 0x9: "adcb", 0xA: "orab", 0xB: "addb"}
RMW = {0x0: "neg", 0x3: "com", 0x4: "lsr", 0x6: "ror", 0x7: "asr", 0x8: "asl", 0x9: "rol",
       0xA: "dec", 0xC: "inc", 0xD: "tst", 0xE: "jmp", 0xF: "clr"}
INH = {0x01: "nop", 0x04: "lsrd", 0x05: "asld", 0x06: "tap", 0x07: "tpa", 0x08: "inx",
       0x09: "dex", 0x0A: "clv", 0x0B: "sev", 0x0C: "clc", 0x0D: "sec", 0x0E: "cli",
       0x0F: "sei", 0x10: "sba", 0x11: "cba", 0x16: "tab", 0x17: "tba", 0x19: "daa",
       0x1B: "aba", 0x30: "tsx", 0x31: "ins", 0x32: "pula", 0x33: "pulb", 0x34: "des",
       0x35: "txs", 0x36: "psha", 0x37: "pshb", 0x38: "pulx", 0x39: "rts", 0x3A: "abx",
       0x3B: "rti", 0x3C: "pshx", 0x3D: "mul", 0x3E: "wai", 0x3F: "swi"}
BRANCH = {0x20: "bra", 0x21: "brn", 0x22: "bhi", 0x23: "bls", 0x24: "bcc", 0x25: "bcs",
          0x26: "bne", 0x27: "beq", 0x28: "bvc", 0x29: "bvs", 0x2A: "bpl", 0x2B: "bmi",
          0x2C: "bge", 0x2D: "blt", 0x2E: "bgt", 0x2F: "ble"}
RMW_NAMES = ("neg", "com", "lsr", "ror", "asr", "asl", "rol", "dec", "inc", "tst", "clr")


def build_table():
    """opcode -> (mnemonic, mode)"""
    t = {}
    for op, m in INH.items():
        t[op] = (m, "inh")
    for op, m in BRANCH.items():
        t[op] = (m, "rel")
    for hi, base in ((0x4, "a"), (0x5, "b")):
        for lo, m in RMW.items():
            if m == "jmp":
                continue
            t[(hi << 4) | lo] = (m + base, "acc")
    for lo, m in RMW.items():
        t[0x60 | lo] = (m, "idx")
        t[0x70 | lo] = (m, "ext")
    for hi, tbl, d16 in ((0x8, ALU_A, {0x3: "subd", 0xC: "cpx", 0xE: "lds"}),
                         (0xC, ALU_B, {0x3: "addd", 0xC: "ldd", 0xE: "ldx"})):
        for lo, m in tbl.items():
            if m.startswith("st"):
                continue
            t[(hi << 4) | lo] = (m, "imm8")
        for lo, m in d16.items():
            t[(hi << 4) | lo] = (m, "imm16")
    t[0x8D] = ("bsr", "rel")
    for hi, mode in ((0x9, "dir"), (0xA, "idx"), (0xB, "ext")):
        for lo, m in ALU_A.items():
            t[(hi << 4) | lo] = (m, mode)
        for lo, m in {0x3: "subd", 0xC: "cpx", 0xE: "lds", 0xF: "sts", 0xD: "jsr"}.items():
            t[(hi << 4) | lo] = (m, mode)
    for hi, mode in ((0xD, "dir"), (0xE, "idx"), (0xF, "ext")):
        for lo, m in ALU_B.items():
            t[(hi << 4) | lo] = (m, mode)
        for lo, m in {0x3: "addd", 0xC: "ldd", 0xD: "std", 0xE: "ldx", 0xF: "stx"}.items():
            t[(hi << 4) | lo] = (m, mode)
    return t


OPS = build_table()
LEN = {"inh": 1, "acc": 1, "imm8": 2, "imm16": 3, "dir": 2, "ext": 3, "idx": 2, "rel": 2}


def disasm(rd, pc):
    """-> (length, text, branch/call target or None, mnemonic)"""
    op = rd(pc)
    if op not in OPS:
        return 1, "db $%02X" % op, None, "db"
    m, mode = OPS[op]
    n = LEN[mode]
    b1 = rd(pc + 1) if n > 1 else 0
    w = (rd(pc + 1) << 8 | rd(pc + 2)) if n > 2 else 0
    tgt = None
    if mode in ("inh", "acc"):
        s = m
    elif mode == "imm8":
        s = "%s #$%02X" % (m, b1)
    elif mode == "imm16":
        s = "%s #$%04X" % (m, w)
    elif mode == "dir":
        s = "%s $%02X" % (m, b1)
    elif mode == "ext":
        s = "%s $%04X" % (m, w)
        if m in ("jsr", "jmp"):
            tgt = w
    elif mode == "idx":
        s = "%s $%02X,x" % (m, b1)
    else:
        off = b1 - 256 if b1 >= 128 else b1
        tgt = (pc + 2 + off) & 0xFFFF
        s = "%s $%04X" % (m, tgt)
    return n, s, tgt, m


# ---- cycle counts (E-clock cycles; MC6801 datasheet, close enough for timers) ----
def cycles_for(op):
    m, mode = OPS[op]
    if mode == "inh":
        return {"lsrd": 3, "asld": 3, "inx": 3, "dex": 3, "tsx": 3, "ins": 3, "des": 3, "txs": 3,
                "pula": 4, "pulb": 4, "psha": 3, "pshb": 3, "pulx": 5, "rts": 5, "abx": 3,
                "rti": 10, "pshx": 4, "mul": 10, "wai": 9, "swi": 12}.get(m, 2)
    if mode == "acc":
        return 2
    if mode == "rel":
        return 6 if m == "bsr" else 3
    d16 = m in ("subd", "addd", "ldd", "std", "ldx", "stx", "cpx", "lds", "sts")
    store = m in ("staa", "stab", "std", "stx", "sts")
    if mode == "imm8":
        return 2
    if mode == "imm16":
        return 4 if m in ("subd", "addd", "cpx") else 3
    if mode == "dir":
        if m == "jsr":
            return 5
        return 3 + (1 if d16 else 0)
    if mode == "idx":
        if m == "jsr":
            return 5
        if m == "jmp":
            return 3
        if m in RMW_NAMES and m != "tst":
            return 6
        if m == "tst":
            return 4
        return 4 + (1 if d16 else 0)
    if mode == "ext":
        if m == "jsr":
            return 6
        if m == "jmp":
            return 3
        if m in RMW_NAMES:
            return 6
        return 4 + (1 if (d16 or store) else 0)
    return 4


CYC = {op: cycles_for(op) for op in OPS}

H, I, N, Z, V, C = 0x20, 0x10, 0x08, 0x04, 0x02, 0x01


class M6801:
    def __init__(self, rd8, wr8):
        self.rd8 = rd8
        self.wr8 = wr8
        # on-chip I/O hooks: port_in[n]() -> pin levels; port_out[n](value, ddr)
        self.port_in = {1: lambda: 0xFF, 2: lambda: 0xFF, 3: lambda: 0xFF, 4: lambda: 0xFF}
        self.port_out = {}
        self.unhandled = {}
        self.irq_line = False
        self.reset()

    def reset(self):
        self.a = self.b = 0
        self.x = 0
        self.sp = 0
        self.cc = 0xD0          # 11I00000
        self.cycles = 0
        self.frc = 0
        self.ocr = 0xFFFF
        self.tcsr = 0
        self.tcsr_read = False   # TCSR read since OCF/TOF set (arms the clearing sequence)
        self.p3csr = 0
        self.frc_lo_latch = 0
        self.waiting = False
        self.ddr = {1: 0, 2: 0, 3: 0, 4: 0}
        self.pout = {1: 0, 2: 0, 3: 0, 4: 0}
        self.pc = (self.rd8(0xFFFE) << 8) | self.rd8(0xFFFF)

    # ---- bus with on-chip registers ------------------------------------
    def rd(self, a):
        a &= 0xFFFF
        if a >= 0x20:
            return self.rd8(a)
        if a in (0, 1, 4, 5):
            return 0xFF  # DDRs are write-only
        if a in (2, 3, 6, 7):
            p = {2: 1, 3: 2, 6: 3, 7: 4}[a]
            d = self.ddr[p]
            return (self.pout[p] & d) | (self.port_in[p]() & ~d & 0xFF)
        if a == 8:
            self.tcsr_read = True
            return self.tcsr
        if a == 9:
            self.frc_lo_latch = self.frc & 0xFF
            if self.tcsr_read:
                self.tcsr &= ~0x20      # TOF cleared by TCSR read + FRC high read
            return self.frc >> 8
        if a == 0x0A:
            return self.frc_lo_latch
        if a == 0x0B:
            return self.ocr >> 8
        if a == 0x0C:
            return self.ocr & 0xFF
        if a == 0x0F:
            return self.p3csr
        self.unhandled[("r", a)] = self.unhandled.get(("r", a), 0) + 1
        return 0

    def wr(self, a, v):
        a &= 0xFFFF
        v &= 0xFF
        if a >= 0x20:
            return self.wr8(a, v)
        if a in (0, 1, 4, 5):
            p = {0: 1, 1: 2, 4: 3, 5: 4}[a]
            self.ddr[p] = v
            self._port_changed(p)
        elif a in (2, 3, 6, 7):
            p = {2: 1, 3: 2, 6: 3, 7: 4}[a]
            self.pout[p] = v
            self._port_changed(p)
        elif a == 8:
            self.tcsr = (self.tcsr & 0xE0) | (v & 0x1F)
        elif a == 0x0B:
            self.ocr = (v << 8) | (self.ocr & 0xFF)
            if self.tcsr_read:
                self.tcsr &= ~0x40
        elif a == 0x0C:
            self.ocr = (self.ocr & 0xFF00) | v
            if self.tcsr_read:
                self.tcsr &= ~0x40
        elif a == 0x0F:
            self.p3csr = v
        else:
            self.unhandled[("w", a, v)] = self.unhandled.get(("w", a, v), 0) + 1

    def _port_changed(self, p):
        f = self.port_out.get(p)
        if f:
            f(self.pout[p] & self.ddr[p], self.ddr[p])

    # ---- stack / fetch ----------------------------------------------------
    def fetch(self):
        v = self.rd(self.pc)
        self.pc = (self.pc + 1) & 0xFFFF
        return v

    def fetch16(self):
        h = self.fetch()
        return (h << 8) | self.fetch()

    def push8(self, v):
        self.wr(self.sp, v)
        self.sp = (self.sp - 1) & 0xFFFF

    def pull8(self):
        self.sp = (self.sp + 1) & 0xFFFF
        return self.rd(self.sp)

    def push16(self, v):
        self.push8(v & 0xFF)
        self.push8(v >> 8)

    def pull16(self):
        h = self.pull8()
        return (h << 8) | self.pull8()

    @property
    def d(self):
        return (self.a << 8) | self.b

    @d.setter
    def d(self, v):
        self.a = (v >> 8) & 0xFF
        self.b = v & 0xFF

    # ---- flag helpers ------------------------------------------------------
    def setnz8(self, r):
        self.cc = (self.cc & ~(N | Z)) | (N if r & 0x80 else 0) | (Z if (r & 0xFF) == 0 else 0)

    def setnz16(self, r):
        self.cc = (self.cc & ~(N | Z)) | (N if r & 0x8000 else 0) | (Z if (r & 0xFFFF) == 0 else 0)

    def setv(self, f):
        self.cc = (self.cc & ~V) | (V if f else 0)

    def setc(self, f):
        self.cc = (self.cc & ~C) | (C if f else 0)

    def nxc(self):
        """V = N xor C (shift/rotate)."""
        self.setv(((self.cc & N) != 0) != ((self.cc & C) != 0))

    def add8(self, a, b, c=0):
        r = a + b + c
        if ((a & 0xF) + (b & 0xF) + c) > 0xF:
            self.cc |= H
        else:
            self.cc &= ~H
        self.setnz8(r)
        self.setv(((a ^ r) & (b ^ r) & 0x80) != 0)
        self.setc(r > 0xFF)
        return r & 0xFF

    def sub8(self, a, b, c=0):
        r = a - b - c
        self.setnz8(r)
        self.setv(((a ^ b) & (a ^ r) & 0x80) != 0)
        self.setc(r < 0)
        return r & 0xFF

    def sub16(self, a, b):
        r = a - b
        self.setnz16(r)
        self.setv(((a ^ b) & (a ^ r) & 0x8000) != 0)
        self.setc(r < 0)
        return r & 0xFFFF

    def add16(self, a, b):
        r = a + b
        self.setnz16(r)
        self.setv(((a ^ r) & (b ^ r) & 0x8000) != 0)
        self.setc(r > 0xFFFF)
        return r & 0xFFFF

    def logic(self, r):
        r &= 0xFF
        self.setnz8(r)
        self.setv(False)
        return r

    # ---- read-modify-write ------------------------------------------------------
    def rmw(self, m, v):
        """returns new value, or None when there is no write-back (tst)."""
        if m == "neg":
            r = self.sub8(0, v)
            return r
        if m == "com":
            r = (~v) & 0xFF
            self.setnz8(r)
            self.setv(False)
            self.setc(True)
            return r
        if m == "lsr":
            self.setc(v & 1)
            r = v >> 1
            self.setnz8(r)
            self.nxc()
            return r
        if m == "ror":
            c = self.cc & C
            self.setc(v & 1)
            r = (v >> 1) | (0x80 if c else 0)
            self.setnz8(r)
            self.nxc()
            return r
        if m == "asr":
            self.setc(v & 1)
            r = (v >> 1) | (v & 0x80)
            self.setnz8(r)
            self.nxc()
            return r
        if m == "asl":
            self.setc(v & 0x80)
            r = (v << 1) & 0xFF
            self.setnz8(r)
            self.nxc()
            return r
        if m == "rol":
            c = self.cc & C
            self.setc(v & 0x80)
            r = ((v << 1) | (1 if c else 0)) & 0xFF
            self.setnz8(r)
            self.nxc()
            return r
        if m == "dec":
            r = (v - 1) & 0xFF
            self.setnz8(r)
            self.setv(v == 0x80)
            return r
        if m == "inc":
            r = (v + 1) & 0xFF
            self.setnz8(r)
            self.setv(v == 0x7F)
            return r
        if m == "tst":
            self.setnz8(v)
            self.setv(False)
            self.setc(False)
            return None
        if m == "clr":
            self.cc = (self.cc & ~(N | V | C)) | Z
            return 0
        raise ValueError(m)

    def cond(self, m):
        c = self.cc
        n = bool(c & N); z = bool(c & Z); v = bool(c & V); cy = bool(c & C)
        return {"bra": True, "brn": False, "bhi": not (cy or z), "bls": cy or z,
                "bcc": not cy, "bcs": cy, "bne": not z, "beq": z, "bvc": not v, "bvs": v,
                "bpl": not n, "bmi": n, "bge": n == v, "blt": n != v,
                "bgt": (not z) and n == v, "ble": z or n != v}[m]

    # ---- interrupts / timers ----------------------------------------------------
    def _stack_regs(self):
        self.push16(self.pc)
        self.push16(self.x)
        self.push8(self.a)
        self.push8(self.b)
        self.push8(self.cc)

    def _service(self, vec):
        self._stack_regs()
        self.cc |= I
        self.pc = (self.rd8(vec) << 8) | self.rd8(vec + 1)
        self._tick(12)

    def _tick(self, n):
        self.cycles += n
        old = self.frc
        new = old + n
        self.frc = new & 0xFFFF
        # output compare: FRC passed OCR (match when FRC == OCR after increment)
        if ((self.ocr - old - 1) & 0xFFFF) < n:
            self.tcsr |= 0x40
            self.tcsr_read = False
        if new > 0xFFFF:
            self.tcsr |= 0x20

    def check_interrupts(self):
        if self.cc & I:
            return False
        if self.irq_line:
            self.irq_line = False        # hold-line: cleared when taken
            self.waiting = False
            self._service(0xFFF8)
            return True
        if (self.tcsr & 0x40) and (self.tcsr & 0x08):
            self.waiting = False
            self._service(0xFFF4)
            return True
        if (self.tcsr & 0x20) and (self.tcsr & 0x04):
            self.waiting = False
            self._service(0xFFF2)
            return True
        return False

    # ---- execute ----------------------------------------------------------------------
    def step(self):
        """Execute one instruction (or idle/service an interrupt)."""
        if self.waiting:
            if not self.check_interrupts():
                self._tick(4)
            return
        if self.check_interrupts():
            return
        pc0 = self.pc
        op = self.fetch()
        if op not in OPS:
            raise RuntimeError("6801: illegal opcode %02X at %04X" % (op, pc0))
        m, mode = OPS[op]
        self._tick(CYC[op])
        if mode == "inh":
            return self._inh(m)
        if mode == "rel":
            off = self.fetch()
            off = off - 256 if off >= 128 else off
            if m == "bsr":
                self.push16(self.pc)
                self.pc = (self.pc + off) & 0xFFFF
            elif self.cond(m):
                self.pc = (self.pc + off) & 0xFFFF
            return
        if mode == "acc":
            reg = "a" if op < 0x50 else "b"
            r = self.rmw(m[:-1], getattr(self, reg))
            if r is not None:
                setattr(self, reg, r)
            return
        if mode == "imm8":
            return self._alu(m, self.fetch())
        if mode == "imm16":
            return self._alu16(m, self.fetch16())
        if mode == "dir":
            addr = self.fetch()
        elif mode == "ext":
            addr = self.fetch16()
        else:
            addr = (self.x + self.fetch()) & 0xFFFF
        if m in RMW_NAMES:
            r = self.rmw(m, 0 if m == "clr" else self.rd(addr))
            if r is not None:
                self.wr(addr, r)
            return
        if m == "jmp":
            self.pc = addr
            return
        if m == "jsr":
            self.push16(self.pc)
            self.pc = addr
            return
        if m in ("staa", "stab"):
            v = self.a if m == "staa" else self.b
            self.logic(v)
            self.wr(addr, v)
            return
        if m in ("std", "stx", "sts"):
            v = {"std": self.d, "stx": self.x, "sts": self.sp}[m]
            self.setnz16(v)
            self.setv(False)
            self.wr(addr, v >> 8)
            self.wr(addr + 1, v & 0xFF)
            return
        if m in ("subd", "addd", "ldd", "ldx", "lds", "cpx"):
            return self._alu16(m, (self.rd(addr) << 8) | self.rd(addr + 1))
        return self._alu(m, self.rd(addr))

    def _alu(self, m, val):
        reg = "a" if m[-1] == "a" else "b"
        cur = getattr(self, reg)
        base = m[:-1]
        if base == "sub":
            r = self.sub8(cur, val)
        elif base == "cmp":
            self.sub8(cur, val)
            return
        elif base == "sbc":
            r = self.sub8(cur, val, self.cc & C)
        elif base == "and":
            r = self.logic(cur & val)
        elif base == "bit":
            self.logic(cur & val)
            return
        elif base == "lda":
            r = self.logic(val)
        elif base == "eor":
            r = self.logic(cur ^ val)
        elif base == "adc":
            r = self.add8(cur, val, self.cc & C)
        elif base == "ora":
            r = self.logic(cur | val)
        elif base == "add":
            r = self.add8(cur, val)
        else:
            raise ValueError(m)
        setattr(self, reg, r)

    def _alu16(self, m, val):
        if m == "subd":
            self.d = self.sub16(self.d, val)
        elif m == "addd":
            self.d = self.add16(self.d, val)
        elif m == "ldd":
            self.d = val
            self.setnz16(val)
            self.setv(False)
        elif m == "ldx":
            self.x = val
            self.setnz16(val)
            self.setv(False)
        elif m == "lds":
            self.sp = val
            self.setnz16(val)
            self.setv(False)
        elif m == "cpx":
            c = self.cc & C
            self.sub16(self.x, val)
            self.cc = (self.cc & ~C) | c        # CPX leaves C untouched (6800 behaviour)
        else:
            raise ValueError(m)

    def _inh(self, m):
        if m == "nop":
            pass
        elif m == "lsrd":
            self.setc(self.d & 1)
            r = self.d >> 1
            self.d = r
            self.setnz16(r)
            self.nxc()
        elif m == "asld":
            self.setc(self.d & 0x8000)
            r = (self.d << 1) & 0xFFFF
            self.d = r
            self.setnz16(r)
            self.nxc()
        elif m == "tap":
            self.cc = self.a | 0xC0
        elif m == "tpa":
            self.a = self.cc | 0xC0
        elif m == "inx":
            self.x = (self.x + 1) & 0xFFFF
            self.cc = (self.cc & ~Z) | (Z if self.x == 0 else 0)
        elif m == "dex":
            self.x = (self.x - 1) & 0xFFFF
            self.cc = (self.cc & ~Z) | (Z if self.x == 0 else 0)
        elif m == "clv":
            self.cc &= ~V
        elif m == "sev":
            self.cc |= V
        elif m == "clc":
            self.cc &= ~C
        elif m == "sec":
            self.cc |= C
        elif m == "cli":
            self.cc &= ~I
        elif m == "sei":
            self.cc |= I
        elif m == "sba":
            self.a = self.sub8(self.a, self.b)
        elif m == "cba":
            self.sub8(self.a, self.b)
        elif m == "tab":
            self.b = self.logic(self.a)
        elif m == "tba":
            self.a = self.logic(self.b)
        elif m == "aba":
            self.a = self.add8(self.a, self.b)
        elif m == "daa":
            self._daa()
        elif m == "tsx":
            self.x = (self.sp + 1) & 0xFFFF
        elif m == "txs":
            self.sp = (self.x - 1) & 0xFFFF
        elif m == "ins":
            self.sp = (self.sp + 1) & 0xFFFF
        elif m == "des":
            self.sp = (self.sp - 1) & 0xFFFF
        elif m == "pula":
            self.a = self.pull8()
        elif m == "pulb":
            self.b = self.pull8()
        elif m == "psha":
            self.push8(self.a)
        elif m == "pshb":
            self.push8(self.b)
        elif m == "pulx":
            self.x = self.pull16()
        elif m == "pshx":
            self.push16(self.x)
        elif m == "rts":
            self.pc = self.pull16()
        elif m == "abx":
            self.x = (self.x + self.b) & 0xFFFF
        elif m == "rti":
            self.cc = self.pull8() | 0xC0
            self.b = self.pull8()
            self.a = self.pull8()
            self.x = self.pull16()
            self.pc = self.pull16()
        elif m == "mul":
            r = self.a * self.b
            self.d = r
            self.setc(r & 0x80)
        elif m == "wai":
            self._stack_regs()
            self.waiting = True
        elif m == "swi":
            self._stack_regs()
            self.cc |= I
            self.pc = (self.rd8(0xFFFA) << 8) | self.rd8(0xFFFB)
        else:
            raise ValueError(m)

    def _daa(self):
        a = self.a
        hi, lo = a >> 4, a & 0xF
        corr = 0
        if (self.cc & H) or lo > 9:
            corr |= 0x06
        if (self.cc & C) or hi > 9 or (hi > 8 and lo > 9):
            corr |= 0x60
        r = a + corr
        c = (self.cc & C) or r > 0xFF
        self.a = r & 0xFF
        self.setnz8(self.a)
        self.setc(c)
