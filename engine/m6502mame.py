"""The NMOS 6502 as MAME 0.289 runs it (src/devices/cpu/m6502/m6502.cpp, m6502.h, om6502.lst; BSD-3-Clause,
copyright-holders Olivier Galibert): bus access for bus access and cycle exact against MAME's scheduler, for boards
that must follow MAME instruction for instruction (Gauntlet's sound CPU, MAME's atari/gauntlet.cpp).

MAME's core counts one cycle per bus access, dummy reads and the read-modify-write instructions' second (dummy)
write included: the access happens, then m_icount--, and the core returns from execute_run() when icount <= 0; the
rest of the instruction runs in the next time slice (do_exec_partial; its accesses see the state of that slice).
Every instruction ends with the prefetch of the next opcode (prefetch_start; m_IR = read_sync(PC); prefetch_end), so
an instruction's last cycle is the next opcode's fetch and the interrupt lines are sampled in prefetch_end, after the
fetch, i.e. possibly at the start of the next slice: an NMI that is pending (edge triggered, set in
execute_set_input) or an IRQ line that is held while I is clear makes the CPU keep PC, set m_irq_taken and run
m_IR = 0 (BRK) as the interrupt sequence (brk_imp: a dummy read, three pushes, the vector, I set, the prefetch at the
vector; an NMI pending by the time of the vector fetch takes $FFFA even in an IRQ or BRK sequence: the 6502 bug MAME
reproduces).  CLI, SEI and PLP change I after their prefetch, so the next instruction's sampling still sees the old
I (RTI sets P before its prefetch).  The opcode bodies are generated from om6502.lst (engine/m6502mame_gen.py ->
engine/m6502mame_ops.py) as Python generators that yield at those points; this file holds the registers, m6502.cpp's
helpers (NMOS decimal mode of ADC/SBC/ARR as MAME computes it) and the run loop of execute_run().

Interface (as engine/z80mame.py): M6502Mame(rd8, wr8, irq_ack=None); rd8(addr) -> byte for every read (opcode,
operand, data, dummy: one program space, no decrypted opcodes), wr8(addr, value).  run(n) sets icount = n and runs
until icount <= 0 after an access (returns n - icount; every access is one cycle, so a run ends exactly at n, or
one past the access that called abort()); executed() = cycles done in this run as MAME's machine().time() sees
them during an access (n - icount: the access's own cycle is not counted yet); abort() = abort_timeslice (icount ->
0 after the current access, returns the swallowed cycles); set_input("irq"|"nmi"|"so", state, total_cycles) =
execute_set_input (an NMI / SO edge at total_cycles 0 is not taken); reset() = device_reset (the next run does the
reset sequence: two dummy reads at PC, three dummy stack reads, I set, the vector at $FFFC, the prefetch; A X Y P S
keep their values, power on is A=0 X=$80 Y=0 P=$36 S=$0100 as device_start sets them); total: cycles of finished
runs (run() adds to it; MAME's totalcycles, which the reset of the device does not clear by itself - the board's
reset does, as device_execute_interface::interface_pre_reset); hook: called before each instruction (MAME's
debugger_instruction_hook, with NPC = the instruction's address; not called for the reset sequence; called at the
interrupted instruction's address for an IRQ/NMI sequence, as MAME's trace shows it).  irq_ack(line) is called as
standard_irq_callback ("irq" / "nmi") inside the sequence before the vector reads.

The bodies come from the vendored MAME source (F030Arcade's copy, 0.286 with local changes); the behaviour was
checked against the installed MAME 0.289 binary by engine/m6502mame_test.py: hand-made programs (cycle counts, page crossings, the dummy accesses' cycles
and addresses, slices ending inside instructions, BRK/RTI/IRQ/NMI, ADC/SBC in both modes against m6502.cpp's
formulas) and MAME 0.289's gauntlet: every bus access (address, data, cycle) and every instruction (totalcycles and
registers) of the sound CPU from its release from reset, the I/O reads and the interrupts replayed from MAME's log.
"""
from m6502mame_ops import OPS, RESET

F_N, F_V, F_E, F_B, F_D, F_I, F_Z, F_C = 0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01


