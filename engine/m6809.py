"""Motorola MC6809E reference interpreter (Namco System 1: the main, sub and sound CPUs).

The complete instruction set with all indexed modes, pages 2/3, and MAME's handling of the undocumented
opcodes (XNC XDEC XCLR XST XADD X18 XANDCC XRES XSWI2 XFIRQ; the free-run opcodes $14 $15 $CD stop with an
error). As in MAME, repeated $10/$11 prefixes keep the first page, and a byte after $10/$11 that is no page 2/3
opcode is skipped: the byte after it runs as a page 1 opcode (MAME's disassembler shows that byte instead).
Memory goes through rd(addr)/wr(addr, v) callbacks over the 64 KB space (the board does the banking).

Cycles are MAME's mc6809e core: one per bus cycle including the dummy and VMA cycles of its microcode
(base6x09.lst, m6809.lst). The dummy reads themselves are not issued (they read the opcode stream, $FFFF or the
stack); every real operand read and write is, in MAME's order (CLR reads its operand first, as MAME does).
reset() keeps CC's other bits and sets I and F, clears DP, fetches the vector at $FFFE: 4 cycles.
m6809_test.py checks all this against MAME 0.289 traces (registers, writes and cycles of every step).

Interrupts: IRQ and FIRQ are level inputs, NMI is an edge, armed only after S was first loaded (LDS, LEAS,
TFR to S). Lines are sampled before each instruction, as MAME does. CWAI pushes the entire state and waits for an
unmasked interrupt; SYNC waits for any asserted line, masked or not, and then continues (taking the interrupt if
it is unmasked). While waiting, step() returns 1 idle cycle; run() skips the rest of its slice at once.
"""

C, V, Z, N, I, H, F, E = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80
VEC_SWI3, VEC_SWI2, VEC_FIRQ, VEC_IRQ, VEC_SWI, VEC_NMI, VEC_RESET = 0xFFF2, 0xFFF4, 0xFFF6, 0xFFF8, 0xFFFA, 0xFFFC, 0xFFFE
CWAI, SYNC = 1, 2


class M6809Error(Exception):
    pass


