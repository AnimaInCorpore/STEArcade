"""The FM part of a YM3526 (OPL) as far as a square-wave chip can play it: per channel the pitch of its carriers and
their loudness through the envelope generator, from the register writes a sound driver makes (engine/opn.py is the
YM2203's).

After MAME's ymfm (ymfm_opl.cpp cache_operator_data, ymfm_fm.ipp clock_envelope): nine channels of two operators
(modulator, carrier: register offsets 0-2, 8-10, 16-18 and + 3), the envelope clocked every sample (clock / 72), the
rates AR / DR / RR * 4 with the key scale (KSR: the keycode, else >> 2), the sustain bit (EG-TYP: hold at the sustain
level, else go on at the release rate), total level << 3 plus the key scale level.  Carriers: the second operator,
both with the connection bit (C0).  Not modelled: the rhythm mode, the LFO (AM / vibrato), the waveform.

    chip = OPL(clock_hz)    write(reg, value), advance(eg_clocks), channel(ch) -> (hz, amplitude)
"""
from opn import INCREMENTS, ATTACK, DECAY, SUSTAIN, RELEASE, Operator

MOD = (0, 1, 2, 8, 9, 10, 16, 17, 18)       # the modulator's register offset of each channel (the carrier: + 3)
KSL_ATTEN = (0, 24, 32, 37, 40, 43, 45, 47, 48, 50, 51, 52, 53, 54, 55, 56)
MULT = (1, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 20, 24, 24, 30, 30)    # x 2 (0: 0.5)


class OPL:
    def __init__(self, clock=3000000):
        self.regs = [0] * 256
        self.fs = clock / 72
        self.eg_rate = self.fs                          # envelope clocks a second
        self.counter = 0
        self.ops = [[Operator() for _ in range(2)] for _ in range(9)]

    def off(self, ch, op):
        return MOD[ch] + 3 * op

    def block_freq(self, ch):
        return (self.regs[0xB0 + ch] & 0x1F) << 8 | self.regs[0xA0 + ch]

    def keycode(self, ch):
        bf = self.block_freq(ch)
        nts = self.regs[0x08] >> 6 & 1
        return ((bf >> 10) & 7) << 1 | (bf >> (9 - nts)) & 1

    def rate(self, ch, op, state):
        o = self.off(ch, op)
        ksr = self.keycode(ch) >> (2 * ((self.regs[0x20 + o] >> 4 & 1) ^ 1))
        if state == ATTACK:
            raw = (self.regs[0x60 + o] >> 4) * 4
        elif state == DECAY:
            raw = (self.regs[0x60 + o] & 15) * 4
        elif state == SUSTAIN:
            raw = 0 if self.regs[0x20 + o] & 0x20 else (self.regs[0x80 + o] & 15) * 4
        else:
            raw = (self.regs[0x80 + o] & 15) * 4
        return 0 if raw == 0 else min(raw + ksr, 63)

    def sustain(self, ch, op):
        sl = self.regs[0x80 + self.off(ch, op)] >> 4
        return (sl | ((sl + 1) & 0x10)) << 5

    def total_level(self, ch, op):
        o = self.off(ch, op)
        tl = (self.regs[0x40 + o] & 63) << 3
        k = self.regs[0x40 + o] >> 6
        ksl = (k >> 1) | (k & 1) << 1
        if ksl:
            bf = self.block_freq(ch)
            tl += max(0, KSL_ATTEN[(bf >> 6) & 15] - 8 * (((bf >> 10) & 7) ^ 7)) << ksl
        return tl

    def write(self, reg, v):
        self.regs[reg] = v
        if 0xB0 <= reg <= 0xB8:
            ch = reg - 0xB0
            on = v >> 5 & 1
            for op in range(2):
                o = self.ops[ch][op]
                if on and not o.key:
                    if o.state != ATTACK:
                        o.state = ATTACK
                        if self.rate(ch, op, ATTACK) >= 62:
                            o.att = 0
                elif o.key and not on:
                    o.state = RELEASE
                o.key = on

    def carriers(self, ch):
        return (0, 1) if self.regs[0xC0 + ch] & 1 else (1,)

    def advance(self, clocks):
        end = self.counter + clocks
        for ch in range(9):
            for op in self.carriers(ch):
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
            if shift < 11:
                step = 1 << (11 - shift)
                c = (c + step - 1) // step * step
                if c >= end:
                    return
            ec = c << shift
            inc = INCREMENTS[rate] >> (4 * ((ec >> max(11, shift)) & 7)) & 15
            if o.state == ATTACK:
                if rate < 62:
                    o.att += (~o.att * inc) >> 4
            else:
                o.att = min(o.att + inc, 0x3FF)
            c += 1

    def channel(self, ch):
        """(frequency in Hz, the carriers' summed amplitude: 1 = one at full level); the frequency of the lowest
        carrier within 12 dB of the loudest"""
        bf = self.block_freq(ch)
        fnum, block = bf & 0x3FF, (bf >> 10) & 7
        car = []
        for op in self.carriers(ch):
            a = min(self.ops[ch][op].att + self.total_level(ch, op), 0x3FF)
            m = MULT[self.regs[0x20 + self.off(ch, op)] & 15] / 2
            car.append((0.0 if a >= 0x3FF else 2.0 ** (-a / 64), m if m else 0.5))
        amp = sum(v for v, m in car)
        top = max(v for v, m in car)
        mul = min(m for v, m in car if v >= top / 4)
        hz = (fnum << block) * mul * self.fs / (1 << 20)
        return hz, amp
