"""Reference Intel 8080 interpreter — the CPU of Namco's "System 16" board (geebee, warpwarp, navarone, ...).

Transliterated from `src/devices/cpu/i8085/i8085.cpp` of MAME 0.269 (the machine these ports are checked against),
in the variant the core runs for an `i8080_cpu_device`: `is_8085()` is false, so the 8085's RIM/SIM, its
undocumented opcodes (DSUB, ARHL, RDEL, LDHI, LDSI, SHLX, RSTV, JX5/JNX5, LHLX) and its interrupt mask register are
not executed, and `execute_input_lines()` is 1 — the only interrupt source this board has is INTR.

Things worth knowing before reading the code, because they are what a port gets wrong:

  * Interrupts.  `I8080(...)` connects no INTA callback, so the acknowledge goes through MAME's
    `device_execute_interface::standard_irq_callback()` to `execute_default_irq_vector()`, which is 0xFF
    (i8085.h).  The board really does put 0xFF on the bus, so the byte is taken as an opcode: `RST 7`, entering at
    0x0038 after 11 cycles.  That is the whole interrupt contract of the board.
  * INR/DCR change the flag register here (only the carry is carried over, and DCR sets bit 1) even though the
    datasheet says they leave it alone.  It is what the reference machine does, so it is what the games run under.
  * The flag register is MAME's 8085 layout: S Z K H X3 P V C.  On the 8080 the K and X3 bits are dead, P is parity
    of the result (the 8080's bit 2 is supposed to be a constant 1 — the core uses it as parity, which is what makes
    RPO/RPE/RPO-branching behave the way the games were played against), and V is set by DCR/SUB/SBB/CMP and by
    PUSH AF (`case 0xf5`: V is forced to 1 and K to 0 before the push, for an 8080).
  * Cycles are the 8080 table (real T-states) with `jmp_taken()` 0, `call_taken()` 6 and `ret_taken()` 6 — so a
    not-taken conditional jump costs as much as a taken one, which only ever matters to the renderer's timing.
  * An `EI` enables interrupts only for the instruction after the next one (`m_after_ei = 2`), and `HALT` re-executes
    itself (PC is pulled back one) until an interrupt breaks it out.

Memory goes through the machine's `rd8`/`wr8`; `inta()` returns the acknowledge byte (0xFF on this board) and
`io_in`/`io_out` are the IN/OUT space, which the board maps for geebee (`geebee_port_map`) and leaves unconnected
for the colour games.
"""

SF, ZF, KF, HF, X3F, PF, VF, CF = 0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01
IM_IE = 0x08                                      # the one bit of the 8085's IM register the 8080 uses

# MAME's i8085a_cpu_device::lut_cycles_8080, verbatim.
CYCLES = bytes((
    4, 10, 7, 5, 5, 5, 7, 4, 4, 10, 7, 5, 5, 5, 7, 4,
    4, 10, 7, 5, 5, 5, 7, 4, 4, 10, 7, 5, 5, 5, 7, 4,
    4, 10, 16, 5, 5, 5, 7, 4, 4, 10, 16, 5, 5, 5, 7, 4,
    4, 10, 13, 5, 10, 10, 10, 4, 4, 10, 13, 5, 5, 5, 7, 4,
    5, 5, 5, 5, 5, 5, 7, 5, 5, 5, 5, 5, 5, 5, 7, 5,
    5, 5, 5, 5, 5, 5, 7, 5, 5, 5, 5, 5, 5, 5, 7, 5,
    5, 5, 5, 5, 5, 5, 7, 5, 5, 5, 5, 5, 5, 5, 7, 5,
    7, 7, 7, 7, 7, 7, 7, 7, 5, 5, 5, 5, 5, 5, 7, 5,
    4, 4, 4, 4, 4, 4, 7, 4, 4, 4, 4, 4, 4, 4, 7, 4,
    4, 4, 4, 4, 4, 4, 7, 4, 4, 4, 4, 4, 4, 4, 7, 4,
    4, 4, 4, 4, 4, 4, 7, 4, 4, 4, 4, 4, 4, 4, 7, 4,
    4, 4, 4, 4, 4, 4, 7, 4, 4, 4, 4, 4, 4, 4, 7, 4,
    5, 10, 10, 10, 11, 11, 7, 11, 5, 10, 10, 10, 11, 11, 7, 11,
    5, 10, 10, 10, 11, 11, 7, 11, 5, 10, 10, 10, 11, 11, 7, 11,
    5, 10, 10, 18, 11, 11, 7, 11, 5, 5, 10, 4, 11, 11, 7, 11,
    5, 10, 10, 4, 11, 11, 7, 11, 5, 5, 10, 4, 11, 11, 7, 11,
))