class M6809:
    def __init__(self, rd, wr):
        self.rd, self.wr = rd, wr
        self.a = self.b = self.dp = 0
        self.x = self.y = self.u = self.s = 0
        self.pc = 0
        self.cc = 0
        self.cycles = 0
        self.ic = 0                          # cycles of the last indexed operand (postbyte included)
        self.irq_line = self.firq_line = self.nmi_line = False
        self.nmi_asserted = False
        self.lds = False                     # S was loaded: NMI armed
        self.wait = 0                        # CWAI / SYNC
        self.attn = False                    # a line asserted or waiting: step() takes the slow path
        self.end = 0                         # run()'s end cycle

    @property
    def d(self):
        return (self.a << 8) | self.b

    @d.setter
    def d(self, v):
        self.a, self.b = (v >> 8) & 0xFF, v & 0xFF

    def reset(self):
        self.nmi_asserted = False
        self.lds = False
        self.dp = 0
        self.cc |= I | F
        self.wait = 0
        self._upd()
        self.pc = (self.rd(VEC_RESET) << 8) | self.rd(VEC_RESET + 1)
        self.cycles += 4

    # ---- interrupt lines -----------------------------------------------
    def _upd(self):
        self.attn = bool(self.irq_line or self.firq_line or self.nmi_asserted or self.wait)

    def set_irq(self, state):
        self.irq_line = bool(state)
        self._upd()

    def set_firq(self, state):
        self.firq_line = bool(state)
        self._upd()

    def set_nmi(self, state):
        """The NMI pin as a level: a rising edge asserts NMI (once S was loaded)."""
        state = bool(state)
        if state and not self.nmi_line and self.lds:
            self.nmi_asserted = True
        self.nmi_line = state
        self._upd()

    def nmi(self):
        """An NMI edge (pulse)."""
        self.set_nmi(True)
        self.set_nmi(False)

    def pending(self):
        if self.nmi_asserted:
            return VEC_NMI
        if self.firq_line and not self.cc & F:
            return VEC_FIRQ
        if self.irq_line and not self.cc & I:
            return VEC_IRQ
        return 0

    def can_wake(self):
        if self.wait == SYNC:
            return self.nmi_asserted or self.firq_line or self.irq_line
        return self.pending() != 0

    # ---- stack ---------------------------------------------------------
    def push_regs(self, mask, on_s=True):
        """PSHS/PSHU order; on_s: S is the stack (bit 6 pushes U), else U (bit 6 pushes S)."""
        wr = self.wr
        sp = self.s if on_s else self.u
        if mask & 0x80:
            sp = (sp - 1) & 0xFFFF; wr(sp, self.pc & 0xFF)
            sp = (sp - 1) & 0xFFFF; wr(sp, self.pc >> 8)
        if mask & 0x40:
            o = self.u if on_s else self.s
            sp = (sp - 1) & 0xFFFF; wr(sp, o & 0xFF)
            sp = (sp - 1) & 0xFFFF; wr(sp, o >> 8)
        if mask & 0x20:
            sp = (sp - 1) & 0xFFFF; wr(sp, self.y & 0xFF)
            sp = (sp - 1) & 0xFFFF; wr(sp, self.y >> 8)
        if mask & 0x10:
            sp = (sp - 1) & 0xFFFF; wr(sp, self.x & 0xFF)
            sp = (sp - 1) & 0xFFFF; wr(sp, self.x >> 8)
        if mask & 0x08:
            sp = (sp - 1) & 0xFFFF; wr(sp, self.dp)
        if mask & 0x04:
            sp = (sp - 1) & 0xFFFF; wr(sp, self.b)
        if mask & 0x02:
            sp = (sp - 1) & 0xFFFF; wr(sp, self.a)
        if mask & 0x01:
            sp = (sp - 1) & 0xFFFF; wr(sp, self.cc)
        if on_s:
            self.s = sp
        else:
            self.u = sp

    def pull_regs(self, mask, on_s=True):
        rd = self.rd
        sp = self.s if on_s else self.u
        if mask & 0x01:
            self.cc = rd(sp); sp = (sp + 1) & 0xFFFF
        if mask & 0x02:
            self.a = rd(sp); sp = (sp + 1) & 0xFFFF
        if mask & 0x04:
            self.b = rd(sp); sp = (sp + 1) & 0xFFFF
        if mask & 0x08:
            self.dp = rd(sp); sp = (sp + 1) & 0xFFFF
        if mask & 0x10:
            self.x = (rd(sp) << 8) | rd((sp + 1) & 0xFFFF); sp = (sp + 2) & 0xFFFF
        if mask & 0x20:
            self.y = (rd(sp) << 8) | rd((sp + 1) & 0xFFFF); sp = (sp + 2) & 0xFFFF
        if mask & 0x40:
            v = (rd(sp) << 8) | rd((sp + 1) & 0xFFFF); sp = (sp + 2) & 0xFFFF
            if on_s:
                self.u = v
            else:
                self.s = v
        if mask & 0x80:
            self.pc = (rd(sp) << 8) | rd((sp + 1) & 0xFFFF); sp = (sp + 2) & 0xFFFF
        if on_s:
            self.s = sp
        else:
            self.u = sp

    def vector(self, vec):
        self.pc = (self.rd(vec) << 8) | self.rd((vec + 1) & 0xFFFF)

    # ---- execution -----------------------------------------------------
    def _slow(self):
        """Interrupts and wait states; 0 = go on with the next instruction."""
        if self.wait == SYNC:
            if self.nmi_asserted or self.firq_line or self.irq_line:
                self.wait = 0
                self._upd()
            self.cycles += 1
            return 1
        v = self.pending()
        if self.wait == CWAI:
            if not v:
                self.cycles += 1
                return 1
            self.wait = 0
            if v == VEC_NMI:
                self.nmi_asserted = False
            self.cc |= I | (F if v != VEC_IRQ else 0)
            self._upd()
            self.vector(v)
            self.cycles += 4
            return 4
        if not v:
            return 0
        if v == VEC_FIRQ:
            self.cc &= ~E
            self.push_regs(0x81)
            self.cc |= I | F
            n = 10
        else:
            if v == VEC_NMI:
                self.nmi_asserted = False
                self._upd()
            self.cc |= E
            self.push_regs(0xFF)
            self.cc |= I | (F if v == VEC_NMI else 0)
            n = 19
        self.vector(v)
        self.cycles += n
        return n

    def step(self):
        """One instruction (or one interrupt entry, or 1 idle cycle while waiting); returns its cycles."""
        if self.attn:
            n = self._slow()
            if n:
                return n
        pc = self.pc
        op = self.rd(pc)
        self.pc = (pc + 1) & 0xFFFF
        n = P1[op](self)
        self.cycles += n
        return n

    def run(self, n):
        """Runs until at least n more cycles elapsed (a wait without a wake-up uses the rest at once).  The end is
        self.end: setting it to self.cycles from a memory handler stops the slice after the current instruction
        (MAME's abort_timeslice)."""
        start = self.cycles
        self.end = start + n
        rd = self.rd
        while self.cycles < self.end:
            if self.attn:
                if self.wait and not self.can_wake():
                    self.cycles = self.end
                    break
                if self._slow():
                    continue
            pc = self.pc
            op = rd(pc)
            self.pc = (pc + 1) & 0xFFFF
            self.cycles += P1[op](self)
        return self.cycles - start

    def state(self):
        return (self.a, self.b, self.x, self.y, self.u, self.s, self.dp, self.cc, self.pc)


