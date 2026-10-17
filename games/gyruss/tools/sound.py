"""Gyruss's sound board (MAME konami/gyruss.cpp): the model of the STE's schedule and its YM mix-down.

The board: a Z80 at 14.318181 MHz / 4 = 3.579545 MHz (ROM gyrussk.1a / 2a at $0000-$3FFF, RAM $6000-$63FF, the command
latch read at $8000), five AY-3-8910 at 1.789772 MHz (I/O: address $00 / $04 / $08 / $0C / $10, data write +2, data
read +1), an i8039 playing sampled effects through a DAC (`out ($18),a`: its command latch, `out ($14),a`: its IRQ).  The
main CPU's write to $C080 raises the Z80's IRQ (HOLD_LINE; IM 1), whose handler ($0038) reads the command and puts it
into one of the driver's slots ($6000-$6006).  The driver's main loop ($00FD) waits for the rising edge of bit 2 of the
third AY's port A, a counter of the CPU's clock (/1024, then a bi-quinary /10: bit 2 rises twice in 10240 cycles: a
tick every 5120 cycles, 699.1 a second, 11.536 an arcade frame); a tick steps the slots' effect sequencers (01BF /
01D1 per slot), and the music's nine channels (0281, IX = $6008 + 12 k) or the other path at 0455.  Interrupts are
taken only in the loop's `ei; nop; nop; di` windows.

The STE's schedule (TickBoard, src/sound.s): each arcade frame, the commands the game wrote since the last frame each
run the IRQ handler (as a subroutine: no window to wait for), then the frame's ticks run the loop once each, from
$010C (after the waits) back to $00FD.  TICKS_FX ticks a frame in 16.16 fixed point.

YM: each arcade frame the three loudest audible channels of the 15 (volume or envelope, tone or noise on) go to the
YM2149's three, a channel keeping its YM channel while it stays chosen; the periods scaled 1789772 -> 2000000; noise
and envelope from the chip of the first chosen channel that uses them (Kung-Fu Master's method, its src/sound.s).
"""
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import load
from z80 import Z80

TICKS_FX = round(3579545 * 396 * 256 * 3 / (5120 * 18432000) * 65536)     # 11.536 ticks an arcade frame
LOOP, TICK = 0x00FD, 0x010C
TOKEN = 0xFFFE
AY_CLOCK, YM_CLOCK = 1789772, 2000000


class TickBoard:
    """the sound Z80 in the STE's schedule; ay[5][16] the register files, dac_log (frame, i8039 command)"""

    def __init__(self):
        self.mem = bytearray(0x10000)
        self.mem[0:0x2000] = load('gyrussk.1a')
        self.mem[0x2000:0x4000] = load('gyrussk.2a')
        self.ay = [[0] * 16 for _ in range(5)]
        self.addr = [0] * 5
        self.latch = 0
        self.latch2 = 0
        self.dac_log = []
        self.frame = 0
        self.acc = 0
        self.cpu = Z80(self.rd, self.wr, self.io_in, self.io_out)
        self.run_until({LOOP})                    # the boot: RAM cleared, the AYs set up, to the loop

    def rd(self, a):
        if a < 0x4000 or 0x6000 <= a < 0x6400:
            return self.mem[a]
        if a == 0x8000:
            return self.latch
        return 0

    def wr(self, a, v):
        if 0x6000 <= a < 0x6400:
            self.mem[a] = v

    def io_in(self, p):
        p &= 0xFF
        if p <= 0x12 and p & 3 == 1:
            k = p >> 2
            r = self.addr[k]
            if k == 2 and r == 14:
                return 0                          # (port A: the timer; the schedule leaves out the waits)
            return self.ay[k][r]
        return 0xFF

    def io_out(self, p, v):
        p &= 0xFF
        if p <= 0x12:
            k = p >> 2
            if p & 3 == 0:
                self.addr[k] = v & 15
            elif p & 3 == 2:
                self.ay[k][self.addr[k]] = v
        elif p == 0x18:
            self.latch2 = v
        elif p == 0x14:
            self.dac_log.append((self.frame, self.latch2))

    def run_until(self, pcs, limit=2000000):
        c = self.cpu
        for _ in range(limit):
            c.step()
            if c.pc in pcs:
                return
        raise RuntimeError('the sound CPU did not come to %s (pc %04X)' % (sorted(pcs), c.pc))

    def command(self, v):
        c = self.cpu
        self.latch = v
        c.push(c.pc)
        c.push(TOKEN)
        c.pc = 0x0038
        self.run_until({TOKEN})
        c.pc = c.pop()

    def run_frame(self, commands):
        for v in commands:
            self.command(v)
        self.acc += TICKS_FX
        n, self.acc = self.acc >> 16, self.acc & 0xFFFF
        for _ in range(n):
            self.cpu.pc = TICK
            self.run_until({LOOP})
        self.frame += 1


