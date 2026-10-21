"""Fujitsu MB88xx 4-bit MCU (MB8843 / MB8844: the Namco 51XX, 54XX), a port of MAME 0.289's mb88xx.cpp.

The program is 1 KB (PA:PC, 6-bit PC in 64-byte pages), the data RAM 64 nibbles addressed by X:Y.  One machine cycle is
six input clocks: the 1.536 MHz of Galaga's custom chips give 256,000 cycles a second, most instructions take one.
`cycles` counts machine cycles, interrupts included, as MAME's icount does.

The ports are callbacks (an unconnected input reads 0, as in MAME): read_k(), read_r(n), write_r(n, v), write_o(byte, mask) (the 8-bit PLA: OUTO writes the nibble
selected by the carry), write_p(v).  set_irq() is the /IRQ pin (an interrupt on the rising logical edge when the
external interrupt is enabled), set_tc() the timer clock pin (counts on the falling edge when enabled).  The serial port
is not used by the 51XX and 54XX and is not modelled (enabling it raises).
"""

TIMER_PRESCALE = 32
SERIAL_PRESCALE = 6          # input clocks per serial bit: one machine cycle
SERIAL_DISABLE_THRESH = 1000
INT_SERIAL, INT_TIMER, INT_EXTERNAL = 1, 2, 4