# ---- TFR / EXG (MAME's rules for mixed register sizes) ----------------------
def _r816(c, r):
    r &= 15
    if r == 0: return (c.a << 8) | c.b
    if r == 1: return c.x
    if r == 2: return c.y
    if r == 3: return c.u
    if r == 4: return c.s
    if r == 5: return c.pc
    if r == 8: return 0xFF00 | c.a
    if r == 9: return 0xFF00 | c.b
    if r == 10: return (c.cc << 8) | c.cc
    if r == 11: return (c.dp << 8) | c.dp
    return 0xFFFF


def _r168(c, r):
    r &= 15
    if r == 10: return 0xFF00 | c.cc
    if r == 11: return 0xFF00 | c.dp
    return _r816(c, r)


def _wreg(c, r, v):
    r &= 15
    if r == 0: c.a, c.b = (v >> 8) & 0xFF, v & 0xFF
    elif r == 1: c.x = v
    elif r == 2: c.y = v
    elif r == 3: c.u = v
    elif r == 4: c.s = v
    elif r == 5: c.pc = v
    elif r == 8: c.a = v & 0xFF
    elif r == 9: c.b = v & 0xFF
    elif r == 10: c.cc = v & 0xFF
    elif r == 11: c.dp = v & 0xFF


# ---- handlers that are not generated ----------------------------------------
def _tfr(c):
    pc = c.pc
    p = c.rd(pc)
    c.pc = (pc + 1) & 0xFFFF
    _wreg(c, p, _r816(c, p >> 4))
    if p & 15 == 4:
        c.lds = True
    return 6


def _exg(c):
    pc = c.pc
    p = c.rd(pc)
    c.pc = (pc + 1) & 0xFFFF
    get = _r816 if p & 0x80 else _r168
    r1, r2 = get(c, p >> 4), get(c, p)
    _wreg(c, p, r1)
    _wreg(c, p >> 4, r2)
    return 8


def _daa(c):
    a, cc = c.a, c.cc
    msn, lsn = a & 0xF0, a & 0x0F
    cf = 0
    if lsn > 9 or cc & H: cf |= 0x06
    if msn > 0x80 and lsn > 9: cf |= 0x60
    if msn > 0x90 or cc & C: cf |= 0x60
    t = a + cf
    cc &= ~V
    if t & 0x100:
        cc |= C
    t &= 0xFF
    c.cc = (cc & 0xF3) | ((t >> 4) & 8) | (0 if t else 4)
    c.a = t
    return 2


def _mul(c):
    r = c.a * c.b
    c.a, c.b = r >> 8, r & 0xFF
    c.cc = (c.cc & 0xFA) | (0 if r else 4) | ((r >> 7) & 1)
    return 11


def _sex(c):
    b = c.b
    c.a = 0xFF if b & 0x80 else 0
    c.cc = (c.cc & 0xF3) | ((b >> 4) & 8) | (0 if b else 4)
    return 2


def _abx(c):
    c.x = (c.x + c.b) & 0xFFFF
    return 3


def _nop(c):
    return 2


def _orcc(c):
    pc = c.pc
    c.cc |= c.rd(pc)
    c.pc = (pc + 1) & 0xFFFF
    return 3


def _andcc(c):
    pc = c.pc
    c.cc &= c.rd(pc)
    c.pc = (pc + 1) & 0xFFFF
    return 3


def _xandcc(c):
    _andcc(c)
    return 4


def _x18(c):
    v = c.rd(c.pc)                             # (no pc increment)
    cc = c.cc
    c.cc = (((cc & v) << 1) & 0xFF) | ((cc & 4) >> 1)
    return 2


def _sync(c):
    c.wait = SYNC
    c._upd()
    return 2                                   # (+1 when a line wakes it)


def _cwai(c):
    pc = c.pc
    c.cc = (c.cc & c.rd(pc)) | E
    c.pc = (pc + 1) & 0xFFFF
    c.push_regs(0xFF)
    c.wait = CWAI
    c._upd()
    return 16                                  # (+4 for the vector when an interrupt ends it)


def _rti(c):
    rd = c.rd
    s = c.s
    c.cc = cc = rd(s)
    c.s = (s + 1) & 0xFFFF
    if cc & E:
        c.pull_regs(0xFE)
        return 15
    c.pull_regs(0x80)
    return 6


def _rts(c):
    rd = c.rd
    s = c.s
    c.pc = (rd(s) << 8) | rd((s + 1) & 0xFFFF)
    c.s = (s + 2) & 0xFFFF
    return 5


def _nbits(m):
    return (m & 1) + ((m >> 1) & 1) + ((m >> 2) & 1) + ((m >> 3) & 1) + 2 * (((m >> 4) & 1) + ((m >> 5) & 1) + ((m >> 6) & 1) + ((m >> 7) & 1))


NBYTES = [_nbits(m) for m in range(256)]


