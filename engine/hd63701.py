"""Hitachi HD63701V0 (Namco CUS64, the System 1 I/O and voice MCU) reference interpreter.

Follows MAME's m6800/m6801 cores (hd63701v0_cpu_device: m6801_io + hd6801_mem, hd63701_insn, cycles_63701):
  - memory: internal registers $00-$14, RAM $80-$FF, the 4 KB ROM at $F000 (read only); everything else, writes to
    $F000-$FFFF and reads of the write-only $13 included, goes to the rd/wr callbacks (the external bus).  Like MAME
    the mode pins are not modelled: ports 3/4 always stay internal registers, the external bus is always there
    (CUS64 runs expanded, it executes code from the voice ROM at $4000-$BFFF).
  - the 6301 instruction set: 6801 + AIM OIM EIM TIM XGDX SLP, MAME's $12/$13 (X += (S+1)), TRAP ($FFEE) for the
    undefined opcodes, MAME's flag formulas (TAP/RTI load all 8 CC bits) and HD6301 cycle counts.
  - interrupts as MAME: NMI (edge), IRQ1 (level, set_irq1), timer ICI/OCI/TOI and SCI (TIE/RIE flags only, no
    serial shifting).  IRQ1 is sampled only where MAME samples it: at the start of run() (MAME's execute_run, one
    scheduler slice), in CLI/TAP (after the next instruction), RTI, WAI, SLP; the timer interrupts are taken the
    moment the free running counter reaches the event (increment_counter -> check_timer_event).
  - the free running counter with MAME's quirks: TOF at $FFFF, a write to $09 loads $FFF8, $0A loads latch:data,
    OCF/TOF/ICF cleared by the read-TCSR-then-access sequence (pending_tcsr).
  - ports 1-4 with DDRs; output callbacks get (value, ddr) like MAME's out_pN_cb (value = data&ddr | ~ddr), port 2
    only bits 0-4 and only after a data write (m_port2_written).  Not modelled: P3 handshake (OS3), SCI shifting.

    cpu = HD63701(rom, rd, wr, in_p1=..., out_p1=..., out_p2=...)
    cpu.run(n)          # one scheduler slice (MAME's quantum on System 1 is 1/38400 s = 40 E clocks)
    cpu.set_irq1(True)  # between slices; the program acknowledges with a write to $F000 (board: set_irq1(False))
    cpu.step()          # one instruction (tests); cycles, a b x sp pc cc as attributes
Verified against MAME traces by engine/hd63701_test.py.
"""

N, Z, V, C, I, H = 0x08, 0x04, 0x02, 0x01, 0x10, 0x20
WAI_ST, SLP_ST = 1, 2

XX = 4      # MAME: illegal opcode, unknown cycle count
CYCLES = [
    XX, 1, XX, XX, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
    1, 1, XX, XX, XX, XX, 1, 1, 2, 2, 4, 1, XX, XX, XX, XX,
    3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3,
    1, 1, 3, 3, 1, 1, 4, 4, 4, 5, 1, 10, 5, 7, 9, 12,
    1, XX, XX, 1, 1, XX, 1, 1, 1, 1, 1, XX, 1, 1, XX, 1,
    1, XX, XX, 1, 1, XX, 1, 1, 1, 1, 1, XX, 1, 1, XX, 1,
    6, 7, 7, 6, 6, 7, 6, 6, 6, 6, 6, 5, 6, 4, 3, 5,
    6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 4, 6, 4, 3, 5,
    2, 2, 2, 3, 2, 2, 2, XX, 2, 2, 2, 2, 3, 5, 3, XX,
    3, 3, 3, 4, 3, 3, 3, 3, 3, 3, 3, 3, 4, 5, 4, 4,
    4, 4, 4, 5, 4, 4, 4, 4, 4, 4, 4, 4, 5, 5, 5, 5,
    4, 4, 4, 5, 4, 4, 4, 4, 4, 4, 4, 4, 5, 6, 5, 5,
    2, 2, 2, 3, 2, 2, 2, XX, 2, 2, 2, 2, 3, XX, 3, XX,
    3, 3, 3, 4, 3, 3, 3, 3, 3, 3, 3, 3, 4, 4, 4, 4,
    4, 4, 4, 5, 4, 4, 4, 4, 4, 4, 4, 4, 5, 5, 5, 5,
    4, 4, 4, 5, 4, 4, 4, 4, 4, 4, 4, 4, 5, 5, 5, 5,
]

