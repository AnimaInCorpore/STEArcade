"""Intel MCS-51 (8031/8051/8751) reference interpreter, exact against MAME 0.289's mcs51 core (i8751_device).

Follows MAME's mcs51_cpu_device (src/devices/cpu/mcs51/i8051.cpp, mcs51ops.cpp) in every detail that a program can
observe, quirks included:
  - time is counted in machine cycles (MAME's icount and totalcycles for mcs51: clock / 12; m72's 8 MHz i8751 runs
    666 666.7 cycles a second), with MAME's cycle table (1, 2 or 4 a instruction, MUL/DIV 4, A5 1).
  - MAME's execute loop: per iteration check_irqs(), the debugger hook, one instruction, then burn_cycles(): the
    timers and the serial port advance cycle by cycle after the instruction, so an overflow during an instruction is
    seen by the next check_irqs().  Taking an interrupt pushes PC, jumps to the vector and adds 2 cycles, and the
    vector's first instruction runs in the same iteration (the hook sees the vector address; the 2 cycles are burnt
    with that instruction's).  Priorities: IP (IPH = 0), equal levels in the order IE0 TF0 IE1 TF1 RI|TI; a level in
    service blocks equal and lower ones until RETI (MAME's irq_active / cur_irq_prio).  Taking IE0/IE1 clears the flag
    only when edge triggered (IT0/IT1), TF0/TF1 always, RI/TI never.  MAME's "JB INT0/INT1" latency hack (the
    interrupt taken right after JB P3.2/P3.3 returns past the JB) is reproduced.
  - external interrupt lines as MAME's execute_set_input: set_input_line(INT0_LINE, state): level mode (IT0 = 0):
    assert sets IE0 (every call, even if already asserted), clear clears IE0; edge mode: a clear->assert transition sets
    IE0.  MAME applies a line change only between instructions (scheduler synchronize): the board calls
    set_input_line between run() slices, for every call MAME's devices make (a generic latch asserts again on every
    write).  T0_LINE/T1_LINE: rising edges count when the timer is in counter mode (as MAME: only while TRx is set).
  - timers 0/1 in all modes (MAME: GATE looks at IE0/IE1, not at the pin; mode 3 splits timer 0, timer 1 then runs
    on without TR1 and without TF1), the serial port as MAME has it (mode 0 transmit only, modes 1-3 transmit/receive
    clocked by timer 1 overflows or the mode 2 clock; RXD is port 3 bit 0 of port_in(3)).
  - memory: internal RAM 128 bytes (ram_size=256 for the 8052-like parts: indirect access to $80-$FF), SFRs at
    $80-$FF of the direct space (unmapped ones read 0, writes ignored), indirect access above the RAM reads 0 and
    drops writes (MAME's unmapped idata), the program ROM (4 KB for the 8751; above it rd_code(addr), default 0: MAME's
    unmapped program space, EA is not modelled).  MOVX @DPTR uses DPTR, MOVX @Ri uses P2:Ri (external_ram_iaddr).
  - ports: writes call port_out(n, value) (MAME's out callbacks, P3 bit 1 ANDed with the serial TxD); reads by the
    read-modify-write instructions (ANL/ORL/XRL/INC/DEC/DJNZ direct, JBC, CPL/CLR/SETB bit, MOV bit,C) get the latch,
    every other read gets latch & port_in(n) (P3: also with bits 2/3 low while INT0/INT1 are asserted), port_in
    defaults to $FF like MAME's unbound port callbacks.  At reset P3, P2, P1, P0 are written $FF (port_out called).
  - PSW: the parity bit always follows A (MAME's acc_w; a write to PSW keeps it).  MAME's oddities kept: DJNZ direct
    reads its operand twice, PUSH SP pushes the incremented SP, POP SP decrements the popped value, CJNE sets C only,
    DA A never clears C, DIV by 0 sets OV and clears C leaving A and B, A5 is a 1-cycle no-op.
  - PCON IDL/PD do nothing on the 8051/8751 (MAME: m_has_pd is false for them); has_pd=True gives MAME's base
    behaviour for the CMOS parts (PD stops, IDL burns single cycles until an interrupt; untested against MAME).

API (MAME's names in brackets):
    cpu = I8051(rom, rd_data=None, wr_data=None, port_in=None, port_out=None, ram_size=128, rd_code=None)
        rom: the internal program ROM (bytes, 4096 for the 8751); rd_data(addr16) -> byte and wr_data(addr16, byte):
        the MOVX space (xdata); port_in(n) -> byte, port_out(n, byte): ports 0-3.
    cpu.run(n)                  # one scheduler slice of n machine cycles (execute_run with icount += n); MAME's
                                # do/while overshoot is carried into the next call.  Returns the cycles run.
    cpu.set_input_line(I8051.INT0_LINE, True)   # INT0_LINE INT1_LINE T0_LINE T1_LINE (MCS51_*_LINE), between slices
    cpu.abort_timeslice()       # icount = 0: the slice ends after the current instruction (MAME's abort_timeslice)
    cpu.step()                  # one loop iteration (interrupt check + one instruction + its cycles); returns cycles
    cpu.reset()                 # device_reset (RAM is kept)
    cpu.cycles                  # machine cycles executed (MAME's totalcycles)
    cpu.pc acc b sp dptr ie ip tcon tmod tl0 th0 tl1 th1 scon sbuf pcon p (port latches [p0, p1, p2, p3]) ram
    cpu.get_psw()               # PSW with the parity bit (cpu.psw holds bits 7-1); cpu.reg(r) = R0-R7 of the bank
    cpu.hook(cpu)               # before each instruction, after the interrupt check (MAME's debugger hook)
    cpu.irq_hook(cpu, line)     # when IE0 (0) / IE1 (1) is taken (MAME's standard_irq_callback)
Verified against MAME traces of mrheli's i8751 by engine/i8051_test.py.
"""