def _pshs(c):
    pc = c.pc
    m = c.rd(pc)
    c.pc = (pc + 1) & 0xFFFF
    c.push_regs(m, True)
    return 5 + NBYTES[m]


def _puls(c):
    pc = c.pc
    m = c.rd(pc)
    c.pc = (pc + 1) & 0xFFFF
    c.pull_regs(m, True)
    return 5 + NBYTES[m]


def _pshu(c):
    pc = c.pc
    m = c.rd(pc)
    c.pc = (pc + 1) & 0xFFFF
    c.push_regs(m, False)
    return 5 + NBYTES[m]


def _pulu(c):
    pc = c.pc
    m = c.rd(pc)
    c.pc = (pc + 1) & 0xFFFF
    c.pull_regs(m, False)
    return 5 + NBYTES[m]


def _swi(c):
    c.cc |= E
    c.push_regs(0xFF)
    c.cc |= I | F
    c.vector(VEC_SWI)
    return 19


def _swi_n(vec, e, n):
    def h(c):
        if e:
            c.cc |= E
        c.push_regs(0xFF)
        c.vector(vec)
        return n
    return h


def _bsr(c):
    rd = c.rd
    pc = c.pc
    d = rd(pc)
    pc = (pc + 1) & 0xFFFF
    s = c.s
    s = (s - 1) & 0xFFFF; c.wr(s, pc & 0xFF)
    s = (s - 1) & 0xFFFF; c.wr(s, pc >> 8)
    c.s = s
    c.pc = (pc + d - ((d & 0x80) << 1)) & 0xFFFF
    return 7


def _lbsr(c):
    rd = c.rd
    pc = c.pc
    d = (rd(pc) << 8) | rd((pc + 1) & 0xFFFF)
    pc = (pc + 2) & 0xFFFF
    s = c.s
    s = (s - 1) & 0xFFFF; c.wr(s, pc & 0xFF)
    s = (s - 1) & 0xFFFF; c.wr(s, pc >> 8)
    c.s = s
    c.pc = (pc + d) & 0xFFFF
    return 9


def _freerun(c):
    pc = (c.pc - 1) & 0xFFFF
    raise M6809Error("free-run opcode $%02X at $%04X (the CPU stops until reset)" % (c.rd(pc), pc))


# ---- generated handlers -------------------------------------------------------
COND = {"ra": "True", "rn": "False", "hi": "not cc & 5", "ls": "cc & 5", "cc": "not cc & 1", "cs": "cc & 1",
        "ne": "not cc & 4", "eq": "cc & 4", "vc": "not cc & 2", "vs": "cc & 2", "pl": "not cc & 8", "mi": "cc & 8",
        "ge": "not ((cc >> 3) ^ (cc >> 1)) & 1", "lt": "((cc >> 3) ^ (cc >> 1)) & 1",
        "gt": "not (((cc >> 3) ^ (cc >> 1)) & 1 or cc & 4)", "le": "((cc >> 3) ^ (cc >> 1)) & 1 or cc & 4"}
BCC = ["ra", "rn", "hi", "ls", "cc", "cs", "ne", "eq", "vc", "vs", "pl", "mi", "ge", "lt", "gt", "le"]

NZ8 = "((r >> 4) & 8) | (0 if r & 0xFF else 4)"
NZVC8 = "((r >> 4) & 8) | (0 if r & 0xFF else 4) | (((a ^ v ^ r ^ (r >> 1)) >> 6) & 2) | ((r >> 8) & 1)"
NZVC16 = "((r >> 12) & 8) | (0 if r & 0xFFFF else 4) | (((a ^ v ^ r ^ (r >> 1)) >> 14) & 2) | ((r >> 16) & 1)"
NZ16 = "((r >> 12) & 8) | (0 if r else 4)"

# effective address: (code, cycles after the opcode, cycles of the indexed operand added)
EA = {"dir": (["pc = c.pc", "ea = (c.dp << 8) | rd(pc)", "c.pc = (pc + 1) & 0xFFFF"], 2, False),
      "ext": (["pc = c.pc", "ea = (rd(pc) << 8) | rd((pc + 1) & 0xFFFF)", "c.pc = (pc + 2) & 0xFFFF"], 3, False),
      "idx": (["pc = c.pc", "ea = IDX[rd(pc)](c, (pc + 1) & 0xFFFF)"], 0, True)}
IMM8 = ["pc = c.pc", "v = rd(pc)", "c.pc = (pc + 1) & 0xFFFF"]
IMM16 = ["pc = c.pc", "v = (rd(pc) << 8) | rd((pc + 1) & 0xFFFF)", "c.pc = (pc + 2) & 0xFFFF"]
MEM8 = ["v = rd(ea)"]
MEM16 = ["v = (rd(ea) << 8) | rd((ea + 1) & 0xFFFF)"]
R16GET = {"d": "((c.a << 8) | c.b)", "x": "c.x", "y": "c.y", "u": "c.u", "s": "c.s"}
R16SET = {"d": "c.a = (r >> 8) & 0xFF; c.b = r & 0xFF", "x": "c.x = r & 0xFFFF", "y": "c.y = r & 0xFFFF",
          "u": "c.u = r & 0xFFFF", "s": "c.s = r & 0xFFFF"}

