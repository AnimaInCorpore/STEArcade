"""Pooyan's sound board, Time Pilot's (MAME 0.286 shared/timeplt_a.cpp, `timeplt_audio`): the reference, the model of
the STE's schedule and its YM mix-down.

The board (generic for the Time Pilot family: Board takes the ROM and the driver's two entry points):
a Z80 at 14.318181 MHz / 8 = 1.789772 MHz; ROM $0000-$2FFF (Pooyan: xx.7a, xx.8a at $0000-$1FFF; the rest of the
region 0), RAM $3000-$33FF (mirrored to $3FFF), AY-3-8910 #1 data $4000 (read and write) / address $5000, #2 data $6000 /
address $7000 (each mirrored over $0FFF), writes to $8000-$FFFF set the RC filters (the address bits: filter_w; not
modelled on the STE: the YM has none).  Both AYs at 1.789772 MHz.  AY #1's port A reads the command latch, its port B
the timer: MAME's portB_r, timeplt_timer[(total_cycles / 512) % 10] = $00 $10 $20 $30 $40 $90 $A0 $B0 $A0 $D0 (bit 7
rises once in 5120 cycles: 349.6 a second).  The main CPU writes the latch ($A100) and raises the IRQ (HOLD_LINE, IM 1)
at latch Q1's rising edge; Q2 mutes the amplifier.  The AYs (MAME ay8910.cpp): an address write with the upper nibble
non-zero deselects the chip (reads $FF, data writes ignored); a register read is masked to the register's width (AY8910:
$FF $0F $FF $0F $FF $0F $1F $FF $1F $1F $1F $FF $FF $0F $FF $FF); the ports read their callbacks (AY #2's: none, the
register stays).

Pooyan's driver (xx.7a): the loop's head $00CB `ei`, waits for the rising edge of the timer's bit 7 ($00CC-$00D8), then
`di` and the six slots ($3000-$300B: the effect and its state; slot k drives AY (k-1)/3's voice (k-1)%3), each slot
followed by an `ei; nop; nop; di` window, and back to $00CB.  The IRQ handler $0038 (`exx`, `ex af,af'`) reads the latch
(AY #1 register 14) and puts the command into a slot.

Reference (MameBoard): the sound CPU at its clock against the main CPU's time (MAME synchronises the latch write and the
IRQ line: the command takes effect at the main CPU's instant), the IRQ taken at the first instruction boundary with
interrupts enabled.  Fed by the main board in MAME's schedule (machine.Pooyan) with the trigger's cycle.

The STE's schedule (TickBoard, src/sound.s): each arcade frame, the commands the game wrote since the last frame each
run the IRQ handler (as a subroutine: no window to wait for), then the frame's ticks run the loop once each, from TICK
(after the waits) to the loop's head LOOP (the hook).  TICKS_FX ticks an arcade frame in 16.16 fixed point.  Equal to
the reference but for when an effect starts within its frame (up to a tick: 2.9 ms).

YM: each arcade frame the three loudest audible channels of the six (volume or envelope, tone or noise on) go to the
YM2149's three, a channel keeping its YM channel while it stays chosen; the periods scaled 1789772 -> 2000000; noise
and envelope from the chip of the first chosen channel that uses them (Gyruss's method, its src/sound.s, for n chips).
"""
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import load, Pooyan, FRAME
from z80 import Z80

CLOCK = 14318181 // 8                     # the sound Z80 and the AYs: 1789772 Hz
MAIN_CLOCK = 3072000
TICK_CYCLES = 5120
TICKS_FX = round(CLOCK * FRAME * 65536 / (MAIN_CLOCK * TICK_CYCLES))      # 5.768 ticks an arcade frame
YM_CLOCK = 2000000
TOKEN = 0xFFFE                            # (never code: above the ROM)
LOOP, TICK = 0x00CB, 0x00DA               # Pooyan's driver: the loop's head (ei), after the timer waits
TIMER = (0x00, 0x10, 0x20, 0x30, 0x40, 0x90, 0xA0, 0xB0, 0xA0, 0xD0)
AY_MASK = (0xFF, 0x0F, 0xFF, 0x0F, 0xFF, 0x0F, 0x1F, 0xFF, 0x1F, 0x1F, 0x1F, 0xFF, 0xFF, 0x0F, 0xFF, 0xFF)


def rom():
    return load('xx.7a') + load('xx.8a')


