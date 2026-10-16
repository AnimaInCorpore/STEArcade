"""Double Dragon's sprite MCU (HD63701Y0, 21jm-0.ic55) as a model of its one job: what its NMI handler does to the
shared RAM and its own RAM, instruction for instruction in effect (src/mcu.s is the same on the STE; tools/mcu_test.py
checks this against the HD63701Y0 interpreter on every job of a port run).

    m = Mcu(rom); m.job(comram)       # comram: the 512-byte shared RAM ($8000-$81FF of the MCU), changed in place

The first job sums the ROM into $8000.  Every later one:
  1. sort ($C0A8): the 8-byte object records at $8001 ($8000 = the end offset) bubble-sorted until a pass swaps
     none: a record goes after the next one when its word at +4 is lower (unsigned)
  2. expand ($C06C): each record whose byte 1 & $7F is not $7F becomes sprite entries ($C10B): its animation's
     parts from the ROM tables ($C2EF: object type -> frame table -> part list), placed relative to the camera
     ($81F9 x, $81FB y), 5 bytes each from $8081 on, counted in $81FD (at most 75)
  3. $8000 = 0
Then port 6 (its shadow $65): bit 1 rises (the main CPU's IRQ), bit 0 drops and rises (its NMI released).
The MCU's RAM ($40-$66) carries over between jobs: a part list without its own start byte ($51) goes on from the last.
"""