def scale(p):
    """an AY period -> the YM's: x 2000000 / 1789772 as src/sound.s snd_scale (p + p * 7698 >> 16)"""
    return p + ((p * 7698) >> 16)


class YM:
    """src/sound.s snd_ym: the YM2149's registers from the five AYs each arcade frame; writes: [(reg, value)]"""

    def __init__(self):
        self.ch = [-1, -1, -1]
        self.cache = [0xFF] * 16

    def frame(self, ay, env_written):
        score = []
        for c in range(15):
            chip, v = divmod(c, 3)
            r = ay[chip]
            vol = r[8 + v] & 0x1F
            s = -1
            if vol and (not r[7] >> v & 1 or not r[7] >> (v + 3) & 1):
                s = 15 if vol & 16 else vol
            score.append(s)
        pick = []
        for _ in range(3):
            best, bc = -1, -1
            for c in range(15):
                if score[c] > best:
                    best, bc = score[c], c
            pick.append(bc)
            if bc >= 0:
                score[bc] = -2
        new = [-1, -1, -1]
        for i, c in enumerate(pick):
            if c >= 0:
                for k in (2, 1, 0):
                    if self.ch[k] == c:
                        new[k] = c
                        pick[i] = -1
        for c in pick:
            if c >= 0:
                new[new.index(-1)] = c
        self.ch = new
        out = [0] * 16
        mixer = 0x3F
        noise = env = -1
        for k in range(3):
            c = new[k]
            if c < 0:
                continue
            chip, v = divmod(c, 3)
            r = ay[chip]
            p = min(scale((r[2 * v] | r[2 * v + 1] << 8) & 0x0FFF), 0x0FFF)
            out[2 * k], out[2 * k + 1] = p & 0xFF, p >> 8
            vol = r[8 + v] & 0x1F
            out[8 + k] = vol
            if vol & 16 and env < 0:
                env = chip
            if not r[7] >> v & 1:
                mixer &= ~(1 << k)
            if not r[7] >> (v + 3) & 1:
                mixer &= ~(8 << k)
                if noise < 0:
                    noise = chip
        out[7] = mixer | 0xC0
        if noise >= 0:
            out[6] = min(scale(ay[noise][6] & 0x1F), 31)
        if env >= 0:
            p = min(scale(ay[env][11] | ay[env][12] << 8), 0xFFFF)
            out[11], out[12] = p & 0xFF, p >> 8
            out[13] = ay[env][13]
        writes = []
        for r in range(14):
            if r == 13:
                if env >= 0 and env_written[env]:
                    self.cache[13] = out[13]
                    writes.append((13, out[13]))
                continue
            if out[r] != self.cache[r]:
                self.cache[r] = out[r]
                writes.append((r, out[r]))
        return writes


class STEBoard(TickBoard):
    """TickBoard and YM: what src/sound.s does in an arcade frame (the YM writes of each frame in ym_log)"""

    def __init__(self):
        self.env_written = [False] * 5
        self.dirty = True
        super().__init__()
        self.ym = YM()
        self.ym_log = []

    def io_out(self, p, v):
        p &= 0xFF
        if p <= 0x12 and p & 3 == 2:
            k = p >> 2
            if self.addr[k] == 13:
                self.env_written[k] = True
            self.dirty = True
        super().io_out(p, v)

    def run_frame(self, commands):
        super().run_frame(commands)
        w = []
        if self.dirty:
            self.dirty = False
            w = self.ym.frame(self.ay, self.env_written)
        self.env_written = [False] * 5
        self.ym_log.append(w)