class Board:
    """the board's memory and AYs around engine/z80.py; ay[2][16] the register files, writes [(cycle, chip, reg, v)],
    reads15: the pcs that read the timer"""

    def __init__(self, code=None):
        code = rom() if code is None else code
        self.mem = bytearray(0x10000)
        self.mem[:len(code)] = code
        self.ay = [[0] * 16 for _ in range(2)]
        self.addr = [0, 0]
        self.active = [True, True]
        self.latch = 0
        self.filter = 0
        self.writes = []
        self.odd = []                           # accesses the translation would not expect (pc, address, kind)
        self.cpu = Z80(self.rd, self.wr)

    def timer(self):
        return TIMER[(self.cpu.cycles // 512) % 10]

    def rd(self, a):
        if a < 0x3000:
            return self.mem[a]
        if a < 0x4000:
            if a >= 0x3400:
                self.odd.append((self.cpu.pc, a, 'ram mirror'))
            return self.mem[0x3000 | (a & 0x3FF)]
        if a < 0x8000 and not a & 0x1000:
            k = (a >> 13) & 1
            if not self.active[k]:
                return 0xFF
            r = self.addr[k]
            if k == 0 and r == 14:
                self.ay[0][14] = self.latch
            elif k == 0 and r == 15:
                self.ay[0][15] = self.timer()
            return self.ay[k][r] & AY_MASK[r]
        return 0

    def wr(self, a, v):
        if 0x3000 <= a < 0x4000:
            if a >= 0x3400:
                self.odd.append((self.cpu.pc, a, 'ram mirror'))
            self.mem[0x3000 | (a & 0x3FF)] = v
        elif 0x4000 <= a < 0x8000:
            k = (a >> 13) & 1
            if a & 0x1000:
                self.active[k] = v >> 4 == 0
                if self.active[k]:
                    self.addr[k] = v & 15
                else:
                    self.odd.append((self.cpu.pc, a, 'deselect'))
            elif self.active[k]:
                self.ay[k][self.addr[k]] = v
                self.writes.append((self.cpu.cycles, k, self.addr[k], v))
        elif a >= 0x8000:
            self.filter = a & 0x7FFF


class MameBoard(Board):
    """the reference: the sound CPU at its clock, commands at the main CPU's instants (cycle in main CPU cycles)"""

    def __init__(self, code=None):
        super().__init__(code)
        self.irq = False

    def run_to(self, t):
        """the sound CPU up to the time t (its own cycles)"""
        c = self.cpu
        while c.cycles < t:
            if self.irq and c.iff1 and not c.ei_delay:
                self.irq = False                # (HOLD_LINE: released at the acknowledge)
                c.irq()
                continue
            c.ei_delay = False                  # (engine/z80.py sets it at `ei`; the instruction after it runs first)
            c.step()

    def command(self, main_cycle, v):
        self.run_to(main_cycle * CLOCK // MAIN_CLOCK)
        self.latch = v
        self.irq = True


class TickBoard(Board):
    """the sound Z80 in the STE's schedule"""

    def __init__(self, code=None, loop=LOOP, tick=TICK):
        super().__init__(code)
        self.loop, self.tick = loop, tick
        self.frame = 0
        self.acc = 0
        self.run_until({loop})                  # the boot: RAM cleared, the AYs set up, to the loop's head

    def timer(self):
        self.odd.append((self.cpu.pc, 0x4000, 'timer'))
        return super().timer()

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
            self.cpu.pc = self.tick
            self.run_until({self.loop})
        self.frame += 1


class TimedPooyan(Pooyan):
    """machine.Pooyan (MAME's schedule) with each command's main CPU cycle: timed [(cycle, command)]"""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.timed = []

    def wr(self, a, v):
        n = len(self.sound_log)
        super().wr(a, v)
        if len(self.sound_log) > n:
            self.timed.append((self.cpu.cycles, self.sound_log[-1][1]))


def scale(p):
    """an AY period -> the YM's: x 2000000 / 1789772 as src/sound.s snd_scale (p + p * 7698 >> 16)"""
    return p + ((p * 7698) >> 16)


class YM:
    """src/sound.s snd_ym: the YM2149's registers from the AYs each arcade frame; frame() -> writes [(reg, value)]"""

    def __init__(self, chips=2):
        self.n = 3 * chips
        self.ch = [-1, -1, -1]
        self.cache = [0xFF] * 16

    def frame(self, ay, env_written):
        score = []
        for c in range(self.n):
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
            for c in range(self.n):
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

    def __init__(self, code=None, loop=LOOP, tick=TICK):
        self.env_written = [False, False]
        self.dirty = True
        super().__init__(code, loop, tick)
        self.ym = YM(2)
        self.ym_log = []

    def wr(self, a, v):
        if 0x4000 <= a < 0x8000 and not a & 0x1000:
            k = (a >> 13) & 1
            if self.active[k]:
                if self.addr[k] == 13:
                    self.env_written[k] = True
                self.dirty = True
        super().wr(a, v)

    def run_frame(self, commands):
        super().run_frame(commands)
        w = []
        if self.dirty:
            self.dirty = False
            w = self.ym.frame(self.ay, self.env_written)
        self.env_written = [False, False]
        self.ym_log.append(w)