class Mcu:
    def __init__(self, rom):
        assert len(rom) == 0x4000
        self.rom = bytes(rom)
        self.ram = bytearray(0x100)            # $40-$13F (index = address - $40)
        self.ram[0x65 - 0x40] = 1               # (its reset code: the port 6 shadow, NMI line released)
        self.first = True

    def r(self, a):
        return self.ram[a - 0x40]

    def w(self, a, v):
        self.ram[a - 0x40] = v & 0xFF

    def rw(self, a):
        return (self.ram[a - 0x40] << 8) | self.ram[a - 0x3F]

    def ww(self, a, v):
        self.ram[a - 0x40] = (v >> 8) & 0xFF
        self.ram[a - 0x3F] = v & 0xFF

    def rom8(self, a):
        return self.rom[(a & 0xFFFF) - 0xC000] if a & 0xFFFF >= 0xC000 else 0xFF

    def rom16(self, a):
        return (self.rom8(a) << 8) | self.rom8(a + 1)

    def job(self, c):
        self._job(c)
        self.w(0x65, self.r(0x65) | 3)         # (port 6: the main CPU's IRQ raised, its own NMI released)

    def _job(self, c):
        if self.first:
            self.first = False
            c[0] = sum(self.rom) & 0xFF
            self.w(0x66, 1)
            return
        self.sort(c)
        n = c[0]
        i = 1
        x = 1
        while i < n:
            for k in range(8):
                self.w(0x40 + k, c[x + k])
            self.w(0x4F, i)
            if c[x + 1] & 0x7F != 0x7F:
                self.expand(c)
            x = (x + 8) & 0x1FF
            i = (i + 8) & 0xFF
        self.w(0x4F, i)
        c[0] = 0

    def sort(self, c):
        if not c[0]:
            return
        while True:
            swaps = 0
            i = 1
            while ((i + 8) & 0xFF) < c[0]:
                w4 = (c[i + 4] << 8) | c[i + 5]
                w12 = (c[i + 12] << 8) | c[i + 13]
                if w4 < w12:
                    for k in (0, 2, 4, 6):
                        self.w(0x40, c[i + k])
                        self.w(0x41, c[i + k + 1])
                        c[i + k], c[i + k + 1], c[i + k + 8], c[i + k + 9] = c[i + k + 8], c[i + k + 9], c[i + k], c[i + k + 1]
                    swaps = (swaps + 1) & 0xFF
                i = (i + 8) & 0xFF
            self.w(0x4E, i)
            self.w(0x4F, swaps)
            if not swaps:
                return

    def expand(self, c):
        if c[0x1FD] >= 0x4B:
            return
        self.ww(0x56, self.rw(0x44) + self.rw(0x46) - ((c[0x1FB] << 8) | c[0x1FC]))
        self.ww(0x58, self.rw(0x42) - ((c[0x1F9] << 8) | c[0x1FA]))
        b1 = self.r(0x41)
        self.w(0x54, (b1 >> 4) & 0x08)
        self.w(0x5E, self.r(0x40))
        self.w(0x5F, self.r(0x40) & 0x7F)
        x = self.rom16(0xC2EF + 2 * self.r(0x5F))
        x = self.rom16(x + 2 * (b1 & 0x7F))
        self.ww(0x48, x)
        self.ww(0x4A, 0x8081 + c[0x1FD] * 5)
        b = self.rom8(x)
        x += 1
        self.w(0x50, 0)
        self.w(0x52, 0)
        self.w(0x5A, 0)
        self.w(0x4E, b)
        self.w(0x53, b & 0x1F)
        if b & 0x80:
            self.w(0x50, self.rom8(x))
            x += 1
        if b & 0x40:
            self.w(0x51, self.rom8(x))
            x += 1
            self.w(0x52, 0xFF)
        if b & 0x20:
            self.w(0x5A, 0xFF)
            self.ww(0x4C, self.rom16(x))
            x += 2
        x &= 0xFFFF
        while True:
            if self.r(0x4E) & 0x80:
                a = self.r(0x50)
            else:
                a = self.rom8(x)
                x = (x + 1) & 0xFFFF
            self.ww(0x48, x)
            x2 = 0xC27F + ((3 * self.r(0x5F)) & 0xFF) + ((a & 0x30) >> 4)
            v62 = (a & 0x0F) | self.rom8(x2)
            if (v62 & 0xF0) < 0x20 and self.r(0x5E) & 0x80:
                v62 ^= 0x10
            self.w(0x62, v62)
            v61 = self.rom8(0xC2EB + (a >> 6))
            x = self.rw(0x48)
            v61 = (v61 ^ self.r(0x54)) | 0x80
            self.w(0x61, v61)
            a = self.r(0x51)
            self.w(0x51, self.r(0x51) + 1)
            if v61 & 0x10:
                self.w(0x51, self.r(0x51) + 1)
            if not self.r(0x52):
                a = self.rom8(x)
                x = (x + 1) & 0xFFFF
            self.w(0x63, a)
            if self.r(0x5A) & 0x80:
                self.ww(0x48, x)
                x = self.rw(0x4C)
            b = self.rom8(x)
            x = (x + 1) & 0xFFFF
            if self.r(0x54) & 0x08:
                b = -b & 0xFF
            d = (b - 0x100 if b & 0x80 else b) & 0xFFFF
            d = (d + self.rw(0x58) + 7) & 0xFFFF
            if d >> 8:
                self.w(0x61, self.r(0x61) | 0x02)
            self.w(0x64, (d & 0xFF) ^ 0xFF)
            b = self.rom8(x)
            x = (x + 1) & 0xFFFF
            d = (b - 0x100 if b & 0x80 else b) & 0xFFFF
            d = (d + self.rw(0x56) - 7) & 0xFFFF
            self.w(0x60, d)
            if self.r(0x61) & 0x10:
                d = (d - 8) & 0xFFFF
                self.w(0x60, d)
            if d >> 8:
                self.w(0x61, self.r(0x61) | 0x01)
            if self.r(0x5A) & 0x80:
                self.ww(0x4C, x)
                x = self.rw(0x48)
            self.ww(0x48, x)
            o = self.rw(0x4A) - 0x8000
            for k in range(5):
                c[(o + k) & 0x1FF] = self.r(0x60 + k)
            self.ww(0x4A, self.rw(0x4A) + 5)
            c[0x1FD] = (c[0x1FD] + 1) & 0xFF
            if c[0x1FD] >= 0x4B:
                return
            self.w(0x53, self.r(0x53) - 1)
            if not self.r(0x53):
                return