# read-modify-write: v -> r, flags
RMW = {"neg": ["r = -v", "c.cc = (c.cc & 0xF0) | ((r >> 4) & 8) | (0 if r & 0xFF else 4) | (((v ^ r ^ (r >> 1)) >> 6) & 2) | ((r >> 8) & 1)"],
       "com": ["r = v ^ 0xFF", "c.cc = (c.cc & 0xF0) | " + NZ8 + " | 1"],
       "lsr": ["r = v >> 1", "c.cc = (c.cc & 0xF2) | (0 if r else 4) | (v & 1)"],
       "ror": ["r = (v >> 1) | ((c.cc & 1) << 7)", "c.cc = (c.cc & 0xF2) | " + NZ8 + " | (v & 1)"],
       "asr": ["r = (v >> 1) | (v & 0x80)", "c.cc = (c.cc & 0xF2) | " + NZ8 + " | (v & 1)"],
       "asl": ["r = v << 1", "c.cc = (c.cc & 0xF0) | " + NZ8 + " | (((r ^ (r >> 1)) >> 6) & 2) | ((r >> 8) & 1)"],
       "rol": ["r = (v << 1) | (c.cc & 1)", "c.cc = (c.cc & 0xF0) | " + NZ8 + " | (((r ^ (r >> 1)) >> 6) & 2) | (v >> 7)"],
       "dec": ["r = v - 1", "c.cc = (c.cc & 0xF1) | " + NZ8 + " | (2 if v == 0x80 else 0)"],
       "xdec": ["r = v - 1", "c.cc = (c.cc & 0xF0) | " + NZ8 + " | (2 if v == 0x80 else 0) | (1 if v else 0)"],
       "inc": ["r = v + 1", "c.cc = (c.cc & 0xF1) | " + NZ8 + " | (2 if v == 0x7F else 0)"],
       "tst": ["r = v", "c.cc = (c.cc & 0xF1) | " + NZ8],
       "clr": ["r = 0", "c.cc = (c.cc & 0xF0) | 4"],
       "xclr": ["r = 0", "c.cc = (c.cc & 0xF1) | 4"]}
RMW["xnc"] = (["if c.cc & 1:"] + ["    " + s for s in RMW["com"]] + ["else:"] + ["    " + s for s in RMW["neg"]])
RMWNAMES = ["neg", "neg", "xnc", "com", "lsr", "lsr", "ror", "asr", "asl", "rol", "dec", "xdec", "inc", "tst", None, "clr"]

ALU8 = {"sub": (["a = G", "r = a - v", "c.cc = (c.cc & 0xF0) | " + NZVC8, "S"]),
        "cmp": (["a = G", "r = a - v", "c.cc = (c.cc & 0xF0) | " + NZVC8]),
        "sbc": (["a = G", "r = a - v - (c.cc & 1)", "c.cc = (c.cc & 0xF0) | " + NZVC8, "S"]),
        "and": (["r = G & v", "c.cc = (c.cc & 0xF1) | " + NZ8, "S"]),
        "bit": (["r = G & v", "c.cc = (c.cc & 0xF1) | " + NZ8]),
        "ld": (["r = v", "c.cc = (c.cc & 0xF1) | " + NZ8, "S"]),
        "eor": (["r = G ^ v", "c.cc = (c.cc & 0xF1) | " + NZ8, "S"]),
        "adc": (["a = G", "r = a + v + (c.cc & 1)", "c.cc = (c.cc & 0xD0) | (((a ^ v ^ r) & 0x10) << 1) | " + NZVC8, "S"]),
        "or": (["r = G | v", "c.cc = (c.cc & 0xF1) | " + NZ8, "S"]),
        "add": (["a = G", "r = a + v", "c.cc = (c.cc & 0xD0) | (((a ^ v ^ r) & 0x10) << 1) | " + NZVC8, "S"]),
        "xst": (["r = G", "c.cc = (c.cc & 0xF1) | " + NZ8])}
ALU8NAMES = {0: "sub", 1: "cmp", 2: "sbc", 4: "and", 5: "bit", 6: "ld", 7: "st", 8: "eor", 9: "adc", 10: "or", 11: "add"}

_src = []
P1, P2, P3 = [None] * 256, [None] * 256, [None] * 256
_names = {}


