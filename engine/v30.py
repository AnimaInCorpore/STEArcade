"""NEC V30 (uPD70116) reference interpreter (Irem M72: R-Type, Mr. Heli): MAME's nec core, V30 timing.

API
    cpu = V30(rd, wr, io_rd, io_wr, inta, rd16=None, wr16=None, io_rd16=None, io_wr16=None, rd_op=None)
      rd(addr20) -> byte, wr(addr20, byte): data accesses; addr20 is already masked to 20 bits.
      rd16(addr20) -> word, wr16(addr20, word): word accesses (MAME's read/write_word_unaligned: little endian; an odd
          address is two bus cycles on the 16-bit bus, the caller may just compose bytes).  Default: two rd/wr calls,
          the second at (addr20 + 1) & $FFFFF.
      io_rd(port16) -> byte, io_wr(port16, byte), io_rd16/io_wr16 likewise for IN/OUT AW (default: composed).
      inta() -> vector number: called when a maskable interrupt is taken (after FLAGS were pushed and IE cleared;
          the uPD71059's INTA cycle).
      rd_op(addr20) -> byte: instruction stream fetches (opcodes, ModRM, displacements, immediates); default rd.
    cpu.reset()                      PS=$FFFF, IP=0, other registers 0 (MAME's device_reset), flags $F002.
    cpu.step() -> cycles             one turn of MAME's execute loop: a pending interrupt is taken first (its
                                     cycles are counted in this step), then one instruction or one REP chunk.
    cpu.run(n) -> cycles used        adds n to cpu.icount and steps while icount > 0 (MAME's slice; the overshoot is
                                     carried into the next run).  A REP string instruction runs only until icount is
                                     used up and continues in the next step (as in MAME).  HALT uses the slice.
    cpu.cycles                       total cycles.
    cpu.irq_line = True / False      INT pin.  Like MAME's set_input_line(0): asserting sets the request (and
                                     ends HALT); taking the interrupt clears the request even if the line stays up,
                                     so a controller that still wants service must assert again (MAME's pic8259
                                     does that through its out_int callback).  Taken before an instruction when IE=1
                                     and not right after MOV/POP sreg or BUSLOCK.
    cpu.set_nmi(state) / cpu.nmi()   NMI pin: a rising edge requests vector 2 (taken regardless of IE).
    Registers: ax cx dx bx sp bp si di (also aw cw dw bw ix iy), al..bh, cs ds es ss (also ps ds0 ds1),
    ip, flags (the PSW as a word; setting it expands it).  pc: the linear address cs*16+ip.
    cpu.state(): (aw cw dw bw sp bp ix iy ds1 ps ss ds0 psw ip), the order of MAME's register view.

Timing is MAME's nec core for the V30 (necinstr.hxx: the middle column of CLKS/CLKW/CLKM/CLKR; odd/even word
address variants) plus its prefetch model: every fetched byte takes one from a 6-byte queue; after an instruction
each missing byte costs 2 cycles, taken from the instruction's own cycles while it has more than 2 left (else
added); a jump empties the queue after that; spare instruction cycles (2 per byte) refill it.  Conditional
branches empty the queue even when not taken; JMP short, LOOP/BCWZ do not.
SHL/SHR/SHRA by 1 (D0/D1) take one cycle more than the table (MAME's shift macros count their shift).
Flags and the odd cases follow MAME exactly (lazy flag values, NEG/NOT, MUL's CY/V from the high word, DIV/DIVU
setting CY and V (MAME 0.289; the older source leaves them), the BL/BNL/BLE/BNLE conditions, ADJBA/ADJBS evaluating
AH's step after AL's, ADD4S/SUB4S on invalid digits with C's division, shift counts mod 32 on the host,
GetnextRMWord wrapping within 64 KB, MOV sreg (8C/8E) with reg 4-7 doing nothing, etc.).  On a divide error the
registers stay and CY/V are untouched (not checked against MAME).  8080 emulation mode (BRKEM) is entered but not
emulated (V30Error).
v30_test.py checks all of it against MAME 0.289: traces of R-Type (boot, title, demo: 1.2 M steps, the interrupts)
and probe programs with every opcode (registers, flags, every access, cycles per step).
"""

AW, CW, DW, BW, SP, BP, IX, IY = range(8)
DS1, PS, SS, DS0 = range(4)
INT_IRQ, NMI_IRQ = 1, 2
PAR = bytes(1 - bin(i).count("1") % 2 for i in range(256))


class V30Error(Exception):
    pass


def _r(i):
    return property(lambda s: s.r[i], lambda s, v: s.r.__setitem__(i, v & 0xFFFF))


def _s(i):
    return property(lambda s: s.sr[i], lambda s, v: s.sr.__setitem__(i, v & 0xFFFF))


def _b(i):
    return property(lambda s: s.get8(i), lambda s, v: s.set8(i, v))


