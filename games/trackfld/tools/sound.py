"""The Track & Field / Hyper Sports sound board (MAME 0.286 konami/trackfld.cpp sound_map, hyperspt.cpp sound_map,
trackfld_a.cpp `trackfld_audio`): the reference, the model of the STE's schedule and its YM mix-down.  Shared by
games/trackfld and games/hyperspt (GAMES holds what differs).

The board: a Z80 at 14.318181 MHz / 4 = 3.579545 MHz; an SN76489A at 14.318181 MHz / 8 = 1.789772 MHz (written through
a latch: the byte to a latch address, then a strobe), a VLM5030 at 3.579545 MHz (its 8 KB ROM, the phrases through its
indirect table), an 8-bit DAC.  The main CPU's command latch read at $6000; latch Q1's rising edge raises the IRQ
(HOLD_LINE, vector $FF: IM 1, $0038).  The timer (trackfld_sh_timer_r / hyperspt_sh_timer_r): total_cycles / 1024.

  Track & Field (trackfld_state::sound_map): ROM $0000-$3FFF (c2_d13.bin at $0000-$1FFF), RAM $4000-$43FF (mirrored
  to $5FFF), $6000 the latch (mirror $1FFF), $8000 the timer (& $0F), $A000 the SN latch, $C000 the SN strobe (a read
  strobes too and gives $FF), $E000 the DAC, $E001 nothing, $E002 the VLM's BSY (bit 4), $E003 + A7-A9 the VLM's pins
  (A8 ST, A9 RST), $E004 the VLM's data (mirror $1FF8 each).
  Hyper Sports (hyperspt_state::sound_map, no mirrors): ROM $0000-$3FFF (c10, c09), RAM $4000-$4FFF, $6000 the latch,
  $8000 the timer (& 3) and BSY (bit 2), $A000 the VLM's data, $C000-$DFFF the VLM's pins (A4 ST, A5 RST), $E000 the
  DAC, $E001 the SN latch, $E002 the SN strobe.

The drivers (the same family): the main loop waits for a rising edge of the timer's bit 1 (every 4096 cycles: 873.9
ticks a second; Hyper Sports with $400B set: bit 0, every 2048), then runs the three SN channels' effects (each followed
by an `ei; nop; nop; di` window on Track & Field), the speech queue (a phrase started with the data byte and an ST pulse
when BSY is low) and back to the loop's head; the IRQ handler ($0038) reads the latch and starts an effect, queues a
phrase, or (commands $40- with bit 6) a tune: $4009 / $400A, played at the loop's top by a cycle-timed routine (TUNE:
`rst $10` through a table) that writes the DAC and the SN with busy-wait delays, interrupts off, and returns to the
loop's head.

Reference (MameBoard): the sound CPU at its clock, the VLM5030 (engine/vlm5030.py) rendered up to each access, the
timer from the cycles, commands at given cycles, the IRQ taken at the first instruction with interrupts enabled.

The STE's schedule (TickBoard, src/sound.s): time in half Z80 cycles.  Each arcade frame:
the commands the game wrote since the last frame each run the IRQ handler (a subroutine: TOKEN as the return address);
while a tune runs (the time below 0), the commands wait and only the last is delivered after it, as the held IRQ line
gives the last latch value.  Then the frame's time (FRAME_FX) runs ticks from TICK to the loop's head LOOP (the hook),
each costing 4096 cycles (Hyper Sports with $400B set: 2048).  The VLM: BSY high from ST's rising edge; at ST's falling edge
the phrase of the latched byte starts (busy for its measured length: phrase_busy, 440 cycles a sample) and the DMA plays its
samples; a tick's cost counts it down; RST rising while busy stops it.  A tune (the hook at TUNE): its measured effect
applied at once (tunes(): the RAM bytes and SN registers it leaves, the time it takes, subtracted from the time and from
the VLM's busy time) and its samples on the DMA.

YM (STEBoard.ym, src/sound.s snd_ym): the SN's four voices (three tones, the noise) on the YM2149's three channels: the
three loudest (ties: the lower voice), a YM channel keeping its voice while it stays chosen (Mr. Do!'s method); a tone's
period N -> N x 2 x 2000000 / 1789772 (the YM: 2 MHz / 16 P, the SN: 1.789772 MHz / 32 N); the noise on its channel
with the tone off and the YM's noise period: the SN's shift period (32, 64, 128 or 2 N of tone 2) x 2000000 / 1789772,
at most 31 (the YM's slowest: the SN's slower noises are lower); the attenuation (2 dB steps) to the YM's level
15 - round(2 a / 3) (~3 dB), 15 -> 0.
"""
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from paths import EXTRACTED
from z80 import Z80

