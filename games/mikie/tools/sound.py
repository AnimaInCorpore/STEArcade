"""Mikie's sound board (MAME 0.286 konami/mikie.cpp sound_map): the reference, the model of the STE's schedule and its YM
mix-down.  The same family as games/trackfld (tools/sound.py), without speech, DAC and tunes, with two SN chips.

The board: a Z80 at 14.318181 MHz / 4 = 3.579545 MHz (ROM n10.6e $0000-$1FFF, RAM $4000-$43FF); two SN76489As: sn1 at
14.318181 MHz / 8, sn2 at 14.318181 MHz / 4 (written at $8002 / $8004: the byte the CPU stores; the latch store at $8000
only precedes it); the main CPU's command latch read at $8003; the timer read at $8005 (total_cycles / 512).  The
latch's Q2 rising edge raises the IRQ (HOLD_LINE, vector $FF: IM 1, $0038).  $8000, $8001, $8079, $A003: nothing.

The driver: after the boot (a RAM and ROM check, left out: the STE starts at $0156, where the RAM is cleared and the chips
silenced) the main loop ($0178) waits for the timer's bit 2 to fall and rise (every 4096 cycles: 873.9 ticks a second), then
runs six channels' effects ($4000.. a pair of bytes per channel: effect, started), each followed by an `ei; nop; nop;
di` window, and back to the loop's head.  The IRQ handler ($0038) reads the latch and starts an effect.

Reference (MameBoard): the sound CPU at its clock, the timer from the cycles, commands at given cycles, the IRQ taken at
the first instruction with interrupts enabled.  The STE's schedule (TickBoard, src/sound.s): time in half Z80 cycles; each
arcade frame the commands the game wrote since the last frame each run the IRQ handler (a subroutine: TOKEN as the return
address), then the frame's time runs ticks from TICK (after the timer's waits) to the loop's head LOOP, each costing 4096
cycles.

YM (STEBoard.ym, src/sound.s snd_ym): the SN voices (two chips' three tones and noise, k = 4 chip + voice) on the YM2149's
three channels: the three loudest (ties: the lower voice), a YM channel keeping its voice while it stays chosen (Mr. Do!'s
method); a tone's period N -> N x 4000000 / the chip's clock; a noise voice on its channel with the tone off, the YM's
noise period from the chip's shift period (32, 64, 128 or 2 N of its tone 2) x 2000000 / the chip's clock, at most 31;
a second noise voice shares the first's period; the attenuation (2 dB steps) to the YM's level 15 - round(2 a / 3), 15 -> 0.
"""
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from paths import EXTRACTED
from z80 import Z80