class V30:
    aw = ax = _r(AW); cw = cx = _r(CW); dw = dx = _r(DW); bw = bx = _r(BW)
    sp = _r(SP); bp = _r(BP); ix = si = _r(IX); iy = di = _r(IY)
    ds1 = es = _s(DS1); ps = cs = _s(PS); ss = _s(SS); ds0 = ds = _s(DS0)
    al, cl, dl, bl, ah, ch, dh, bh = (_b(i) for i in range(8))

    def __init__(self, rd, wr, io_rd, io_wr, inta=None, rd16=None, wr16=None, io_rd16=None, io_wr16=None, rd_op=None):
        self.rd, self.wr, self.io_rd, self.io_wr = rd, wr, io_rd, io_wr
        self.inta = inta or (lambda: 0)
        self.rd16 = rd16 or (lambda a: rd(a) | (rd((a + 1) & 0xFFFFF) << 8))
        self.wr16 = wr16 or (lambda a, v: (wr(a, v & 0xFF), wr((a + 1) & 0xFFFFF, v >> 8)))
        self.io_rd16 = io_rd16 or (lambda p: io_rd(p) | (io_rd((p + 1) & 0xFFFF) << 8))
        self.io_wr16 = io_wr16 or (lambda p, v: (io_wr(p, v & 0xFF), io_wr((p + 1) & 0xFFFF, v >> 8)))
        self.rd_op = rd_op or rd
        self.r = [0] * 8
        self.sr = [0] * 4
        self.ip = self.prev_ip = self.rep_ip = 0
        self.cf = self.pv = self.av = self.zv = self.sv = self.ov = 0
        self.tf = self.ie = self.df = 0
        self.mf = self.em = 1
        self.seg_prefix = False
        self.prefix_base = 0
        self.ea = self.eo = 0
        self.pf_count = self.pf_reset = 0
        self.flushed = False                 # (tests) the queue was emptied: its state is known from then on
        self.cur = 0
        self.icount = 0
        self.cycles = 0
        self.rep_params = 0
        self.rep_limit = None              # (tests) iterations a REP chunk may run, else until icount is used up
        self.pending = 0
        self.nmi_state = self.irq_state = 0
        self.no_interrupt = 0
        self.halted = 0
        self.poll_state = 1
        self.ops = [getattr(self, "op_%02x" % i, self.op_invalid) for i in range(256)]
        self.reset()

    # ---- registers --------------------------------------------------------
    def get8(self, i):
        return self.r[i] & 0xFF if i < 4 else self.r[i - 4] >> 8

    def set8(self, i, v):
        r = self.r
        if i < 4:
            r[i] = (r[i] & 0xFF00) | (v & 0xFF)
        else:
            r[i - 4] = (r[i - 4] & 0xFF) | ((v & 0xFF) << 8)

    def compress(self):
        return ((self.cf != 0) | 2 | (PAR[self.pv & 0xFF] << 2) | ((self.av != 0) << 4) | ((self.zv == 0) << 6)
                | ((self.sv != 0) << 7) | (self.tf << 8) | (self.ie << 9) | (self.df << 10) | ((self.ov != 0) << 11)
                | 0x7000 | (self.mf << 15))

    def expand(self, f):
        self.cf = f & 1
        self.pv = 0 if f & 4 else 1
        self.av = f & 0x10
        self.zv = 0 if f & 0x40 else 1
        self.sv = f & 0x80
        self.tf = (f >> 8) & 1
        self.ie = (f >> 9) & 1
        self.df = (f >> 10) & 1
        self.ov = f & 0x800
        self.mf = 1 if (f & 0x8000) or self.em else 0

    flags = property(compress, expand)

    @property
    def pc(self):
        return ((self.sr[PS] << 4) + self.ip) & 0xFFFFF

    def state(self):
        return tuple(self.r) + (self.sr[DS1], self.sr[PS], self.sr[SS], self.sr[DS0], self.compress(), self.ip)

    def reset(self):
        self.r[:] = [0] * 8
        self.ip = self.prev_ip = self.rep_ip = 0
        self.tf = self.ie = self.df = 0
        self.mf = self.em = 1
        self.sv = self.av = self.ov = self.cf = 0
        self.zv = self.pv = 1
        self.pending = self.nmi_state = self.irq_state = 0
        self.poll_state = 1
        self.halted = 0
        self.rep_params = 0
        self.sr[:] = [0, 0xFFFF, 0, 0]
        self.pf_reset = 1

    # ---- interrupt lines -----------------------------------------------------
    @property
    def irq_line(self):
        return bool(self.irq_state)

    @irq_line.setter
    def irq_line(self, state):
        self.irq_state = 1 if state else 0
        if state:
            self.pending |= INT_IRQ
            self.halted = 0
        else:
            self.pending &= ~INT_IRQ

    def set_nmi(self, state):
        state = 1 if state else 0
        if self.nmi_state == state:
            return
        self.nmi_state = state
        if state:
            self.pending |= NMI_IRQ
            self.halted = 0

    def nmi(self):
        self.set_nmi(True)
        self.set_nmi(False)

    def interrupt(self, num, irq=False):
        """MAME's nec_interrupt: FLAGS, PS, IP pushed (8 cycles: PUSHF's), IE/BRK cleared, vector read."""
        self.rep_params = 0
        self.op_9c()
        self.tf = self.ie = 0
        self.mf = 1
        if irq:
            num = self.inta()
        off = self.rw(num * 4)
        seg = self.rw(num * 4 + 2)
        self.push(self.sr[PS])
        self.push(self.ip)
        self.prev_ip = self.ip = off
        self.sr[PS] = seg
        self.pf_reset = 1

    def external_int(self):
        if self.pending & NMI_IRQ:
            self.interrupt(2)
            self.pending &= ~NMI_IRQ
        elif self.pending:
            self.interrupt(-1, True)
            self.irq_state = 0
            self.pending &= ~INT_IRQ

    # ---- execution -------------------------------------------------------------
    def dispatch(self):
        """The start of MAME's execute loop: a pending interrupt is taken; returns its cycles."""
        start = self.icount
        self.prev_ip = self.ip
        if self.pending and not self.no_interrupt and (self.pending & NMI_IRQ or self.ie):
            self.external_int()
        n = start - self.icount
        self.cycles += n
        return n

    def step(self):
        start = self.icount
        if self.halted:
            return 0
        self.prev_ip = self.ip
        if self.pending and not self.no_interrupt and (self.pending & NMI_IRQ or self.ie):
            self.external_int()
        if self.no_interrupt:
            self.no_interrupt -= 1
        self.cur = 0
        if self.rep_params:
            self.cont_rep()
        else:
            if not self.mf:
                raise V30Error("8080 emulation mode at %05X" % self.pc)
            self.ops[self.fetch()]()
        # do_prefetch
        c = self.pf_count
        while c < 0:
            c += 1
            if self.cur > 2:
                self.cur -= 2
            else:
                self.icount -= 2
        if self.pf_reset:
            c = 0
            self.pf_reset = 0
            self.flushed = True
        else:
            while self.cur >= 2 and c < 6:
                self.cur -= 2
                c += 1
        self.pf_count = c
        n = start - self.icount
        self.cycles += n
        return n

    def run(self, n):
        start = self.cycles
        self.icount += n
        while self.icount > 0:
            if self.halted:
                self.cycles += self.icount
                self.icount = 0
                break
            self.step()
        return self.cycles - start

    def clk(self, n):
        self.cur += n
        self.icount -= n

    # ---- bus -------------------------------------------------------------------
    def fetch(self):
        self.pf_count -= 1
        ip = self.ip
        self.ip = (ip + 1) & 0xFFFF
        return self.rd_op(((self.sr[PS] << 4) + ip) & 0xFFFFF)

    def fetchword(self):
        lo = self.fetch()
        return lo | (self.fetch() << 8)

    def rb(self, a):
        return self.rd(a & 0xFFFFF)

    def rw(self, a):
        return self.rd16(a & 0xFFFFF)

    def wb(self, a, v):
        self.wr(a & 0xFFFFF, v & 0xFF)

    def ww(self, a, v):
        self.wr16(a & 0xFFFFF, v & 0xFFFF)

    def base(self, seg):
        if self.seg_prefix and (seg == DS0 or seg == SS):
            return self.prefix_base
        return self.sr[seg] << 4

    def push(self, v):
        sp = (self.r[SP] - 2) & 0xFFFF
        self.r[SP] = sp
        self.ww((self.sr[SS] << 4) + sp, v)

    def pop(self):
        sp = self.r[SP]
        self.r[SP] = (sp + 2) & 0xFFFF
        return self.rw((self.sr[SS] << 4) + sp)

    # ---- ModRM -----------------------------------------------------------------
    def get_ea(self, m):
        rm = m & 7
        mod = m >> 6
        r = self.r
        seg = DS0
        if rm == 0:
            eo = r[BW] + r[IX]
        elif rm == 1:
            eo = r[BW] + r[IY]
        elif rm == 2:
            eo = r[BP] + r[IX]; seg = SS
        elif rm == 3:
            eo = r[BP] + r[IY]; seg = SS
        elif rm == 4:
            eo = r[IX]
        elif rm == 5:
            eo = r[IY]
        elif rm == 6:
            if mod == 0:
                eo = self.fetchword()
            else:
                eo = r[BP]; seg = SS
        else:
            eo = r[BW]
        if mod == 1:
            d = self.fetch()
            eo += d - 256 if d & 0x80 else d
        elif mod == 2:
            d = self.fetchword()
            eo += d - 0x10000 if d & 0x8000 else d
        eo &= 0xFFFF
        self.eo = eo
        ea = self.base(seg) + eo
        self.ea = ea
        return ea

    def get_rm8(self, m):
        if m >= 0xC0:
            return self.get8(m & 7)
        return self.rb(self.get_ea(m))

    def get_rm16(self, m):
        if m >= 0xC0:
            return self.r[m & 7]
        return self.rw(self.get_ea(m))

    def putback_rm8(self, m, v):
        if m >= 0xC0:
            self.set8(m & 7, v)
        else:
            self.wb(self.ea, v)

    def putback_rm16(self, m, v):
        if m >= 0xC0:
            self.r[m & 7] = v & 0xFFFF
        else:
            self.ww(self.ea, v)

    def put_rm8(self, m, v):
        if m >= 0xC0:
            self.set8(m & 7, v)
        else:
            self.wb(self.get_ea(m), v)

    def put_rm16(self, m, v):
        if m >= 0xC0:
            self.r[m & 7] = v & 0xFFFF
        else:
            self.ww(self.get_ea(m), v)

    def next_rm16(self):
        ea = self.ea
        return self.rw((ea & 0xF0000) | ((ea + 2) & 0xFFFF))

    # ---- ALU (MAME's macros; results unmasked, callers store them) --------------------
    def szp8(self, x):
        v = x & 0xFF
        self.sv = v & 0x80
        self.zv = self.pv = v

    def szp16(self, x):
        v = x & 0xFFFF
        self.sv = v & 0x8000
        self.zv = v
        self.pv = v & 0xFF

    def alu8(self, k, dst, src):
        """k: 0 add 1 or 2 adc 3 sbb 4 and 5 sub 6 xor 7 cmp; returns the byte result."""
        if k == 1 or k == 4 or k == 6:
            res = dst | src if k == 1 else (dst & src if k == 4 else dst ^ src)
            self.cf = self.ov = self.av = 0
            self.szp8(res)
            return res & 0xFF
        if k == 0 or k == 2:
            res = dst + src + (1 if k == 2 and self.cf else 0)
            self.cf = res & 0x100
            self.ov = (res ^ src) & (res ^ dst) & 0x80
        else:
            res = dst - src - (1 if k == 3 and self.cf else 0)
            self.cf = res & 0x100
            self.ov = (dst ^ src) & (dst ^ res) & 0x80
        self.av = (res ^ src ^ dst) & 0x10
        self.szp8(res)
        return res & 0xFF

    def alu16(self, k, dst, src):
        if k == 1 or k == 4 or k == 6:
            res = dst | src if k == 1 else (dst & src if k == 4 else dst ^ src)
            self.cf = self.ov = self.av = 0
            self.szp16(res)
            return res & 0xFFFF
        if k == 0 or k == 2:
            res = dst + src + (1 if k == 2 and self.cf else 0)
            self.cf = res & 0x10000
            self.ov = (res ^ src) & (res ^ dst) & 0x8000
        else:
            res = dst - src - (1 if k == 3 and self.cf else 0)
            self.cf = res & 0x10000
            self.ov = (dst ^ src) & (dst ^ res) & 0x8000
        self.av = (res ^ src ^ dst) & 0x10
        self.szp16(res)
        return res & 0xFFFF

    # the ALU block 00-3D: br8 wr16 r8b r16w ald8 axd16
    def alu_br8(self, k):
        m = self.fetch()
        src = self.get8((m >> 3) & 7)
        dst = self.get_rm8(m)
        res = self.alu8(k, dst, src)
        if k != 7:
            self.putback_rm8(m, res)
        self.clk(2 if m >= 0xC0 else (11 if k == 7 else 16))

    def alu_wr16(self, k):
        m = self.fetch()
        src = self.r[(m >> 3) & 7]
        dst = self.get_rm16(m)
        res = self.alu16(k, dst, src)
        if k != 7:
            self.putback_rm16(m, res)
            self.clk(2 if m >= 0xC0 else (24 if self.ea & 1 else 16))
        else:
            self.clk(2 if m >= 0xC0 else (15 if self.ea & 1 else 11))

    def alu_r8b(self, k):
        m = self.fetch()
        reg = (m >> 3) & 7
        dst = self.get8(reg)
        src = self.get_rm8(m)
        res = self.alu8(k, dst, src)
        if k != 7:
            self.set8(reg, res)
        self.clk(2 if m >= 0xC0 else 11)

    def alu_r16w(self, k):
        m = self.fetch()
        reg = (m >> 3) & 7
        dst = self.r[reg]
        src = self.get_rm16(m)
        res = self.alu16(k, dst, src)
        if k != 7:
            self.r[reg] = res
        self.clk(2 if m >= 0xC0 else (15 if self.ea & 1 else 11))

    def alu_ald8(self, k):
        src = self.fetch()
        res = self.alu8(k, self.r[AW] & 0xFF, src)
        if k != 7:
            self.set8(0, res)
        self.clk(4)

    def alu_axd16(self, k):
        src = self.fetchword()
        res = self.alu16(k, self.r[AW], src)
        if k != 7:
            self.r[AW] = res
        self.clk(4)

    # ---- opcodes -------------------------------------------------------------------
    def op_invalid(self):
        self.clk(10)

    def op_06(self): self.push(self.sr[DS1]); self.clk(8)
    def op_07(self): self.sr[DS1] = self.pop(); self.clk(8)
    def op_0e(self): self.push(self.sr[PS]); self.clk(8)
    def op_16(self): self.push(self.sr[SS]); self.clk(8)
    def op_17(self): self.sr[SS] = self.pop(); self.clk(8); self.no_interrupt = 1
    def op_1e(self): self.push(self.sr[DS0]); self.clk(8)
    def op_1f(self): self.sr[DS0] = self.pop(); self.clk(8)

    def prefix(self, seg):
        self.seg_prefix = True
        self.prefix_base = self.sr[seg] << 4
        self.clk(2)
        self.ops[self.fetch()]()
        self.seg_prefix = False

    def op_26(self): self.prefix(DS1)
    def op_2e(self): self.prefix(PS)
    def op_36(self): self.prefix(SS)
    def op_3e(self): self.prefix(DS0)

    def adj4(self, p1, p2):
        al = self.r[AW] & 0xFF
        if self.av or (al & 0xF) > 9:
            tmp = al + p1
            al = tmp & 0xFF
            self.av = 1
            self.cf |= tmp & 0x100
        if self.cf or al > 0x9F:
            al = (al + p2) & 0xFF
            self.cf = 1
        self.set8(0, al)
        self.szp8(al)
        self.clk(3)

    def op_27(self): self.adj4(6, 0x60)
    def op_2f(self): self.adj4(-6, -0x60)

    def adjb(self, sub):
        al = self.r[AW] & 0xFF
        if self.av or (al & 0xF) > 9:
            al = (al + (-6 if sub else 6)) & 0xFF
            if sub:
                step = -2 if al < 6 else -1
            else:
                step = 2 if al > 0xF9 else 1
            self.set8(4, (self.r[AW] >> 8) + step)
            self.av = self.cf = 1
        else:
            self.av = self.cf = 0
        self.set8(0, al & 0x0F)
        self.clk(7)

    def op_37(self): self.adjb(False)
    def op_3f(self): self.adjb(True)

    def incdec_reg(self, i, d):
        tmp = self.r[i]
        t1 = tmp + d
        self.ov = tmp == (0x7FFF if d > 0 else 0x8000)
        self.av = (t1 ^ tmp ^ 1) & 0x10
        self.szp16(t1)
        self.r[i] = t1 & 0xFFFF
        self.clk(2)

    def op_60(self):
        tmp = self.r[SP]
        for i in (AW, CW, DW, BW):
            self.push(self.r[i])
        self.push(tmp)
        for i in (BP, IX, IY):
            self.push(self.r[i])
        self.clk(35)

    def op_61(self):
        r = self.r
        r[IY] = self.pop(); r[IX] = self.pop(); r[BP] = self.pop(); self.pop()
        r[BW] = self.pop(); r[DW] = self.pop(); r[CW] = self.pop(); r[AW] = self.pop()
        self.clk(43)

    def op_62(self):                                    # CHKIND
        m = self.fetch()
        low = self.get_rm16(m)
        high = self.next_rm16()
        tmp = self.r[(m >> 3) & 7]
        if tmp < low or tmp > high:
            self.interrupt(5)
        self.clk(20)

    def op_68(self):
        self.push(self.fetchword())
        self.clk(12 if self.r[SP] & 1 else 8)

    def op_6a(self):
        self.push((self.fetch() ^ 0x80) - 0x80)
        self.clk(11 if self.r[SP] & 1 else 7)

    def imul(self, imm8):
        m = self.fetch()
        src = self.get_rm16(m)
        if imm8:
            t = self.fetch()
            t = t - 256 if t & 0x80 else t
        else:
            t = self.fetchword()
            t = t - 0x10000 if t & 0x8000 else t
        dst = ((src ^ 0x8000) - 0x8000) * t
        dst = ((dst + 0x80000000) & 0xFFFFFFFF) - 0x80000000
        self.cf = self.ov = (dst >> 15) not in (0, -1)
        self.r[(m >> 3) & 7] = dst & 0xFFFF
        if imm8:
            self.clk(34 if m >= 0xC0 else 40)
        else:
            self.clk(42 if m >= 0xC0 else 48)

    def op_69(self): self.imul(False)
    def op_6b(self): self.imul(True)

    def strstep(self, n):
        return -n if self.df else n

    def op_6c(self):                                    # INM byte
        r = self.r
        self.wb((self.sr[DS1] << 4) + r[IY], self.io_rd(r[DW]))
        r[IY] = (r[IY] + self.strstep(1)) & 0xFFFF
        self.clk(8)

    def op_6d(self):
        r = self.r
        self.ww((self.sr[DS1] << 4) + r[IY], self.io_rd16(r[DW]))
        r[IY] = (r[IY] + self.strstep(2)) & 0xFFFF
        self.clk(10)

    def op_6e(self):
        r = self.r
        self.io_wr(r[DW], self.rb(self.base(DS0) + r[IX]))
        r[IX] = (r[IX] + self.strstep(1)) & 0xFFFF
        self.clk(8)

    def op_6f(self):
        r = self.r
        self.io_wr16(r[DW], self.rw(self.base(DS0) + r[IX]))
        r[IX] = (r[IX] + self.strstep(2)) & 0xFFFF
        self.clk(10)

    def cond(self, k):
        sf = self.sv != 0
        zf = self.zv == 0
        of = self.ov != 0
        cf = self.cf != 0
        c = k >> 1
        if c == 0:
            t = of
        elif c == 1:
            t = cf
        elif c == 2:
            t = zf
        elif c == 3:
            t = cf or zf
        elif c == 4:
            t = sf
        elif c == 5:
            t = PAR[self.pv & 0xFF] != 0
        elif c == 6:
            t = sf != of and not zf                     # (MAME's BL / BNL)
            return zf or sf == of if k & 1 else t
        else:
            return (sf == of and not zf) if k & 1 else (zf or sf != of)
        return not t if k & 1 else t

    def jcc(self, k):
        self.pf_reset = 1
        d = self.fetch()
        if self.cond(k):
            self.ip = (self.ip + (d - 256 if d & 0x80 else d)) & 0xFFFF
            self.clk(10)
            self.pf_reset = 1
            return
        self.clk(4)

    def op_80(self):
        m = self.fetch()
        dst = self.get_rm8(m)
        src = self.fetch()
        k = (m >> 3) & 7
        self.clk(4 if m >= 0xC0 else (13 if k == 7 else 18))
        res = self.alu8(k, dst, src)
        if k != 7:
            self.putback_rm8(m, res)

    def op_81(self, sx=False):
        m = self.fetch()
        dst = self.get_rm16(m)
        if sx:
            src = self.fetch()
            src = (src | 0xFF00) if src & 0x80 else src
        else:
            src = self.fetchword()
        k = (m >> 3) & 7
        if m >= 0xC0:
            self.clk(4)
        elif k == 7:
            self.clk(17 if self.ea & 1 else 13)
        else:
            self.clk(26 if self.ea & 1 else 18)
        res = self.alu16(k, dst, src)
        if k != 7:
            self.putback_rm16(m, res)

    def op_82(self): self.op_80()
    def op_83(self): self.op_81(True)

    def op_84(self):
        m = self.fetch()
        src = self.get8((m >> 3) & 7)
        self.alu8(4, self.get_rm8(m), src)
        self.clk(2 if m >= 0xC0 else 10)

    def op_85(self):
        m = self.fetch()
        src = self.r[(m >> 3) & 7]
        self.alu16(4, self.get_rm16(m), src)
        self.clk(2 if m >= 0xC0 else (14 if self.ea & 1 else 10))

    def op_86(self):
        m = self.fetch()
        reg = (m >> 3) & 7
        src = self.get8(reg)
        dst = self.get_rm8(m)
        self.set8(reg, dst)
        self.putback_rm8(m, src)
        self.clk(3 if m >= 0xC0 else 18)

    def op_87(self):
        m = self.fetch()
        reg = (m >> 3) & 7
        src = self.r[reg]
        dst = self.get_rm16(m)
        self.r[reg] = dst
        self.putback_rm16(m, src)
        self.clk(3 if m >= 0xC0 else (24 if self.ea & 1 else 16))

    def op_88(self):
        m = self.fetch()
        self.put_rm8(m, self.get8((m >> 3) & 7))
        self.clk(2 if m >= 0xC0 else 9)

    def op_89(self):
        m = self.fetch()
        self.put_rm16(m, self.r[(m >> 3) & 7])
        self.clk(2 if m >= 0xC0 else (13 if self.ea & 1 else 9))

    def op_8a(self):
        m = self.fetch()
        self.set8((m >> 3) & 7, self.get_rm8(m))
        self.clk(2 if m >= 0xC0 else 11)

    def op_8b(self):
        m = self.fetch()
        self.r[(m >> 3) & 7] = self.get_rm16(m)
        self.clk(2 if m >= 0xC0 else (15 if self.ea & 1 else 11))

    def op_8c(self):
        m = self.fetch()
        k = (m >> 3) & 7
        if k < 4:
            self.put_rm16(m, self.sr[k])
            self.clk(2 if m >= 0xC0 else (14 if self.ea & 1 else 10))

    def op_8d(self):
        m = self.fetch()
        if m < 0xC0:
            self.get_ea(m)
            self.r[(m >> 3) & 7] = self.eo
        self.clk(4)

    def op_8e(self):
        m = self.fetch()
        src = self.get_rm16(m)
        self.clk(2 if m >= 0xC0 else (15 if self.ea & 1 else 11))
        k = (m >> 3) & 7
        if k < 4:
            self.sr[k] = src
        self.no_interrupt = 1

    def op_8f(self):
        m = self.fetch()
        tmp = self.pop()
        self.put_rm16(m, tmp)
        self.clk(21)

    def op_90(self): self.clk(3)

    def xchg_aw(self, i):
        r = self.r
        r[AW], r[i] = r[i], r[AW]
        self.clk(3)

    def op_98(self):
        self.set8(4, 0xFF if self.r[AW] & 0x80 else 0)
        self.clk(2)

    def op_99(self):
        self.r[DW] = 0xFFFF if self.r[AW] & 0x8000 else 0
        self.clk(4)

    def op_9a(self):
        off = self.fetchword()
        seg = self.fetchword()
        self.push(self.sr[PS])
        self.push(self.ip)
        self.ip = off
        self.sr[PS] = seg
        self.pf_reset = 1
        self.clk(29 if self.r[SP] & 1 else 21)

    def op_9b(self):
        if not self.poll_state:
            self.ip = (self.ip - 1) & 0xFFFF
        self.clk(5)

    def op_9c(self):
        self.push(self.compress())
        self.clk(8)

    def op_9d(self):
        self.expand(self.pop())
        self.clk(8)
        if self.tf:
            self.trap()

    def trap(self):
        self.ops[self.fetch()]()
        self.interrupt(1)

    def op_9e(self):
        self.expand((self.compress() & 0xFF00) | ((self.r[AW] >> 8) & 0xD5))
        self.clk(3)

    def op_9f(self):
        self.set8(4, self.compress() & 0xFF)
        self.clk(3)

    def op_a0(self):
        a = self.fetchword()
        self.set8(0, self.rb(self.base(DS0) + a))
        self.clk(10)

    def op_a1(self):
        a = self.fetchword()
        self.r[AW] = self.rw(self.base(DS0) + a)
        self.clk(14 if a & 1 else 10)

    def op_a2(self):
        a = self.fetchword()
        self.wb(self.base(DS0) + a, self.r[AW])
        self.clk(9)

    def op_a3(self):
        a = self.fetchword()
        self.ww(self.base(DS0) + a, self.r[AW])
        self.clk(13 if a & 1 else 9)

    def op_a4(self):
        r = self.r
        tmp = self.rb(self.base(DS0) + r[IX])
        self.wb((self.sr[DS1] << 4) + r[IY], tmp)
        d = self.strstep(1)
        r[IY] = (r[IY] + d) & 0xFFFF
        r[IX] = (r[IX] + d) & 0xFFFF
        self.clk(8)

    def op_a5(self):
        r = self.r
        tmp = self.rw(self.base(DS0) + r[IX])
        self.ww((self.sr[DS1] << 4) + r[IY], tmp)
        d = self.strstep(2)
        r[IY] = (r[IY] + d) & 0xFFFF
        r[IX] = (r[IX] + d) & 0xFFFF
        self.clk(16)

    def op_a6(self):
        r = self.r
        src = self.rb((self.sr[DS1] << 4) + r[IY])
        dst = self.rb(self.base(DS0) + r[IX])
        self.alu8(5, dst, src)
        d = self.strstep(1)
        r[IY] = (r[IY] + d) & 0xFFFF
        r[IX] = (r[IX] + d) & 0xFFFF
        self.clk(14)

    def op_a7(self):
        r = self.r
        src = self.rw((self.sr[DS1] << 4) + r[IY])
        dst = self.rw(self.base(DS0) + r[IX])
        self.alu16(5, dst, src)
        d = self.strstep(2)
        r[IY] = (r[IY] + d) & 0xFFFF
        r[IX] = (r[IX] + d) & 0xFFFF
        self.clk(14)

    def op_a8(self):
        self.alu8(4, self.r[AW] & 0xFF, self.fetch())
        self.clk(4)

    def op_a9(self):
        self.alu16(4, self.r[AW], self.fetchword())
        self.clk(4)

    def op_aa(self):
        r = self.r
        self.wb((self.sr[DS1] << 4) + r[IY], r[AW])
        r[IY] = (r[IY] + self.strstep(1)) & 0xFFFF
        self.clk(4)

    def op_ab(self):
        r = self.r
        self.ww((self.sr[DS1] << 4) + r[IY], r[AW])
        r[IY] = (r[IY] + self.strstep(2)) & 0xFFFF
        self.clk(8 if r[IY] & 1 else 4)

    def op_ac(self):
        r = self.r
        self.set8(0, self.rb(self.base(DS0) + r[IX]))
        r[IX] = (r[IX] + self.strstep(1)) & 0xFFFF
        self.clk(4)

    def op_ad(self):
        r = self.r
        r[AW] = self.rw(self.base(DS0) + r[IX])
        r[IX] = (r[IX] + self.strstep(2)) & 0xFFFF
        self.clk(8 if r[IX] & 1 else 4)

    def op_ae(self):
        r = self.r
        src = self.rb((self.sr[DS1] << 4) + r[IY])
        self.alu8(5, r[AW] & 0xFF, src)
        r[IY] = (r[IY] + self.strstep(1)) & 0xFFFF
        self.clk(4)

    def op_af(self):
        r = self.r
        src = self.rw((self.sr[DS1] << 4) + r[IY])
        self.alu16(5, r[AW], src)
        r[IY] = (r[IY] + self.strstep(2)) & 0xFFFF
        self.clk(8 if r[IY] & 1 else 4)

    def mov_r8(self, i):
        self.set8(i, self.fetch())
        self.clk(4)

    def mov_r16(self, i):
        self.r[i] = self.fetchword()
        self.clk(4)

    # shifts and rotates: MAME's ROL/ROR/ROLC/RORC/SHL/SHR/SHRA on an unmasked dst (shift counts mod 32, as the
    # host's 32-bit shifts do)
    def op_c0(self):
        m = self.fetch()
        self._rot_imm(m, False)

    def op_c1(self):
        m = self.fetch()
        self._rot_imm(m, True)

    def _rot_imm(self, m, word):
        dst = self.get_rm16(m) if word else self.get_rm8(m)
        c = self.fetch()
        self._rot_n(m, word, dst, c)

    def _rot_n(self, m, word, dst, c):
        self.clk(7 if m >= 0xC0 else 19)
        if not c:
            return
        hi = 0x8000 if word else 0x80
        bits = 16 if word else 8
        mask = 0xFFFF if word else 0xFF
        k = (m >> 3) & 7
        put = self.putback_rm16 if word else self.putback_rm8
        if k <= 3:
            for _ in range(c):
                if k == 0:
                    self.cf = dst & hi
                    dst = (dst << 1) + (self.cf != 0)
                elif k == 1:
                    self.cf = dst & 1
                    dst = (dst >> 1) + ((self.cf != 0) << (bits - 1))
                elif k == 2:
                    dst = (dst << 1) + (self.cf != 0)
                    self.cf = dst & (hi << 1)
                else:
                    dst = ((self.cf != 0) << bits) + dst
                    self.cf = dst & 1
                    dst >>= 1
                dst &= 0xFFFFFFFF
                self.clk(1)
            put(m, dst & mask)
            return
        if k == 6:
            return
        self.clk(c)
        dst = self._shift(k, dst, c, hi, mask)
        put(m, dst & mask)

    def _shift(self, k, dst, c, hi, mask):
        if k == 4:
            dst = (dst << (c & 31)) & 0xFFFFFFFF
            self.cf = dst & (hi << 1)
        elif k == 5:
            dst >>= (c - 1) & 31
            self.cf = dst & 1
            dst >>= 1
        else:
            dst = ((dst ^ hi) - hi) >> ((c - 1) & 31)
            self.cf = dst & 1
            dst = (((dst & mask) ^ hi) - hi) >> 1
        if mask == 0xFF:
            self.szp8(dst)
        else:
            self.szp16(dst)
        return dst

    def _rot1(self, word):
        m = self.fetch()
        src = dst = self.get_rm16(m) if word else self.get_rm8(m)
        self.clk(6 if m >= 0xC0 else 16)
        hi = 0x8000 if word else 0x80
        bits = 16 if word else 8
        mask = 0xFFFF if word else 0xFF
        k = (m >> 3) & 7
        put = self.putback_rm16 if word else self.putback_rm8
        if k == 0:
            self.cf = dst & hi
            dst = (dst << 1) + (self.cf != 0)
        elif k == 1:
            self.cf = dst & 1
            dst = (dst >> 1) + ((self.cf != 0) << (bits - 1))
        elif k == 2:
            dst = (dst << 1) + (self.cf != 0)
            self.cf = dst & (hi << 1)
        elif k == 3:
            dst = ((self.cf != 0) << bits) + dst
            self.cf = dst & 1
            dst >>= 1
        elif k == 6:
            return
        else:
            self.clk(1)                                 # (MAME's SHL/SHR/SHRA macros count their shift)
            dst = self._shift(k, dst, 1, hi, mask)
            put(m, dst & mask)
            self.ov = 0 if k == 7 else (src ^ dst) & hi
            return
        put(m, dst & mask)
        self.ov = (src ^ dst) & hi

    def op_d0(self): self._rot1(False)
    def op_d1(self): self._rot1(True)

    def op_d2(self):
        m = self.fetch()
        dst = self.get_rm8(m)
        self._rot_n(m, False, dst, self.r[CW] & 0xFF)

    def op_d3(self):
        m = self.fetch()
        dst = self.get_rm16(m)
        self._rot_n(m, True, dst, self.r[CW] & 0xFF)

    def op_c2(self):
        n = self.fetchword()
        self.ip = self.pop()
        self.r[SP] = (self.r[SP] + n) & 0xFFFF
        self.pf_reset = 1
        self.clk(24)

    def op_c3(self):
        self.ip = self.pop()
        self.pf_reset = 1
        self.clk(19)

    def op_c4(self, seg=DS1):
        m = self.fetch()
        tmp = self.get_rm16(m)
        self.r[(m >> 3) & 7] = tmp
        self.sr[seg] = self.next_rm16()
        self.clk(26 if self.ea & 1 else 18)

    def op_c5(self): self.op_c4(DS0)

    def op_c6(self):
        m = self.fetch()
        if m >= 0xC0:
            self.set8(m & 7, self.fetch())
        else:
            ea = self.get_ea(m)
            self.wb(ea, self.fetch())
        self.clk(4 if m >= 0xC0 else 11)

    def op_c7(self):
        m = self.fetch()
        if m >= 0xC0:
            self.r[m & 7] = self.fetchword()
        else:
            ea = self.get_ea(m)
            self.ww(ea, self.fetchword())
        self.clk(4 if m >= 0xC0 else 15)

    def op_c8(self):                                    # PREPARE (ENTER)
        nb = self.fetch()
        self.clk(23)
        nb += self.fetch() << 8
        level = self.fetch()
        r = self.r
        self.push(r[BP])
        r[BP] = r[SP]
        r[SP] = (r[SP] - nb) & 0xFFFF
        for i in range(1, level):
            v = self.rw(self.base(SS) + r[BP] - i * 2)
            self.push(v)
            self.clk(16)
        if level:
            self.push(r[BP])

    def op_c9(self):                                    # DISPOSE (LEAVE)
        self.r[SP] = self.r[BP]
        self.r[BP] = self.pop()
        self.clk(8)

    def op_ca(self):
        n = self.fetchword()
        self.ip = self.pop()
        self.sr[PS] = self.pop()
        self.r[SP] = (self.r[SP] + n) & 0xFFFF
        self.pf_reset = 1
        self.clk(32)

    def op_cb(self):
        self.ip = self.pop()
        self.sr[PS] = self.pop()
        self.pf_reset = 1
        self.clk(29)

    def op_cc(self):
        self.interrupt(3)
        self.clk(50)

    def op_cd(self):
        self.interrupt(self.fetch())
        self.clk(50)

    def op_ce(self):
        if self.ov:
            self.interrupt(4)
            self.clk(52)
        else:
            self.clk(3)

    def op_cf(self):
        self.ip = self.pop()
        self.sr[PS] = self.pop()
        self.op_9d()
        self.pf_reset = 1
        self.clk(39)

    def op_d4(self):
        self.fetch()
        al = self.r[AW] & 0xFF
        self.r[AW] = ((al // 10) << 8) | (al % 10)
        self.szp16(self.r[AW])
        self.clk(15)

    def op_d5(self):
        self.fetch()
        al = ((self.r[AW] >> 8) * 10 + (self.r[AW] & 0xFF)) & 0xFF
        self.r[AW] = al
        self.szp8(al)
        self.clk(7)

    def op_d6(self):
        self.set8(0, 0xFF if self.cf else 0)
        self.clk(3)

    def op_d7(self):
        a = (self.r[BW] + (self.r[AW] & 0xFF)) & 0xFFFF
        self.set8(0, self.rb(self.base(DS0) + a))
        self.clk(9)

    def op_fpo(self):
        m = self.fetch()
        self.get_rm8(m)
        self.clk(2)

    def loop(self, kind):
        d = self.fetch()
        r = self.r
        if kind < 3:
            r[CW] = (r[CW] - 1) & 0xFFFF
            zf = self.zv == 0
            t = r[CW] and (kind == 2 or (kind == 0 and not zf) or (kind == 1 and zf))
            n = 13 if kind == 2 else 14
        else:
            t = r[CW] == 0
            n = 13
        if t:
            self.ip = (self.ip + (d - 256 if d & 0x80 else d)) & 0xFFFF
            self.clk(n)
        else:
            self.clk(5)

    def op_e0(self): self.loop(0)
    def op_e1(self): self.loop(1)
    def op_e2(self): self.loop(2)
    def op_e3(self): self.loop(3)

    def op_e4(self):
        self.set8(0, self.io_rd(self.fetch()))
        self.clk(9)

    def op_e5(self):
        p = self.fetch()
        self.r[AW] = self.io_rd16(p)
        self.clk(13 if p & 1 else 9)

    def op_e6(self):
        self.io_wr(self.fetch(), self.r[AW] & 0xFF)
        self.clk(8)

    def op_e7(self):
        p = self.fetch()
        self.io_wr16(p, self.r[AW])
        self.clk(12 if p & 1 else 8)

    def op_e8(self):
        d = self.fetchword()
        self.push(self.ip)
        self.ip = (self.ip + d) & 0xFFFF
        self.pf_reset = 1
        self.clk(24)

    def op_e9(self):
        d = self.fetchword()
        self.ip = (self.ip + d) & 0xFFFF
        self.pf_reset = 1
        self.clk(15)

    def op_ea(self):
        off = self.fetchword()
        seg = self.fetchword()
        self.sr[PS] = seg
        self.ip = off
        self.pf_reset = 1
        self.clk(27)

    def op_eb(self):
        d = self.fetch()
        self.clk(12)
        self.ip = (self.ip + (d - 256 if d & 0x80 else d)) & 0xFFFF

    def op_ec(self):
        self.set8(0, self.io_rd(self.r[DW]))
        self.clk(8)

    def op_ed(self):
        p = self.r[DW]
        self.r[AW] = self.io_rd16(p)
        self.clk(12 if p & 1 else 8)

    def op_ee(self):
        self.io_wr(self.r[DW], self.r[AW] & 0xFF)
        self.clk(8)

    def op_ef(self):
        p = self.r[DW]
        self.io_wr16(p, self.r[AW])
        self.clk(12 if p & 1 else 8)

    def op_f0(self):
        self.no_interrupt = 1
        self.clk(2)

    def op_f4(self):
        self.halted = 1
        self.icount = 0

    def op_f5(self):
        self.cf = 0 if self.cf else 1
        self.clk(2)

    def op_f6(self):
        m = self.fetch()
        tmp = self.get_rm8(m)
        k = (m >> 3) & 7
        reg = m >= 0xC0
        r = self.r
        if k == 0:
            tmp &= self.fetch()
            self.cf = self.ov = 0
            self.szp8(tmp)
            self.clk(4 if reg else 11)
        elif k == 2:
            self.putback_rm8(m, ~tmp)
            self.clk(2 if reg else 16)
        elif k == 3:
            self.cf = tmp != 0
            tmp = (~tmp + 1) & 0xFFFFFFFF
            self.szp8(tmp)
            self.putback_rm8(m, tmp)
            self.clk(2 if reg else 16)
        elif k == 4:
            r[AW] = (r[AW] & 0xFF) * tmp
            self.cf = self.ov = r[AW] >> 8 != 0
            self.clk(30 if reg else 36)
        elif k == 5:
            res = (((r[AW] & 0xFF) ^ 0x80) - 0x80) * ((tmp ^ 0x80) - 0x80)
            r[AW] = res & 0xFFFF
            self.cf = self.ov = r[AW] >> 8 != 0
            self.clk(47 if reg else 53)
        elif k == 6:
            if tmp:
                q, rem = divmod(r[AW], tmp)
                if q > 0xFF:
                    self.interrupt(0)
                else:
                    r[AW] = ((rem & 0xFF) << 8) | q
                    self.cf = self.ov = 1
            else:
                self.interrupt(0)
            self.clk(25 if reg else 31)
        elif k == 7:
            if tmp:
                a = (r[AW] ^ 0x8000) - 0x8000
                b = (tmp ^ 0x80) - 0x80
                q = abs(a) // abs(b)
                if (a < 0) != (b < 0):
                    q = -q
                rem = a - q * b
                if q > 0x7F or q < -0x7F:
                    self.interrupt(0)
                else:
                    r[AW] = ((rem & 0xFF) << 8) | (q & 0xFF)
                    self.cf = self.ov = 1
            else:
                self.interrupt(0)
            self.clk(43 if reg else 49)

    def op_f7(self):
        m = self.fetch()
        tmp = self.get_rm16(m)
        k = (m >> 3) & 7
        reg = m >= 0xC0
        r = self.r
        if k == 0:
            tmp &= self.fetchword()
            self.cf = self.ov = 0
            self.szp16(tmp)
            self.clk(4 if reg else 11)
        elif k == 2:
            self.putback_rm16(m, ~tmp)
            self.clk(2 if reg else 16)
        elif k == 3:
            self.cf = tmp != 0
            tmp = (~tmp + 1) & 0xFFFFFFFF
            self.szp16(tmp)
            self.putback_rm16(m, tmp)
            self.clk(2 if reg else 16)
        elif k == 4:
            res = r[AW] * tmp
            r[AW] = res & 0xFFFF
            r[DW] = res >> 16
            self.cf = self.ov = r[DW] != 0
            self.clk(30 if reg else 36)
        elif k == 5:
            res = ((r[AW] ^ 0x8000) - 0x8000) * ((tmp ^ 0x8000) - 0x8000)
            r[AW] = res & 0xFFFF
            r[DW] = (res >> 16) & 0xFFFF
            self.cf = self.ov = r[DW] != 0
            self.clk(47 if reg else 53)
        elif k == 6:
            if tmp:
                q, rem = divmod((r[DW] << 16) | r[AW], tmp)
                if q > 0xFFFF:
                    self.interrupt(0)
                else:
                    r[AW], r[DW] = q, rem & 0xFFFF
                    self.cf = self.ov = 1
            else:
                self.interrupt(0)
            self.clk(25 if reg else 31)
        elif k == 7:
            if tmp:
                a = (((r[DW] << 16) | r[AW]) ^ 0x80000000) - 0x80000000
                b = (tmp ^ 0x8000) - 0x8000
                q = abs(a) // abs(b)
                if (a < 0) != (b < 0):
                    q = -q
                rem = a - q * b
                if q > 0x7FFF or q < -0x7FFF:
                    self.interrupt(0)
                else:
                    r[AW], r[DW] = q & 0xFFFF, rem & 0xFFFF
                    self.cf = self.ov = 1
            else:
                self.interrupt(0)
            self.clk(43 if reg else 49)

    def op_f8(self): self.cf = 0; self.clk(2)
    def op_f9(self): self.cf = 1; self.clk(2)
    def op_fa(self): self.ie = 0; self.clk(2)
    def op_fb(self): self.ie = 1; self.clk(2)
    def op_fc(self): self.df = 0; self.clk(2)
    def op_fd(self): self.df = 1; self.clk(2)

    def op_fe(self):
        m = self.fetch()
        tmp = self.get_rm8(m)
        k = (m >> 3) & 7
        if k < 2:
            t1 = tmp + 1 if k == 0 else tmp - 1
            self.ov = tmp == (0x7F if k == 0 else 0x80)
            self.av = (t1 ^ tmp ^ 1) & 0x10
            self.szp8(t1)
            self.putback_rm8(m, t1 & 0xFF)
            self.clk(2 if m >= 0xC0 else 16)

    def op_ff(self):
        m = self.fetch()
        tmp = self.get_rm16(m)
        k = (m >> 3) & 7
        reg = m >= 0xC0
        if k < 2:
            t1 = tmp + 1 if k == 0 else tmp - 1
            self.ov = tmp == (0x7FFF if k == 0 else 0x8000)
            self.av = (t1 ^ tmp ^ 1) & 0x10
            self.szp16(t1)
            self.putback_rm16(m, t1 & 0xFFFF)
            self.clk(2 if reg else 16)
        elif k == 2:
            self.push(self.ip)
            self.ip = tmp
            self.pf_reset = 1
            self.clk(16 if reg else 20)
        elif k == 3:
            t1 = self.sr[PS]
            self.sr[PS] = self.next_rm16()
            self.push(t1)
            self.push(self.ip)
            self.ip = tmp
            self.pf_reset = 1
            self.clk(16 if reg else 26)
        elif k == 4:
            self.ip = tmp
            self.pf_reset = 1
            self.clk(13)
        elif k == 5:
            self.ip = tmp
            self.sr[PS] = self.next_rm16()
            self.pf_reset = 1
            self.clk(15)
        elif k == 6:
            self.push(tmp)
            self.clk(4)

    # ---- REP -------------------------------------------------------------------------
    STRING_OPS = (0x6C, 0x6D, 0x6E, 0x6F, 0xA4, 0xA5, 0xA6, 0xA7, 0xAA, 0xAB, 0xAC, 0xAD, 0xAE, 0xAF)

    def start_rep(self):
        nxt = self.fetch()
        if nxt in (0x26, 0x2E, 0x36, 0x3E):
            self.seg_prefix = True
            self.prefix_base = self.sr[(DS1, PS, SS, DS0)[(nxt >> 3) & 3]] << 4
            nxt = self.fetch()
            self.clk(2)
        return nxt

    def cont_rep(self):
        self.ip = self.rep_ip
        p = self.rep_params
        self.seg_prefix = bool(p & 4)
        self.rep_params = 0
        self.do_rep(p & 3, (p >> 8) & 0xFF)

    def do_rep(self, kind, nxt):
        """kind: 0 REPNC, 1 REPC, 2 REPNE, 3 REPE (MAME's do_repnc/do_repc/do_repne/do_repe)."""
        c = self.r[CW]
        cmp = (nxt & 0x86) == 0x86
        if nxt in self.STRING_OPS:
            self.clk(2)
            if c:
                op = self.ops[nxt]
                lim = self.rep_limit
                n = 0
                while True:
                    op()
                    c = (c - 1) & 0xFFFF
                    n += 1
                    if not c or self.icount <= 0 or (lim is not None and n >= lim):
                        break
                    if kind == 0:
                        if self.cf:
                            break
                    elif kind == 1:
                        if not self.cf:
                            break
                    elif cmp:
                        if (self.zv == 0) != (kind == 3):
                            break
                self.r[CW] = c
        else:
            c = 0
            self.ops[nxt]()
        if c:
            if kind == 0:
                go = not self.cf
            elif kind == 1:
                go = bool(self.cf)
            elif kind == 2:
                go = not (self.zv == 0 and cmp)
            else:
                go = not (self.zv != 0 and cmp)
            if go:
                self.rep_ip = self.ip
                self.ip = self.prev_ip
                self.rep_params = (nxt << 8) | kind | (4 if self.seg_prefix else 0)
        self.seg_prefix = False

    def op_64(self): self.do_rep(0, self.start_rep())
    def op_65(self): self.do_rep(1, self.start_rep())
    def op_f2(self): self.do_rep(2, self.start_rep())
    def op_f3(self): self.do_rep(3, self.start_rep())

    # ---- $0F: the NEC instructions -------------------------------------------------------------
    def op_0f(self):
        sub = self.fetch()
        if 0x10 <= sub <= 0x1F:
            word = sub & 1
            m = self.fetch()
            if m >= 0xC0:
                tmp = self.r[m & 7] if word else self.get8(m & 7)
            else:
                self.get_ea(m)
                tmp = self.rw(self.ea) if word else self.rb(self.ea)
            kind = (sub >> 1) & 3                       # test clr set not
            if sub < 0x18:
                self.clk((3, 5, 4, 4)[kind])
                bit = self.r[CW] & (15 if word else 7)
            else:
                self.clk((4, 6, 5, 5)[kind])
                bit = self.fetch() & (15 if word else 7)
            if kind == 0:
                self.zv = 1 if tmp & (1 << bit) else 0
                self.cf = self.ov = 0
                return
            if kind == 1:
                tmp &= ~(1 << bit)
            elif kind == 2:
                tmp |= 1 << bit
            else:
                tmp ^= 1 << bit
            if word:
                self.putback_rm16(m, tmp)
            else:
                self.putback_rm8(m, tmp)
        elif sub in (0x20, 0x22, 0x26):
            self.bcd4s(sub)
            self.clk(7)
        elif sub == 0x28:                               # ROL4
            m = self.fetch()
            tmp = self.get_rm8(m)
            tmp = (tmp << 4) | (self.r[AW] & 0xF)
            self.set8(0, (self.r[AW] & 0xF0) | ((tmp >> 8) & 0xF))
            self.putback_rm8(m, tmp & 0xFF)
            self.clk(13 if m >= 0xC0 else 28)
        elif sub == 0x2A:                               # ROR4
            m = self.fetch()
            tmp = self.get_rm8(m)
            t2 = (self.r[AW] & 0xF) << 4
            self.set8(0, (self.r[AW] & 0xF0) | (tmp & 0xF))
            self.putback_rm8(m, t2 | (tmp >> 4))
            self.clk(17 if m >= 0xC0 else 32)
        elif sub in (0x31, 0x39):                       # INS
            m = self.fetch()
            if sub == 0x31:
                tmp = self.get8(m & 7) & 0xF
                t2 = (self.get8((m >> 3) & 7) & 0xF) + 1
            else:
                tmp = self.get_rm8(m) & 0xF
                t2 = (self.fetch() & 0xF) + 1
            r = self.r
            aw = r[AW]
            a = (self.sr[DS1] << 4) + r[IY]
            self.ww(a, (self.rw(a) & ~(((1 << t2) - 1) << tmp)) | ((aw & ((1 << t2) - 1)) << tmp))
            if tmp + t2 > 15:
                r[IY] = (r[IY] + 2) & 0xFFFF
                a = (self.sr[DS1] << 4) + r[IY]
                k = (1 << (t2 - (16 - tmp))) - 1
                self.ww(a, (self.rw(a) & ~k) | ((aw >> (16 - tmp)) & k))
            self.put_rm8(m, (tmp + t2) & 0xF)
            if sub == 0x31:
                self.clk(113 if r[IY] & 1 else 117)
            else:
                self.clk(103 if r[IY] & 1 else 87)
        elif sub in (0x33, 0x3B):                       # EXT
            m = self.fetch()
            if sub == 0x33:
                tmp = self.get8(m & 7) & 0xF
                t2 = (self.get8((m >> 3) & 7) & 0xF) + 1
            else:
                tmp = self.get_rm8(m) & 0xF
                t2 = (self.fetch() & 0xF) + 1
            r = self.r
            aw = self.rw(self.base(DS0) + r[IX]) >> tmp
            if tmp + t2 > 15:
                r[IX] = (r[IX] + 2) & 0xFFFF
                aw |= self.rw(self.base(DS0) + r[IX]) << (16 - tmp)
            r[AW] = aw & 0xFFFF & ((1 << t2) - 1)
            self.put_rm8(m, (tmp + t2) & 0xF)
            if sub == 0x33:
                self.clk(59 if r[IX] & 1 else 55)
            else:
                self.clk(52 if r[IX] & 1 else 44)
        elif sub in (0xE0, 0xF0):                       # BRKXA/RETXA: V33 only
            self.clk(12)
        elif sub == 0xFF:                               # BRKEM
            n = self.fetch()
            self.em = 0
            self.mf = 0
            self.op_9c()
            self.push(self.sr[PS])
            self.push(self.ip)
            self.prev_ip = self.ip = self.rw(n * 4)
            self.sr[PS] = self.rw(n * 4 + 2)
            self.pf_reset = 1
            self.clk(50)

    def bcd4s(self, sub):
        count = ((self.r[CW] & 0xFF) + 1) // 2
        di = self.r[IY]
        si = self.r[IX]
        self.zv = self.cf = 0
        for _ in range(count):
            self.clk(19)
            if sub == 0x20:
                tmp = self.rb(self.base(DS0) + si)
                t2 = self.rb((self.sr[DS1] << 4) + di)
            else:
                tmp = self.rb((self.sr[DS1] << 4) + di)
                t2 = self.rb(self.base(DS0) + si)
            v1 = (tmp >> 4) * 10 + (tmp & 0xF)
            v2 = (t2 >> 4) * 10 + (t2 & 0xF)
            if sub == 0x20:
                res = v1 + v2 + self.cf
                self.cf = 1 if res > 99 else 0
                res %= 100
            else:
                if v1 < v2 + self.cf:
                    res = v1 + 100 - (v2 + self.cf)
                    self.cf = 1
                else:
                    res = v1 - (v2 + self.cf)
                    self.cf = 0
            q = -(-res // 10) if res < 0 else res // 10           # (C's truncating / and %: invalid digits)
            v1 = (q << 4) | (res - q * 10)
            if sub != 0x26:
                self.wb((self.sr[DS1] << 4) + di, v1)
            if v1:
                self.zv = 1
            si += 1
            di += 1


def _setup():
    for k in range(8):
        for j, name in enumerate(("alu_br8", "alu_wr16", "alu_r8b", "alu_r16w", "alu_ald8", "alu_axd16")):
            setattr(V30, "op_%02x" % (k * 8 + j), (lambda n, k: lambda self: getattr(self, n)(k))(name, k))
    for i in range(8):
        setattr(V30, "op_%02x" % (0x40 + i), (lambda i: lambda self: self.incdec_reg(i, 1))(i))
        setattr(V30, "op_%02x" % (0x48 + i), (lambda i: lambda self: self.incdec_reg(i, -1))(i))
        setattr(V30, "op_%02x" % (0x50 + i), (lambda i: lambda self: (self.push(self.r[i] if i != SP else (self.r[SP] - 2) & 0xFFFF), self.clk(8)))(i))
        setattr(V30, "op_%02x" % (0x58 + i), (lambda i: lambda self: (self.r.__setitem__(i, self.pop()), self.clk(8)))(i))
        setattr(V30, "op_%02x" % (0xB0 + i), (lambda i: lambda self: self.mov_r8(i))(i))
        setattr(V30, "op_%02x" % (0xB8 + i), (lambda i: lambda self: self.mov_r16(i))(i))
        if i:
            setattr(V30, "op_%02x" % (0x90 + i), (lambda i: lambda self: self.xchg_aw(i))(i))
        setattr(V30, "op_%02x" % (0xD8 + i), V30.op_fpo)
    for k in range(16):
        setattr(V30, "op_%02x" % (0x70 + k), (lambda k: lambda self: self.jcc(k))(k))


_setup()