CLOCK = 14318181 // 4                     # the Z80, the VLM5030: 3579545 Hz
SN_CLOCK = 14318181 // 8
YM_CLOCK = 2000000
TOKEN = 0xFFFE                            # (never code: above the ROM)
HALF = 2                                  # the schedule's time unit: half a Z80 cycle
SAMPLE_FX = 440 * HALF                    # a VLM sample: 880
TICK_FX = 4096 * HALF                     # a tick (the timer's bit 1); bit 0 (Hyper Sports, $400B set): half
VTAB = (15, 14, 14, 13, 12, 12, 11, 10, 10, 9, 8, 8, 7, 6, 6, 0)


class Game:
    def __init__(self, name, rom_files, vlm_file, frame_hz, loop, tick, tune, fast=None):
        self.name, self.rom_files, self.vlm_file = name, rom_files, vlm_file
        self.frame_hz = frame_hz
        self.frame_fx = round(CLOCK * HALF / frame_hz)       # an arcade frame (half cycles)
        self.loop, self.tick, self.tune, self.fast = loop, tick, tune, fast

    def rom(self):
        return b''.join((EXTRACTED / self.name / f).read_bytes() for f in self.rom_files)

    def vlm_rom(self):
        return (EXTRACTED / self.name / self.vlm_file).read_bytes()


# Track & Field: 18.432 MHz / 3 / 384 / 264 = 60.606 Hz -> 59062.5 Z80 cycles a frame (118125); Hyper Sports 60 Hz:
# 59659.1 (119318).
GAMES = {
    'trackfld': Game('trackfld', ['c2_d13.bin'], 'c9_d15.bin', 18432000 / 3 / 384 / 264, loop=0x01A8, tick=0x01B7,
                     tune=0x0251),
    'hyperspt': Game('hyperspt', ['c10', 'c09'], 'c08', 60.0, loop=0x0238, tick=0x024E, tune=0x030D, fast=0x400B),
}


