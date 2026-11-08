"""Juno First's sound board (MAME konami/junofrst.cpp): the model of the STE's schedule and its YM mix-down.

The board: a Z80 at 14.318181 MHz / 8 = 1.789773 MHz (ROM jfs1_j3.bin at $0000-$0FFF, RAM $2000-$23FF), one AY-3-8910
at the same clock ($4000 address write, $4001 data read, $4002 data write), the command latch read at $3000, the
i8039's command latch written at $5000 and its IRQ at $6000.  The main CPU's rising $8040 raises the Z80's IRQ
(HOLD_LINE, vector $FF = RST 38, IM 1); its handler ($0038) reads the command ($3000) and puts it into the driver's
slots ($2000-$200A).  Bit 7 of a command is an effect of the i8039 (handler path $00C9: $5000 = the command & 127,
$6000 = its IRQ).  The driver's main loop ($0169) waits for a rising edge of bit 5 of the AY's port A (register 14: the
Z80's cycle counter / 512 in bits 7-4, the i8039's status in bits 2-0): every 2048 cycles, a tick 873.9 times a second,
14.42 an arcade frame; a tick steps the sequencers of the slots ($01ED / $01CD).  While bit 6 of the slot $2000 is set
the loop does not wait for a tick (it steps the sequencer at once, `ei; nop; nop; di`, jr $01AF) until the sequence
ends.  Interrupts are taken only in the loop's `ei ... di` windows.

The STE's schedule (TickBoard, src/sound.s): each arcade frame, the commands the game wrote since the last frame each
run the IRQ handler (as a subroutine: no window to wait for), then the frame's ticks run the loop once each, from
$0186 (after the waits) back to $0169; while bit 6 of $2000 is set the loop passes run at once instead of the ticks (at
most MAX_FAST a frame, the rest of the frame's ticks are dropped).  The i8039's status (port A bits 0-2) is 1 while an effect of the commands 5-8 plays (P2 bit 4 set by its
program, see i8039.py), per frame: EFFECT_FRAMES.

YM: the AY's three channels are the YM2149's three (periods scaled 1789773 -> 2000000, noise and envelope periods
too, the mixer as is, the shape register when the AY's was written); only changed registers are written.  The AY's
port B (the filters' capacitors, MAME's flt_rc) is not modelled.
"""
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import load
from z80 import Z80

AY_CLOCK, YM_CLOCK = 14318181 // 8, 2000000
FPS = 1536000 / 25344                                          # the arcade frame rate (the main CPU's 25,344 cycles)
TICKS_FX = round(AY_CLOCK / 2048 / FPS * 65536)                # ticks an arcade frame, 16.16 (14.42)
LOOP, TICK = 0x0169, 0x0186
TOKEN = 0xFFFE
MAX_FAST = 64                                                  # loop passes a frame with bit 6 of $2000 set (the real
                                                               # ones take 300-900 Z80 cycles of the frame's 29,500)
EFFECT_FRAMES = {5: 22, 6: 24, 7: 22, 8: 23}                   # the i8039 busy (status 1): seconds x FPS (i8039.py)


class TickBoard:
    """the sound Z80 in the STE's schedule; ay[16] the AY's register file, dac_log (frame, i8039 command)"""

    def __init__(self):
        self.mem = bytearray(0x10000)
        self.mem[0:0x1000] = load('jfs1_j3.bin')
        self.ay = [0] * 16
        self.addr = 0
        self.latch = 0
        self.latch2 = 0
        self.status = 0                             # the i8039's status bits (port A bits 2-0)
        self.busy = 0                               # frames of an effect (5-8) left
        self.dac_log = []
        self.frame = 0
        self.acc = 0
        self.fast = 0
        self.cpu = Z80(self.rd, self.wr, self.io_in, self.io_out)
        self.run_until({LOOP})                      # the boot: RAM cleared, the AY set up, to the loop

    def rd(self, a):
        if a < 0x1000 or 0x2000 <= a < 0x2400:
            return self.mem[a]
        if a == 0x3000:
            return self.latch
        if a == 0x4001:
            return self.status if self.addr == 14 else self.ay[self.addr]     # (port A: the schedule leaves out the timer)
        return 0

    def wr(self, a, v):
        if 0x2000 <= a < 0x2400:
            self.mem[a] = v
        elif a == 0x4000:
            self.addr = v & 15
        elif a == 0x4002:
            self.ay[self.addr] = v
        elif a == 0x5000:
            self.latch2 = v
        elif a == 0x6000:
            self.dac_log.append((self.frame, self.latch2))
            c = self.latch2 & 15
            self.busy = EFFECT_FRAMES.get(c, 0)
            self.status = 1 if self.busy else 0

    def io_in(self, p):
        return 0xFF

    def io_out(self, p, v):
        pass

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
        c.push(LOOP)
        c.push(TOKEN)
        c.pc = 0x0038
        self.run_until({TOKEN})
        c.pc = c.pop()

    def run_frame(self, commands):
        for v in commands:
            self.command(v)
        self.acc += TICKS_FX
        n, self.acc = self.acc >> 16, self.acc & 0xFFFF
        budget = MAX_FAST
        for _ in range(n):
            while self.mem[0x2000] & 0x40 and budget:   # (bit 6 of the slot: the loop goes on at once, no tick)
                budget -= 1
                self.fast += 1
                self.run_until({LOOP})
            if self.mem[0x2000] & 0x40:
                break                                   # (the frame's time is spent)
            self.cpu.pc = TICK
            self.run_until({LOOP})
        if self.busy:
            self.busy -= 1
            if not self.busy:
                self.status = 0
        self.frame += 1


def scale(p):
    """an AY period -> the YM's: x 2000000 / 1789773 as src/sound.s snd_scale (p + p * 7698 >> 16)"""
    return p + ((p * 7698) >> 16)


class YM:
    """src/sound.s snd_ym: the YM2149's registers from the AY each arcade frame; writes: [(reg, value)]"""

    def __init__(self):
        self.cache = [0xFF] * 16

    def frame(self, ay, env_written):
        out = [0] * 16
        for k in range(3):
            p = min(scale((ay[2 * k] | ay[2 * k + 1] << 8) & 0x0FFF), 0x0FFF)
            out[2 * k], out[2 * k + 1] = p & 0xFF, p >> 8
            out[8 + k] = ay[8 + k] & 0x1F
        out[6] = min(scale(ay[6] & 0x1F), 31)
        out[7] = (ay[7] & 0x3F) | 0xC0
        p = min(scale(ay[11] | ay[12] << 8), 0xFFFF)
        out[11], out[12] = p & 0xFF, p >> 8
        out[13] = ay[13]
        writes = []
        for r in range(14):
            if r == 13:
                if env_written:
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
        self.env_written = False
        self.dirty = True
        super().__init__()
        self.ym = YM()
        self.ym_log = []

    def wr(self, a, v):
        if a == 0x4002:
            if self.addr == 13:
                self.env_written = True
            self.dirty = True
        super().wr(a, v)

    def run_frame(self, commands):
        super().run_frame(commands)
        w = []
        if self.dirty:
            self.dirty = False
            w = self.ym.frame(self.ay, self.env_written)
        self.env_written = False
        self.ym_log.append(w)