def _emit(table, op, name, lines):
    fname = "op%d_%s_%02x" % (1 if table is P1 else 2 if table is P2 else 3, name, op)
    _src.append("def %s(c):\n    rd = c.rd\n    wr = c.wr\n%s\n" % (fname, "\n".join("    " + l for l in lines)))
    _names[fname] = (table, op)


def _ret(n, idx):
    return "return %d + c.ic" % n if idx else "return %d" % n


def _gen():
    modes = ["imm", "dir", "idx", "ext"]
    # RMW rows: $0x direct, $4x A, $5x B, $6x indexed, $7x extended
    for row, mode in ((0x00, "dir"), (0x40, "a"), (0x50, "b"), (0x60, "idx"), (0x70, "ext")):
        for k in range(16):
            op = row + k
            nm = RMWNAMES[k]
            if mode in ("a", "b"):
                if k == 14:
                    nm = "xclr"
                body = ["v = c.%s" % mode] + RMW[nm]
                if nm != "tst":
                    body.append("c.%s = r & 0xFF" % mode)
                body.append("return 2")
                _emit(P1, op, nm + mode, body)
                continue
            code, n, idx = EA[mode]
            if k == 14:
                _emit(P1, op, "jmp", code + ["c.pc = ea", _ret(1 + n, idx)])
                continue
            body = list(code) + MEM8 + RMW[nm]
            if nm != "tst":
                body.append("wr(ea, r & 0xFF)")
            body.append(_ret(1 + n + 3, idx))
            _emit(P1, op, nm, body)
    # branches
    for k in range(16):
        body = ["pc = c.pc", "d = rd(pc)", "pc = (pc + 1) & 0xFFFF", "cc = c.cc",
                "if %s:" % COND[BCC[k]], "    pc = (pc + d - ((d & 0x80) << 1)) & 0xFFFF", "c.pc = pc", "return 3"]
        _emit(P1, 0x20 + k, "b" + BCC[k], body)
        body = ["pc = c.pc", "d = (rd(pc) << 8) | rd((pc + 1) & 0xFFFF)", "pc = (pc + 2) & 0xFFFF", "cc = c.cc",
                "if %s:" % COND[BCC[k]], "    c.pc = (pc + d) & 0xFFFF", "    return 6", "c.pc = pc", "return 5"]
        _emit(P2, 0x20 + k, "lb" + BCC[k], body)
    _emit(P1, 0x16, "lbra", ["pc = c.pc", "d = (rd(pc) << 8) | rd((pc + 1) & 0xFFFF)", "c.pc = (pc + 2 + d) & 0xFFFF", "return 5"])
    # LEA
    for op, r in ((0x30, "x"), (0x31, "y"), (0x32, "s"), (0x33, "u")):
        body = list(EA["idx"][0]) + ["c.%s = ea" % r]
        if r in "xy":
            body.append("c.cc = (c.cc & 0xFB) | (0 if ea else 4)")
        if r == "s":
            body.append("c.lds = True")
        body.append("return 2 + c.ic")
        _emit(P1, op, "lea" + r, body)
    # 8-bit ALU, $8x-$Fx
    for hi in range(8, 16):
        mode = modes[hi & 3]
        reg = "a" if hi < 12 else "b"
        for k, nm in ALU8NAMES.items():
            op = hi * 16 + k
            if nm == "st":
                if mode == "imm":
                    _alu8(P1, op, "xst" + reg, reg, "imm", "xst", 0)
                    continue
                code, n, idx = EA[mode]
                _emit(P1, op, "st" + reg, list(code) + ["r = c.%s" % reg, "wr(ea, r)", "c.cc = (c.cc & 0xF1) | " + NZ8,
                                                        _ret(1 + n + 1, idx)])
                continue
            _alu8(P1, op, nm + reg, reg, mode, nm, 0)
    for p, tbl, reg in ((1, P2, "a"), (1, P2, "b"), (1, P3, "a"), (1, P3, "b")):
        _alu8(tbl, 0x87 if reg == "a" else 0xC7, "xst" + reg, reg, "imm", "xst", 1)
    # 16-bit
    for m in range(4):
        mode = modes[m]
        base = 0x80 + m * 16
        _alu16(P1, base + 0x03, "subd", "d", mode, "sub", 0)
        _alu16(P1, base + 0x43, "addd", "d", mode, "add", 0)
        _alu16(P1, base + 0x0C, "cmpx", "x", mode, "cmp", 0)
        _alu16(P1, base + 0x0E, "ldx", "x", mode, "ld", 0)
        _alu16(P1, base + 0x4C, "ldd", "d", mode, "ld", 0)
        _alu16(P1, base + 0x4E, "ldu", "u", mode, "ld", 0)
        _alu16(P1, base + 0x0F, "stx", "x", mode, "st", 0)
        if mode != "imm":
            _alu16(P1, base + 0x4D, "std", "d", mode, "st", 0)
        _alu16(P1, base + 0x4F, "stu", "u", mode, "st", 0)
        _alu16(P2, base + 0x03, "cmpd", "d", mode, "cmp", 1)
        _alu16(P2, base + 0x0C, "cmpy", "y", mode, "cmp", 1)
        _alu16(P2, base + 0x0E, "ldy", "y", mode, "ld", 1)
        _alu16(P2, base + 0x0F, "sty", "y", mode, "st", 1)
        _alu16(P2, base + 0x43, "xaddd", "d", mode, "xadd", 1)
        _alu16(P2, base + 0x4E, "lds", "s", mode, "ld", 1)
        _alu16(P2, base + 0x4F, "sts", "s", mode, "st", 1)
        _alu16(P3, base + 0x03, "cmpu", "u", mode, "cmp", 1)
        _alu16(P3, base + 0x0C, "cmps", "s", mode, "cmp", 1)
        _alu16(P3, base + 0x43, "xaddu", "u", mode, "xadd", 1)
        if mode == "imm":
            _alu16(P3, 0x8F, "xstx", "x", mode, "st", 1)
            _alu16(P3, 0xCF, "xstu", "u", mode, "st", 1)
        if mode != "imm":
            code, n, idx = EA[mode]
            _emit(P1, base + 0x0D, "jsr", list(code) + [
                "pc = c.pc", "s = c.s", "s = (s - 1) & 0xFFFF", "wr(s, pc & 0xFF)", "s = (s - 1) & 0xFFFF",
                "wr(s, pc >> 8)", "c.s = s", "c.pc = ea", _ret(1 + n + 4, idx)])


