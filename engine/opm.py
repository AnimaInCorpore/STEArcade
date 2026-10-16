"""The FM part of a YM2151 (OPM) as far as a square-wave chip can play it: per channel the pitch of its carriers and
their loudness through the envelope generator, from the register writes a sound driver makes (engine/opn.py for the
YM2151's register layout).

As opn.py, after MAME's ymfm (ymfm_fm.ipp clock_envelope / start_attack / start_release, ymfm_opm.cpp): 10-bit
attenuation, the rate table, key scaling, the sustain level, total level << 3, an envelope clock every 3 FM samples
(the clock / 64).  Only the carriers are modelled.  Not modelled: the LFO, detune, noise.
The YM2151's layout: 8 channels; $08 key on (bits 0-2 the channel, bits 3-6 the operators M1 C1 M2 C2); $20 + ch the
algorithm (bits 0-2); $28 + ch the key code (octave bits 4-6, note bits 0-3: C# D D# - E F F# - G G# A - A# B C), $30 +
ch the key fraction (bits 2-7, 64ths of a semitone); per operator $40 MUL, $60 TL, $80 KS / AR, $A0 D1R, $C0 D2R, $E0
D1L / RR at + ch + the slot (M1 0, M2 8, C1 16, C2 24).

    chip = OPM(3579545)    write(reg, value), advance(eg_clocks), channel(ch) -> (hz, amplitude)
"""
from opn import INCREMENTS, ATTACK, DECAY, SUSTAIN, RELEASE, CARRIERS, Operator

SLOT_OFFSET = (0, 16, 8, 24)     # S1..S4 = M1, C1, M2, C2 (opn.py's operator numbering, its CARRIERS table)
NOTE = {0: 0, 1: 1, 2: 2, 4: 3, 5: 4, 6: 5, 8: 6, 9: 7, 10: 8, 12: 9, 13: 10, 14: 11}   # semitones above C#


class OPM:
    def __init__(self, clock=3579545):
        self.clock = clock
        self.regs = [0] * 256
        self.fs = clock / 64                            # FM samples a second
        self.eg_rate = self.fs / 3                      # envelope clocks a second
        self.counter = 0
        self.ops = [[Operator() for _ in range(4)] for _ in range(8)]

    def op_reg(self, ch, op, base):
        return self.regs[base + ch + SLOT_OFFSET[op]]

    def keycode(self, ch):
        return (self.regs[0x28 + ch] >> 2) & 0x1F

    def rate(self, ch, op, state):
        ksr = self.keycode(ch) >> ((self.op_reg(ch, op, 0x80) >> 6) ^ 3)
        raw = [(self.op_reg(ch, op, 0x80) & 31) * 2, (self.op_reg(ch, op, 0xA0) & 31) * 2,
               (self.op_reg(ch, op, 0xC0) & 31) * 2, (self.op_reg(ch, op, 0xE0) & 15) * 4 + 2][state]
        return 0 if raw == 0 else min(raw + ksr, 63)

    def sustain(self, ch, op):
        sl = self.op_reg(ch, op, 0xE0) >> 4
        return (sl | ((sl + 1) & 0x10)) << 5

    def write(self, reg, v):
        self.regs[reg] = v
        if reg == 0x08:
            ch = v & 7
            for op in range(4):
                on = v >> (3 + op) & 1
                o = self.ops[ch][op]
                if on and not o.key:
                    if o.state != ATTACK:
                        o.state = ATTACK
                        if self.rate(ch, op, ATTACK) >= 62:
                            o.att = 0
                elif o.key and not on:
                    o.state = RELEASE
                o.key = on

    def advance(self, clocks):
        end = self.counter + clocks
        for ch in range(8):
            for op in CARRIERS[self.regs[0x20 + ch] & 7]:
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
        """(frequency in Hz, the carriers' summed amplitude: 1 = one at full level); the frequency the lowest carrier's
        within 12 dB of the loudest"""
        kc = self.regs[0x28 + ch]
        octave, note = (kc >> 4) & 7, NOTE.get(kc & 15, 11)
        semis = (octave - 4) * 12 + note - 8 + (self.regs[0x30 + ch] >> 2) / 64
        base = 440.0 * 2 ** (semis / 12) * self.clock / 3579545
        car = []
        for op in CARRIERS[self.regs[0x20 + ch] & 7]:
            a = min(self.ops[ch][op].att + ((self.op_reg(ch, op, 0x60) & 127) << 3), 0x3FF)
            m = self.op_reg(ch, op, 0x40) & 15
            car.append((0.0 if a >= 0x3FF else 2.0 ** (-a / 64), m if m else 0.5))
        amp = sum(v for v, m in car)
        top = max(v for v, m in car)
        mul = min(m for v, m in car if v >= top / 4) if top > 0 else 1
        return base * mul, amp