XTAL = 14318181
CLOCK = XTAL // 4                         # the Z80: 3579545 Hz
SN_CLOCKS = (XTAL // 8, XTAL // 4)        # sn1, sn2
FRAME_HZ = 60.59
TOKEN = 0xFFFE                            # (never code: above the ROM)
HALF = 2                                  # the schedule's time unit: half a Z80 cycle
TICK_FX = 4096 * HALF
FRAME_FX = round(CLOCK * HALF / FRAME_HZ)
LOOP, TICK, BOOT = 0x0178, 0x0187, 0x0156
WAITS = {0x0179, 0x0180}                  # the timer's reads (the schedule leaves the waits out)
VTAB = (15, 14, 14, 13, 12, 12, 11, 10, 10, 9, 8, 8, 7, 6, 6, 0)


def rom():
    return (EXTRACTED / 'mikie' / 'n10.6e').read_bytes()


class SN76489:
    """the registers of MAME's sn76496_base_device: 0, 2, 4 periods, 6 the noise control, 1, 3, 5, 7 volumes
    (attenuations); after reset all 0"""

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


class Board:
    """the board's memory and chips around engine/z80.py.  odd: accesses the translation would not expect (pc, address,
    kind); sn_log: (cycle, chip, byte) of the SN writes"""

    def __init__(self):
        code = rom()
        self.mem = bytearray(0x10000)
        self.mem[:len(code)] = code
        self.latch = 0
        self.sn = [SN76489(), SN76489()]
        self.sn_log = []
        self.odd = []
        self.cpu = Z80(self.rd, self.wr)
        self.cpu.pc = BOOT
        self.cpu.h, self.cpu.l = 0x44, 0x00      # (what the RAM test leaves: SP = $4400 at $0156)

    def timer(self):
        return (self.cpu.cycles // 512) & 0xFF

    def sn_write(self, chip, v):
        self.sn[chip].write(v)
        self.sn_log.append((self.cpu.cycles, chip, v))

    def rd(self, a):
        if a < 0x2000:
            return self.mem[a]
        if 0x4000 <= a < 0x4400:
            return self.mem[a]
        if a == 0x8003:
            return self.latch
        if a == 0x8005:
            return self.timer()
        self.odd.append((self.cpu.pc, a, 'read'))
        return 0

    def wr(self, a, v):
        if 0x4000 <= a < 0x4400:
            self.mem[a] = v
        elif a == 0x8002:
            self.sn_write(0, v)
        elif a == 0x8004:
            self.sn_write(1, v)
        elif a not in (0x8000, 0x8001, 0x8079, 0xA003):
            self.odd.append((self.cpu.pc, a, 'write'))


class MameBoard(Board):
    """the reference: the sound CPU at its clock, commands at given instants (cycle: the sound CPU's)"""

    def __init__(self):
        super().__init__()
        self.irq = False

    def run_to(self, t):
        c = self.cpu
        while c.cycles < t:
            if self.irq and c.iff1 and not c.ei_delay:
                self.irq = False
                c.irq()
                continue
            c.ei_delay = False
            c.step()

    def command(self, cycle, v):
        self.run_to(cycle)
        self.latch = v
        self.irq = True


class TickBoard(Board):
    """the sound Z80 in the STE's schedule (the module's doc); boot=False: boot() later (ref/cover_sound.py)"""

    def __init__(self, boot=True):
        super().__init__()
        self.frame = 0
        self.acc = 0
        if boot:
            self.boot()

    def boot(self):
        self.run_until({LOOP})            # RAM cleared, the chips silenced, to the loop's head

    def timer(self):
        if self.cpu.pc not in WAITS:
            self.odd.append((self.cpu.pc, 0x8005, 'timer'))
        return 0

    def run_until(self, pcs, limit=3000000):
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
        self.acc += FRAME_FX
        while self.acc >= TICK_FX:
            self.acc -= TICK_FX
            self.cpu.pc = TICK
            self.run_until({LOOP})
        self.frame += 1


def ym_period(n, chip):
    """the YM period for an SN tone period (0 counts as 1024): N x 4000000 / the chip's clock rounded"""
    c = SN_CLOCKS[chip]
    return ((n or 1024) * 4000000 + c // 2) // c


def ym_noise(reg6, n2, chip):
    """the YM noise period for the SN's noise control (the shift period 32 / 64 / 128 or 2 x tone 2's), at most 31"""
    c = SN_CLOCKS[chip]
    p = 2 * (n2 or 1024) if reg6 & 3 == 3 else 32 << (reg6 & 3)
    return min(31, (p * 2000000 + c // 2) // c)


class YM:
    """src/sound.s snd_ym: the YM2149's registers from the SNs' (ch: per YM channel its voice, -1 none; cache: the
    registers as written, 0xFF not yet)"""

    def __init__(self):
        self.ch = [-1, -1, -1]
        self.cache = [0xFF] * 16

    def frame(self, sn):
        keys = []
        for k in range(8):
            a = sn[k >> 2].reg[2 * (k & 3) + 1] & 15
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
        noise = None
        for j, k in enumerate(new):
            if k < 0:
                continue
            chip, v = k >> 2, k & 3
            s = sn[chip]
            if v == 3:
                mixer &= ~(8 << j)
                if noise is None:
                    noise = ym_noise(s.reg[6], s.reg[4], chip)
            else:
                p = ym_period(s.reg[2 * v], chip)
                regs[2 * j], regs[2 * j + 1] = p & 0xFF, p >> 8
                mixer &= ~(1 << j)
            regs[8 + j] = VTAB[s.reg[2 * v + 1] & 15]
        regs[6] = noise or 0
        regs[7] = mixer | 0xC0
        out = []
        for r in range(11):
            if regs[r] != self.cache[r]:
                self.cache[r] = regs[r]
                out.append((r, regs[r]))
        return out


class STEBoard(TickBoard):
    """TickBoard and YM: what src/sound.s does in an arcade frame (the YM writes of each frame in ym_log)"""

    def __init__(self):
        self.dirty = True
        super().__init__()
        self.ym = YM()
        self.ym_log = []

    def sn_write(self, chip, v):
        self.dirty = True
        super().sn_write(chip, v)

    def run_frame(self, commands):
        super().run_frame(commands)
        w = []
        if self.dirty:
            self.dirty = False
            w = self.ym.frame(self.sn)
        self.ym_log.append(w)