class SN76489:
    """the registers of MAME's sn76496_base_device (an SN76489A): 0, 2, 4 periods, 6 the noise control, 1, 3, 5, 7
    volumes (attenuations); after reset all 0"""

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
    """the board's memory, latches and chips around engine/z80.py.  odd: accesses the translation would not expect
    (pc, address, kind); sn_log: (cycle, byte) of the SN's strobes; dac: (cycle, value); vlm_log: (cycle, pin, value)"""

    def __init__(self, game):
        self.g = GAMES[game] if isinstance(game, str) else game
        self.hs = self.g.name == 'hyperspt'
        code = self.g.rom()
        self.mem = bytearray(0x10000)
        self.mem[:len(code)] = code
        self.latch = 0
        self.sn = SN76489()
        self.snl = 0
        self.sn_log = []
        self.dac = []
        self.vlm_log = []
        self.odd = []
        self.st = self.rst = 0
        self.vlm_data = 0
        self.cpu = Z80(self.rd, self.wr)

    # the chip hooks (the boards below)
    def timer(self):
        return (self.cpu.cycles // 1024) & 0x0F

    def bsy(self):
        return 0

    def vlm_pins(self, st, rst):
        if st != self.st:
            self.vlm_log.append((self.cpu.cycles, 'st', st))
        if rst != self.rst:
            self.vlm_log.append((self.cpu.cycles, 'rst', rst))
        self.st, self.rst = st, rst

    def sn_write(self, v):
        self.sn.write(v)
        self.sn_log.append((self.cpu.cycles, v))

    def rd(self, a):
        if a < 0x4000:
            return self.mem[a]
        if self.hs:
            if a < 0x5000:
                return self.mem[a]
            if a == 0x6000:
                return self.latch
            if a == 0x8000:
                return (self.timer() & 3) | (4 if self.bsy() else 0)
            self.odd.append((self.cpu.pc, a, 'read'))
            return 0
        if a < 0x6000:
            if a >= 0x4400:
                self.odd.append((self.cpu.pc, a, 'ram mirror'))
            return self.mem[0x4000 | (a & 0x3FF)]
        if a < 0x8000:
            return self.latch
        if a < 0xA000:
            return self.timer()
        if 0xC000 <= a < 0xE000:
            self.odd.append((self.cpu.pc, a, 'sn read'))
            self.sn_write(self.snl)
            return 0xFF
        if a >= 0xE000 and a & 7 == 2:
            return 0x10 if self.bsy() else 0
        if a < 0xE000 or a & 7 != 1:
            self.odd.append((self.cpu.pc, a, 'read'))
        return 0

    def wr(self, a, v):
        if 0x4000 <= a < 0x6000:
            if self.hs:
                if a < 0x5000:
                    self.mem[a] = v
                else:
                    self.odd.append((self.cpu.pc, a, 'write'))
                return
            if a >= 0x4400:
                self.odd.append((self.cpu.pc, a, 'ram mirror'))
            self.mem[0x4000 | (a & 0x3FF)] = v
            return
        if self.hs:
            if a == 0xA000:
                self.vlm_data = v
                self.vlm_log.append((self.cpu.cycles, 'data', v))
            elif 0xC000 <= a < 0xE000:
                self.vlm_pins((a >> 4) & 1, (a >> 5) & 1)
            elif a == 0xE000:
                self.dac.append((self.cpu.cycles, v))
            elif a == 0xE001:
                self.snl = v
            elif a == 0xE002:
                self.sn_write(self.snl)
            else:
                self.odd.append((self.cpu.pc, a, 'write'))
            return
        if 0xA000 <= a < 0xC000:
            self.snl = v
        elif 0xC000 <= a < 0xE000:
            self.sn_write(self.snl)
        elif a >= 0xE000:
            k = a & 7
            if k == 0:
                self.dac.append((self.cpu.cycles, v))
            elif k == 3:
                self.vlm_pins((a >> 8) & 1, (a >> 9) & 1)
            elif k == 4:
                self.vlm_data = v
                self.vlm_log.append((self.cpu.cycles, 'data', v))
            elif k != 1:
                self.odd.append((self.cpu.pc, a, 'write'))
        else:
            self.odd.append((self.cpu.pc, a, 'write'))


class MameBoard(Board):
    """the reference: the sound CPU at its clock, the VLM5030 rendered up to each access (engine/vlm5030.py), commands
    at given instants (cycle: the sound CPU's)"""

    def __init__(self, game):
        super().__init__(game)
        from vlm5030 import VLM5030
        self.vlm = VLM5030(self.g.vlm_rom())
        self.vlm_done = 0                 # samples rendered
        self.speech = []                  # the VLM's samples
        self.irq = False

    def vlm_update(self):
        n = self.cpu.cycles // 440 - self.vlm_done
        if n > 0:
            self.speech += self.vlm.render(n)
            self.vlm_done += n

    def bsy(self):
        self.vlm_update()
        return self.vlm.bsy_r()

    def vlm_pins(self, st, rst):
        self.vlm_update()
        self.vlm.data_w(self.vlm_data)
        self.vlm.st_w(st)
        self.vlm.rst_w(rst)
        super().vlm_pins(st, rst)

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


def phrase_busy(game):
    """per VLM data byte (0-255) the samples BSY stays high after ST falls (engine/vlm5030.phrase), parameter 0"""
    from vlm5030 import phrase
    rom = GAMES[game].vlm_rom()
    out = {}
    for d in range(256):
        out[d] = phrase(rom, d)[1]
    return out


_BUSY = {}


def busy_table(game):
    if game not in _BUSY:
        cache = Path(__file__).resolve().parents[3] / 'build' / game / 'vlm_busy.txt'
        if cache.exists():
            _BUSY[game] = [int(x) for x in cache.read_text().split()]
        else:
            t = phrase_busy(game)
            _BUSY[game] = [t[d] for d in range(256)]
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(' '.join(map(str, _BUSY[game])) + '\n')
    return _BUSY[game]


class TickBoard(Board):
    """the sound Z80 in the STE's schedule (the module's doc).  tune_fx: the tunes' effects (tunes(): index ->
    (half cycles, [(address, value)], [SN bytes], [the VLM's data byte if it resets the VLM])); tunes_run: the tune
    code runs instead (with its delays: for tune_render); boot=False: boot() later (ref/cover_sound.py)"""

    def __init__(self, game, tune_fx=None, tunes_run=False, boot=True):
        super().__init__(game)
        g = self.g
        self.busy_t = busy_table(g.name)
        self.dac_on = 0
        self.busy = 0                     # the VLM's BSY time left (half cycles; -1: set up, not started)
        self.events = []                  # (frame, 'phrase' / 'tune' / 'stop', n): the DMA's work
        self.tune_fx = tune_fx if tune_fx is not None or tunes_run else tunes(g.name)
        self.frame = 0
        self.acc = 0
        self.pending = None
        if boot:
            self.boot()

    def boot(self):
        self.run_until({self.g.loop})     # the boot: RAM cleared, the SN silenced, the VLM reset, to the loop's head

    def timer(self):
        if not self.hs and self.cpu.pc not in WAITS[self.g.name]:   # (Hyper Sports reads BSY there too: & 4)
            self.odd.append((self.cpu.pc, 0x8000, 'timer'))
        return 0

    def bsy(self):
        return self.busy != 0

    def vlm_pins(self, st, rst):
        if rst != self.rst:
            if rst and self.busy:
                self.busy = 0
                self.events.append((self.frame, 'stop', 0))
            if not rst and self.vlm_data != 0:
                self.odd.append((self.cpu.pc, self.vlm_data, 'vlm parameter'))
        if st != self.st:
            if st:
                self.busy = -1
            else:
                self.busy = self.busy_t[self.vlm_data] * SAMPLE_FX
                self.events.append((self.frame, 'phrase', self.vlm_data))
        super().vlm_pins(st, rst)

    def wr(self, a, v):
        if (a & 0xE007 if not self.hs else a) == 0xE000 and v:
            self.dac_on += 1              # (the DAC's pulses outside the tunes: left out on the STE)
        super().wr(a, v)

    def run_until(self, pcs, limit=3000000):
        c = self.cpu
        for _ in range(limit):
            c.step()
            if c.pc in pcs:
                return
            if c.pc == self.g.tune and self.tune_fx is not None:
                self.tune()
                if c.pc in pcs:
                    return
        raise RuntimeError('the sound CPU did not come to %s (pc %04X)' % (sorted(pcs), c.pc))

    def tune(self):
        """the hook at TUNE: the tune's effect, its time; the cpu continues at the loop's head"""
        i = self.mem[0x400A]
        units, ram, sn, vlm = self.tune_fx[i]
        for a, v in ram:
            self.mem[a] = v
        for v in sn:
            self.sn.write(v)
        if vlm:                           # (the tune resets the VLM: RST pulsed, the parameter byte latched)
            if self.busy:
                self.busy = 0
                self.events.append((self.frame, 'stop', 0))
            self.vlm_data = vlm[0]
        self.acc -= units
        if self.busy > 0:
            self.busy = max(0, self.busy - units)
        self.events.append((self.frame, 'tune', i))
        self.cpu.pc = self.g.loop

    def command(self, v):
        c = self.cpu
        self.latch = v
        c.push(c.pc)
        c.push(TOKEN)
        c.pc = 0x0038
        self.run_until({TOKEN})
        c.pc = c.pop()

    def cost(self):
        return TICK_FX // 2 if self.g.fast and self.mem[self.g.fast] else TICK_FX

    def run_frame(self, commands):
        if self.acc < 0:                  # (a tune plays: the last command waits)
            if commands:
                self.pending = commands[-1]
        else:
            if self.pending is not None:
                self.command(self.pending)
                self.pending = None
            for v in commands:
                self.command(v)
        self.acc += self.g.frame_fx
        while self.acc >= self.cost():
            k = self.cost()
            self.acc -= k
            if self.busy > 0:
                self.busy = max(0, self.busy - k)
            self.cpu.pc = self.g.tick
            self.run_until({self.g.loop})
        self.frame += 1


# the timer's reads in the loop's waits (the STE's schedule leaves the waits out)
WAITS = {'trackfld': {0x01A9, 0x01B0}, 'hyperspt': {0x0240, 0x0247, 0x0317, 0x031E}}


def tunes(game, verbose=False):
    """index -> (half cycles, [(address, value)], [SN bytes], [VLM data byte if it resets the VLM]): each tune's effect, measured on the MameBoard-timed
    code from the boot's state (tune_render); cached in build/<game>/tunes.txt"""
    cache = Path(__file__).resolve().parents[3] / 'build' / game / 'tunes.txt'
    if cache.exists():
        out = {}
        for line in cache.read_text().splitlines():
            i, units, ram, sn, vlm = line.split(';')
            out[int(i)] = (int(units), [tuple(int(x, 16) for x in p.split(':')) for p in ram.split()],
                           [int(x, 16) for x in sn.split()], [int(x, 16) for x in vlm.split()])
        return out
    out = {i: r['effect'] for i, r in tune_render(game).items()}
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(''.join('%d;%d;%s;%s;%s\n' % (i, u, ' '.join('%04X:%02X' % p for p in ram),
                                                 ' '.join('%02X' % v for v in sn), ' '.join('%02X' % v for v in vlm))
                             for i, (u, ram, sn, vlm) in sorted(out.items())))
    return out


TUNE_COUNT = {'trackfld': 2, 'hyperspt': 8}


def tune_render(game, which=None, verbose=False):
    """each tune run as on the board: from the boot's state, $4009 = 1 and $400A = i, from TUNE to the loop's head at
    the Z80's clock.  -> i -> {'cycles', 'sn': [(cycle, byte)], 'dac': [(cycle, value)], 'effect': (half cycles, RAM
    bytes written (their last values, the stack's left out), SN bytes giving the registers it wrote their last values,
    [the data byte] if it pulsed the VLM's RST)}; only a reset of the VLM is allowed (Hyper Sports' tunes stop the
    speech first)"""
    g = GAMES[game]
    out = {}
    for i in range(TUNE_COUNT[game]) if which is None else which:
        b = TickBoard(game, tunes_run=True)
        c = b.cpu
        b.mem[0x4009], b.mem[0x400A] = 1, i
        written = {}
        wr0 = b.wr

        def wr(a, v, wr0=wr0, written=written):
            if 0x4000 <= a < 0x5000:
                written[a] = v
            wr0(a, v)
        c.wr8 = b.wr = wr
        b.sn_log, b.dac, b.vlm_log = [], [], []
        c.pc = g.tune
        c.cycles = 0
        sp0 = c.sp
        regs = [0] * 8
        touched = set()
        latch = [0]
        n0 = 0
        while c.pc != g.loop:
            c.step()
            if c.cycles > 60 * CLOCK:
                raise RuntimeError('tune %d does not end' % i)
            for cy, v in b.sn_log[n0:]:
                if v & 0x80:
                    latch[0] = (v >> 4) & 7
                touched.add(latch[0])
            n0 = len(b.sn_log)
        odd = [o for o in b.odd if o[2] != 'dac']
        if odd:
            raise RuntimeError('tune %d: unexpected accesses %s' % (i, odd[:10]))
        ram = sorted((a, v) for a, v in written.items() if not sp0 - 0x40 <= a < sp0)    # (the stack: dead)
        sn = []
        for r in sorted(touched):
            v = b.sn.reg[r]
            if r in (0, 2, 4):
                sn += [0x80 | r << 4 | (v & 15), (v >> 4) & 0x3F]
            else:
                sn.append(0x80 | r << 4 | (v & 15))
        units = c.cycles * HALF
        pins = [e for e in b.vlm_log if e[1] != 'data']
        if pins and (b.st or not b.rst and not any(e[1] == 'rst' for e in pins)):
            raise RuntimeError('tune %d: the VLM pins %s (only a reset is modelled)' % (i, pins))
        if b.rst:
            raise RuntimeError('tune %d leaves RST high' % i)
        vlm = [b.vlm_data] if pins else []
        out[i] = {'cycles': c.cycles, 'sn': b.sn_log, 'dac': b.dac, 'effect': (units, ram, sn, vlm), 'vlm': b.vlm_log}
        if verbose:
            print('tune %d: %.2f s, %d SN bytes, %d DAC writes' % (i, c.cycles / CLOCK, len(b.sn_log), len(b.dac)))
    return out


def ym_period(n):
    """the YM period for an SN tone period (0 counts as 1024): N x 4000000 / 1789772 rounded"""
    return ((n or 1024) * 4000000 + SN_CLOCK // 2) // SN_CLOCK


def ym_noise(reg6, n2):
    """the YM noise period for the SN's noise control (the shift period 32 / 64 / 128 or 2 x tone 2's), at most 31"""
    p = 2 * (n2 or 1024) if reg6 & 3 == 3 else 32 << (reg6 & 3)
    return min(31, (p * 2000000 + SN_CLOCK // 2) // SN_CLOCK)


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
        for r in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10):
            if regs[r] != self.cache[r]:
                self.cache[r] = regs[r]
                out.append((r, regs[r]))
        return out


class STEBoard(TickBoard):
    """TickBoard and YM: what src/sound.s does in an arcade frame (the YM writes of each frame in ym_log)"""

    def __init__(self, game):
        self.dirty = True
        super().__init__(game)
        self.ym = YM()
        self.ym_log = []

    def sn_write(self, v):
        self.dirty = True
        super().sn_write(v)

    def tune(self):
        self.dirty = True
        super().tune()

    def run_frame(self, commands):
        super().run_frame(commands)
        w = []
        if self.dirty:
            self.dirty = False
            w = self.ym.frame(self.sn)
        self.ym_log.append(w)


if __name__ == '__main__':
    game = sys.argv[1] if len(sys.argv) > 1 else 'trackfld'
    r = tune_render(game, verbose=True)
    for i, t in r.items():
        print(i, 'half cycles', t['effect'][0], 'ram', ['%04X:%02X' % p for p in t['effect'][1]], 'sn', t['effect'][2])