class M6502Mame:
    def __init__(self, rd8, wr8, irq_ack=None):
        self.rd = rd8
        self.wr = wr8
        self.irq_ack_cb = irq_ack
        self.hook = None
        self.icount = 0
        self.n = 0
        self.total = 0
        # device_start (init)
        self.PPC = self.PC = self.NPC = 0
        self.A, self.X, self.Y, self.P = 0x00, 0x80, 0x00, 0x36
        self.SP = 0x0100
        self.TMP = self.TMP2 = 0
        self.IR = 0
        self.nmi_state = self.irq_state = self.v_state = 0
        self.nmi_pending = self.irq_taken = 0
        self.sync = 0
        self.inhibit = 0
        self.reset()

    # ---- device_reset / lines ------------------------------------------------------------------------------
    def reset(self):
        self.in_reset = True             # m_inst_state = STATE_RESET
        self.nmi_pending = self.irq_taken = 0
        self.sync = 0
        self.inhibit = 0
        self.loop = self._loop()         # m_inst_substate = 0: an interrupted instruction is dropped

    def set_input(self, line, state, total_cycles=1):
        """execute_set_input; total_cycles: the device's total_cycles() (edges at 0, the reset's moment, are not
        taken)"""
        state = 1 if state else 0
        if line == "irq":
            self.irq_state = state
        elif line == "nmi":
            if not self.nmi_state and state and total_cycles:
                self.nmi_pending = 1
            self.nmi_state = state
        elif line == "so":
            if not self.v_state and state and total_cycles:
                self.P |= F_V
            self.v_state = state
        else:
            raise ValueError(line)

    # ---- the scheduler's protocol --------------------------------------------------------------------------
    def run(self, n):
        self.icount = n
        self.n = n
        if n > 0:
            next(self.loop)
        ran = self.n - self.icount
        self.total += ran
        return ran

    def executed(self):
        return self.n - self.icount

    def total_cycles(self):
        """MAME's total_cycles() (inside a run: the finished runs plus this one so far)"""
        return self.total + self.n - self.icount

    def abort(self):
        """abort_timeslice: the remaining cycles are swallowed (returns them: MAME's cycles_stolen)"""
        k = self.icount
        if k > 0:
            self.n -= k
            self.icount = 0
            return k
        return 0

    def irq_ack(self, line):
        if self.irq_ack_cb is not None:
            self.irq_ack_cb(line)

    # ---- execute_run ------------------------------------------------------------------------------------------
    def _loop(s):
        ops = OPS
        while True:
            while s.icount <= 0:
                yield
            if s.in_reset:
                s.in_reset = False
                yield from RESET(s)
                continue
            s.PPC = s.NPC
            if s.hook is not None:
                s.hook()
            yield from ops[s.IR](s)

    # ---- registers as MAME's state shows them ----------------------------------------------------------------
    def regs(self):
        """(pc, a, x, y, p, sp) with pc = NPC (the debugger's PC)"""
        return (self.NPC, self.A, self.X, self.Y, self.P, self.SP)

    # ---- m6502.cpp's helpers ----------------------------------------------------------------------------------
    def do_adc(self, val):
        if self.P & F_D:
            self.do_adc_d(val)
        else:
            self.do_adc_nd(val)

    def do_adc_nd(self, val):
        a = self.A
        s = a + val + (self.P & F_C)
        p = self.P & ~(F_N | F_V | F_Z | F_C)
        if not s & 0xFF:
            p |= F_Z
        elif s & 0x80:
            p |= F_N
        if ~(a ^ val) & (a ^ s) & 0x80:
            p |= F_V
        if s & 0xFF00:
            p |= F_C
        self.P = p
        self.A = s & 0xFF

    def do_adc_d(self, val):
        a = self.A
        c = self.P & F_C
        p = self.P & ~(F_N | F_V | F_Z | F_C)
        al = ((a & 15) + (val & 15) + c) & 0xFF
        if al > 9:
            al = (al + 6) & 0xFF
        ah = ((a >> 4) + (val >> 4) + (1 if al > 15 else 0)) & 0xFF
        if not (a + val + c) & 0xFF:
            p |= F_Z
        elif ah & 8:
            p |= F_N
        if ~(a ^ val) & (a ^ (ah << 4)) & 0x80:
            p |= F_V
        if ah > 9:
            ah = (ah + 6) & 0xFF
        if ah > 15:
            p |= F_C
        self.P = p
        self.A = ((ah << 4) | (al & 15)) & 0xFF

    def do_sbc(self, val):
        if self.P & F_D:
            self.do_sbc_d(val)
        else:
            self.do_sbc_nd(val)

    def do_sbc_nd(self, val):
        a = self.A
        d = (a - val - (0 if self.P & F_C else 1)) & 0xFFFF
        p = self.P & ~(F_N | F_V | F_Z | F_C)
        if not d & 0xFF:
            p |= F_Z
        elif d & 0x80:
            p |= F_N
        if (a ^ val) & (a ^ d) & 0x80:
            p |= F_V
        if not d & 0xFF00:
            p |= F_C
        self.P = p
        self.A = d & 0xFF

    def do_sbc_d(self, val):
        a = self.A
        c = 0 if self.P & F_C else 1
        p = self.P & ~(F_N | F_V | F_Z | F_C)
        d = (a - val - c) & 0xFFFF
        al = ((a & 15) - (val & 15) - c) & 0xFF
        ah = ((a >> 4) - (val >> 4) - (1 if al & 0x80 else 0)) & 0xFF
        if not d & 0xFF:
            p |= F_Z
        elif d & 0x80:
            p |= F_N
        if (a ^ val) & (a ^ d) & 0x80:
            p |= F_V
        if not d & 0xFF00:
            p |= F_C
        if al & 0x80:
            al = (al - 6) & 0xFF
        if ah & 0x80:
            ah = (ah - 6) & 0xFF
        self.P = p
        self.A = ((ah << 4) | (al & 15)) & 0xFF

    def do_arr(self):
        if self.P & F_D:
            self.do_arr_d()
        else:
            self.do_arr_nd()

    def do_arr_nd(self):
        c = self.P & F_C
        p = self.P & ~(F_N | F_Z | F_C | F_V)
        a = self.A >> 1
        if c:
            a |= 0x80
        if not a:
            p |= F_Z
        elif a & 0x80:
            p |= F_N
        if a & 0x40:
            p |= F_V | F_C
        if a & 0x20:
            p ^= F_V
        self.P = p
        self.A = a

    def do_arr_d(self):
        c = self.P & F_C
        p = self.P & ~(F_N | F_Z | F_C | F_V)
        A = self.A
        a = A >> 1
        if c:
            a |= 0x80
        if not a:
            p |= F_Z
        elif a & 0x80:
            p |= F_N
        if (a ^ A) & 0x40:
            p |= F_V
        if (A & 0x0F) >= 0x05:
            a = ((a + 6) & 0x0F) | (a & 0xF0)
        if (A & 0xF0) >= 0x50:
            a = (a + 0x60) & 0xFF
            p |= F_C
        self.P = p
        self.A = a

    def do_cmp(self, v1, v2):
        r = (v1 - v2) & 0xFFFF
        p = self.P & ~(F_N | F_Z | F_C)
        if not r:
            p |= F_Z
        elif r & 0x80:
            p |= F_N
        if not r & 0xFF00:
            p |= F_C
        self.P = p

    def do_bit(self, val):
        p = self.P & ~(F_N | F_Z | F_V)
        if not self.A & val:
            p |= F_Z
        self.P = p | (val & (F_N | F_V))

    def do_asl(self, v):
        r = (v << 1) & 0xFF
        p = self.P & ~(F_N | F_Z | F_C)
        if not r:
            p |= F_Z
        elif r & 0x80:
            p |= F_N
        if v & 0x80:
            p |= F_C
        self.P = p
        return r

    def do_lsr(self, v):
        p = self.P & ~(F_N | F_Z | F_C)
        if v & 1:
            p |= F_C
        v >>= 1
        if not v:
            p |= F_Z
        self.P = p
        return v

    def do_ror(self, v):
        c = self.P & F_C
        p = self.P & ~(F_N | F_Z | F_C)
        if v & 1:
            p |= F_C
        v >>= 1
        if c:
            v |= 0x80
        if not v:
            p |= F_Z
        elif v & 0x80:
            p |= F_N
        self.P = p
        return v

    def do_rol(self, v):
        c = self.P & F_C
        p = self.P & ~(F_N | F_Z | F_C)
        if v & 0x80:
            p |= F_C
        v = (v << 1) & 0xFF
        if c:
            v |= 0x01
        if not v:
            p |= F_Z
        elif v & 0x80:
            p |= F_N
        self.P = p
        return v