PARITY = bytes(bin(i).count("1") & 1 for i in range(256))

# MAME's mcs51_cycles (machine cycles per opcode)
CYCLES = bytes([
    1, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
    2, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
    2, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
    2, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
    2, 2, 1, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
    2, 2, 1, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
    2, 2, 1, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
    2, 2, 2, 2, 1, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
    2, 2, 2, 2, 4, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2,
    2, 2, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
    2, 2, 1, 2, 4, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2,
    2, 2, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2,
    2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
    2, 2, 1, 1, 1, 2, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2,
    2, 2, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
    2, 2, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
])

# TCON bits
TF1, TR1, TF0, TR0, IE1, IT1, IE0, IT0 = 0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01
# SCON bits
SM0, SM1, SM2, REN, TB8, RB8, TI, RI = 0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01
CY, AC, OV = 0x80, 0x40, 0x04
# serial states (MAME's serial_state)
SIO_IDLE, SIO_START_LE, SIO_START, SIO_DATA0, SIO_DATA7, SIO_DATA8, SIO_STOP = 0, 1, 2, 3, 10, 11, 12


def s8(v):
    return v - 256 if v & 0x80 else v


class I8051:
    INT0_LINE, INT1_LINE, T0_LINE, T1_LINE = 0, 1, 2, 3

    def __init__(self, rom, rd_data=None, wr_data=None, port_in=None, port_out=None, ram_size=128, rd_code=None,
                 has_pd=False):
        self.rom = bytes(rom)
        self.rom_size = len(self.rom)
        self.rd_data = rd_data or (lambda a: 0xFF)
        self.wr_data = wr_data or (lambda a, v: None)
        self.port_in = port_in or (lambda n: 0xFF)
        self.port_out = port_out or (lambda n, v: None)
        self.rd_code = rd_code or (lambda a: 0)
        self.ram_mask = ram_size - 1
        self.has_pd = has_pd
        self.ram = bytearray(256)
        self.forced_inputs = [0, 0, 0, 0]
        self.hook = None
        self.irq_hook = None
        self.cycles = 0
        self.icount = 0
        self.inst_cycles = 0
        self.pc = self.ppc = 0
        self.acc = self.b = self.psw = self.sp = self.dptr = 0
        self.p = [0xFF, 0xFF, 0xFF, 0xFF]
        self.uart_txd = 1
        self._sfr_rd = {0x80: lambda: self.port_rd(0), 0x81: lambda: self.sp, 0x82: lambda: self.dptr & 0xFF,
                        0x83: lambda: self.dptr >> 8, 0x87: lambda: self.pcon, 0x88: lambda: self.tcon,
                        0x89: lambda: self.tmod, 0x8A: lambda: self.tl0, 0x8B: lambda: self.tl1,
                        0x8C: lambda: self.th0, 0x8D: lambda: self.th1, 0x90: lambda: self.port_rd(1),
                        0x98: lambda: self.scon, 0x99: lambda: self.sbuf, 0xA0: lambda: self.port_rd(2),
                        0xA8: lambda: self.ie, 0xB0: lambda: self.port_rd(3), 0xB8: lambda: self.ip,
                        0xD0: self.get_psw, 0xE0: lambda: self.acc, 0xF0: lambda: self.b}
        self._sfr_wr = {0x80: lambda v: self.port_wr(0, v), 0x81: self._w_sp, 0x82: self._w_dpl, 0x83: self._w_dph,
                        0x87: self._w_pcon, 0x88: self._w_tcon, 0x89: self._w_tmod, 0x8A: self._w_tl0,
                        0x8B: self._w_tl1, 0x8C: self._w_th0, 0x8D: self._w_th1, 0x90: lambda v: self.port_wr(1, v),
                        0x98: self._w_scon, 0x99: self._w_sbuf, 0xA0: lambda v: self.port_wr(2, v),
                        0xA8: self._w_ie, 0xB0: lambda v: self.port_wr(3, v), 0xB8: self._w_ip,
                        0xD0: self._w_psw, 0xE0: self._w_acc, 0xF0: self._w_b}
        self.sbuf = 0
        self.insn = [self._decode(op) for op in range(256)]
        self.reset()

    # ---- reset -----------------------------------------------------------------------------------------------------
    def reset(self):
        self.last_line_state = 0
        self.t0_cnt = self.t1_cnt = 0
        self.irq_active = 0
        self.cur_irq_prio = -1
        self.last_op = self.last_bit = 0
        self.rwm = 0
        self.ppc = self.pc
        self.pc = 0
        self.sp = 7
        self.psw = 0
        self.acc = 0
        self.dptr = 0
        self.b = 0
        self.ip = self.iph = self.ie = 0
        self.scon = self.tcon = self.tmod = self.pcon = 0
        self.th1 = self.th0 = self.tl1 = self.tl0 = 0
        self.port_wr(3, 0xFF)
        self.port_wr(2, 0xFF)
        self.port_wr(1, 0xFF)
        self.port_wr(0, 0xFF)
        self.uart_data_out = self.uart_data_in = 0
        self.rx_clk = self.tx_clk = 0
        self.txbit = SIO_IDLE
        self.uart_txd = 1
        self.rxbit = SIO_IDLE
        self.rxb8 = 0
        self.smod_div = 0
        self.irq_prio = [0] * 8

    # ---- registers -------------------------------------------------------------------------------------------------
    def get_psw(self):
        return self.psw | PARITY[self.acc]

    def reg(self, r):
        return self.ram[r | (self.psw & 0x18)]

    def _w_psw(self, v): self.psw = v & 0xFE

    def _w_acc(self, v): self.acc = v

    def _w_b(self, v): self.b = v

    def _w_sp(self, v): self.sp = v

    def _w_dpl(self, v): self.dptr = (self.dptr & 0xFF00) | v

    def _w_dph(self, v): self.dptr = (self.dptr & 0x00FF) | (v << 8)

    def _w_pcon(self, v): self.pcon = v

    def _w_tcon(self, v): self.tcon = v

    def _w_tmod(self, v): self.tmod = v

    def _w_tl0(self, v): self.tl0 = v

    def _w_tl1(self, v): self.tl1 = v

    def _w_th0(self, v): self.th0 = v

    def _w_th1(self, v): self.th1 = v

    def _w_ie(self, v): self.ie = v

    def _w_ip(self, v):
        self.ip = v
        self.irq_prio = [((v >> i) & 1) | (((self.iph >> i) & 1) << 1) for i in range(8)]

    def _w_scon(self, v):
        old = self.scon
        self.scon = v
        if not old & REN and v & REN:
            self.rxbit = SIO_IDLE

    def _w_sbuf(self, v):
        self.sbuf = v
        self.uart_data_out = v
        self.txbit = SIO_START

    def port_rd(self, n):
        if self.rwm:
            return self.p[n]
        v = (self.p[n] | self.forced_inputs[n]) & self.port_in(n)
        if n == 3:
            ls = self.last_line_state
            if ls & 1:
                v &= ~4
            if ls & 2:
                v &= ~8
        return v

    def port_wr(self, n, v):
        self.p[n] = v
        if n == 3 and not self.uart_txd:
            v &= ~2
        self.port_out(n, v)

    # ---- memory ----------------------------------------------------------------------------------------------------
    def rd_dir(self, a):
        if a < 0x80:
            return self.ram[a]
        f = self._sfr_rd.get(a)
        return f() if f else 0

    def wr_dir(self, a, v):
        if a < 0x80:
            self.ram[a] = v
        else:
            f = self._sfr_wr.get(a)
            if f:
                f(v)

    def rd_ind(self, a):
        return self.ram[a] if a <= self.ram_mask else 0

    def wr_ind(self, a, v):
        if a <= self.ram_mask:
            self.ram[a] = v

    def code(self, a):
        return self.rom[a] if a < self.rom_size else self.rd_code(a)

    def bit_rd(self, b):
        self.last_bit = b
        if b < 0x80:
            return (self.ram[0x20 + (b >> 3)] >> (b & 7)) & 1
        return (self.rd_dir(b & 0xF8) >> (b & 7)) & 1

    def bit_wr(self, b, v):
        if b < 0x80:
            a = 0x20 + (b >> 3)
            m = 1 << (b & 7)
            self.ram[a] = (self.ram[a] & ~m) | (m if v else 0)
        else:
            a = b & 0xF8
            m = 1 << (b & 7)
            self.wr_dir(a, (self.rd_dir(a) & ~m & 0xFF) | (m if v else 0))

    def push_pc(self):
        self.sp = (self.sp + 1) & 0xFF
        self.wr_ind(self.sp, self.pc & 0xFF)
        self.sp = (self.sp + 1) & 0xFF
        self.wr_ind(self.sp, self.pc >> 8)

    def pop_pc(self):
        hi = self.rd_ind(self.sp)
        self.sp = (self.sp - 1) & 0xFF
        self.pc = (hi << 8) | self.rd_ind(self.sp)
        self.sp = (self.sp - 1) & 0xFF

    # ---- interrupts ------------------------------------------------------------------------------------------------
    def set_input_line(self, line, state):
        """MAME's execute_set_input"""
        bit = 1 << line
        new = (self.last_line_state & ~bit) | (bit if state else 0)
        tr = ~self.last_line_state & new
        tcon = self.tcon
        if line == 0:
            if state:
                if not tcon & IT0 or tr & 1:
                    self.tcon = tcon | IE0
            elif not tcon & IT0:
                self.tcon = tcon & ~IE0
        elif line == 1:
            if state:
                if not tcon & IT1 or tr & 2:
                    self.tcon = tcon | IE1
            elif not tcon & IT1:
                self.tcon = tcon & ~IE1
        elif line == 2:
            if tr & 4 and tcon & TR0:
                self.t0_cnt += 1
        elif line == 3:
            if tr & 8 and tcon & TR1:
                self.t1_cnt += 1
        self.last_line_state = new

    def clear_current_irq(self):
        if self.cur_irq_prio >= 0:
            self.irq_active &= ~(1 << self.cur_irq_prio)
        a = self.irq_active
        self.cur_irq_prio = 2 if a & 4 else 1 if a & 2 else 0 if a & 1 else -1

    def check_irqs(self):
        tcon = self.tcon
        ints = (((tcon >> 1) & 1) | ((tcon >> 4) & 2) | ((tcon >> 1) & 4) | ((tcon >> 4) & 8)
                | (((self.scon | (self.scon >> 1)) & 1) << 4)) & self.ie
        if not ints:
            return
        prio = -1
        vec = 0
        for i in range(5):
            if ints & (1 << i) and self.irq_prio[i] > prio:
                prio = self.irq_prio[i]
                vec = (i << 3) | 3
        if self.irq_active and prio <= self.cur_irq_prio:
            return
        if vec == 0x03 or vec == 0x13:
            if self.last_op == 0x20 and self.last_bit == (0xB2 if vec == 3 else 0xB3):
                self.pc = (self.ppc + 3) & 0xFFFF
            if self.irq_hook:
                self.irq_hook(self, vec >> 4)
        if self.has_pd and self.pcon & 1:
            self.pcon &= ~1                      # (the CMOS parts' manage_idle_on_interrupt; not in the 8751)
        self.push_pc()
        self.pc = vec
        self.inst_cycles += 2
        self.cur_irq_prio = prio
        self.irq_active |= 1 << prio
        if vec == 0x03:
            if tcon & IT0:
                self.tcon &= ~IE0
        elif vec == 0x0B:
            self.tcon &= ~TF0
        elif vec == 0x13:
            if tcon & IT1:
                self.tcon &= ~IE1
        elif vec == 0x1B:
            self.tcon &= ~TF1

    # ---- timers and serial port ------------------------------------------------------------------------------------
    def timer0(self, cycles):
        """MAME's update_timer_t0 (cycles at once: exact for every mode but 2, which burn() steps cycle by cycle)"""
        tmod, tcon = self.tmod, self.tcon
        mode = tmod & 3
        if tcon & TR0:
            delta = self.t0_cnt if tmod & 4 else cycles
            self.t0_cnt = 0
            if tmod & 8 and not tcon & IE0:
                delta = 0
            if mode == 0:
                count = ((self.th0 << 5) | (self.tl0 & 0x1F)) + delta
                if count & ~0x1FFF:
                    self.tcon |= TF0
                self.th0 = (count >> 5) & 0xFF
                self.tl0 = count & 0x1F
            elif mode == 1:
                count = ((self.th0 << 8) | self.tl0) + delta
                if count & ~0xFFFF:
                    self.tcon |= TF0
                self.th0 = (count >> 8) & 0xFF
                self.tl0 = count & 0xFF
            elif mode == 2:
                count = self.tl0 + delta
                if count & ~0xFF:
                    self.tcon |= TF0
                    count += self.th0
                self.tl0 = count & 0xFF
            else:
                count = self.tl0 + delta
                if count & ~0xFF:
                    self.tcon |= TF0
                self.tl0 = count & 0xFF
        if tcon & TR1 and mode == 3:
            count = self.th0 + cycles
            if count & ~0xFF:
                self.tcon |= TF1
            self.th0 = count & 0xFF

    def timer1(self, cycles):
        """MAME's update_timer_t1"""
        tmod = self.tmod
        mode = (tmod >> 4) & 3
        if tmod & 3 != 3:
            if not self.tcon & TR1:
                return
            delta = self.t1_cnt if tmod & 0x40 else cycles
            self.t1_cnt = 0
            if tmod & 0x80 and not self.tcon & IE1:
                delta = 0
            tf = True
        else:
            delta = cycles
            self.t1_cnt = 0
            tf = False
        overflow = 0
        if mode == 0:
            count = ((self.th1 << 5) | (self.tl1 & 0x1F)) + delta
            overflow = count & ~0x1FFF
            self.th1 = (count >> 5) & 0xFF
            self.tl1 = count & 0x1F
        elif mode == 1:
            count = ((self.th1 << 8) | self.tl1) + delta
            overflow = count & ~0xFFFF
            self.th1 = (count >> 8) & 0xFF
            self.tl1 = count & 0xFF
        elif mode == 2:
            count = self.tl1 + delta
            overflow = count & ~0xFF
            if overflow:
                count += self.th1
            self.tl1 = count & 0xFF
        if overflow:
            if tf:
                self.tcon |= TF1
            self.transmit_receive(1)

    def serial_busy(self):
        """True when the serial port does something on its own clock (else burn() may skip transmit_receive(0))"""
        scon = self.scon
        mode = scon >> 6
        if mode == 0:
            return self.txbit != SIO_IDLE
        return mode == 2 or bool(scon & REN)

    def transmit(self, state):
        if self.uart_txd != state:
            self.uart_txd = state
            if self.p[3] & 2:
                self.port_out(3, self.p[3] if state else self.p[3] & ~2)

    def transmit_receive(self, source):
        """MAME's transmit_receive"""
        scon = self.scon
        mode = scon >> 6
        if source == 1:
            self.smod_div = (self.smod_div + 1) & (0 if self.pcon & 0x80 else 1)
        if mode == 0:
            if source == 0:
                t = self.txbit
                if t == SIO_START:
                    self.p[3] |= 3
                    self.port_out(3, self.p[3])
                    self.txbit = SIO_DATA0
                elif SIO_DATA0 <= t <= SIO_DATA7:
                    self.p[3] &= ~3
                    if (self.uart_data_out >> (t - SIO_DATA0)) & 1:
                        self.p[3] |= 1
                    self.port_out(3, self.p[3])
                    if t == SIO_DATA7:
                        self.scon |= TI
                        self.txbit = SIO_STOP
                    else:
                        self.txbit = t + 1
                elif t == SIO_STOP:
                    self.p[3] |= 3
                    self.port_out(3, self.p[3])
                    self.txbit = SIO_IDLE
            return
        if mode in (1, 3):
            if source == 1:
                self.tx_clk += 0 if self.smod_div else 1
                self.rx_clk += 0 if self.smod_div else 1
        else:
            if source == 0:
                k = 6 if self.pcon & 0x80 else 3
                self.rx_clk += k
                self.tx_clk += k
        if self.tx_clk >= 16:
            self.tx_clk &= 0x0F
            t = self.txbit
            if t == SIO_IDLE:
                self.transmit(1)
            elif t == SIO_START:
                self.transmit(0)
                self.txbit = SIO_DATA0
            elif SIO_DATA0 <= t <= SIO_DATA7:
                self.transmit((self.uart_data_out >> (t - SIO_DATA0)) & 1)
                self.txbit = SIO_STOP if mode == 1 and t == SIO_DATA7 else t + 1
            elif t == SIO_DATA8:
                self.transmit(1 if self.scon & TB8 else 0)
                self.txbit = SIO_STOP
            elif t == SIO_STOP:
                self.transmit(1)
                self.scon |= TI
                self.txbit = SIO_IDLE
        if self.rx_clk >= 16 or self.rxbit < SIO_START:
            self.rx_clk &= 0x0F
            if self.scon & REN:
                data = self.port_in(3) & 1
                r = self.rxbit
                if r == SIO_IDLE:
                    if data:
                        self.rxbit = SIO_START_LE
                elif r == SIO_START_LE:
                    if not data:
                        self.rxbit = SIO_START
                        self.rx_clk = 8
                elif r == SIO_START:
                    if not data:
                        self.uart_data_in = 0
                        self.rxbit = SIO_DATA0
                    else:
                        self.rxbit = SIO_START_LE
                elif SIO_DATA0 <= r <= SIO_DATA7:
                    if data:
                        self.uart_data_in |= 1 << (r - SIO_DATA0)
                    self.rxbit = SIO_STOP if mode == 1 and r == SIO_DATA7 else r + 1
                elif r == SIO_DATA8:
                    self.rxb8 = data
                    self.rxbit = SIO_STOP
                elif r == SIO_STOP:
                    if not self.scon & RI:
                        if mode == 1:
                            self.sbuf = self.uart_data_in
                            if not self.scon & SM2:
                                self.scon = (self.scon & ~RB8) | (RB8 if data else 0)
                                self.scon |= RI
                            elif data:
                                self.scon |= RI
                        else:
                            self.sbuf = self.uart_data_in
                            self.scon = (self.scon & ~RB8) | (RB8 if self.rxb8 else 0)
                            if not self.scon & SM2 or self.scon & RB8:
                                self.scon |= RI
                    self.rxbit = SIO_START_LE if data else SIO_IDLE

    def burn(self, n):
        """MAME's burn_cycles: n cycles of the timers and the serial port"""
        self.icount -= n
        self.cycles += n
        tmod = self.tmod
        if tmod & 3 == 3 or (self.scon or self.txbit) and self.serial_busy():          # timer 0 split / the serial port busy: cycle by cycle
            for _ in range(n):
                self.timer0(1)
                self.timer1(1)
                self.transmit_receive(0)
            return
        tcon = self.tcon                                 # else the timers are independent and run in one go, except
        if tcon & TR0:                                   # for a mode 2 reload within the n cycles (stepped)
            if tmod & 7 == 2 and self.tl0 + n > 0xFF:
                for _ in range(n):
                    self.timer0(1)
            else:
                self.timer0(n)
        if tcon & TR1:
            if tmod & 0x70 == 0x20 and self.tl1 + n > 0xFF:
                for _ in range(n):
                    self.timer1(1)
            else:
                self.timer1(n)

    # ---- execution -------------------------------------------------------------------------------------------------
    def run(self, n):
        """one MAME execute_run slice of n machine cycles; returns the cycles run"""
        start = self.cycles
        self.icount += n
        if self.icount <= 0:
            return 0
        step = self.step
        while self.icount > 0:
            step()
        return self.cycles - start

    def abort_timeslice(self):
        self.icount = 0

    def step(self):
        """one iteration of MAME's execute loop; returns its cycles"""
        self.inst_cycles = 0
        if self.ie & 0x80:
            self.check_irqs()
        pcon = self.pcon
        if self.has_pd and pcon & 2:
            self.icount = 0
            return 0
        if not (self.has_pd and pcon & 1):
            pc = self.pc
            self.ppc = pc
            if self.hook:
                self.hook(self)
                pc = self.pc
            op = self.rom[pc] if pc < self.rom_size else self.rd_code(pc)
            self.pc = (pc + 1) & 0xFFFF
            self.inst_cycles += CYCLES[op]
            self.last_op = op
            self.insn[op]()
        else:
            self.inst_cycles += 1
        n = self.inst_cycles
        self.burn(n)
        return n

    # ---- instructions ----------------------------------------------------------------------------------------------
    def fetch(self):
        pc = self.pc
        self.pc = (pc + 1) & 0xFFFF
        return self.rom[pc] if pc < self.rom_size else self.rd_code(pc)

    def rel(self, d):
        self.pc = (self.pc + s8(d)) & 0xFFFF

    def add_flags(self, a, d, c):
        r = a + d + c
        psw = self.psw & ~(CY | AC | OV)
        if r & 0x100:
            psw |= CY
        if ((a & 0x0F) + (d & 0x0F) + c) & 0x10:
            psw |= AC
        r1 = s8(a) + s8(d) + c
        if r1 < -128 or r1 > 127:
            psw |= OV
        self.psw = psw
        return r & 0xFF

    def sub_flags(self, a, d, c):
        r = a - (d + c)
        psw = self.psw & ~(CY | AC | OV)
        if r & 0x100:
            psw |= CY
        if ((a & 0x0F) - ((d & 0x0F) + c)) & 0x10:
            psw |= AC
        r1 = s8(a) - s8((d + c) & 0xFF)
        if r1 < -128 or r1 > 127:
            psw |= OV
        self.psw = psw
        return r & 0xFF

    def _decode(self, op):
        hi, lo = op >> 4, op & 15
        ram = self.ram
        fetch, rd_dir, wr_dir, rd_ind, wr_ind = self.fetch, self.rd_dir, self.wr_dir, self.rd_ind, self.wr_ind
        bit_rd, bit_wr = self.bit_rd, self.bit_wr

        def rmw(f):                              # m_rwm = 1 around the instruction
            def g():
                self.rwm = 1
                f()
                self.rwm = 0
            return g

        # Rn / @Ri operand access (no side effects: the address may be computed twice)
        if lo >= 8:
            r = op & 7

            def g():
                return ram[r | (self.psw & 0x18)]

            def s(v):
                ram[r | (self.psw & 0x18)] = v
        elif lo in (6, 7):
            r = op & 1

            def g():
                return rd_ind(ram[r | (self.psw & 0x18)])

            def s(v):
                wr_ind(ram[r | (self.psw & 0x18)], v)

        def ir_addr():
            return ram[(op & 1) | (self.psw & 0x18)]

        if lo == 1:
            if op & 0x10:                        # ACALL
                def f():
                    a = fetch()
                    self.push_pc()
                    self.pc = (self.pc & 0xF800) | ((op & 0xE0) << 3) | a
            else:                                # AJMP
                def f():
                    a = fetch()
                    self.pc = (self.pc & 0xF800) | ((op & 0xE0) << 3) | a
            return f

        alu = {0x2: "add", 0x3: "addc", 0x4: "orl", 0x5: "anl", 0x6: "xrl", 0x9: "subb"}
        if hi in alu and lo >= 4:
            kind = alu[hi]
            if lo == 4:
                def src(): return fetch()
            elif lo == 5:
                def src(): return rd_dir(fetch())
            else:
                src = g

            if kind == "add":
                def f(): self.acc = self.add_flags(self.acc, src(), 0)
            elif kind == "addc":
                def f(): self.acc = self.add_flags(self.acc, src(), (self.psw >> 7) & 1)
            elif kind == "subb":
                def f(): self.acc = self.sub_flags(self.acc, src(), (self.psw >> 7) & 1)
            elif kind == "orl":
                def f(): self.acc |= src()
            elif kind == "anl":
                def f(): self.acc &= src()
            else:
                def f(): self.acc ^= src()
            return f

        if hi in (4, 5, 6) and lo in (2, 3):     # ORL/ANL/XRL direct,A / direct,#data (read-modify-write)
            fn = {4: lambda x, y: x | y, 5: lambda x, y: x & y, 6: lambda x, y: x ^ y}[hi]
            if lo == 2:
                def f():
                    a = fetch()
                    wr_dir(a, fn(rd_dir(a), self.acc))
            else:
                def f():
                    a = fetch()
                    d = fetch()
                    wr_dir(a, fn(rd_dir(a), d))
            return rmw(f)

        if lo >= 6:                              # Rn / @Ri forms of the remaining rows
            if hi == 0x0:
                def f(): s((g() + 1) & 0xFF)
            elif hi == 0x1:
                def f(): s((g() - 1) & 0xFF)
            elif hi == 0x7:
                def f():
                    d = fetch()
                    s(d)
            elif hi == 0x8:
                def f():
                    a = fetch()
                    wr_dir(a, g())
            elif hi == 0xA:
                def f():
                    a = fetch()
                    s(rd_dir(a))
            elif hi == 0xB:
                def f():
                    d = fetch()
                    e = fetch()
                    v = g()
                    if v != d:
                        self.rel(e)
                    self.psw = (self.psw & ~CY) | (CY if v < d else 0)
            elif hi == 0xC:
                def f():
                    v = g()
                    old = self.acc
                    self.acc = v
                    s(old)
            elif hi == 0xD:
                if lo >= 8:
                    def f():
                        e = fetch()
                        s((g() - 1) & 0xFF)
                        if g():
                            self.rel(e)
                else:                            # XCHD A,@Ri
                    def f():
                        a = ir_addr()
                        acc = self.acc
                        d = rd_ind(a)
                        self.acc = (acc & 0xF0) | (d & 0x0F)
                        wr_ind(a, (d & 0xF0) | (acc & 0x0F))
            elif hi == 0xE:
                def f(): self.acc = g()
            elif hi == 0xF:
                def f(): s(self.acc)
            else:
                raise AssertionError(hex(op))
            return f

        # the rest: one by one
        def nop():
            pass

        def ljmp():
            h = fetch()
            lo_ = fetch()
            self.pc = (h << 8) | lo_

        def lcall():
            h = fetch()
            lo_ = fetch()
            self.push_pc()
            self.pc = (h << 8) | lo_

        def rr_a():
            a = self.acc
            self.acc = (a >> 1) | ((a & 1) << 7)

        def rrc_a():
            a = self.acc
            self.acc = (a >> 1) | (self.psw & CY)
            self.psw = (self.psw & ~CY) | ((a & 1) << 7)

        def rl_a():
            a = self.acc
            self.acc = ((a << 1) & 0xFF) | (a >> 7)

        def rlc_a():
            a = self.acc
            self.acc = ((a << 1) & 0xFF) | (self.psw >> 7)
            self.psw = (self.psw & ~CY) | (a & 0x80)

        def inc_a(): self.acc = (self.acc + 1) & 0xFF

        def dec_a(): self.acc = (self.acc - 1) & 0xFF

        def inc_mem():
            a = fetch()
            wr_dir(a, (rd_dir(a) + 1) & 0xFF)

        def dec_mem():
            a = fetch()
            wr_dir(a, (rd_dir(a) - 1) & 0xFF)

        def jbc():
            a = fetch()
            e = fetch()
            if bit_rd(a):
                self.rel(e)
                bit_wr(a, 0)

        def jb():
            a = fetch()
            e = fetch()
            if bit_rd(a):
                self.rel(e)

        def jnb():
            a = fetch()
            e = fetch()
            if not bit_rd(a):
                self.rel(e)

        def ret(): self.pop_pc()

        def reti():
            self.pop_pc()
            self.clear_current_irq()

        def jc():
            e = fetch()
            if self.psw & CY:
                self.rel(e)

        def jnc():
            e = fetch()
            if not self.psw & CY:
                self.rel(e)

        def jz():
            e = fetch()
            if not self.acc:
                self.rel(e)

        def jnz():
            e = fetch()
            if self.acc:
                self.rel(e)

        def sjmp():
            self.rel(fetch())

        def orl_c_bit():
            if bit_rd(fetch()):
                self.psw |= CY

        def anl_c_bit():
            if not bit_rd(fetch()):
                self.psw &= ~CY

        def orl_c_nbit():
            if not bit_rd(fetch()):
                self.psw |= CY

        def anl_c_nbit():
            if bit_rd(fetch()):
                self.psw &= ~CY

        def jmp_adptr(): self.pc = (self.acc + self.dptr) & 0xFFFF

        def mov_a_imm(): self.acc = fetch()

        def mov_dir_imm():
            a = fetch()
            wr_dir(a, fetch())

        def movc_pc(): self.acc = self.code((self.acc + self.pc) & 0xFFFF)

        def movc_dptr(): self.acc = self.code((self.acc + self.dptr) & 0xFFFF)

        def div_ab():
            if self.b == 0:
                self.psw |= OV
            else:
                a, b = self.acc, self.b
                self.acc = a // b
                self.b = a % b
                self.psw &= ~OV
            self.psw &= ~CY

        def mul_ab():
            r = self.acc * self.b
            self.b = r >> 8
            self.acc = r & 0xFF
            self.psw = (self.psw & ~(CY | OV)) | (OV if r & 0x100 else 0)   # (MAME: OV = bit 8 of the product)

        def mov_dir_dir():
            s = fetch()
            d = fetch()
            wr_dir(d, rd_dir(s))

        def mov_dptr():
            h = fetch()
            lo_ = fetch()
            self.dptr = (h << 8) | lo_

        def mov_bit_c():
            bit_wr(fetch(), self.psw >> 7)

        def mov_c_bit():
            self.psw = (self.psw & ~CY) | (CY if bit_rd(fetch()) else 0)

        def inc_dptr(): self.dptr = (self.dptr + 1) & 0xFFFF

        def cpl_bit():
            a = fetch()
            bit_wr(a, bit_rd(a) ^ 1)

        def cpl_c(): self.psw ^= CY

        def cjne_a_imm():
            d = fetch()
            e = fetch()
            if self.acc != d:
                self.rel(e)
            self.psw = (self.psw & ~CY) | (CY if self.acc < d else 0)

        def cjne_a_dir():
            a = fetch()
            e = fetch()
            d = rd_dir(a)
            if self.acc != d:
                self.rel(e)
            self.psw = (self.psw & ~CY) | (CY if self.acc < d else 0)

        def push():
            a = fetch()
            self.sp = (self.sp + 1) & 0xFF
            wr_ind(self.sp, rd_dir(a))

        def pop():
            a = fetch()
            wr_dir(a, rd_ind(self.sp))
            self.sp = (self.sp - 1) & 0xFF

        def clr_bit(): bit_wr(fetch(), 0)

        def setb_bit(): bit_wr(fetch(), 1)

        def clr_c(): self.psw &= ~CY

        def setb_c(): self.psw |= CY

        def swap_a():
            a = self.acc
            self.acc = ((a << 4) & 0xF0) | (a >> 4)

        def xch_a_dir():
            a = fetch()
            d = rd_dir(a)
            old = self.acc
            self.acc = d
            wr_dir(a, old)

        def da_a():
            a = self.acc
            if self.psw & AC or (a & 0x0F) > 9:
                a += 6
            if self.psw & CY or (a & 0xF0) > 0x90 or a & ~0xFF:
                a += 0x60
            self.acc = a & 0xFF
            if a & ~0xFF:
                self.psw |= CY

        def djnz_dir():
            a = fetch()
            e = fetch()
            wr_dir(a, (rd_dir(a) - 1) & 0xFF)
            if rd_dir(a):
                self.rel(e)

        def movx_a_dptr(): self.acc = self.rd_data(self.dptr)

        def movx_a_ir0(): self.acc = self.rd_data(ram[self.psw & 0x18] | (self.p[2] << 8))

        def movx_a_ir1(): self.acc = self.rd_data(ram[1 | (self.psw & 0x18)] | (self.p[2] << 8))

        def movx_dptr_a(): self.wr_data(self.dptr, self.acc)

        def movx_ir0_a(): self.wr_data(ram[self.psw & 0x18] | (self.p[2] << 8), self.acc)

        def movx_ir1_a(): self.wr_data(ram[1 | (self.psw & 0x18)] | (self.p[2] << 8), self.acc)

        def clr_a(): self.acc = 0

        def mov_a_dir(): self.acc = rd_dir(fetch())

        def cpl_a(): self.acc ^= 0xFF

        def mov_dir_a(): wr_dir(fetch(), self.acc)

        T = {0x00: nop, 0x02: ljmp, 0x03: rr_a, 0x04: inc_a, 0x05: rmw(inc_mem), 0x10: rmw(jbc), 0x12: lcall,
             0x13: rrc_a, 0x14: dec_a, 0x15: rmw(dec_mem), 0x20: jb, 0x22: ret, 0x23: rl_a, 0x30: jnb, 0x32: reti,
             0x33: rlc_a, 0x40: jc, 0x50: jnc, 0x60: jz, 0x70: jnz, 0x72: orl_c_bit, 0x73: jmp_adptr,
             0x74: mov_a_imm, 0x75: mov_dir_imm, 0x80: sjmp, 0x82: anl_c_bit, 0x83: movc_pc, 0x84: div_ab,
             0x85: mov_dir_dir, 0x90: mov_dptr, 0x92: rmw(mov_bit_c), 0x93: movc_dptr, 0xA0: orl_c_nbit,
             0xA2: mov_c_bit, 0xA3: inc_dptr, 0xA4: mul_ab, 0xA5: nop, 0xB0: anl_c_nbit, 0xB2: rmw(cpl_bit),
             0xB3: cpl_c, 0xB4: cjne_a_imm, 0xB5: cjne_a_dir, 0xC0: push, 0xC2: rmw(clr_bit), 0xC3: clr_c,
             0xC4: swap_a, 0xC5: xch_a_dir, 0xD0: pop, 0xD2: rmw(setb_bit), 0xD3: setb_c, 0xD4: da_a,
             0xD5: rmw(djnz_dir), 0xE0: movx_a_dptr, 0xE2: movx_a_ir0, 0xE3: movx_a_ir1, 0xE4: clr_a,
             0xE5: mov_a_dir, 0xF0: movx_dptr_a, 0xF2: movx_ir0_a, 0xF3: movx_ir1_a, 0xF4: cpl_a,
             0xF5: mov_dir_a}
        return T[op]
