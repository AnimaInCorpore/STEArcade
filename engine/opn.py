"""The FM part of a YM2203 (OPN) as far as a square-wave chip can play it: per channel the pitch of its carriers and
their loudness through the envelope generator, from the register writes a sound driver makes.

The envelope generator follows MAME's ymfm (3rdparty/ymfm/src/ymfm_fm.ipp clock_envelope / start_attack /
start_release, ymfm_opn.cpp cache_operator_data): 10-bit attenuation (64 units = 6 dB), the rate table, key scaling,
the sustain level, total level << 3; an envelope clock every 3 FM samples.  Only the carriers are modelled: the
modulators shape the timbre, which a square wave does not have.  Not modelled: SSG-EG, the LFO (the YM2203 has
none), detune, channel 3's special mode.

    chip = OPN(clock_hz, prescale)    write(reg, value), advance(eg_clocks), channel(ch) -> (hz, amplitude)
"""

INCREMENTS = [
    0x00000000, 0x00000000, 0x10101010, 0x10101010, 0x10101010, 0x10101010, 0x11101110, 0x11101110,
    0x10101010, 0x10111010, 0x11101110, 0x11111110, 0x10101010, 0x10111010, 0x11101110, 0x11111110,
    0x10101010, 0x10111010, 0x11101110, 0x11111110, 0x10101010, 0x10111010, 0x11101110, 0x11111110,
    0x10101010, 0x10111010, 0x11101110, 0x11111110, 0x10101010, 0x10111010, 0x11101110, 0x11111110,
    0x10101010, 0x10111010, 0x11101110, 0x11111110, 0x10101010, 0x10111010, 0x11101110, 0x11111110,
    0x10101010, 0x10111010, 0x11101110, 0x11111110, 0x10101010, 0x10111010, 0x11101110, 0x11111110,
    0x11111111, 0x21112111, 0x21212121, 0x22212221, 0x22222222, 0x42224222, 0x42424242, 0x44424442,
    0x44444444, 0x84448444, 0x84848484, 0x88848884, 0x88888888, 0x88888888, 0x88888888, 0x88888888]

ATTACK, DECAY, SUSTAIN, RELEASE = range(4)
CARRIERS = [(3,), (3,), (3,), (3,), (1, 3), (1, 2, 3), (1, 2, 3), (0, 1, 2, 3)]    # operators S1..S4 = 0..3
SLOT_OFFSET = (0, 8, 4, 12)     # register offset of S1, S2, S3, S4 (the register order is S1 S3 S2 S4)


class Operator:
    def __init__(self):
        self.att = 0x3FF
        self.state = RELEASE
        self.key = 0


class OPN:
    def __init__(self, clock=1500000, prescale=3):
        self.regs = [0] * 256
        self.fs = clock / (12 * prescale)              # FM samples a second
        self.eg_rate = self.fs / 3                      # envelope clocks a second
        self.counter = 0                                # envelope clocks so far
        self.ops = [[Operator() for _ in range(4)] for _ in range(3)]

    # ---- the registers
    def op_reg(self, ch, op, base):
        return self.regs[base + ch + SLOT_OFFSET[op]]

    def block_freq(self, ch):
        return (self.regs[0xA4 + ch] & 0x3F) << 8 | self.regs[0xA0 + ch]

    def keycode(self, ch):
        bf = self.block_freq(ch)
        return ((bf >> 10) & 15) << 1 | (0xFE80 >> ((bf >> 7) & 15)) & 1

    def rate(self, ch, op, state):
        ksr = self.keycode(ch) >> ((self.op_reg(ch, op, 0x50) >> 6) ^ 3)
        raw = [(self.op_reg(ch, op, 0x50) & 31) * 2, (self.op_reg(ch, op, 0x60) & 31) * 2,
               (self.op_reg(ch, op, 0x70) & 31) * 2, (self.op_reg(ch, op, 0x80) & 15) * 4 + 2][state]
        return 0 if raw == 0 else min(raw + ksr, 63)

    def sustain(self, ch, op):
        sl = self.op_reg(ch, op, 0x80) >> 4
        return (sl | ((sl + 1) & 0x10)) << 5

    def write(self, reg, v):
        if reg == 0xA4 or reg == 0xA5 or reg == 0xA6:
            self.regs[reg] = v                          # (latched: takes effect with the A0 write; drivers write A4 first)
            return
        self.regs[reg] = v
        if reg == 0x28:
            ch = v & 3
            if ch == 3:
                return
            for op in range(4):
                on = v >> (4 + op) & 1
                o = self.ops[ch][op]
                if on and not o.key:
                    if o.state != ATTACK:
                        o.state = ATTACK
                        if self.rate(ch, op, ATTACK) >= 62:
                            o.att = 0
                elif o.key and not on:
                    o.state = RELEASE
                o.key = on

    # ---- the envelopes
    def advance(self, clocks):
        """run `clocks` envelope clocks (the carriers only)"""
        end = self.counter + clocks
        for ch in range(3):
            for op in CARRIERS[self.regs[0xB0 + ch] & 7]:
                self.run_op(ch, op, self.counter, end)
        self.counter = end

    def run_op(self, ch, op, c, end):
        o = self.ops[ch][op]
        rates = [self.rate(ch, op, s) for s in range(4)]
        sustain = self.sustain(ch, op)
        while c < end:
            if o.state == ATTACK and o.att == 0:
                o.state = DECAY
            if o.state == DECAY and o.att >= sustain:
                o.state = SUSTAIN
            rate = rates[o.state]
            if rate == 0 or (o.state != ATTACK and o.att >= 0x3FF):
                return
            shift = rate >> 2
            if shift < 11:                              # (the clocks where (c << shift) & 0x7FF == 0)
                step = 1 << (11 - shift)
                c = (c + step - 1) // step * step
                if c >= end:
                    return
            ec = c << shift
            inc = INCREMENTS[rate] >> (4 * ((ec >> max(11, shift)) & 7)) & 15
            if o.state == ATTACK:
                if rate < 62:
                    o.att += (~o.att * inc) >> 4        # (C: ~ of the promoted int, an arithmetic shift)
            else:
                o.att = min(o.att + inc, 0x3FF)
            c += 1

    # ---- the output
    def channel(self, ch):
        """(frequency in Hz, the carriers' summed amplitude: 1 = one at full level).  The frequency is the lowest of
        the carriers within 12 dB of the loudest (their multipliers differ: the lowest is the fundamental)."""
        bf = self.block_freq(ch)
        fnum, block = bf & 0x7FF, bf >> 11
        car = []
        for op in CARRIERS[self.regs[0xB0 + ch] & 7]:
            a = min(self.ops[ch][op].att + ((self.op_reg(ch, op, 0x40) & 127) << 3), 0x3FF)
            m = self.op_reg(ch, op, 0x30) & 15
            car.append((0.0 if a >= 0x3FF else 2.0 ** (-a / 64), m if m else 0.5))
        amp = sum(v for v, m in car)
        top = max(v for v, m in car)
        mul = min(m for v, m in car if v >= top / 4)
        hz = (fnum << block) / 2 * mul * self.fs / (1 << 20)
        return hz, amp