class MB88:
    def __init__(self, rom, ram_size=64, read_k=None, read_r=None, write_r=None, write_o=None, write_p=None,
                 read_si=None):
        self.rom = bytes(rom)
        self.pmask = len(self.rom) - 1
        self.ram = bytearray(ram_size)
        self.dmask = ram_size - 1
        self.read_k = read_k or (lambda: 0)
        self.read_r = read_r or (lambda n: 0)
        self.write_r = write_r or (lambda n, v: None)
        self.write_o = write_o or (lambda v, mask: None)
        self.write_p = write_p or (lambda v: None)
        self.read_si = read_si or (lambda: 0)
        self.irq_line = 0         # m_if
        self.ctr = 0              # the TC pin
        self.o_output = 0
        self.cycles = 0
        self.reset()

    def reset(self):
        self.pc = self.pa = 0
        self.sp = [0, 0, 0, 0]
        self.si = 0
        self.a = self.x = self.y = 0
        self.st = 1
        self.zf = self.cf = self.vf = self.sf = 0
        self.pio = 0
        self.th = self.tl = self.tp = 0
        self.sb = 0
        self.sbcount = 0
        self.serial_on = False
        self.pending = 0
        self.in_irq = False

    # ---- pins ----------------------------------------------------------
    def set_irq(self, state):
        state = 1 if state else 0
        if not self.irq_line and state and (self.pio & INT_EXTERNAL):
            self.pending |= INT_EXTERNAL
        self.irq_line = state

    def set_tc(self, state):
        state = 1 if state else 0
        if self.ctr and not state and (self.pio & 0x40):
            self._timer()
        self.ctr = state

    # ---- helpers -------------------------------------------------------
    @property
    def addr(self):
        return (self.pa << 6) | self.pc

    def _fetch(self):
        v = self.rom[((self.pa << 6) | self.pc) & self.pmask]
        self.pc += 1
        if self.pc >= 0x40:
            self.pc = 0
            self.pa += 1
        return v

    def _ea(self):
        return ((self.x << 4) | self.y) & self.dmask

    def _rd(self):
        return self.ram[self._ea()] & 0x0f

    def _wr(self, v):
        self.ram[self._ea()] = v & 0x0f

    def _pio_enable(self, new):
        if (self.pio ^ new) & 0x30:
            if new & 0x30 == 0:
                self.serial_on = False
            elif new & 0x30 == 0x20:
                self.serial_on = True
            else:
                raise NotImplementedError("MB88 serial enable %02X" % (new & 0x30))
        self.pio = new

    def _serial(self, n):
        for _ in range(n):
            self.sbcount += 1
            if self.sbcount >= SERIAL_DISABLE_THRESH:
                self.serial_on = False
            if not self.sf:
                self.sb = (self.sb >> 1) | (8 if self.read_si() else 0)
                if self.sbcount >= 4:
                    self.sf = 1
                    self.pending |= INT_SERIAL
            if not self.serial_on:
                break

    def _timer(self):
        self.tl = (self.tl + 1) & 0x0f
        if self.tl == 0:
            self.th = (self.th + 1) & 0x0f
            if self.th == 0:
                self.vf = 1
                self.pending |= INT_TIMER

    def _pla(self, index):
        shift = 4 if index & 0x10 else 0
        mask = 0x0f << shift
        self.o_output = (self.o_output & ~mask) | ((index << shift) & mask)
        self.write_o(self.o_output, mask)

    def _burn(self, n):
        self.cycles += n
        if self.serial_on:
            self._serial(n)
        if self.pio & 0x80:
            self.tp += n
            while self.tp >= TIMER_PRESCALE:
                self.tp -= TIMER_PRESCALE
                self._timer()
        if not self.in_irq and self.pending & self.pio:
            self.in_irq = True
            self.sp[self.si] = ((self.pa << 6) | self.pc) | (self.cf << 15) | (self.zf << 14) | (self.st << 13)
            self.si = (self.si + 1) & 3
            p = self.pending & self.pio
            if p & INT_EXTERNAL:
                self.pc = 0x02
            elif p & INT_TIMER:
                self.pc = 0x04
            else:
                self.pc = 0x06
            self.pa = 0
            self.st = 1
            self.pending = 0
            self._burn(3)

    def run_to(self, cycle):
        while self.cycles < cycle:
            self.step()

    # ---- one instruction -----------------------------------------------
    def step(self):
        op = self._fetch()
        oc = 1
        if op >= 0xc0:                                   # jmp
            if self.st:
                self.pc = op & 0x3f
            self.st = 1
        elif op >= 0xb0:                                 # ci
            arg = (op & 0x0f) - self.a
            self.cf = 1 if arg & 0x10 else 0
            arg &= 0x0f
            self.st = 0 if arg == 0 else 1
            self.zf = self.st ^ 1
        elif op >= 0xa0:                                 # cyi
            arg = (op & 0x0f) - self.y
            self.cf = 1 if arg & 0x10 else 0
            arg &= 0x0f
            self.st = 0 if arg == 0 else 1
            self.zf = self.st ^ 1
        elif op >= 0x90:                                 # li
            self.a = op & 0x0f
            self.zf = 1 if self.a == 0 else 0
            self.st = 1
        elif op >= 0x80:                                 # lyi
            self.y = op & 0x0f
            self.zf = 1 if self.y == 0 else 0
            self.st = 1
        elif op >= 0x70:                                 # ai
            arg = (op & 0x0f) + self.a
            self.st = 0 if arg & 0x10 else 1
            self.cf = self.st ^ 1
            self.a = arg & 0x0f
            self.zf = 1 if self.a == 0 else 0
        elif op >= 0x60:                                 # call / jpl
            arg = self._fetch()
            oc = 2
            if self.st:
                if op < 0x68:
                    self.sp[self.si] = (self.pa << 6) | self.pc
                    self.si = (self.si + 1) & 3
                self.pc = arg & 0x3f
                self.pa = ((op & 7) << 2) | (arg >> 6)
            self.st = 1
        elif op >= 0x40:
            self._op40(op)
        else:
            oc = self._op00(op)
        self._burn(oc)
        return oc

    def _op40(self, op):
        b = op & 3
        g = op & 0xfc
        if g == 0x40:                                    # setD
            self.write_r(0, (self.read_r(0) & 0x0f) | (1 << b))
            self.st = 1
        elif g == 0x44:                                  # rstD
            self.write_r(0, (self.read_r(0) & 0x0f) & ~(1 << b))
            self.st = 1
        elif g == 0x48:                                  # tstD
            self.st = 0 if (self.read_r(2) & 0x0f) & (1 << b) else 1
        elif g == 0x4c:                                  # tba
            self.st = 0 if self.a & (1 << b) else 1
        elif g == 0x50:                                  # xd
            arg = self.ram[b] & 0x0f
            self.ram[b] = self.a
            self.a = arg
            self.zf = 1 if self.a == 0 else 0
            self.st = 1
        elif g == 0x54:                                  # xyd
            arg = self.ram[b + 4] & 0x0f
            self.ram[b + 4] = self.y
            self.y = arg
            self.zf = 1 if self.y == 0 else 0
            self.st = 1
        else:                                            # lxi
            self.x = op & 7
            self.zf = 1 if self.x == 0 else 0
            self.st = 1

    def _op00(self, op):
        oc = 1
        if op == 0x00:                                   # nop
            self.st = 1
        elif op == 0x01:                                 # outO
            self._pla((self.cf << 4) | self.a)
            self.st = 1
        elif op == 0x02:                                 # outP
            self.write_p(self.a)
            self.st = 1
        elif op == 0x03:                                 # outR
            self.write_r(self.y & 3, self.a)
            self.st = 1
        elif op == 0x04:                                 # tay
            self.y = self.a
            self.st = 1
        elif op == 0x05:                                 # tath
            self.th = self.a
            self.st = 1
        elif op == 0x06:                                 # tatl
            self.tl = self.a
            self.st = 1
        elif op == 0x07:                                 # tas
            self.sb = self.a
            self.st = 1
        elif op == 0x08:                                 # icy
            self.y += 1
            self.st = 0 if self.y & 0x10 else 1
            self.y &= 0x0f
            self.zf = 1 if self.y == 0 else 0
        elif op == 0x09:                                 # icm
            arg = self._rd() + 1
            self.st = 0 if arg & 0x10 else 1
            arg &= 0x0f
            self.zf = 1 if arg == 0 else 0
            self._wr(arg)
        elif op == 0x0a:                                 # stic
            self._wr(self.a)
            self.y += 1
            self.st = 0 if self.y & 0x10 else 1
            self.y &= 0x0f
            self.zf = 1 if self.y == 0 else 0
        elif op == 0x0b:                                 # x
            arg = self._rd()
            self._wr(self.a)
            self.a = arg
            self.zf = 1 if self.a == 0 else 0
            self.st = 1
        elif op == 0x0c:                                 # rol
            self.a = (self.a << 1) | self.cf
            self.st = 0 if self.a & 0x10 else 1
            self.cf = self.st ^ 1
            self.a &= 0x0f
            self.zf = 1 if self.a == 0 else 0
        elif op == 0x0d:                                 # l
            self.a = self._rd()
            self.zf = 1 if self.a == 0 else 0
            self.st = 1
        elif op == 0x0e:                                 # adc
            arg = self._rd() + self.a + self.cf
            self.st = 0 if arg & 0x10 else 1
            self.cf = self.st ^ 1
            self.a = arg & 0x0f
            self.zf = 1 if self.a == 0 else 0
        elif op == 0x0f:                                 # and
            self.a &= self._rd()
            self.zf = 1 if self.a == 0 else 0
            self.st = self.zf ^ 1
        elif op == 0x10:                                 # daa
            if self.cf or self.a > 9:
                self.a += 6
            self.st = 0 if self.a & 0x10 else 1
            self.cf = self.st ^ 1
            self.a &= 0x0f
        elif op == 0x11:                                 # das
            if self.cf or self.a > 9:
                self.a += 10
            self.st = 0 if self.a & 0x10 else 1
            self.cf = self.st ^ 1
            self.a &= 0x0f
        elif op == 0x12:                                 # inK
            self.a = self.read_k() & 0x0f
            self.zf = 1 if self.a == 0 else 0
            self.st = 1
        elif op == 0x13:                                 # inR
            self.a = self.read_r(self.y & 3) & 0x0f
            self.zf = 1 if self.a == 0 else 0
            self.st = 1
        elif op == 0x14:                                 # tya
            self.a = self.y
            self.zf = 1 if self.a == 0 else 0
            self.st = 1
        elif op == 0x15:                                 # ttha
            self.a = self.th
            self.zf = 1 if self.a == 0 else 0
            self.st = 1
        elif op == 0x16:                                 # ttla
            self.a = self.tl
            self.zf = 1 if self.a == 0 else 0
            self.st = 1
        elif op == 0x17:                                 # tsa
            self.a = self.sb
            self.zf = 1 if self.a == 0 else 0
            self.st = 1
        elif op == 0x18:                                 # dcy (zf unchanged)
            self.y -= 1
            self.st = 0 if self.y & 0x10 else 1
            self.y &= 0x0f
        elif op == 0x19:                                 # dcm
            arg = self._rd() - 1
            self.st = 0 if arg & 0x10 else 1
            arg &= 0x0f
            self.zf = 1 if arg == 0 else 0
            self._wr(arg)
        elif op == 0x1a:                                 # stdc
            self._wr(self.a)
            self.y -= 1
            self.st = 0 if self.y & 0x10 else 1
            self.y &= 0x0f
            self.zf = 1 if self.y == 0 else 0
        elif op == 0x1b:                                 # xx
            self.x, self.a = self.a, self.x
            self.zf = 1 if self.a == 0 else 0
            self.st = 1
        elif op == 0x1c:                                 # ror
            self.a |= self.cf << 4
            self.st = 0 if (self.a << 4) & 0x10 else 1
            self.cf = self.st ^ 1
            self.a = (self.a >> 1) & 0x0f
            self.zf = 1 if self.a == 0 else 0
        elif op == 0x1d:                                 # st
            self._wr(self.a)
            self.st = 1
        elif op == 0x1e:                                 # sbc
            arg = self._rd() - self.a - self.cf
            self.st = 0 if arg & 0x10 else 1
            self.cf = self.st ^ 1
            self.a = arg & 0x0f
            self.zf = 1 if self.a == 0 else 0
        elif op == 0x1f:                                 # or
            self.a |= self._rd()
            self.zf = 1 if self.a == 0 else 0
            self.st = self.zf ^ 1
        elif op == 0x20:                                 # setR
            n = self.y >> 2
            self.write_r(n, (self.read_r(n) & 0x0f) | (1 << (self.y & 3)))
            self.st = 1
        elif op == 0x21:                                 # setc
            self.cf = 1
            self.st = 1
        elif op == 0x22:                                 # rstR
            n = self.y >> 2
            self.write_r(n, (self.read_r(n) & 0x0f) & ~(1 << (self.y & 3)))
            self.st = 1
        elif op == 0x23:                                 # rstc
            self.cf = 0
            self.st = 1
        elif op == 0x24:                                 # tstr
            self.st = 0 if (self.read_r(self.y >> 2) & 0x0f) & (1 << (self.y & 3)) else 1
        elif op == 0x25:                                 # tsti
            self.st = self.irq_line ^ 1
        elif op == 0x26:                                 # tstv
            self.st = self.vf ^ 1
            self.vf = 0
        elif op == 0x27:                                 # tsts
            self.st = self.sf ^ 1
            if self.sf:
                if self.sbcount >= SERIAL_DISABLE_THRESH and self.pio & 0x30 == 0x20:
                    self.serial_on = True
                self.sbcount = 0
            self.sf = 0
        elif op == 0x28:                                 # tstc
            self.st = self.cf ^ 1
        elif op == 0x29:                                 # tstz
            self.st = self.zf ^ 1
        elif op == 0x2a:                                 # sts
            self._wr(self.sb)
            self.zf = 1 if self.sb == 0 else 0
            self.st = 1
        elif op == 0x2b:                                 # ls
            self.sb = self._rd()
            self.zf = 1 if self.sb == 0 else 0
            self.st = 1
        elif op == 0x2c:                                 # rts
            self.si = (self.si - 1) & 3
            self.pc = self.sp[self.si] & 0x3f
            self.pa = (self.sp[self.si] >> 6) & 0x1f
            self.st = 1
        elif op == 0x2d:                                 # neg
            self.a = (-self.a) & 0x0f
            self.st = 0 if self.a == 0 else 1
        elif op == 0x2e:                                 # c
            arg = self._rd() - self.a
            self.cf = 1 if arg & 0x10 else 0
            arg &= 0x0f
            self.st = 0 if arg == 0 else 1
            self.zf = self.st ^ 1
        elif op == 0x2f:                                 # eor
            self.a ^= self._rd()
            self.st = 0 if self.a == 0 else 1
            self.zf = self.st ^ 1
        elif op < 0x34:                                  # sbit
            self._wr(self._rd() | (1 << (op & 3)))
            self.st = 1
        elif op < 0x38:                                  # rbit
            self._wr(self._rd() & ~(1 << (op & 3)))
            self.st = 1
        elif op < 0x3c:                                  # tbit
            self.st = 0 if self._rd() & (1 << (op & 3)) else 1
        elif op == 0x3c:                                 # rti
            self.in_irq = False
            self.si = (self.si - 1) & 3
            v = self.sp[self.si]
            self.pc = v & 0x3f
            self.pa = (v >> 6) & 0x1f
            self.st = (v >> 13) & 1
            self.zf = (v >> 14) & 1
            self.cf = (v >> 15) & 1
        elif op == 0x3d:                                 # jpa (the operand is not skipped: the jump leaves anyway)
            self.pa = self.rom[((self.pa << 6) | self.pc) & self.pmask] & 0x1f
            self.pc = self.a * 4
            oc = 2
            self.st = 1
        elif op == 0x3e:                                 # en
            self._pio_enable(self.pio | self._fetch())
            oc = 2
            self.st = 1
        else:                                            # dis
            self._pio_enable(self.pio & ~self._fetch())
            oc = 2
            self.st = 1
        return oc
