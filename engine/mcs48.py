"""Intel MCS-48 (8035/8039/8048/8049) reference interpreter, after MAME 0.289's mcs48 core (i8039_device,
src/devices/cpu/mcs48/mcs48.cpp).

It follows MAME's mcs48_cpu_device in what a program can observe:
  - time is counted in machine cycles (MAME divides the clock by 15: the Gyruss board's 8 MHz i8039 runs 533 333.3
    cycles a second), 1 or 2 a instruction as MAME's burn_cycles calls, 2 more for taking an interrupt.
  - MAME's execute loop: per instruction check_irqs() first (the external INT, if enabled and no interrupt is in
    progress, then the timer overflow), then the instruction.  An interrupt pushes PC and PSW and calls 3 (INT) or 7
    (timer); while it is in progress JMP/CALL ignore SEL MB1 and returns mask PC to 11 bits; RETR ends it.  MAME's JNI
    hack is kept: an INT taken right after a JNI that was not taken returns to the JNI's target.
  - the INT input is a level (set_int(True/False), as MAME's set_input_line ASSERT/CLEAR): it stays pending until the
    program's I/O clears it (on the Gyruss board a write to P2).
  - the timer (STRT T: +1 every 32 cycles, overflow sets the timer flag for JTF and, with EN TCNTI, the timer
    interrupt) and the event counter (STRT CNT: falling edges of T1, polled once a cycle).
  - memory: 128 bytes of RAM (addresses wrap at 128 like MAME's 7-bit data space; ram_size=64 or 256 for the other
    parts), registers R0-R7 at 0 or 24 (SEL RB0/RB1), the stack of 8 PC/PSW pairs at 8-23, the program in `rom`
    (an 8039 runs external ROM: 4 KB with SEL MB0/MB1, PC increments within 2 KB as MAME's opcode_fetch).
  - I/O as MAME's callbacks: port_w(n, v) for P1/P2 (also at reset: both are written $FF), port_r(n) for IN A,Pn
    (ANDed with the latch as MAME does), bus_r() for INS A,BUS, ext_r(a) / ext_w(a, v) for MOVX (the I/O address
    space), bus_w(v) for OUTL BUS and ANL/ORL BUS, test_r(n) for T0/T1 (JT0/JNT0/JT1/JNT1).  Unbound reads give $FF
    (ports, bus, ext) or 0 (T0/T1) like MAME's defaults.

Differences from MAME: no UPI-41 / 8021 / 8022 variants, no 8243 expander (MOVD/ANLD/ORLD raise Unsupported), ENT0
CLK only notes the request, no internal ROM (EA is always 1), no debugger or save states.  Interrupt lines change
only between instructions (MAME applies them at its quantum boundaries; the board model decides when to call
set_int).
"""

C_FLAG, A_FLAG, F_FLAG, B_FLAG = 0x80, 0x40, 0x20, 0x10
TIMER_ENABLED, COUNTER_ENABLED = 1, 2


class Unsupported(Exception):
    pass