JMP_TAKEN, CALL_TAKEN, RET_TAKEN = 0, 6, 6       # i8080_cpu_device's override (ret_taken is the 8085's)

PARITY = bytearray(PF if bin(i).count("1") % 2 == 0 else 0 for i in range(256))
ZS = bytearray((ZF if i == 0 else 0) | (SF if i & 0x80 else 0) for i in range(256))
ZSP = bytes(ZS[i] | PARITY[i] for i in range(256))         # MAME's lut_zsp


class I8080:
    """The 8080 as MAME 0.269 runs it.  The machine supplies the memory and the interrupt acknowledge."""

    def __init__(self, rd8, wr8, inta=None, io_in=None, io_out=None):
        self.rd8 = rd8
        self.wr8 = wr8
        self.inta = inta or (lambda: 0xFF)                 # the byte the interrupting device puts on the bus
        self.io_in = io_in or self._io_unmapped
        self.io_out = io_out or self._io_unmapped
        self.reset()

    def _io_unmapped(self, *a):
        raise RuntimeError("I8080: IN/OUT on a board with no I/O space mapped")

    def reset(self):
        self.a = self.f = self.b = self.c = self.d = self.e = self.h = self.l = 0
        self.pc = self.sp = 0
        self.halt = False
        self.im = 0                                        # only IM_IE is used on an 8080
        self.after_ei = 0
        self.irq_state = 0                                 # INTR level, set by the machine
        self.in_acknowledge = False
        self.cycles = 0

    # --- register pairs, as MAME's PAIR members behave ---------------------------------------------------------
    @property
    def bc(self):
        return (self.b << 8) | self.c

    @bc.setter
    def bc(self, v):
        self.b, self.c = (v >> 8) & 0xFF, v & 0xFF

    @property
    def de(self):
        return (self.d << 8) | self.e

    @de.setter
    def de(self, v):
        self.d, self.e = (v >> 8) & 0xFF, v & 0xFF

    @property
    def hl(self):
        return (self.h << 8) | self.l

    @hl.setter
    def hl(self, v):
        self.h, self.l = (v >> 8) & 0xFF, v & 0xFF

    @property
    def af(self):
        return (self.a << 8) | self.f

    @af.setter
    def af(self, v):
        self.a, self.f = (v >> 8) & 0xFF, v & 0xFF

    def state(self):
        """(pc, sp, af, bc, de, hl, ie, halt) — what a snapshot of MAME's CPU looks like."""
        return (self.pc, self.sp, self.af, self.bc, self.de, self.hl, self.im & IM_IE, self.halt)

    # --- fetch and stack (MAME's read_op/read_arg/read_arg16/op_push/op_pop) -----------------------------------
    def read_op(self):
        v = self.rd8(self.pc)
        self.pc = (self.pc + 1) & 0xFFFF
        return v

    def read_arg(self):
        if self.in_acknowledge:
            return self.inta()
        return self.read_op()

    def read_arg16(self):
        if self.in_acknowledge:
            return self.inta() | (self.inta() << 8)
        return self.read_arg() | (self.read_arg() << 8)

    def op_push(self, p):
        self.sp = (self.sp - 1) & 0xFFFF
        self.wr8(self.sp, (p >> 8) & 0xFF)
        self.sp = (self.sp - 1) & 0xFFFF
        self.wr8(self.sp, p & 0xFF)

    def op_pop(self):
        p = self.rd8(self.sp)
        self.sp = (self.sp + 1) & 0xFFFF
        p |= self.rd8(self.sp) << 8
        self.sp = (self.sp + 1) & 0xFFFF
        return p

    # --- the ALU (MAME's op_*) ---------------------------------------------------------------------------------
    def op_ora(self, v):
        self.a = (self.a | v) & 0xFF
        self.f = ZSP[self.a]

    def op_xra(self, v):
        self.a ^= v
        self.f = ZSP[self.a]

    def op_ana(self, v):
        hc = ((self.a | v) << 1) & HF                  # the 8080 branch: half-carry out of the OR of the operands
        self.a &= v
        self.f = ZSP[self.a] | hc

    def op_inr(self, v):
        hc = HF if (v & 0x0F) == 0x0F else 0
        v = (v + 1) & 0xFF
        self.f = (self.f & CF) | ZSP[v] | hc
        return v

    def op_dcr(self, v):
        hc = HF if (v & 0x0F) != 0 else 0
        v = (v - 1) & 0xFF
        self.f = (self.f & CF) | ZSP[v] | hc | VF
        return v

    def op_add(self, v):
        q = self.a + v
        self.f = ZSP[q & 0xFF] | ((q >> 8) & CF) | ((self.a ^ q ^ v) & HF)
        self.a = q & 0xFF

    def op_adc(self, v):
        q = self.a + v + (self.f & CF)
        self.f = ZSP[q & 0xFF] | ((q >> 8) & CF) | ((self.a ^ q ^ v) & HF)
        self.a = q & 0xFF

    def op_sub(self, v):
        q = self.a - v
        self.f = ZSP[q & 0xFF] | ((q >> 8) & CF) | (~(self.a ^ q ^ v) & HF) | VF
        self.a = q & 0xFF

    def op_sbb(self, v):
        q = self.a - v - (self.f & CF)
        self.f = ZSP[q & 0xFF] | ((q >> 8) & CF) | (~(self.a ^ q ^ v) & HF) | VF
        self.a = q & 0xFF

    def op_cmp(self, v):
        q = self.a - v
        self.f = ZSP[q & 0xFF] | ((q >> 8) & CF) | (~(self.a ^ q ^ v) & HF) | VF

    def op_dad(self, v):
        q = self.hl + v
        self.f = (self.f & ~CF) | ((q >> 16) & CF)
        self.hl = q & 0xFFFF

    # --- jumps (MAME's op_jmp/op_call/op_ret/op_rst; the taken adjustments are the 8080 ones) --------------------
    def op_jmp(self, cond):
        if cond:
            self.cycles -= JMP_TAKEN
            self.pc = self.read_arg16()
        else:
            self.pc = (self.pc + 2) & 0xFFFF

    def op_call(self, cond):
        if cond:
            p = self.read_arg16()
            self.cycles -= CALL_TAKEN
            self.op_push(self.pc)
            self.pc = p
        else:
            self.pc = (self.pc + 2) & 0xFFFF

    def op_ret(self, cond):
        if cond:
            self.cycles -= RET_TAKEN
            self.pc = self.op_pop()

    def op_rst(self, v):
        self.op_push(self.pc)
        self.pc = 8 * v

    # --- the loop (MAME's execute_run / check_for_interrupts / break_halt_for_interrupt) ------------------------
    def break_halt_for_interrupt(self):
        if self.halt:
            self.pc = (self.pc + 1) & 0xFFFF
            self.halt = False
        self.in_acknowledge = True

    def check_for_interrupts(self):
        if not self.irq_state or not (self.im & IM_IE):
            return False
        self.break_halt_for_interrupt()
        vector = self.inta()
        self.im &= ~IM_IE
        self.execute_one(vector)
        return True

    def run(self, cycles):
        """Run for `cycles` T-states, sampling INTR between instructions exactly where MAME does."""
        self.cycles = cycles
        if self.after_ei == 0:
            self.check_for_interrupts()
        while True:
            if self.after_ei != 0:
                self.after_ei -= 1
                if self.after_ei == 0:
                    self.check_for_interrupts()
            self.in_acknowledge = False
            self.execute_one(self.read_op())
            if self.cycles <= 0:
                return

    def step(self):
        """One instruction, INTR sampled first as MAME's loop does (what a coverage run wraps)."""
        self.cycles = 1
        if self.after_ei == 0:
            if self.check_for_interrupts():
                self.cycles = 1                  # an interrupt ran a whole instruction; keep `step` one-for-one
        if self.after_ei != 0:
            self.after_ei -= 1
            if self.after_ei == 0:
                self.check_for_interrupts()
        self.in_acknowledge = False
        self.execute_one(self.read_op())

    def set_irq(self, state):
        self.irq_state = 1 if state else 0

    # --- execute_one ----------------------------------------------------------------------------------------------
    def execute_one(self, op):
        self.cycles -= CYCLES[op]
        z = 0                                              # MAME's m_WZ, the operand/temporary of the switch

        if op < 0x40:
            if op == 0x00:  pass                                       # NOP
            elif op == 0x01: self.bc = self.read_arg16()               # LXI B,nn
            elif op == 0x02: self.wr8(self.bc, self.a)                 # STAX B
            elif op == 0x03: self.bc = (self.bc + 1) & 0xFFFF          # INX B
            elif op == 0x04: self.b = self.op_inr(self.b)
            elif op == 0x05: self.b = self.op_dcr(self.b)
            elif op == 0x06: self.b = self.read_arg()
            elif op == 0x07:                                          # RLC
                self.a = ((self.a << 1) | (self.a >> 7)) & 0xFF
                self.f = (self.f & 0xFE) | (self.a & CF)
            elif op == 0x08: pass                                      # (8085 DSUB) undocumented NOP
            elif op == 0x09: self.op_dad(self.bc)
            elif op == 0x0A: self.a = self.rd8(self.bc)
            elif op == 0x0B: self.bc = (self.bc - 1) & 0xFFFF
            elif op == 0x0C: self.c = self.op_inr(self.c)
            elif op == 0x0D: self.c = self.op_dcr(self.c)
            elif op == 0x0E: self.c = self.read_arg()
            elif op == 0x0F:                                          # RRC
                self.f = (self.f & 0xFE) | (self.a & CF)
                self.a = ((self.a >> 1) | (self.a << 7)) & 0xFF
            elif op == 0x10: pass                                      # (8085 ARHL) undocumented NOP
            elif op == 0x11: self.de = self.read_arg16()
            elif op == 0x12: self.wr8(self.de, self.a)
            elif op == 0x13: self.de = (self.de + 1) & 0xFFFF
            elif op == 0x14: self.d = self.op_inr(self.d)
            elif op == 0x15: self.d = self.op_dcr(self.d)
            elif op == 0x16: self.d = self.read_arg()
            elif op == 0x17:                                          # RAL
                c = self.f & CF
                self.f = (self.f & 0xFE) | (self.a >> 7)
                self.a = ((self.a << 1) | c) & 0xFF
            elif op == 0x18: pass                                      # (8085 RDEL) undocumented NOP
            elif op == 0x19: self.op_dad(self.de)
            elif op == 0x1A: self.a = self.rd8(self.de)
            elif op == 0x1B: self.de = (self.de - 1) & 0xFFFF
            elif op == 0x1C: self.e = self.op_inr(self.e)
            elif op == 0x1D: self.e = self.op_dcr(self.e)
            elif op == 0x1E: self.e = self.read_arg()
            elif op == 0x1F:                                          # RAR
                c = (self.f & CF) << 7
                self.f = (self.f & 0xFE) | (self.a & CF)
                self.a = ((self.a >> 1) | c) & 0xFF
            elif op == 0x20: pass                                      # (8085 RIM) undocumented NOP
            elif op == 0x21: self.hl = self.read_arg16()
            elif op == 0x22:                                          # SHLD nn
                z = self.read_arg16()
                self.wr8(z, self.l)
                self.wr8((z + 1) & 0xFFFF, self.h)
            elif op == 0x23: self.hl = (self.hl + 1) & 0xFFFF
            elif op == 0x24: self.h = self.op_inr(self.h)
            elif op == 0x25: self.h = self.op_dcr(self.h)
            elif op == 0x26: self.h = self.read_arg()
            elif op == 0x27:                                          # DAA
                z = self.a
                if (self.f & HF) or ((self.a & 0x0F) > 9):
                    z += 6
                if (self.f & CF) or (self.a > 0x99):
                    z += 0x60
                z &= 0xFF
                self.f = ((self.f & 0x23) | (1 if self.a > 0x99 else 0) |
                          ((self.a ^ z) & HF) | ZSP[z]) & 0xFF
                self.a = z
            elif op == 0x28: pass                                      # (8085 LDHI) undocumented NOP
            elif op == 0x29: self.op_dad(self.hl)
            elif op == 0x2A:                                          # LHLD nn
                z = self.read_arg16()
                self.l = self.rd8(z)
                self.h = self.rd8((z + 1) & 0xFFFF)
            elif op == 0x2B: self.hl = (self.hl - 1) & 0xFFFF
            elif op == 0x2C: self.l = self.op_inr(self.l)
            elif op == 0x2D: self.l = self.op_dcr(self.l)
            elif op == 0x2E: self.l = self.read_arg()
            elif op == 0x2F: self.a ^= 0xFF                            # CMA (the 8085's V is 8085-only)
            elif op == 0x30: pass                                      # (8085 SIM) undocumented NOP
            elif op == 0x31: self.sp = self.read_arg16()               # LXI SP,nn
            elif op == 0x32:                                          # STA nn
                z = self.read_arg16()
                self.wr8(z, self.a)
            elif op == 0x33: self.sp = (self.sp + 1) & 0xFFFF
            elif op == 0x34:
                z = self.op_inr(self.rd8(self.hl))
                self.wr8(self.hl, z)
            elif op == 0x35:
                z = self.op_dcr(self.rd8(self.hl))
                self.wr8(self.hl, z)
            elif op == 0x36:
                z = self.read_arg()
                self.wr8(self.hl, z)
            elif op == 0x37: self.f = (self.f & 0xFE) | CF             # STC
            elif op == 0x38: pass                                      # (8085 LDSI) undocumented NOP
            elif op == 0x39: self.op_dad(self.sp)
            elif op == 0x3A:
                z = self.read_arg16()
                self.a = self.rd8(z)
            elif op == 0x3B: self.sp = (self.sp - 1) & 0xFFFF
            elif op == 0x3C: self.a = self.op_inr(self.a)
            elif op == 0x3D: self.a = self.op_dcr(self.a)
            elif op == 0x3E: self.a = self.read_arg()
            elif op == 0x3F: self.f = (self.f & 0xFE) | (~self.f & CF)  # CMC

        elif op < 0x80:                                                  # MOV
            if op == 0x76:                                             # HLT
                self.pc = (self.pc - 1) & 0xFFFF
                self.halt = True
            else:
                dst, src = (op >> 3) & 7, op & 7
                if dst == 7:
                    self.wr8(self.hl, self.a if src == 7 else self._r8(src))
                else:
                    self._w8(dst, self.a if src == 7 else self._r8(src))

        elif op < 0xC0:                                                  # ALU op r
            src = op & 7
            v = self.rd8(self.hl) if src == 7 else self._r8(src)
            (self.op_add, self.op_adc, self.op_sub, self.op_sbb,
             self.op_ana, self.op_xra, self.op_ora, self.op_cmp)[(op >> 3) & 7](v)

        else:
            f = self.f
            if op == 0xC0: self.op_ret(not (f & ZF))                     # RNZ
            elif op == 0xC1: self.bc = self.op_pop()
            elif op == 0xC2: self.op_jmp(not (f & ZF))                   # JNZ
            elif op == 0xC3: self.op_jmp(True)                           # JMP
            elif op == 0xC4: self.op_call(not (f & ZF))                  # CNZ
            elif op == 0xC5: self.op_push(self.bc)
            elif op == 0xC6:
                z = self.read_arg()
                self.op_add(z)
            elif op == 0xC7: self.op_rst(0)
            elif op == 0xC8: self.op_ret(f & ZF)                         # RZ
            elif op == 0xC9: self.pc = self.op_pop()                     # RET
            elif op == 0xCA: self.op_jmp(f & ZF)                         # JZ
            elif op == 0xCB: self.op_jmp(True)                           # undocumented JMP nn (8085: RSTV)
            elif op == 0xCC: self.op_call(f & ZF)                        # CZ
            elif op == 0xCD: self.op_call(True)                          # CALL
            elif op == 0xCE:
                z = self.read_arg()
                self.op_adc(z)
            elif op == 0xCF: self.op_rst(1)
            elif op == 0xD0: self.op_ret(not (f & CF))                   # RNC
            elif op == 0xD1: self.de = self.op_pop()
            elif op == 0xD2: self.op_jmp(not (f & CF))                   # JNC
            elif op == 0xD3:                                            # OUT nn
                z = self.read_arg()
                self.io_out(z, self.a)
            elif op == 0xD4: self.op_call(not (f & CF))                  # CNC
            elif op == 0xD5: self.op_push(self.de)
            elif op == 0xD6:
                z = self.read_arg()
                self.op_sub(z)
            elif op == 0xD7: self.op_rst(2)
            elif op == 0xD8: self.op_ret(f & CF)                         # RC
            elif op == 0xD9: self.pc = self.op_pop()                     # undocumented RET (8085: SHLX)
            elif op == 0xDA: self.op_jmp(f & CF)                         # JC
            elif op == 0xDB:                                            # IN nn
                z = self.read_arg()
                self.a = self.io_in(z)
            elif op == 0xDC: self.op_call(f & CF)                        # CC
            elif op == 0xDD: self.op_call(True)                          # undocumented CALL nn (8085: JNX5)
            elif op == 0xDE:
                z = self.read_arg()
                self.op_sbb(z)
            elif op == 0xDF: self.op_rst(3)
            elif op == 0xE0: self.op_ret(not (f & PF))                   # RPO
            elif op == 0xE1: self.hl = self.op_pop()
            elif op == 0xE2: self.op_jmp(not (f & PF))                   # JPO
            elif op == 0xE3:                                            # XTHL
                z = self.op_pop()
                self.op_push(self.hl)
                self.hl = z
            elif op == 0xE4: self.op_call(not (f & PF))                  # CPO
            elif op == 0xE5: self.op_push(self.hl)
            elif op == 0xE6:
                z = self.read_arg()
                self.op_ana(z)
            elif op == 0xE7: self.op_rst(4)
            elif op == 0xE8: self.op_ret(f & PF)                         # RPE
            elif op == 0xE9: self.pc = self.hl                           # PCHL
            elif op == 0xEA: self.op_jmp(f & PF)                         # JPE
            elif op == 0xEB:                                            # XCHG
                z = self.de
                self.de = self.hl
                self.hl = z
            elif op == 0xEC: self.op_call(f & PF)                        # CPE
            elif op == 0xED: self.op_call(True)                          # undocumented CALL nn (8085: LHLX)
            elif op == 0xEE:
                z = self.read_arg()
                self.op_xra(z)
            elif op == 0xEF: self.op_rst(5)
            elif op == 0xF0: self.op_ret(not (f & SF))                   # RP
            elif op == 0xF1: self.af = self.op_pop()
            elif op == 0xF2: self.op_jmp(not (f & SF))                   # JP
            elif op == 0xF3: self.im &= ~IM_IE                           # DI
            elif op == 0xF4: self.op_call(not (f & SF))                  # CP
            elif op == 0xF5:                                            # PUSH PSW: X3=0, and for the 8080 V=1 K=0
                self.f = (self.f & ~X3F & ~KF) | VF
                self.op_push(self.af)
            elif op == 0xF6:
                z = self.read_arg()
                self.op_ora(z)
            elif op == 0xF7: self.op_rst(6)
            elif op == 0xF8: self.op_ret(f & SF)                         # RM
            elif op == 0xF9: self.sp = self.hl                           # SPHL
            elif op == 0xFA: self.op_jmp(f & SF)                         # JM
            elif op == 0xFB:                                            # EI: live after the next instruction
                self.im |= IM_IE
                self.after_ei = 2
            elif op == 0xFC: self.op_call(f & SF)                        # CM
            elif op == 0xFD: self.op_call(True)                          # undocumented CALL nn (8085: JX5)
            elif op == 0xFE:
                z = self.read_arg()
                self.op_cmp(z)
            elif op == 0xFF: self.op_rst(7)

    def _r8(self, i):
        return (self.b, self.c, self.d, self.e, self.h, self.l, None, self.a)[i]

    def _w8(self, i, v):
        v &= 0xFF
        if i == 0:   self.b = v
        elif i == 1: self.c = v
        elif i == 2: self.d = v
        elif i == 3: self.e = v
        elif i == 4: self.h = v
        elif i == 5: self.l = v
        elif i == 7: self.a = v