def _alu8(tbl, op, name, reg, mode, nm, pre):
    G = "c.%s" % reg
    body = ALU8[nm]
    lines = []
    if mode == "imm":
        lines += IMM8
        n, idx = 1 + pre + 1, False
    else:
        code, n, idx = EA[mode]
        lines += list(code) + MEM8
        n = 1 + pre + n + 1
    for l in body:
        if l == "S":
            lines.append("%s = r & 0xFF" % G)
        else:
            lines.append(l.replace("G", G))
    lines.append(_ret(n, idx))
    _emit(tbl, op, name, lines)


def _alu16(tbl, op, name, reg, mode, nm, pre):
    G, SET = R16GET[reg], R16SET[reg]
    lines = []
    if nm == "st":
        if mode == "imm":                    # XST16: one operand byte read, the register's low byte written at pc
            lines += ["pc = c.pc", "r = %s" % G, "wr((pc + 1) & 0xFFFF, r & 0xFF)", "c.pc = (pc + 2) & 0xFFFF",
                      "c.cc = (c.cc & 0xF1) | " + NZ16, "return %d" % (1 + pre + 2)]
        else:
            code, n, idx = EA[mode]
            lines += list(code) + ["r = %s" % G, "wr(ea, r >> 8)", "wr((ea + 1) & 0xFFFF, r & 0xFF)",
                                   "c.cc = (c.cc & 0xF1) | " + NZ16, _ret(1 + pre + n + 2, idx)]
        _emit(tbl, op, name, lines)
        return
    if mode == "imm":
        lines += IMM16
        n, idx = 1 + pre, False
    else:
        code, n, idx = EA[mode]
        lines += list(code) + MEM16
        n = 1 + pre + n
    if nm == "ld":
        lines += ["r = v", SET, "c.cc = (c.cc & 0xF1) | " + NZ16]
        if reg == "s":
            lines.append("c.lds = True")
        n += 2
    else:
        lines += ["a = %s" % G, "r = a + v" if nm in ("add", "xadd") else "r = a - v", "c.cc = (c.cc & 0xF0) | " + NZVC16]
        if nm in ("add", "sub"):
            lines.append(SET)
        n += 3
    lines.append(_ret(n, idx))
    _emit(tbl, op, name, lines)