class MCS48:
    """step() runs one instruction (after taking a pending interrupt) and returns its cycles; `cycles` counts them
    all.  `ops` (a Counter or None) gathers the opcodes executed, for checking which instructions a program uses."""

    def __init__(self, rom, port_w=None, port_r=None, bus_r=None, bus_w=None, ext_r=None, ext_w=None, test_r=None,
                 ram_size=128):
        self.rom = bytes(rom) + bytes(max(0, 0x1000 - len(rom)))
        self.ram = bytearray(ram_size)
        self.ram_mask = ram_size - 1
        self.port_w_cb = port_w or (lambda n, v: None)
        self.port_r_cb = port_r or (lambda n: 0xFF)
        self.bus_r_cb = bus_r or (lambda: 0xFF)
        self.bus_w_cb = bus_w or (lambda v: None)
        self.ext_r_cb = ext_r or (lambda a: 0xFF)
        self.ext_w_cb = ext_w or (lambda a, v: None)
        self.test_r_cb = test_r or (lambda n: 0)
        self.ops = None
        self.cycles = 0
        # MAME's device_start zero fill
        self.pc = self.prevpc = self.a = self.psw = 0
        self.f1 = False
        self.a11 = 0
        self.p1 = self.p2 = 0
        self.timer = self.prescaler = 0
        self.t1_history = 0
        self.irq_state = self.irq_polled = self.irq_in_progress = False
        self.timer_overflow = self.timer_flag = False
        self.tirq_enabled = self.xirq_enabled = False
        self.timecount_enabled = 0
        self.t0_clk = False
        self.table = self._build()
        self.reset()

    def reset(self):
        """MAME's device_reset"""
        self.pc = 0
        self.psw &= C_FLAG | A_FLAG
        self.f1 = False
        self.a11 = 0
        self.tirq_enabled = self.xirq_enabled = False
        self.timecount_enabled = 0
        self.timer_flag = False
        self.irq_in_progress = self.timer_overflow = self.irq_polled = False
        self.bus_w_cb(0xFF)
        self.p1 = self.p2 = 0xFF
        self.port_w_cb(1, 0xFF)
        self.port_w_cb(2, 0xFF)

    def set_int(self, state):
        """the INT input: True = asserted (MAME's ASSERT_LINE), False = cleared"""
        self.irq_state = bool(state)

    # --- helpers (MAME's inline functions) ---

    def rb(self):
        return 24 if self.psw & B_FLAG else 0

    def rd_r(self, n):
        return self.ram[self.rb() + n]

    def wr_r(self, n, v):
        self.ram[self.rb() + n] = v & 0xFF

    def ram_r(self, a):
        return self.ram[a & self.ram_mask]

    def ram_w(self, a, v):
        self.ram[a & self.ram_mask] = v & 0xFF

    def fetch(self):
        a = self.pc
        self.pc = ((a + 1) & 0x7FF) | (a & 0x800)
        return self.rom[a & 0xFFF]

    def push_pc_psw(self):
        sp = self.psw & 7
        self.ram_w(8 + 2 * sp, self.pc & 0xFF)
        self.ram_w(9 + 2 * sp, ((self.pc >> 8) & 0x0F) | (self.psw & 0xF0))
        self.psw = (self.psw & 0xF0) | ((sp + 1) & 7)

    def pull_pc_psw(self):
        sp = (self.psw - 1) & 7
        pc = self.ram_r(8 + 2 * sp) | (self.ram_r(9 + 2 * sp) << 8)
        self.psw = ((pc >> 8) & 0xF0) | sp
        self.pc = pc & (0x7FF if self.irq_in_progress else 0xFFF)

    def pull_pc(self):
        sp = (self.psw - 1) & 7
        pc = self.ram_r(8 + 2 * sp) | (self.ram_r(9 + 2 * sp) << 8)
        self.pc = pc & (0x7FF if self.irq_in_progress else 0xFFF)
        self.psw = (self.psw & 0xF0) | sp

    def add(self, d, carry=0):
        t = self.a + d + carry
        t4 = (self.a & 0x0F) + (d & 0x0F) + carry
        self.psw &= ~(C_FLAG | A_FLAG) & 0xFF
        self.psw |= ((t4 << 2) & A_FLAG) | ((t >> 1) & C_FLAG)
        self.a = t & 0xFF

    def jmp(self, addr):
        self.pc = addr | (0 if self.irq_in_progress else self.a11)

    def call(self, addr):
        self.push_pc_psw()
        self.jmp(addr)

    def jcc(self, cond):
        pch = self.pc & 0xF00
        off = self.fetch()
        if cond:
            self.pc = pch | off

    def burn(self, n):
        """MAME's burn_cycles: the timer / counter advance"""
        if self.timecount_enabled:
            over = False
            if self.timecount_enabled & TIMER_ENABLED:
                old = self.timer
                self.prescaler += n
                self.timer = (self.timer + (self.prescaler >> 5)) & 0xFF
                self.prescaler &= 0x1F
                over = self.timer < old
            elif self.timecount_enabled & COUNTER_ENABLED:
                for _ in range(n):
                    self.t1_history = ((self.t1_history << 1) | (self.test_r_cb(1) & 1)) & 0xFF
                    if (self.t1_history & 3) == 2:
                        self.timer = (self.timer + 1) & 0xFF
                        if self.timer == 0:
                            over = True
            if over:
                self.timer_flag = True
                if self.tirq_enabled:
                    self.timer_overflow = True
        self.cycles += n
        return n

    def check_irqs(self):
        if self.irq_in_progress:
            return 0
        if self.irq_state and self.xirq_enabled:
            n = self.burn(2)
            self.irq_in_progress = True
            if self.irq_polled:                 # MAME's JNI hack: the JNI is taken
                self.pc = ((self.prevpc + 1) & 0x7FF) | (self.prevpc & 0x800)
                self.jcc(True)
            self.call(0x03)
            return n
        if self.timer_overflow and self.tirq_enabled:
            n = self.burn(2)
            self.irq_in_progress = True
            self.call(0x07)
            self.timer_overflow = False
            return n
        return 0

    def step(self):
        n = self.check_irqs()
        self.irq_polled = False
        self.prevpc = self.pc
        op = self.fetch()
        if self.ops is not None:
            self.ops[op] += 1
        return n + self.table[op]()

    def run(self, cycles):
        """run at least `cycles` cycles (whole instructions); returns the cycles run"""
        start = self.cycles
        end = start + cycles
        while self.cycles < end:
            self.step()
        return self.cycles - start

    # --- the opcode table (MAME's s_mcs48_opcodes) ---

    def _build(self):
        t = [None] * 256
        s = self

        def illegal():
            return s.burn(1)

        for i in range(256):
            t[i] = illegal

        def op(code):
            def deco(f):
                t[code] = f
                return f
            return deco

        def a_ops(base, fn, cyc_n):
            """the A,Rn / A,@Ri / A,#n family: base+8..15 = Rn, base+0/1 = @R0/@R1, n_code = A,#n"""
            for r in range(8):
                t[base + 8 + r] = (lambda r=r: (s.burn(1), fn(s.rd_r(r)))[0])
            for r in range(2):
                t[base + r] = (lambda r=r: (s.burn(1), fn(s.ram_r(s.rd_r(r))))[0])
            if cyc_n is not None:
                t[cyc_n] = lambda: (s.burn(2), fn(s.fetch()))[0]

        def setf(name):
            def f(v):
                if name == 'and':
                    s.a &= v
                elif name == 'or':
                    s.a |= v
                else:
                    s.a ^= v
            return f

        a_ops(0x60, lambda v: s.add(v), 0x03)
        a_ops(0x70, lambda v: s.add(v, (s.psw & C_FLAG) >> 7), 0x13)
        a_ops(0x50, setf('and'), 0x53)
        a_ops(0x40, setf('or'), 0x43)
        a_ops(0xD0, setf('xor'), 0xD3)

        def mov_a(v):
            s.a = v
        a_ops(0xF0, mov_a, None)
        t[0x23] = lambda: (s.burn(2), mov_a(s.fetch()))[0]

        for r in range(8):
            t[0x18 + r] = (lambda r=r: (s.burn(1), s.wr_r(r, s.rd_r(r) + 1))[0])       # INC Rn
            t[0xC8 + r] = (lambda r=r: (s.burn(1), s.wr_r(r, s.rd_r(r) - 1))[0])       # DEC Rn
            t[0xA8 + r] = (lambda r=r: (s.burn(1), s.wr_r(r, s.a))[0])                 # MOV Rn,A
            t[0xB8 + r] = (lambda r=r: (s.burn(2), s.wr_r(r, s.fetch()))[0])           # MOV Rn,#n

            def xch(r=r):
                n = s.burn(1)
                v = s.rd_r(r)
                s.wr_r(r, s.a)
                s.a = v
                return n
            t[0x28 + r] = xch

            def djnz(r=r):
                n = s.burn(2)
                v = (s.rd_r(r) - 1) & 0xFF
                s.wr_r(r, v)
                s.jcc(v != 0)
                return n
            t[0xE8 + r] = djnz

        for r in range(2):
            t[0x10 + r] = (lambda r=r: (s.burn(1), s.ram_w(s.rd_r(r), s.ram_r(s.rd_r(r)) + 1))[0])   # INC @Ri
            t[0xA0 + r] = (lambda r=r: (s.burn(1), s.ram_w(s.rd_r(r), s.a))[0])                       # MOV @Ri,A
            t[0xB0 + r] = (lambda r=r: (s.burn(2), s.ram_w(s.rd_r(r), s.fetch()))[0])                 # MOV @Ri,#n
            t[0x80 + r] = (lambda r=r: (s.burn(2), mov_a(s.ext_r_cb(s.rd_r(r)) & 0xFF))[0])           # MOVX A,@Ri
            t[0x90 + r] = (lambda r=r: (s.burn(2), s.ext_w_cb(s.rd_r(r), s.a))[0])                    # MOVX @Ri,A

            def xch_i(r=r):
                n = s.burn(1)
                a = s.rd_r(r)
                v = s.ram_r(a)
                s.ram_w(a, s.a)
                s.a = v
                return n
            t[0x20 + r] = xch_i

            def xchd(r=r):
                n = s.burn(1)
                a = s.rd_r(r)
                old = s.ram_r(a)
                s.ram_w(a, (old & 0xF0) | (s.a & 0x0F))
                s.a = (s.a & 0xF0) | (old & 0x0F)
                return n
            t[0x30 + r] = xchd

        for p in range(8):
            t[0x04 + p * 0x20] = (lambda p=p: (s.burn(2), s.jmp(s.fetch() | (p << 8)))[0])    # JMP
            t[0x14 + p * 0x20] = (lambda p=p: (s.burn(2), s.call(s.fetch() | (p << 8)))[0])   # CALL
            t[0x12 + p * 0x20] = (lambda p=p: (s.burn(2), s.jcc(s.a & (1 << p)))[0])          # JBb

        def jc(code, cond):
            t[code] = lambda: (s.burn(2), s.jcc(cond()))[0]
        jc(0xF6, lambda: s.psw & C_FLAG)
        jc(0xE6, lambda: not s.psw & C_FLAG)
        jc(0xB6, lambda: s.psw & F_FLAG)
        jc(0x76, lambda: s.f1)
        jc(0xC6, lambda: s.a == 0)
        jc(0x96, lambda: s.a != 0)
        jc(0x36, lambda: s.test_r_cb(0) != 0)
        jc(0x26, lambda: s.test_r_cb(0) == 0)
        jc(0x56, lambda: s.test_r_cb(1) != 0)
        jc(0x46, lambda: s.test_r_cb(1) == 0)

        @op(0x86)
        def jni():
            n = s.burn(2)
            s.irq_polled = not s.irq_state
            s.jcc(s.irq_state)
            return n

        @op(0x16)
        def jtf():
            n = s.burn(2)
            s.jcc(s.timer_flag)
            s.timer_flag = False
            return n

        @op(0xB3)
        def jmpp():
            n = s.burn(2)
            s.pc = (s.pc & 0xF00) | s.rom[(s.pc & 0xF00) | s.a]
            return n

        @op(0xA3)
        def movp():
            n = s.burn(2)
            s.a = s.rom[(s.pc & 0xF00) | s.a]
            return n

        @op(0xE3)
        def movp3():
            n = s.burn(2)
            s.a = s.rom[0x300 | s.a]
            return n

        @op(0x83)
        def ret():
            n = s.burn(2)
            s.pull_pc()
            return n

        @op(0x93)
        def retr():
            n = s.burn(2)
            s.irq_in_progress = False
            s.pull_pc_psw()
            return n

        def simple(code, fn):
            t[code] = lambda: (s.burn(1), fn())[0]

        def setv(attr, v):
            return lambda: setattr(s, attr, v)

        simple(0x00, lambda: None)                                   # NOP
        simple(0x27, setv('a', 0))                                   # CLR A
        simple(0x37, lambda: setattr(s, 'a', s.a ^ 0xFF))            # CPL A
        simple(0x17, lambda: setattr(s, 'a', (s.a + 1) & 0xFF))      # INC A
        simple(0x07, lambda: setattr(s, 'a', (s.a - 1) & 0xFF))      # DEC A
        simple(0x47, lambda: setattr(s, 'a', ((s.a << 4) | (s.a >> 4)) & 0xFF))   # SWAP A
        simple(0xE7, lambda: setattr(s, 'a', ((s.a << 1) | (s.a >> 7)) & 0xFF))   # RL A
        simple(0x77, lambda: setattr(s, 'a', ((s.a >> 1) | (s.a << 7)) & 0xFF))   # RR A

        def rlc():
            c = s.a & C_FLAG
            s.a = ((s.a << 1) | (s.psw >> 7)) & 0xFF
            s.psw = (s.psw & ~C_FLAG & 0xFF) | c
        simple(0xF7, rlc)

        def rrc():
            c = (s.a << 7) & C_FLAG
            s.a = (s.a >> 1) | (s.psw & C_FLAG)
            s.psw = (s.psw & ~C_FLAG & 0xFF) | c
        simple(0x67, rrc)

        def da():
            if (s.a & 0x0F) > 9 or s.psw & A_FLAG:
                if s.a > 0xF9:
                    s.psw |= C_FLAG
                s.a = (s.a + 6) & 0xFF
            if (s.a & 0xF0) > 0x90 or s.psw & C_FLAG:
                s.a = (s.a + 0x60) & 0xFF
                s.psw |= C_FLAG
        simple(0x57, da)

        simple(0x97, lambda: setattr(s, 'psw', s.psw & ~C_FLAG & 0xFF))  # CLR C
        simple(0xA7, lambda: setattr(s, 'psw', s.psw ^ C_FLAG))          # CPL C
        simple(0x85, lambda: setattr(s, 'psw', s.psw & ~F_FLAG & 0xFF))  # CLR F0
        simple(0x95, lambda: setattr(s, 'psw', s.psw ^ F_FLAG))          # CPL F0
        simple(0xA5, setv('f1', False))                                  # CLR F1
        simple(0xB5, lambda: setattr(s, 'f1', not s.f1))                 # CPL F1
        simple(0x05, setv('xirq_enabled', True))                         # EN I
        simple(0x15, setv('xirq_enabled', False))                        # DIS I
        simple(0x25, setv('tirq_enabled', True))                         # EN TCNTI

        def dis_tcnti():
            s.tirq_enabled = False
            s.timer_overflow = False
        simple(0x35, dis_tcnti)
        simple(0xC5, lambda: setattr(s, 'psw', s.psw & ~B_FLAG & 0xFF))  # SEL RB0
        simple(0xD5, lambda: setattr(s, 'psw', s.psw | B_FLAG))          # SEL RB1
        simple(0xE5, setv('a11', 0x000))                                 # SEL MB0
        simple(0xF5, setv('a11', 0x800))                                 # SEL MB1
        simple(0xC7, lambda: setattr(s, 'a', s.psw | 0x08))              # MOV A,PSW
        simple(0xD7, lambda: setattr(s, 'psw', s.a & ~0x08 & 0xFF))      # MOV PSW,A
        simple(0x42, lambda: setattr(s, 'a', s.timer))                   # MOV A,T
        simple(0x62, lambda: setattr(s, 'timer', s.a))                   # MOV T,A
        simple(0x65, setv('timecount_enabled', 0))                       # STOP TCNT

        def strt_t():
            s.timecount_enabled = TIMER_ENABLED
            s.prescaler = 0
        simple(0x55, strt_t)

        def strt_cnt():
            if not s.timecount_enabled & COUNTER_ENABLED:
                s.t1_history = s.test_r_cb(1)
            s.timecount_enabled = COUNTER_ENABLED
        simple(0x45, strt_cnt)
        simple(0x75, setv('t0_clk', True))                               # ENT0 CLK (noted only)

        # ports and bus (2 cycles each)
        def two(code, fn):
            t[code] = lambda: (s.burn(2), fn())[0]

        def outp(n, v):
            v &= 0xFF
            if n == 1:
                s.p1 = v
            else:
                s.p2 = v
            s.port_w_cb(n, v)

        two(0x08, lambda: mov_a(s.bus_r_cb() & 0xFF))                    # INS A,BUS
        two(0x09, lambda: mov_a(s.port_r_cb(1) & s.p1))                  # IN A,P1
        two(0x0A, lambda: mov_a(s.port_r_cb(2) & s.p2))                  # IN A,P2
        two(0x02, lambda: s.bus_w_cb(s.a))                               # OUTL BUS,A
        two(0x39, lambda: outp(1, s.a))                                  # OUTL P1,A
        two(0x3A, lambda: outp(2, s.a))                                  # OUTL P2,A
        two(0x89, lambda: outp(1, s.p1 | s.fetch()))                     # ORL P1,#n
        two(0x8A, lambda: outp(2, s.p2 | s.fetch()))                     # ORL P2,#n
        two(0x99, lambda: outp(1, s.p1 & s.fetch()))                     # ANL P1,#n
        two(0x9A, lambda: outp(2, s.p2 & s.fetch()))                     # ANL P2,#n
        two(0x88, lambda: s.bus_w_cb(s.bus_r_cb() | s.fetch()))          # ORL BUS,#n
        two(0x98, lambda: s.bus_w_cb(s.bus_r_cb() & s.fetch()))          # ANL BUS,#n

        def expander():
            raise Unsupported('8243 expander op %02X at %03X' % (s.rom[s.prevpc], s.prevpc))
        for c in (0x0C, 0x0D, 0x0E, 0x0F, 0x3C, 0x3D, 0x3E, 0x3F, 0x8C, 0x8D, 0x8E, 0x8F, 0x9C, 0x9D, 0x9E, 0x9F):
            t[c] = expander
        return t


