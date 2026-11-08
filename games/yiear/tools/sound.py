"""Yie Ar Kung-Fu's sound on the STE, in Python (src/sound.s is the same in 68000 code; tools/sound_test.py compares).

The board has no sound CPU: the main CPU's NMI handler writes the SN76489A (18.432 MHz / 12 = 1.536 MHz) through
$4800 / $4900 and drives the VLM5030 speech chip through $4A00 / $4B00.  The STE: an SN76489A register file (the
writes of machine.YieAr's sound_log, kind 'sn') whose three tones and noise go to the YM2149's three channels once an
arcade frame (the three loudest voices, a voice keeping its YM channel while it lasts: Mr. Do!'s method, as in Track &
Field's tools/sound.py), and the VLM5030's phrases, rendered offline (engine/vlm5030.py), on the DMA sound.
"""
SN_CLOCK = 18432000 // 12
YM_CLOCK = 2000000
VTAB = (15, 14, 14, 13, 12, 12, 11, 10, 10, 9, 8, 8, 7, 6, 6, 0)     # SN attenuation (2 dB steps) -> YM level


def ym_period(n):
    """the YM period for an SN tone period (0 counts as 1024): N x 4000000 / 1536000 rounded"""
    return ((n or 1024) * 4000000 + SN_CLOCK // 2) // SN_CLOCK


def ym_noise(reg6, n2):
    """the YM noise period for the SN's noise control (the shift period 32 / 64 / 128 or 2 x tone 2's), at most 31"""
    p = 2 * (n2 or 1024) if reg6 & 3 == 3 else 32 << (reg6 & 3)
    return min(31, (p * 2000000 + SN_CLOCK // 2) // SN_CLOCK)


class SN:
    """the SN76489A's registers as src/sound.s snd_sn_w keeps them: reg[0, 2, 4] tone periods (10 bits), reg[6] the
    noise control, reg[1, 3, 5, 7] the attenuations"""

    def __init__(self):
        self.reg = [0] * 8
        self.latch = 0
        self.last = 0
        self.dirty = True

    def write(self, v):
        self.dirty = True
        if v & 0x80:
            self.latch = (v >> 4) & 7
            self.reg[self.latch] = (self.reg[self.latch] & 0x3F0) | (v & 15)
        elif self.latch & 1 or self.latch == 6:
            self.reg[self.latch] = (self.reg[self.latch] & 0x3F0) | (v & 15)
        else:
            self.reg[self.latch] = (self.reg[self.latch] & 15) | ((v & 0x3F) << 4)


class YM:
    """src/sound.s snd_ym: the YM2149's registers from the SN's (ch: per YM channel its voice, -1 none; cache: the
    registers as written, 0xFF not yet)"""

    def __init__(self):
        self.ch = [-1, -1, -1]
        self.cache = [0xFF] * 16

    def frame(self, sn):
        keys = []
        for k in range(4):
            a = sn.reg[2 * k + 1] & 15
            if a != 15:
                keys.append(((16 - a) * 8 + 7 - k, k))
        pick = [k for _, k in sorted(keys, reverse=True)[:3]]
        new = [-1, -1, -1]
        rest = []
        for k in pick:
            if k in self.ch:
                new[self.ch.index(k)] = k
            else:
                rest.append(k)
        for k in rest:
            new[new.index(-1)] = k
        self.ch = new
        regs = [0] * 16
        mixer = 0x3F
        noise = 0
        for j, k in enumerate(new):
            if k < 0:
                continue
            if k == 3:
                mixer &= ~(8 << j)
                noise = ym_noise(sn.reg[6], sn.reg[4])
            else:
                p = ym_period(sn.reg[2 * k])
                regs[2 * j], regs[2 * j + 1] = p & 0xFF, p >> 8
                mixer &= ~(1 << j)
            regs[8 + j] = VTAB[sn.reg[2 * k + 1] & 15]
        regs[6] = noise
        regs[7] = mixer | 0xC0
        out = []
        for r in range(11):
            if regs[r] != self.cache[r]:
                self.cache[r] = regs[r]
                out.append((r, regs[r]))
        return out