# TCSR
OLVL, IEDG, ETOI, EOCI, EICI, TOF, OCF, ICF = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80
# TRCSR
RDRF, ORFE, TDRE, RIE, RE, TIE, TE = 0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02
# P3CSR
P3_LE, P3_OSS, P3_IS3 = 0x08, 0x10, 0x80


class HD63701:
    def __init__(self, rom, rd=None, wr=None, in_p1=None, out_p1=None, out_p2=None,
                 in_p2=None, in_p3=None, in_p4=None, out_p3=None, out_p4=None):
        assert len(rom) == 0x1000
        self.rom = bytes(rom)                    # $F000-$FFFF
        self.ram = bytearray(0x80)               # $80-$FF (MAME: zero at power on, kept over reset)
        self.ext_rd = rd or (lambda a: 0xFF)
        self.ext_wr = wr or (lambda a, v: None)
        self.in_p = [in_p1, in_p2, in_p3, in_p4]
        self.out_p = [out_p1, out_p2, out_p3, out_p4]
        self.hook = None                         # hook(cpu) before each instruction (MAME's debugger hook)
        self.irq_hook = None                     # irq_hook(cpu, line) when IRQ1 / ICI is taken (MAME's irq callback)
        self.on_rmcr = None                      # on_rmcr(value) when RMCR changes (see set_rmcr)
        self.a = self.b = self.x = self.sp = self.pc = self.ppc = 0
        self.cc = 0
        self.cycles = 0                          # E clocks executed (MAME's total_cycles)
        self.icount = 0
        self.wai_state = 0
        self.nmi_state = self.nmi_pending = False
        self.irq1 = False
        self.tin = False
        self.ctd = 0                             # counter with MAME's high word (CTD); low 16 bits = FRC
        self.ocd = 0
        self.tod = 0
        self.timer_next = 0
        self.tcsr = self.pending_tcsr = 0
        self.latch09 = 0
        self.input_capture = 0
        self.ddr = [0, 0, 0, 0]
        self.data = [0, 0, 0, 0]
        self.p3csr = 0
        self.ram_ctrl = 0
        self.rmcr = self.trcsr = self.rdr = self.tdr = 0
        self.port2_written = False
        self.port3_latched = False
        self.pending_isf_clear = False
        self.trcsr_read = 0                      # bits TDRE/ORFE/RDRF read while set
        self.insn = [self._decode(op) for op in range(256)]
        self.reset()

    # ---- reset ---------------------------------------------------------
    def reset(self):
        """MAME device_reset: A, B, X, S, RAM survive"""
        self.cc = 0xC0 | I
        self.pc = self.rd16(0xFFFE)
        self.wai_state = 0
        self.nmi_state = self.nmi_pending = False
        self.ddr = [0, 0, 0, 0]
        self.p3csr = 0
        self.pending_isf_clear = False
        self.port2_written = False
        self.port3_latched = False
        self.tcsr = self.pending_tcsr = 0
        self.ctd = 0
        self.ocd = 0xFFFF
        self.tod = 0xFFFF
        self.timer_next = 0xFFFF
        self.ram_ctrl |= 0x40
        self.latch09 = 0
        self.trcsr = TDRE
        self.trcsr_read = 0
        self.set_rmcr(0)

    def set_rmcr(self, v):
        """MAME's set_rmcr: the SCI clock is a scheduler timer there (a periodic one when RMCR selects the internal
        clock), which splits every CPU's timeslices; on_rmcr(v) lets a board model it (only called on a change)"""
        if v == self.rmcr:
            return
        self.rmcr = v
        if self.on_rmcr:
            self.on_rmcr(v)

    # ---- inputs --------------------------------------------------------
    def set_irq1(self, state):
        self.irq1 = bool(state)

    def set_nmi(self, state):
        if not self.nmi_state and state:
            self.nmi_pending = True
        self.nmi_state = bool(state)

    def set_tin(self, state):
        """P20/TIN input capture edge"""
        state = bool(state)
        if state != self.tin:
            self.tin = state
            if bool(self.tcsr & IEDG) != state:
                return
            self.tcsr |= ICF
            self.pending_tcsr |= ICF
            self.input_capture = self.ctd & 0xFFFF

    # ---- memory --------------------------------------------------------
    def rd(self, a):
        a &= 0xFFFF
        if a >= 0xF000:
            return self.rom[a - 0xF000]
        if 0x80 <= a < 0x100:
            return self.ram[a - 0x80]
        if a < 0x15 and a != 0x13:
            return self.rd_reg(a)
        return self.ext_rd(a) & 0xFF

    def wr(self, a, v):
        a &= 0xFFFF
        v &= 0xFF
        if 0x80 <= a < 0x100:
            self.ram[a - 0x80] = v
        elif a < 0x15:
            self.wr_reg(a, v)
        else:
            self.ext_wr(a, v)

    def rd16(self, a):
        return (self.rd(a) << 8) | self.rd((a + 1) & 0xFFFF)

    def wr16(self, a, v):
        self.wr(a, v >> 8)
        self.wr((a + 1) & 0xFFFF, v)

    # ---- internal registers ($00-$14) -------------------------------------
    def port_in(self, p):
        cb = self.in_p[p]
        return cb() & 0xFF if cb else 0xFF

    def port_out(self, p):
        cb = self.out_p[p]
        if cb:
            d = self.ddr[p]
            cb((self.data[p] & d) | (d ^ 0xFF), d)

    def write_port2(self):
        if not self.port2_written:
            return
        d = self.ddr[1] & 0x1F
        v = self.data[1]
        if d != 0x1F and d:
            v = (v & d) | (d ^ 0xFF)
        if self.trcsr & TE:
            v = (v & 0xEF) | 0x10
            d |= 0x10
        if self.out_p[1]:
            self.out_p[1](v & 0x1F, d)

    def rd_reg(self, a):
        if a in (0x02, 0x03, 0x07):
            p = (0, 1, 0, 0, 0, 3)[a - 2]
            d = self.ddr[p]
            if d == 0xFF:
                return self.data[p]
            return (self.port_in(p) & ~d & 0xFF) | (self.data[p] & d)
        if a == 0x06:
            if self.pending_isf_clear:
                self.p3csr &= ~P3_IS3
                self.pending_isf_clear = False
            d = self.ddr[2]
            if (self.p3csr & P3_LE) or d == 0xFF:
                v = self.data[2]
            else:
                v = (self.port_in(2) & ~d & 0xFF) | (self.data[2] & d)
            self.port3_latched = False
            return v
        if a == 0x08:
            self.pending_tcsr = 0
            return self.tcsr
        if a == 0x09:
            if not (self.pending_tcsr & TOF):
                self.tcsr &= ~TOF
            return (self.ctd >> 8) & 0xFF
        if a == 0x0A:
            return self.ctd & 0xFF
        if a == 0x0B:
            return (self.ocd >> 8) & 0xFF
        if a == 0x0C:
            return self.ocd & 0xFF
        if a == 0x0D:
            if not (self.pending_tcsr & ICF):
                self.tcsr &= ~ICF
            return (self.input_capture >> 8) & 0xFF
        if a == 0x0E:
            return self.input_capture & 0xFF
        if a == 0x0F:
            if self.p3csr & P3_IS3:
                self.pending_isf_clear = True
            return self.p3csr
        if a == 0x10:
            return self.rmcr
        if a == 0x11:
            self.trcsr_read |= self.trcsr & (TDRE | ORFE | RDRF)
            return self.trcsr
        if a == 0x12:
            self.trcsr &= ~(self.trcsr_read & (ORFE | RDRF))
            self.trcsr_read &= ~(ORFE | RDRF)
            return self.rdr
        if a == 0x14:
            return self.ram_ctrl | 0x3F
        return 0xFF                              # DDRs read $FF

    def wr_reg(self, a, v):
        if a in (0x00, 0x01, 0x04, 0x05):        # DDR1 DDR2 DDR3 DDR4
            p = (0, 1, 0, 0, 2, 3)[a]
            if self.ddr[p] != v:
                self.ddr[p] = v
                if p == 1:
                    self.write_port2()
                else:
                    self.port_out(p)
        elif a == 0x02:
            self.data[0] = v
            self.port_out(0)
        elif a == 0x03:
            self.data[1] = v
            self.port2_written = True
            self.write_port2()
        elif a == 0x06:
            if self.pending_isf_clear:
                self.p3csr &= ~P3_IS3
                self.pending_isf_clear = False
            self.data[2] = v
            self.port_out(2)
        elif a == 0x07:
            self.data[3] = v
            self.port_out(3)
        elif a == 0x08:
            self.tcsr = (v & 0x1F) | (self.tcsr & 0xE0)
            self.pending_tcsr &= self.tcsr
            self.check_irq2()
        elif a == 0x09:
            self.latch09 = v
            self.ctd = (self.ctd & ~0xFFFF) | 0xFFF8
            self.tod = (self.ctd & ~0xFFFF) | 0xFFFF
            self.modified_counters()
        elif a == 0x0A:
            self.ctd = (self.ctd & ~0xFFFF) | (self.latch09 << 8) | v
            self.tod = (self.ctd & ~0xFFFF) | 0xFFFF
            self.modified_counters()
        elif a in (0x0B, 0x0C):
            if not (self.pending_tcsr & OCF):
                self.tcsr &= ~OCF
            sh = 8 if a == 0x0B else 0
            old = (self.ocd >> sh) & 0xFF
            if old != v:
                self.ocd = (self.ocd & ~(0xFF << sh)) | (v << sh)
                self.modified_counters()
        elif a == 0x0F:
            self.p3csr = v
        elif a == 0x10:
            self.set_rmcr(v)
        elif a == 0x11:
            self.trcsr = (self.trcsr & 0xE0) | (v & 0x1F)
        elif a == 0x13:
            if self.trcsr_read & TDRE:
                self.trcsr_read &= ~TDRE
                self.trcsr &= ~TDRE
            self.tdr = v
        elif a == 0x14:
            self.ram_ctrl = v
        # $0D $0E $12 read only

    # ---- timer (MAME's counter with a high word) ----------------------------
    def set_timer_event(self):
        self.timer_next = self.ocd if self.ocd < self.tod else self.tod

    def modified_counters(self):
        ct, cth = self.ctd & 0xFFFF, self.ctd >> 16
        oc = self.ocd & 0xFFFF
        self.ocd = ((cth if oc >= ct else cth + 1) << 16) | oc
        self.set_timer_event()

    def check_timer_event(self):
        if self.ctd >= self.ocd:
            self.ocd += 0x10000
            self.tcsr |= OCF
            self.pending_tcsr |= OCF
            if self.ddr[1] & 2:                  # OLVL to P21
                self.data[1] = (self.data[1] & ~2) | ((self.tcsr & OLVL) << 1)
                self.port2_written = True
                self.write_port2()
        if self.ctd >= self.tod:
            self.tod += 0x10000
            self.tcsr |= TOF
            self.pending_tcsr |= TOF
        self.check_irq2()
        self.set_timer_event()

    def cleanup_counters(self):
        cth = (self.ctd >> 16) << 16
        if cth:
            self.ocd -= cth
            self.tod -= cth
            self.ctd -= cth
        self.set_timer_event()
        if self.ctd >= self.timer_next:
            self.check_timer_event()

    def increment_counter(self, n):
        self.cycles += n
        self.icount -= n
        self.ctd += n
        if self.ctd >= self.timer_next:
            self.check_timer_event()

    def eat_cycles(self):
        n = min(self.timer_next - self.ctd, self.icount)
        if n > 0:
            self.increment_counter(n)

    # ---- interrupts ----------------------------------------------------
    def push(self, v):
        self.wr(self.sp, v)
        self.sp = (self.sp - 1) & 0xFFFF

    def pushw(self, v):
        self.push(v & 0xFF)
        self.push(v >> 8)

    def pull(self):
        self.sp = (self.sp + 1) & 0xFFFF
        return self.rd(self.sp)

    def pullw(self):
        h = self.pull()
        return (h << 8) | self.pull()

    def push_all(self):
        self.pushw(self.pc)
        self.pushw(self.x)
        self.push(self.a)
        self.push(self.b)
        self.push(self.cc)

    def enter_interrupt(self, vec):
        if self.wai_state & WAI_ST:
            n = 4
            self.wai_state &= ~WAI_ST
        else:
            self.push_all()
            n = 12
        self.cc |= I
        self.pc = self.rd16(vec)
        self.increment_counter(n)

    def check_irq_lines(self):
        if self.nmi_pending:
            self.wai_state &= ~SLP_ST
            self.nmi_pending = False
            self.enter_interrupt(0xFFFC)
        elif self.irq1:
            self.wai_state &= ~SLP_ST
            if not (self.cc & I):
                if self.irq_hook:
                    self.irq_hook(self, 0)
                self.enter_interrupt(0xFFF8)
        else:
            self.check_irq2()

    def take_irq2(self, vec):
        self.wai_state &= ~SLP_ST
        if not (self.cc & I):
            self.enter_interrupt(vec)

    def check_irq2(self):
        t = self.tcsr
        if (t & (EICI | ICF)) == (EICI | ICF):
            if not (self.cc & I) and self.irq_hook:
                self.irq_hook(self, 'tin')
            self.take_irq2(0xFFF6)
        elif (t & (EOCI | OCF)) == (EOCI | OCF):
            self.take_irq2(0xFFF4)
        elif (t & (ETOI | TOF)) == (ETOI | TOF):
            self.take_irq2(0xFFF2)
        else:
            s = self.trcsr
            if (s & (RIE | RDRF)) == (RIE | RDRF) or (s & (RIE | ORFE)) == (RIE | ORFE) or \
                    (s & (TIE | TDRE)) == (TIE | TDRE):
                self.take_irq2(0xFFF0)

    # ---- execution -----------------------------------------------------
    def run(self, n):
        """one MAME execute_run slice of n E clocks (overshoot is carried into the next call); returns cycles run"""
        start = self.cycles
        self.icount += n
        if self.icount <= 0:
            return 0
        self.check_irq_lines()
        self.cleanup_counters()
        while self.icount > 0:
            if self.wai_state:
                self.eat_cycles()
            else:
                self.execute_one()
        return self.cycles - start

    def step(self, wait=40):
        """one instruction; in WAI/SLP: up to `wait` clocks, then the interrupt lines are sampled (as at the start of
        a MAME slice).  Returns cycles."""
        start = self.cycles
        if self.wai_state:
            self.icount = wait
            self.eat_cycles()
            if self.wai_state:
                self.check_irq_lines()
        else:
            self.icount = wait
            self.execute_one()
        self.icount = 0
        return self.cycles - start

    def execute_one(self):
        self.ppc = self.pc
        if self.hook:
            self.hook(self)
        pc = self.pc
        op = self.rom[pc - 0xF000] if pc >= 0xF000 else self.rd(pc)
        self.pc = (pc + 1) & 0xFFFF
        self.insn[op]()
        self.increment_counter(CYCLES[op])

    # operand fetch
    def imm8(self):
        pc = self.pc
        self.pc = (pc + 1) & 0xFFFF
        return self.rom[pc - 0xF000] if pc >= 0xF000 else self.rd(pc)

    def imm16(self):
        h = self.imm8()
        return (h << 8) | self.imm8()

    def ea_dir(self):
        return self.imm8()

    def ea_idx(self):
        return (self.x + self.imm8()) & 0xFFFF

    def ea_ext(self):
        return self.imm16()

    # flags (MAME's macros)
    def nz8(self, r):
        self.cc |= (r & 0x80) >> 4
        if not (r & 0xFF):
            self.cc |= Z

    def nz16(self, r):
        self.cc |= (r & 0x8000) >> 12
        if not (r & 0xFFFF):
            self.cc |= Z

    def flags8(self, a, b, r):
        self.cc |= ((r & 0x80) >> 4) | (0 if r & 0xFF else Z) | (((a ^ b ^ r ^ (r >> 1)) & 0x80) >> 6) | \
            ((r & 0x100) >> 8)

    def flags16(self, a, b, r):
        self.cc |= ((r & 0x8000) >> 12) | (0 if r & 0xFFFF else Z) | (((a ^ b ^ r ^ (r >> 1)) & 0x8000) >> 14) | \
            ((r & 0x10000) >> 16)

    def nxorc(self):
        return bool(self.cc & N) != bool(self.cc & C)

    # ---- the opcode table ----------------------------------------------
    def _decode(self, op):
        hi, k = op >> 4, op & 15
        if op < 0x40:
            f = {0x01: self.op_nop, 0x04: self.op_lsrd, 0x05: self.op_asld, 0x06: self.op_tap, 0x07: self.op_tpa,
                 0x08: self.op_inx, 0x09: self.op_dex, 0x0A: self.op_clv, 0x0B: self.op_sev, 0x0C: self.op_clc,
                 0x0D: self.op_sec, 0x0E: self.op_cli, 0x0F: self.op_sei, 0x10: self.op_sba, 0x11: self.op_cba,
                 0x12: self.op_undoc, 0x13: self.op_undoc, 0x16: self.op_tab, 0x17: self.op_tba,
                 0x18: self.op_xgdx, 0x19: self.op_daa, 0x1A: self.op_slp, 0x1B: self.op_aba,
                 0x30: self.op_tsx, 0x31: self.op_ins, 0x32: self.op_pula, 0x33: self.op_pulb, 0x34: self.op_des,
                 0x35: self.op_txs, 0x36: self.op_psha, 0x37: self.op_pshb, 0x38: self.op_pulx, 0x39: self.op_rts,
                 0x3A: self.op_abx, 0x3B: self.op_rti, 0x3C: self.op_pshx, 0x3D: self.op_mul, 0x3E: self.op_wai,
                 0x3F: self.op_swi}.get(op)
            if hi == 2:
                return lambda: self.op_branch(k)
            return f or self.op_trap
        if hi in (4, 5):
            if k in (1, 2, 5, 0xB, 0xE):
                return self.op_trap
            if hi == 4:
                return lambda: setattr(self, 'a', self.unary(k, self.a))
            return lambda: setattr(self, 'b', self.unary(k, self.b))
        if hi in (6, 7):
            ea = self.ea_idx if hi == 6 else (self.ea_ext if k not in (1, 2, 5, 0xB) else self.ea_dir)
            if k == 0xE:
                return lambda: setattr(self, 'pc', ea())
            if k in (1, 2, 5, 0xB):
                return lambda: self.op_imm_mem(k, ea)
            return lambda: self.op_unary_mem(k, ea)
        mode = (hi - 8) & 3
        acc_b = hi >= 0xC
        ea = (None, self.ea_dir, self.ea_idx, self.ea_ext)[mode]
        if op in (0x87, 0x8F, 0xC7, 0xCD, 0xCF):
            return self.op_trap
        if op == 0x8D:
            return self.op_bsr
        if k == 3:
            return lambda: self.op_d16(ea, sub=not acc_b)
        if k == 0xC:
            return (lambda: self.op_ldd(ea)) if acc_b else (lambda: self.op_cpx(ea))
        if k == 0xD:
            return (lambda: self.op_std(ea)) if acc_b else (lambda: self.op_jsr(ea))
        if k == 0xE:
            return lambda: self.op_ld16(ea, 'x' if acc_b else 'sp')
        if k == 0xF:
            return lambda: self.op_st16(ea, 'x' if acc_b else 'sp')
        if k == 7:
            return lambda: self.op_st8(ea, acc_b)
        return lambda: self.op_alu(k, ea, acc_b)

    # ---- inherent ------------------------------------------------------
    def op_trap(self):
        self.pc = (self.pc - 1) & 0xFFFF
        self.enter_interrupt(0xFFEE)

    def op_nop(self):
        pass

    def op_lsrd(self):
        t = (self.a << 8) | self.b
        self.cc &= 0xF0
        self.cc |= t & 1
        t >>= 1
        if not t:
            self.cc |= Z
        if self.nxorc():
            self.cc |= V
        self.a, self.b = t >> 8, t & 0xFF

    def op_asld(self):
        t = (self.a << 8) | self.b
        r = t << 1
        self.cc &= 0xF0
        self.flags16(t, t, r)
        self.a, self.b = (r >> 8) & 0xFF, r & 0xFF

    def op_tap(self):
        self.cc = self.a
        self.execute_one()                      # IRQ blocked until after the next opcode
        self.check_irq_lines()

    def op_tpa(self):
        self.a = self.cc

    def op_inx(self):
        self.x = (self.x + 1) & 0xFFFF
        self.cc &= ~Z
        if not self.x:
            self.cc |= Z

    def op_dex(self):
        self.x = (self.x - 1) & 0xFFFF
        self.cc &= ~Z
        if not self.x:
            self.cc |= Z

    def op_clv(self): self.cc &= ~V
    def op_sev(self): self.cc |= V
    def op_clc(self): self.cc &= ~C
    def op_sec(self): self.cc |= C
    def op_sei(self): self.cc |= I

    def op_cli(self):
        i = self.cc & I
        self.cc &= ~I
        if i:
            self.execute_one()                  # pending IRQ not taken until after the next opcode
        self.check_irq_lines()

    def op_sba(self):
        r = (self.a - self.b) & 0xFFFF
        self.cc &= 0xF0
        self.flags8(self.a, self.b, r)
        self.a = r & 0xFF

    def op_cba(self):
        r = (self.a - self.b) & 0xFFFF
        self.cc &= 0xF0
        self.flags8(self.a, self.b, r)

    def op_undoc(self):                         # $12/$13 (MAME): X += (S+1)
        self.x = (self.x + self.rd((self.sp + 1) & 0xFFFF)) & 0xFFFF

    def op_tab(self):
        self.b = self.a
        self.cc &= 0xF1
        self.nz8(self.b)

    def op_tba(self):
        self.a = self.b
        self.cc &= 0xF1
        self.nz8(self.a)

    def op_xgdx(self):
        t = self.x
        self.x = (self.a << 8) | self.b
        self.a, self.b = t >> 8, t & 0xFF

    def op_daa(self):
        a = self.a
        msn, lsn = a & 0xF0, a & 0x0F
        cf = 0
        if lsn > 9 or self.cc & H: cf |= 0x06
        if msn > 0x80 and lsn > 9: cf |= 0x60
        if msn > 0x90 or self.cc & C: cf |= 0x60
        t = cf + a
        self.cc &= 0xF1                          # carry kept
        self.nz8(t & 0xFF)
        self.cc |= (t & 0x100) >> 8
        self.a = t & 0xFF

    def op_slp(self):
        self.wai_state |= SLP_ST
        self.check_irq_lines()
        if self.wai_state & SLP_ST:
            self.eat_cycles()

    def op_aba(self):
        a, b = self.a, self.b
        r = a + b
        self.cc &= 0xD0
        self.flags8(a, b, r)
        self.cc |= ((a ^ b ^ r) & 0x10) << 1
        self.a = r & 0xFF

    def op_branch(self, k):
        d = self.imm8()
        cc = self.cc
        n, v = bool(cc & N), bool(cc & V)
        if k == 0: t = True
        elif k == 1: t = False
        elif k == 2: t = not (cc & 5)
        elif k == 3: t = bool(cc & 5)
        elif k == 4: t = not (cc & C)
        elif k == 5: t = bool(cc & C)
        elif k == 6: t = not (cc & Z)
        elif k == 7: t = bool(cc & Z)
        elif k == 8: t = not v
        elif k == 9: t = v
        elif k == 10: t = not n
        elif k == 11: t = n
        elif k == 12: t = n == v
        elif k == 13: t = n != v
        elif k == 14: t = not (n != v or cc & Z)
        else: t = n != v or bool(cc & Z)
        if t:
            self.pc = (self.pc + (d - 256 if d & 0x80 else d)) & 0xFFFF

    def op_tsx(self): self.x = (self.sp + 1) & 0xFFFF
    def op_ins(self): self.sp = (self.sp + 1) & 0xFFFF
    def op_pula(self): self.a = self.pull()
    def op_pulb(self): self.b = self.pull()
    def op_des(self): self.sp = (self.sp - 1) & 0xFFFF
    def op_txs(self): self.sp = (self.x - 1) & 0xFFFF
    def op_psha(self): self.push(self.a)
    def op_pshb(self): self.push(self.b)
    def op_pulx(self): self.x = self.pullw()
    def op_rts(self): self.pc = self.pullw()
    def op_abx(self): self.x = (self.x + self.b) & 0xFFFF
    def op_pshx(self): self.pushw(self.x)

    def op_rti(self):
        self.cc = self.pull()
        self.b = self.pull()
        self.a = self.pull()
        self.x = self.pullw()
        self.pc = self.pullw()
        self.check_irq_lines()

    def op_mul(self):
        t = self.a * self.b
        self.cc &= ~C
        if t & 0x80:
            self.cc |= C
        self.a, self.b = t >> 8, t & 0xFF

    def op_wai(self):
        self.wai_state |= WAI_ST
        self.push_all()
        self.check_irq_lines()
        if self.wai_state & WAI_ST:
            self.eat_cycles()

    def op_swi(self):
        self.push_all()
        self.cc |= I
        self.pc = self.rd16(0xFFFA)

    # ---- read-modify-write --------------------------------------------
    def unary(self, k, t):
        """$40-$7F style operation on t; returns the result (t for TST)"""
        cc = self.cc
        if k == 0:                               # NEG
            r = (-t) & 0xFFFF
            self.cc = cc & 0xF0
            self.flags8(0, t, r)
            return r & 0xFF
        if k == 3:                               # COM
            r = ~t & 0xFF
            self.cc = (cc & 0xF1) | C
            self.nz8(r)
            return r
        if k == 4:                               # LSR
            self.cc = (cc & 0xF0) | (t & 1)
            r = t >> 1
            if not r:
                self.cc |= Z
            if self.cc & C:
                self.cc |= V
            return r
        if k == 6:                               # ROR
            r = ((cc & C) << 7) | (t >> 1)
            self.cc = (cc & 0xF0) | (t & 1)
            self.nz8(r)
            if self.nxorc():
                self.cc |= V
            return r
        if k == 7:                               # ASR
            self.cc = (cc & 0xF0) | (t & 1)
            r = (t >> 1) | (t & 0x80)
            self.nz8(r)
            if self.nxorc():
                self.cc |= V
            return r
        if k == 8:                               # ASL
            r = t << 1
            self.cc = cc & 0xF0
            self.flags8(t, t, r)
            return r & 0xFF
        if k == 9:                               # ROL
            r = (cc & C) | (t << 1)
            self.cc = cc & 0xF0
            self.flags8(t, t, r)
            return r & 0xFF
        if k == 0xA:                             # DEC
            r = (t - 1) & 0xFF
            self.cc = (cc & 0xF1) | ((r & 0x80) >> 4) | (Z if r == 0 else 0) | (V if r == 0x7F else 0)
            return r
        if k == 0xC:                             # INC
            r = (t + 1) & 0xFF
            self.cc = (cc & 0xF1) | ((r & 0x80) >> 4) | (Z if r == 0 else 0) | (V if r == 0x80 else 0)
            return r
        if k == 0xD:                             # TST
            self.cc = cc & 0xF0
            self.nz8(t)
            return t
        if k == 0xF:                             # CLR
            self.cc = (cc & 0xF0) | Z
            return 0
        raise AssertionError(k)

    def op_unary_mem(self, k, ea):
        a = ea()
        t = self.rd(a)                           # CLR reads too (MAME: RM then WM)
        r = self.unary(k, t)
        if k != 0xD:
            self.wr(a, r)

    def op_imm_mem(self, k, ea):                 # AIM OIM EIM TIM: #imm, then the address
        m = self.imm8()
        a = ea()
        r = self.rd(a)
        r = r | m if k == 2 else (r ^ m if k == 5 else r & m)
        self.cc &= 0xF1
        self.nz8(r)
        if k != 0xB:
            self.wr(a, r)

    # ---- accumulator / 16 bit -----------------------------------------
    def op_alu(self, k, ea, acc_b):
        t = self.imm8() if ea is None else self.rd(ea())
        r0 = self.b if acc_b else self.a
        cc = self.cc
        if k in (0, 1, 2):                       # SUB CMP SBC
            r = (r0 - t - (cc & C if k == 2 else 0)) & 0xFFFF
            self.cc = cc & 0xF0
            self.flags8(r0, t, r)
            if k == 1:
                return
            r &= 0xFF
        elif k in (9, 0xB):                      # ADC ADD
            r = r0 + t + (cc & C if k == 9 else 0)
            self.cc = cc & 0xD0
            self.flags8(r0, t, r)
            self.cc |= ((r0 ^ t ^ r) & 0x10) << 1
            r &= 0xFF
        else:                                    # AND BIT LDA EOR ORA
            r = r0 & t if k in (4, 5) else (t if k == 6 else (r0 ^ t if k == 8 else r0 | t))
            self.cc = cc & 0xF1
            self.nz8(r)
            if k == 5:
                return
        if acc_b:
            self.b = r
        else:
            self.a = r

    def op_st8(self, ea, acc_b):
        v = self.b if acc_b else self.a
        self.cc &= 0xF1
        self.nz8(v)
        self.wr(ea(), v)

    def word(self, ea):
        return self.imm16() if ea is None else self.rd16(ea())

    def op_d16(self, ea, sub):                   # SUBD / ADDD
        b = self.word(ea)
        d = (self.a << 8) | self.b
        r = (d - b) & 0xFFFFFFFF if sub else d + b
        self.cc &= 0xF0
        self.flags16(d, b, r)
        self.a, self.b = (r >> 8) & 0xFF, r & 0xFF

    def op_cpx(self, ea):
        b = self.word(ea)
        r = (self.x - b) & 0xFFFFFFFF
        self.cc &= 0xF0
        self.flags16(self.x, b, r)

    def op_ldd(self, ea):
        d = self.word(ea)
        self.a, self.b = d >> 8, d & 0xFF
        self.cc &= 0xF1
        self.nz16(d)

    def op_std(self, ea):
        a = ea()
        d = (self.a << 8) | self.b
        self.cc &= 0xF1
        self.nz16(d)
        self.wr16(a, d)

    def op_ld16(self, ea, reg):
        v = self.word(ea)
        setattr(self, reg, v)
        self.cc &= 0xF1
        self.nz16(v)

    def op_st16(self, ea, reg):
        v = getattr(self, reg)
        self.cc &= 0xF1
        self.nz16(v)
        self.wr16(ea(), v)

    def op_jsr(self, ea):
        a = ea()
        self.pushw(self.pc)
        self.pc = a

    def op_bsr(self):
        d = self.imm8()
        self.pushw(self.pc)
        self.pc = (self.pc + (d - 256 if d & 0x80 else d)) & 0xFFFF