# MAME's mcs48 disassembler mnemonics (enough to list a program)
_R = ['r%d' % i for i in range(8)]


def mnemonic(rom, pc):
    """(text, length) of the instruction at pc"""
    op = rom[pc]
    arg = rom[(pc + 1) & 0xFFF]
    page = (pc + 1) & 0xF00
    lo, hi = op & 7, op & 0xF8
    if op & 0x0F in (4,) or op & 0x1F == 0x14:
        k = 'jmp' if op & 0x10 == 0 else 'call'
        return '%s $%03X' % (k, ((op >> 5) << 8) | arg), 2
    if op & 0x1F == 0x12:
        return 'jb%d $%03X' % (op >> 5, page | arg), 2
    if op >= 0xE8 and op <= 0xEF:
        return 'djnz %s,$%03X' % (_R[lo], page | arg), 2
    fam = {0x68: 'add a,%s', 0x78: 'addc a,%s', 0x58: 'anl a,%s', 0x48: 'orl a,%s', 0xD8: 'xrl a,%s',
           0xF8: 'mov a,%s', 0xA8: 'mov %s,a', 0x28: 'xch a,%s', 0x18: 'inc %s', 0xC8: 'dec %s'}
    if hi in fam:
        return fam[hi] % _R[lo], 1
    if hi == 0xB8:
        return 'mov %s,#$%02X' % (_R[lo], arg), 2
    ind = {0x60: 'add a,@r%d', 0x70: 'addc a,@r%d', 0x50: 'anl a,@r%d', 0x40: 'orl a,@r%d', 0xD0: 'xrl a,@r%d',
           0xF0: 'mov a,@r%d', 0xA0: 'mov @r%d,a', 0x20: 'xch a,@r%d', 0x30: 'xchd a,@r%d', 0x10: 'inc @r%d',
           0x80: 'movx a,@r%d', 0x90: 'movx @r%d,a'}
    if op & 0xFE in ind:
        return ind[op & 0xFE] % (op & 1), 1
    if op & 0xFE == 0xB0:
        return 'mov @r%d,#$%02X' % (op & 1, arg), 2
    imm = {0x03: 'add a,#$%02X', 0x13: 'addc a,#$%02X', 0x53: 'anl a,#$%02X', 0x43: 'orl a,#$%02X',
           0xD3: 'xrl a,#$%02X', 0x23: 'mov a,#$%02X', 0x89: 'orl p1,#$%02X', 0x8A: 'orl p2,#$%02X',
           0x99: 'anl p1,#$%02X', 0x9A: 'anl p2,#$%02X', 0x88: 'orl bus,#$%02X', 0x98: 'anl bus,#$%02X'}
    if op in imm:
        return imm[op] % arg, 2
    jcc = {0xF6: 'jc', 0xE6: 'jnc', 0xB6: 'jf0', 0x76: 'jf1', 0xC6: 'jz', 0x96: 'jnz', 0x36: 'jt0', 0x26: 'jnt0',
           0x56: 'jt1', 0x46: 'jnt1', 0x86: 'jni', 0x16: 'jtf'}
    if op in jcc:
        return '%s $%03X' % (jcc[op], page | arg), 2
    one = {0x00: 'nop', 0x27: 'clr a', 0x37: 'cpl a', 0x17: 'inc a', 0x07: 'dec a', 0x47: 'swap a', 0xE7: 'rl a',
           0x77: 'rr a', 0xF7: 'rlc a', 0x67: 'rrc a', 0x57: 'da a', 0x97: 'clr c', 0xA7: 'cpl c', 0x85: 'clr f0',
           0x95: 'cpl f0', 0xA5: 'clr f1', 0xB5: 'cpl f1', 0x05: 'en i', 0x15: 'dis i', 0x25: 'en tcnti',
           0x35: 'dis tcnti', 0xC5: 'sel rb0', 0xD5: 'sel rb1', 0xE5: 'sel mb0', 0xF5: 'sel mb1', 0xC7: 'mov a,psw',
           0xD7: 'mov psw,a', 0x42: 'mov a,t', 0x62: 'mov t,a', 0x65: 'stop tcnt', 0x55: 'strt t', 0x45: 'strt cnt',
           0x75: 'ent0 clk', 0x83: 'ret', 0x93: 'retr', 0xA3: 'movp a,@a', 0xE3: 'movp3 a,@a', 0xB3: 'jmpp @a'}
    if op in one:
        return one[op], 1
    two = {0x08: 'ins a,bus', 0x09: 'in a,p1', 0x0A: 'in a,p2', 0x02: 'outl bus,a', 0x39: 'outl p1,a',
           0x3A: 'outl p2,a'}
    if op in two:
        return two[op], 1
    return 'db $%02X' % op, 1