def _gen_idx():
    """IDX[postbyte](c, pc after the postbyte) -> ea; c.ic = cycles (postbyte included); sets c.pc."""
    out = []
    for pb in range(256):
        r = "xyus"[(pb >> 5) & 3]
        R = "c." + r
        L = []
        if not pb & 0x80:
            off = pb & 0x1F
            off = off - 32 if off & 0x10 else off
            L += ["c.pc = pc", "t = (%s + %d) & 0xFFFF" % (R, off)]
            n = 3
            ind = False
        else:
            k = pb & 0x0F
            ind = bool(pb & 0x10)
            if k == 0:
                L += ["c.pc = pc", "t = %s" % R, "%s = (t + 1) & 0xFFFF" % R]; n = 4
            elif k == 1:
                L += ["c.pc = pc", "t = %s" % R, "%s = (t + 2) & 0xFFFF" % R]; n = 5
            elif k == 2:
                L += ["c.pc = pc", "t = %s = (%s - 1) & 0xFFFF" % (R, R)]; n = 4
            elif k == 3:
                L += ["c.pc = pc", "t = %s = (%s - 2) & 0xFFFF" % (R, R)]; n = 5
            elif k == 4:
                L += ["c.pc = pc", "t = %s" % R]; n = 2
            elif k == 5:
                L += ["c.pc = pc", "v = c.b", "t = (%s + v - ((v & 0x80) << 1)) & 0xFFFF" % R]; n = 3
            elif k == 6:
                L += ["c.pc = pc", "v = c.a", "t = (%s + v - ((v & 0x80) << 1)) & 0xFFFF" % R]; n = 3
            elif k == 8:
                L += ["v = c.rd(pc)", "c.pc = (pc + 1) & 0xFFFF", "t = (%s + v - ((v & 0x80) << 1)) & 0xFFFF" % R]; n = 3
            elif k == 9:
                L += ["rd = c.rd", "t = ((rd(pc) << 8) | rd((pc + 1) & 0xFFFF)) + %s" % R, "c.pc = (pc + 2) & 0xFFFF",
                      "t &= 0xFFFF"]; n = 6
            elif k == 11:
                L += ["c.pc = pc", "t = (%s + ((c.a << 8) | c.b)) & 0xFFFF" % R]; n = 6
            elif k == 12:
                L += ["v = c.rd(pc)", "pc = (pc + 1) & 0xFFFF", "c.pc = pc", "t = (pc + v - ((v & 0x80) << 1)) & 0xFFFF"]; n = 3
            elif k == 13:
                L += ["rd = c.rd", "v = (rd(pc) << 8) | rd((pc + 1) & 0xFFFF)", "pc = (pc + 2) & 0xFFFF", "c.pc = pc",
                      "t = (pc + v) & 0xFFFF"]; n = 7
            elif k == 15:
                L += ["rd = c.rd", "t = (rd(pc) << 8) | rd((pc + 1) & 0xFFFF)", "c.pc = (pc + 2) & 0xFFFF"]; n = 4
            else:                            # $x7 $xA $xE: MAME uses address 0
                L += ["c.pc = pc", "t = 0"]; n = 1
        if ind:
            L += ["rd = c.rd", "t = (rd(t) << 8) | rd((t + 1) & 0xFFFF)"]
            n += 3
        L += ["c.ic = %d" % n, "return t"]
        fname = "idx_%02x" % pb
        out.append("def %s(c, pc):\n%s\n" % (fname, "\n".join("    " + l for l in L)))
    return out


_gen()
_ns = {"IDX": None}
exec(compile("\n".join(_src + _gen_idx()), "<m6809 generated>", "exec"), _ns)
IDX = [_ns["idx_%02x" % pb] for pb in range(256)]
_ns["IDX"] = IDX
for _f, (_t, _op) in _names.items():
    _t[_op] = _ns[_f]


def _page(tbl, own):
    def h(c):
        pc = c.pc
        op = c.rd(pc)
        c.pc = (pc + 1) & 0xFFFF
        f = tbl[op]
        if f is None:                          # not a page 2/3 opcode: MAME fetches the next byte as a page 1 opcode
            pc = c.pc
            op = c.rd(pc)
            c.pc = (pc + 1) & 0xFFFF
            return 2 + P1[op](c)
        return f(c)
    return h


def _again(page):
    def h(c):
        return 1 + page(c)
    return h


for _op, _f in {0x12: _nop, 0x13: _sync, 0x14: _freerun, 0x15: _freerun, 0x17: _lbsr, 0x18: _x18, 0x19: _daa,
                0x1A: _orcc, 0x1B: _nop, 0x1C: _andcc, 0x1D: _sex, 0x1E: _exg, 0x1F: _tfr, 0x34: _pshs, 0x35: _puls,
                0x36: _pshu, 0x37: _pulu, 0x38: _xandcc, 0x39: _rts, 0x3A: _abx, 0x3B: _rti, 0x3C: _cwai, 0x3D: _mul,
                0x3E: _swi_n(VEC_RESET, False, 19), 0x3F: _swi, 0x8D: _bsr, 0xCD: _freerun}.items():
    P1[_op] = _f
_PAGE2, _PAGE3 = _page(P2, 2), _page(P3, 3)
P1[0x10], P1[0x11] = _PAGE2, _PAGE3
P2[0x10] = P2[0x11] = _again(_PAGE2)          # repeated prefixes: the first page counts
P3[0x10] = P3[0x11] = _again(_PAGE3)
P2[0x3F] = _swi_n(VEC_SWI2, True, 20)
P2[0x3E] = _swi_n(VEC_SWI2, False, 20)        # XSWI2: E not set
P3[0x3F] = _swi_n(VEC_SWI3, True, 20)
P3[0x3E] = _swi_n(VEC_FIRQ, False, 20)        # XFIRQ
assert all(P1), [hex(i) for i, f in enumerate(P1) if f is None]
