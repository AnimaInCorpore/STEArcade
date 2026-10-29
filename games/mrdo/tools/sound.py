"""Mr. Do!'s sound on the STE, in Python: the model of src/sound.s (tools/sound_test.py compares them).

The two SN76489s (4.1 MHz) as MAME's sn76496.cpp keeps their registers; once an arcade frame the six tone voices go to
the YM2149's three channels: the three loudest audible ones (ties: the lower voice), a YM channel holding a chosen
voice keeps it, the others take the rest in order.  Periods N -> N * 40 / 41 (the YM at 2 MHz: 2000000 / (16 P) =
4100000 / (32 N)); attenuation a (2 dB a step) -> the YM's level 15 - round(2 a / 3) (~3 dB a step), 15 -> 0.  The
game never programs the noise: it is left out.
"""

SN_CLOCK = 8200000 // 2
YM_CLOCK = 2000000
VTAB = (15, 14, 14, 13, 12, 12, 11, 10, 10, 9, 8, 8, 7, 6, 6, 0)


def ym_period(n):
    """the YM period for an SN period (0 counts as 1024): N * 40 / 41 rounded"""
    return ((n or 1024) * 80 + 41) // 82


class SN76489:
    """the registers of MAME's sn76496_base_device (an SN76489): 0, 2, 4 periods, 6 the noise control, 1, 3, 5, 7
    volumes; after reset all 0 (the volumes the loudest)"""

    def __init__(self):
        self.reg = [0] * 8
        self.latch = 0

    def write(self, v):
        if v & 0x80:
            r = self.latch = (v >> 4) & 7
            self.reg[r] = (self.reg[r] & 0x3F0) | (v & 0x0F)
        else:
            r = self.latch
            if r in (0, 2, 4):
                self.reg[r] = (self.reg[r] & 0x0F) | ((v & 0x3F) << 4)
            else:
                self.reg[r] = (self.reg[r] & 0x3F0) | (v & 0x0F)


class STESound:
    """src/sound.s: the register files, the YM's channel choice (ch) and registers (cache: 16, 0xFF not written yet)"""

    def __init__(self):
        self.sn = [SN76489(), SN76489()]
        self.ch = [-1, -1, -1]
        self.cache = [0xFF] * 16
        self.writes = []
        self.ym()

    def frame(self, data):
        """data: the (chip, byte) pairs of an arcade frame -> the YM writes [(register, value)]"""
        for chip, v in data:
            self.sn[chip].write(v)
        return self.ym() if data else []

    def ym(self):
        keys = []
        for k in range(6):
            a = self.sn[k // 3].reg[2 * (k % 3) + 1] & 15
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
        for j, k in enumerate(new):
            if k < 0:
                continue
            sn = self.sn[k // 3]
            p = ym_period(sn.reg[2 * (k % 3)])
            regs[2 * j], regs[2 * j + 1] = p & 0xFF, p >> 8
            regs[8 + j] = VTAB[sn.reg[2 * (k % 3) + 1] & 15]
            mixer &= ~(1 << j)
        regs[7] = mixer | 0xC0
        out = []
        for r in (0, 1, 2, 3, 4, 5, 7, 8, 9, 10):
            if regs[r] != self.cache[r]:
                self.cache[r] = regs[r]
                out.append((r, regs[r]))
        self.writes.append(out)
        return out
