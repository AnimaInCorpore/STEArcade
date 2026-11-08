"""Dig Dug (Namco, rev. 2) arcade machine model around the reference Z80.

Three Z80s at 3.072 MHz with one shared memory map (MAME galaga.cpp, digdug_state::digdug_map; digdug.cpp is the video):
  0000-3FFF ROM (own per CPU: 16 KB main, 8 KB sub, 4 KB sound)
  6800-681F sound registers (WSG), 6820-6827 latch (IRQ1/IRQ2 enable, CPU3 NMI enable, reset of CPU2/3 and the
  custom chips; Q5-Q7 are also the 53XX's mode inputs), 6830 watchdog
  7000-70FF / 7100 Namco 06XX data / control (51XX: coins, credits, joysticks; 53XX: the DIP switches)
  8000-83FF tile RAM (code only: the colour comes from the code), 8400-87FF work RAM, 8800-8BFF, 9000-93FF,
  9800-9BFF RAM (the sprite table lives at the end of each, +$380: code/colour, y/x, flags)
  A000-A007 video latch (background picture, tile colour mode, background disable, flip)
  B800-B83F / B840 ER2055 EAROM (data / control; the high scores)
Interrupts: IRQ to CPU1 and CPU2 at the vertical blank (scanline 224) if enabled, NMI to CPU3 at scanlines 64 and 192
if enabled, NMI to CPU1 from the 06XX clock while a transfer is running.  The 51XX and the 53XX are the real programs
on the MB88 core (engine/mb88.py; namco51.zip, namco53.zip) behind the 06XX's clock edges, as in Galaga.

render_raw() is the picture (288 x 224 palette indices 0-31, MAME's digdug_v: a 36x28 background picture of 2-bit tiles
selected by the video latch, the 1-bit tile layer with transparent pixel 0, 64 sprites).
"""
import os
import sys
import numpy as np

sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from z80 import Z80
from mb88 import MB88

from paths import EXTRACTED
ROMDIR = str(EXTRACTED / "digdug")

CYCLES_PER_LINE = 192           # 3.072 MHz / (6.144 MHz / 384)
LINES = 264
CYCLES_PER_FRAME = CYCLES_PER_LINE * LINES   # 50688, 60.606 Hz
VBLANK_LINE = 224
CPU3_NMI_LINES = (64, 192)
CLOCK_06XX = 3072000 // 64     # 48 kHz
Z80_PER_MCU = 12              # the custom chips' MB88s: 1.536 MHz / 6 = 256 kHz machine cycles

DSWA_DEFAULT = 0x99           # 1 coin 1 credit (B), bonus 20K 60K, 3 lives
DSWB_DEFAULT = 0x24           # 1 coin 1 credit (A), freeze off, demo sounds on, continue yes, upright, easy

MCU_CRC = {"51xx.bin": 0xc2f57ef8, "53xx.bin": 0xb326fecb}


def load(name):
    with open(os.path.join(ROMDIR, name), "rb") as f:
        return f.read()


def decode_gfx(data, width, height, planes, xoffs, yoffs, size):
    """MAME gfx layout decode: bit offsets count from the MSB of each byte, the first plane is the most significant
    bit of the pixel."""
    n = len(data) // size
    out = np.zeros((n, height, width), np.uint8)
    for i in range(n):
        base = i * size * 8
        for y in range(height):
            for x in range(width):
                v = 0
                for p, po in enumerate(planes):
                    off = base + po + xoffs[x] + yoffs[y]
                    bit = (data[off >> 3] >> (7 - (off & 7))) & 1
                    v |= bit << (len(planes) - 1 - p)
                out[i, y, x] = v
    return out


class Gfx:
    """Decoded characters, background tiles, sprites, palette and colour lookup PROMs (digdug_v.cpp)."""

    def __init__(self):
        step4 = lambda s: [s, s + 1, s + 2, s + 3]
        step8 = lambda s, d: [s + d * i for i in range(8)]
        self.chars = decode_gfx(load("dd1.9"), 8, 8, (0,), [7 - i for i in range(8)], step8(0, 8), 8)    # 1 bit, x = LSB first
        self.bgtiles = decode_gfx(load("dd1.11"), 8, 8, (0, 4), step4(64) + step4(0), step8(0, 8), 16)
        self.sprites = decode_gfx(load("dd1.15") + load("dd1.14") + load("dd1.13") + load("dd1.12"), 16, 16, (0, 4),
                                  step4(0) + step4(64) + step4(128) + step4(192),
                                  step8(0, 8) + step8(256, 8), 64)
        self.bgmap = load("dd1.10b")                       # 4 pictures of 1024 tile codes
        prom = load("136007.113")
        self.palette = []
        for i in range(32):
            c = prom[i]
            r = 0x21 * (c & 1) + 0x47 * ((c >> 1) & 1) + 0x97 * ((c >> 2) & 1)
            g = 0x21 * ((c >> 3) & 1) + 0x47 * ((c >> 4) & 1) + 0x97 * ((c >> 5) & 1)
            b = 0x47 * ((c >> 6) & 1) + 0x97 * ((c >> 7) & 1)
            self.palette.append((r, g, b))
        self.sprite_lut = [(v & 0x0f) | 0x10 for v in load("136007.111")]    # colour*4+pixel -> palette (0x1f: transparent)
        self.bg_lut = [v & 0x0f for v in load("136007.112")]
        self.rgb = np.array(self.palette, np.uint8)


def tile_index(row, col):
    """MAME tilemap_scan: the tile RAM index of screen tile (row 0-27, col 0-35)"""
    row += 2
    col -= 2
    return row + ((col & 0x1f) << 5) if col & 0x20 else col + (row << 5)


def load_mcu(name):
    import zlib
    data = load(name)
    if zlib.crc32(data) != MCU_CRC[name]:
        raise ValueError("%s: crc %08x" % (name, zlib.crc32(data)))
    return data


class Namco51MCU:
    """The real 51XX (namco51.cpp): K = the 06XX's R/W line (bit 3) and the low three bits of the shared latch (portO),
    R0-R3 = IN0 low, IN0 high, IN1 low, IN1 high; P = lamps and coin counters (logged)."""

    def __init__(self, machine):
        self.m = machine
        self.mcu = MB88(load_mcu("51xx.bin"), 64,
                        read_k=lambda: (self.rw << 3) | (self.port_o & 7),
                        read_r=self.read_r, write_o=self.write_o, write_p=self.write_p)
        self.port_o = 0
        self.rw = 0
        self.held = True
        self.log = []
        self.p_log = []

    def read_r(self, n):
        m = self.m
        return (m.in0, m.in0 >> 4, m.in1, m.in1 >> 4)[n & 3] & 0x0f

    def write_o(self, v, mask):
        self.port_o = v & 0xff

    def write_p(self, v):
        self.p_log.append((self.m.frame, v))

    def reset(self):
        self.mcu.reset()

    def write(self, v):
        self.log.append(("w", v))
        self.port_o = v

    def read(self):
        self.log.append(("r", self.port_o))
        return self.port_o


class Namco53MCU:
    """The real 53XX (namco53.cpp, MB8843): K0 open, K1-K3 = the latch's Q5-Q7 (MOD0-MOD2; Dig Dug sets mode 7 when
    running), R0-R3 = DSWA low, DSWA high, DSWB low, DSWB high; O = the byte the main CPU reads."""

    def __init__(self, machine):
        self.m = machine
        self.mcu = MB88(load_mcu("53xx.bin"), 64,
                        read_k=self.read_k, read_r=self.read_r, write_o=self.write_o, write_p=lambda v: None)
        self.port_o = 0
        self.held = True
        self.log = []

    def read_k(self):
        l = self.m.latch
        return (l[7] << 3) | (l[6] << 2) | (l[5] << 1)

    def read_r(self, n):
        m = self.m
        return (m.dswa, m.dswa >> 4, m.dswb, m.dswb >> 4)[n & 3] & 0x0f

    def write_o(self, v, mask):
        self.port_o = v & 0xff

    def reset(self):
        self.mcu.reset()

    def read(self):
        self.log.append(("r", self.port_o))
        return self.port_o


class ER2055:
    """The 64 x 8 EAROM (er2055.cpp): control B840 = CK (bit 0), /C1 (bit 1), C2 (bit 2), CS1 (bit 3); CS2 is tied on"""
    CK, C1, C2, CS1, CS2 = 1, 2, 4, 8, 16

    def __init__(self):
        self.data = bytearray(b"\xff" * 64)
        self.state = 0
        self.address = 0
        self.latch = 0

    def set_address(self, a):
        self.address = a & 0x3f

    def set_data(self, d):
        self.latch = d

    def update(self):
        c = self.state & (self.C1 | self.C2)
        if c == 0:
            self.data[self.address] &= self.latch
        elif c == self.C2:
            self.data[self.address] = 0xff

    def set_control(self, cs1, cs2, c1, c2):
        old = self.state
        self.state = (old & self.CK) | (self.C1 if c1 else 0) | (self.C2 if c2 else 0) | (self.CS1 if cs1 else 0) | \
            (self.CS2 if cs2 else 0)
        if (self.state & (self.CS1 | self.CS2)) != (self.CS1 | self.CS2) or self.state == old:
            return
        self.update()

    def set_clk(self, s):
        old = self.state
        self.state = (self.state | self.CK) if s else (self.state & ~self.CK)
        if (self.state & (self.CS1 | self.CS2)) == (self.CS1 | self.CS2) and self.state != old and not s:
            if (self.state & self.C1) == self.C1:
                self.latch = self.data[self.address]
            self.update()

    def control_w(self, v):
        self.set_control((v >> 3) & 1, 1, 0 if (v >> 1) & 1 else 1, (v >> 2) & 1)
        self.set_clk(v & 1)


DEFER51 = 200                 # event-driven chips: an edge's handler runs after the main CPU's access, at the latest here


def wait51(mcu):
    """the event-driven 51XX is at a wait point: its main loop with the timer unchanged ($182: TTLA / C / JPL $097 /
    JMP $182), or the coinage command's waits for the chip select to end ($00D) and to come again ($010); a pending
    interrupt is taken after the next instruction"""
    if not mcu.in_irq and mcu.pending & mcu.pio:
        return False
    pc = mcu.addr
    if pc == 0x182:
        return not mcu.in_irq and mcu.ram[0x09] == mcu.tl
    if pc == 0x00D:
        return mcu.irq_line == 1
    if pc == 0x010:
        return mcu.irq_line == 0
    return False


def wait53(mcu):
    """the event-driven 53XX is at its wait point: the input loop of mode 7 ($22C: IN / STIC x3, IN / ST, JMP $22C, the
    same four ports read again and again): it stops there whenever no interrupt is pending (the chip select is an edge);
    in a transfer it waits for the chip select to end ($359) and to come again ($35C)"""
    if not mcu.in_irq and mcu.pending & mcu.pio:
        return False
    pc = mcu.addr
    if pc == 0x22C:
        return not mcu.in_irq
    if pc == 0x359:                       # a transfer's bytes: wait for the chip select to end ($359: TSTI / JMP $35C /
        return mcu.irq_line == 1          # JMP $359) and to come again ($35C: TSTI / JMP $35C)
    if pc == 0x35C:
        return mcu.irq_line == 0
    return False


def patch_tests(roms):
    """The boot self-tests patched out (~700 frames of the main CPU's RAM tests and the sub CPUs' ROM checksums, which
    would flood the translation's tests): the main CPU's inline video RAM test ($3897) jumps to the clear that follows
    it and its test routine ($3DE3, called for the other four RAM blocks) to its clear; CPU2's checksum ($1F07) and
    CPU3's ($067F) report their pass ($FF) at once; the delay loop of the EAROM commands ($1EA0, tens of VBLs of the
    STE's time every command, the model needs no waiting) returns at once.  The main CPU's own ROM checksum stays: a dead byte of the replaced routine ($3DE6) keeps the
    sum of its last 4 KB block (which holds its own check byte, $3FFF)."""
    main, sub, snd = (bytearray(r) for r in roms)
    orig = sum(main[0x3000:0x4000])
    main[0x3897:0x389D] = bytes([0x21, 0x00, 0x80, 0xC3, 0xE0, 0x38])      # ld hl,$8000 / jp $38E0
    main[0x3DE3:0x3DE6] = bytes([0xC3, 0x27, 0x3E])                        # jp $3E27
    main[0x3DE6] = (main[0x3DE6] + orig - sum(main[0x3000:0x4000])) & 0xFF         # (dead now: the block's sum is kept)
    sub[0x1F07:0x1F0A] = bytes([0xC3, 0x20, 0x1F])                         # jp $1F20
    snd[0x067F:0x0684] = bytes([0x3E, 0xFF, 0xC3, 0x92, 0x06])             # ld a,$FF / jp $0692
    sub[0x1EA0] = 0xC9                                                     # the EAROM's delay loop ($24DB x 256 counts, ~10 s of the STE's time a command) is a ret
    return bytes(main), bytes(sub), bytes(snd)


class DigDug:
    def __init__(self, frame_line=None, skip_tests=False, mcu_events=False):
        """frame_line: the screen line a frame starts at (224 = the start of the vertical blank, MAME's frame_done).
        skip_tests: the boot self-tests patched out.  mcu_events: the 51XX and 53XX without a clock, run from wait
        point to wait point by their events (wait51, wait53; the model of the STE translation)."""
        self.roms = [load("dd1a.1") + load("dd1a.2") + load("dd1a.3") + load("dd1a.4"),
                     load("dd1a.5") + load("dd1a.6"),
                     load("dd1.7")]
        if skip_tests:
            self.roms = list(patch_tests(self.roms))
        self.mcu_events = mcu_events
        self.defer = None
        self.steps_mcu = 0
        self.port_mode = False                # the STE runtime's schedule (run_frame_port)
        self.in_nmi06 = False
        self.booted = [True, False, False]    # CPU2/3 reached their idle loops (port mode)
        self.handler_runs = [0, 0, 0]
        self.sound_hook = None
        self.rnd_state = 0x1234
        self.ram = bytearray(0x2000)          # 8000-9FFF (the gaps are not mapped)
        self.sound = bytearray(0x20)
        self.latch = [0] * 8                  # 6820-6827
        self.vlatch = [0] * 8                 # A000-A007
        self.earom = ER2055()
        self.earom.control_w(0)
        self.in0 = 0xff
        self.in1 = 0xff
        self.dswa = DSWA_DEFAULT
        self.dswb = DSWB_DEFAULT
        self.frame_line = VBLANK_LINE if frame_line is None else frame_line
        self.n51 = Namco51MCU(self)
        self.n53 = Namco53MCU(self)
        self.t06 = None                       # the 06XX's next clock edge (main CPU cycles)
        self.half06 = 0
        self.state06 = False
        self.stretch06 = False
        self.ctrl06 = 0
        self.cpus = [Z80(self.reader(i), self.writer(i)) for i in range(3)]
        for c in self.cpus:
            c.afmask = 0xC1
        self.held = [False, True, True]       # CPU2 and CPU3 start in reset
        self.irq_pending = [False, False]
        self.frame = 0
        self.gfx = None
        self.io_log = []

    # ---- bus -----------------------------------------------------------
    def reader(self, n):
        rom = self.roms[n]
        ram = self.ram

        def rd8(a):
            if a < 0x4000:
                return rom[a] if a < len(rom) else 0
            if 0x8000 <= a < 0xa000:
                return ram[a - 0x8000]
            if 0x7000 <= a <= 0x70ff:
                return self.data06_r()
            if a == 0x7100:
                return self.ctrl06
            if 0xb800 <= a <= 0xb83f:
                return self.earom.latch
            return 0
        return rd8

    def writer(self, n):
        ram = self.ram

        def wr8(a, v):
            if 0x8000 <= a < 0xa000:
                ram[a - 0x8000] = v
                return
            if a < 0x4000:
                return
            if 0x6800 <= a <= 0x681f:
                self.sound[a & 0x1f] = v
            elif 0x6820 <= a <= 0x6827:
                self.latch_w(a & 7, v & 1)
            elif 0x7000 <= a <= 0x70ff:
                self.data06_w(v)
            elif a == 0x7100:
                self.ctrl06_w(v)
            elif 0xa000 <= a <= 0xa007:
                self.vlatch[a & 7] = v & 1
            elif 0xb800 <= a <= 0xb83f:
                self.earom.set_address(a & 0x3f)
                self.earom.set_data(v)
            elif a == 0xb840:
                self.earom.control_w(v)
            elif a == 0x6830:
                pass
            else:
                self.io_log.append((self.frame, n, a, v))
        return wr8

    def latch_w(self, bit, v):
        self.latch[bit] = v
        if bit == 0 and not v:
            self.irq_pending[0] = False
        elif bit == 1 and not v:
            self.irq_pending[1] = False
        elif bit == 3:
            # CPU2, CPU3 and the custom chips are held in reset while 0
            self.mcu_sync(self.cpus[0].cycles)
            for chip in (self.n51, self.n53):
                if not v:
                    chip.held = True
                elif chip.held:
                    chip.held = False
                    chip.reset()
                    if self.mcu_events:
                        self.run_chip(chip, wait51 if chip is self.n51 else wait53)
            if v and self.held[1]:
                self.cpus[1].reset()
                self.cpus[2].reset()
            self.held[1] = self.held[2] = not v

    # 06XX
    def data06_r(self):
        self.mcu_sync(self.cpus[0].cycles)
        if not (self.ctrl06 & 0x10):
            return 0
        v = 0xff
        if self.ctrl06 & 1:
            v &= self.n51.read()
        if self.ctrl06 & 2:
            v &= self.n53.read()
        return v

    def data06_w(self, v):
        if self.ctrl06 & 0x10:
            return
        self.mcu_sync(self.cpus[0].cycles)
        if self.ctrl06 & 1:
            self.n51.write(v)                 # (the 53XX has no write callback)

    def ctrl06_w(self, v):
        if self.port_mode:
            return self.ctrl06_port(v)
        now = self.cpus[0].cycles
        self.mcu_sync(now)
        self.ctrl06 = v
        if (v & 0xe0) == 0:
            self.t06 = None
            self.state06 = False
            self.n51.mcu.set_irq(0)
            self.n53.mcu.set_irq(0)
            return
        self.stretch06 = bool(v & 0x10)        # a read: the first NMI pulse is suppressed
        self.half06 = (3072000 // CLOCK_06XX // 2) << (v >> 5)
        tick = 3072000 // CLOCK_06XX
        self.t06 = (now // tick + 1) * tick    # the next falling edge of the 48 kHz clock

    def edge06(self):
        """one edge of the 06XX's divided clock (at self.t06): the falling one (state True) sets the R/W lines, pulses
        the main CPU's NMI (unless a read stretches the first) and selects the chips"""
        t = self.t06
        self.mcu_sync(t)
        self.state06 = st = not self.state06
        c = self.ctrl06
        if st:
            self.n51.rw = (c >> 4) & 1
        nmi = st and not self.stretch06
        self.stretch06 = False
        self.n51.mcu.set_irq(st and c & 1)
        self.n53.mcu.set_irq(st and c & 2)
        self.t06 = t + self.half06
        return nmi

    def mcu_sync(self, t):
        """run the MCUs that are out of reset up to main CPU cycle t"""
        target = t // Z80_PER_MCU
        for chip in (self.n51, self.n53):
            mcu = chip.mcu
            if chip.held or self.mcu_events:
                mcu.cycles = max(mcu.cycles, target)
            else:
                mcu.run_to(target)

    def run_main_mcu(self, cpu, t):
        """the main CPU up to cycle t with the 06XX's edges in between"""
        while cpu.cycles < t:
            while self.t06 is not None and self.t06 <= cpu.cycles:
                if self.edge06():
                    cpu.nmi()
            if self.irq_pending[0] and cpu.iff1:
                cpu.irq()
            cpu.step()


    def rnd(self):
        """What the port's z80_rnd gives for `ld a,r`: a 16-bit shift register byte."""
        s = self.rnd_state
        s = (s >> 1) ^ (0xB400 if s & 1 else 0)
        self.rnd_state = s
        return s & 0xFF

    # ---- the event-driven chips (the STE runtime's model) --------------
    def run_chip(self, chip, wait):
        """run the chip to its next wait point"""
        if chip.held:
            return
        mcu = chip.mcu
        k = 0
        while not wait(mcu):
            mcu.step()
            k += 1
            if k > 100000:
                raise RuntimeError("MCU does not reach a wait point (pc %03X)" % mcu.addr)
        self.steps_mcu += k

    def run_chips(self):
        self.run_chip(self.n51, wait51)
        self.run_chip(self.n53, wait53)

    def ctrl06_port(self, v):
        """the STE runtime's 06XX (g_ctrl06) with the event-driven chips: the transfer runs right here, one clock period
        a pass: the R/W line and the chip selects, the main CPU's NMI handler (a read's first pulse is suppressed: the
        chip puts out its byte first), the chips after the handler's access, the chip selects off; a control write from
        inside the handler (its stop) only sets the register"""
        if not self.mcu_events:
            raise NotImplementedError("the STE schedule (run_frame_port) needs the event-driven chips")
        self.ctrl06 = v
        if self.in_nmi06:
            return
        n51, n53 = self.n51, self.n53
        self.in_nmi06 = True
        first = True
        k = 0
        while self.ctrl06 & 0xe0:
            c = self.ctrl06
            n51.rw = (c >> 4) & 1
            n51.mcu.set_irq(c & 1)
            n53.mcu.set_irq(c & 2)
            if first and c & 0x10:
                self.run_chips()
            else:
                self.run_handler(self.cpus[0], nmi=True)
                self.run_chips()
            n51.mcu.set_irq(0)
            n53.mcu.set_irq(0)
            self.run_chips()
            first = False
            k += 1
            if k > 64:
                raise RuntimeError("06XX transfer does not end")
        self.in_nmi06 = False
        n51.mcu.set_irq(0)
        n53.mcu.set_irq(0)
        self.run_chips()

    # ---- the STE runtime's schedule ------------------------------------
    IDLE = [None, 0x0078, 0x00B0]
    # the spin loops of the boot handshake (CPU1 waits for the self-test results of CPU2 and CPU3 at $3973 / $3980,
    # they wait for CPU1 to clear the flags: CPU2 at $1F25, CPU3 at $0695): a CPU that reaches one gives the other
    # booting CPUs a turn (hooks in the translated code, z80_hook)
    YIELD = [{0x3973, 0x3980}, {0x1F25}, {0x0695}]
    FOREGROUND2 = 0x1DDC                  # CPU2's main loop: the EAROM commands (a call, then jr $0078)

    def run_until_yield(self, n):
        """Run cpu n (at a yield point or just released) until it is at a yield point again or in its idle loop."""
        cpu = self.cpus[n]
        stop = self.YIELD[n] | {self.IDLE[n]}
        cpu.step()
        k = 0
        while cpu.pc not in stop:
            cpu.step()
            k += 1
            if k > 20_000_000:
                raise RuntimeError("CPU%d runs away in its boot" % (n + 1))
        if cpu.pc == self.IDLE[n]:
            self.booted[n] = True

    def boot_turns(self):
        for n in (1, 2):
            if not self.held[n] and not self.booted[n]:
                self.run_until_yield(n)

    def run_handler(self, cpu, nmi=False):
        """Run an interrupt handler of cpu to its return (the interrupted pc and sp)."""
        sp0, pc0 = cpu.sp, cpu.pc
        if nmi:
            cpu.nmi()
        elif not cpu.irq():
            return False
        n = 0
        while not (cpu.sp == sp0 and cpu.pc == pc0):
            cpu.step()
            n += 1
            if n > 2_000_000:
                raise RuntimeError("handler of %04X did not return" % pc0)
        return True

    def sound_nmis(self):
        """the sound CPU's two NMIs of a frame (lines 64 and 192), once booted, while its NMION is off"""
        if not self.booted[2]:
            return
        if self.sound_hook:
            self.sound_hook(self, "before")
        for _ in range(2):
            if self.latch[2]:
                break
            self.run_handler(self.cpus[2], nmi=True)
        if self.sound_hook:
            self.sound_hook(self, "after")

    def run_foreground2(self):
        """CPU2's main loop, once a frame after its IRQ handler (the arcade's runs all the time, but only the EAROM
        command in $9B3D does anything): the call at $0078, with the interrupted pc and sp back afterwards"""
        cpu = self.cpus[1]
        if not self.booted[1] or not self.ram[0x1B3D]:
            return
        sp0, pc0 = cpu.sp, cpu.pc
        cpu.sp -= 2
        self.ram[cpu.sp - 0x8000] = pc0 & 0xFF
        self.ram[cpu.sp - 0x8000 + 1] = pc0 >> 8
        cpu.pc = self.FOREGROUND2
        n = 0
        while not (cpu.sp == sp0 and cpu.pc == pc0):
            cpu.step()
            n += 1
            if n > 5_000_000:
                raise RuntimeError("CPU2's foreground did not return")

    def run_frame_port(self):
        """One frame as the STE runtime schedules it: CPU1's main thread for the frame, then at the vertical blank
        CPU1's IRQ handler and CPU2's IRQ handler, each to completion, then CPU2's EAROM command if one is pending.
        CPU2 and CPU3 run their boot code to the idle loop once they are released; then CPU3's NMI handler twice a
        frame (the sound).  06XX NMIs are synchronous (ctrl06_port)."""
        self.port_mode = True
        cpu1 = self.cpus[0]
        for c in self.cpus:
            c.r_hook = self.rnd
        end = cpu1.cycles + CYCLES_PER_FRAME
        yields = self.YIELD[0]
        while cpu1.cycles < end:
            cpu1.step()
            if cpu1.pc in yields:
                self.boot_turns()
        self.boot_turns()                       # the VBL gives the booting CPUs a turn too
        self.n51.mcu.set_tc(1)                  # the 51XX's frame: TC high, then low
        self.run_chip(self.n51, wait51)
        self.n51.mcu.set_tc(0)
        self.run_chip(self.n51, wait51)
        if self.latch[0] and self.run_handler(cpu1):
            self.handler_runs[0] += 1
        if self.latch[1] and self.booted[1] and self.run_handler(self.cpus[1]):
            self.handler_runs[1] += 1
        self.run_foreground2()
        self.sound_nmis()
        self.frame += 1

    # ---- running -------------------------------------------------------
    def run_frame(self, slice_cycles=128):
        cpus = self.cpus
        start = cpus[0].cycles
        end = start + CYCLES_PER_FRAME
        at = lambda line: ((line - self.frame_line) % LINES) * CYCLES_PER_LINE
        events = sorted([(at(VBLANK_LINE), "vbl")] + [(at(l), "nmi3") for l in CPU3_NMI_LINES] +
                        [(at(0), "vblend")])
        ei = 0
        t = start
        while t < end:
            t = min(t + slice_cycles, end)
            while ei < len(events) and start + events[ei][0] < t:
                kind = events[ei][1]
                ei += 1
                if kind == "vblend":
                    self.mcu_sync(start + events[ei - 1][0])
                    self.n51.mcu.set_tc(1)              # the vertical blank ends: the 51XX's TC pin goes high
                elif kind == "vbl":
                    self.mcu_sync(start + events[ei - 1][0])
                    self.n51.mcu.set_tc(0)          # the vertical blank starts: the 51XX's timer counts
                    if self.latch[0]:
                        self.irq_pending[0] = True
                    if self.latch[1]:
                        self.irq_pending[1] = True
                elif kind == "nmi3":
                    if not self.latch[2] and not self.held[2]:
                        cpus[2].nmi()
            for n, cpu in enumerate(cpus):
                if self.held[n]:
                    cpu.cycles = max(cpu.cycles, t)
                    continue
                if n == 0:
                    self.run_main_mcu(cpu, t)
                    continue
                while cpu.cycles < t:
                    if n == 1 and self.irq_pending[1] and cpu.iff1:
                        cpu.irq()
                    cpu.step()
        self.mcu_sync(end)                          # (the inputs change between frames)
        self.frame += 1

    # ---- rendering -----------------------------------------------------
    def render_raw(self, wrap=True):
        """288 x 224 (y, x) bitmap of palette indices 0-31 (digdug_v.cpp).  wrap=False: without the copies of the
        sprites 256 pixels to the right (MAME draws them; the STE's renderer does not, tools/render_test.py)."""
        if self.gfx is None:
            self.gfx = Gfx()
        g = self.gfx
        ram = self.ram
        vl = self.vlatch
        bg_select = vl[0] | (vl[1] << 1)
        bank = (vl[4] << 4) | (vl[5] << 5)
        tx_mode, bg_disable, flip = vl[2], vl[3], vl[7]
        bmp = np.zeros((224, 288), np.uint8)
        bg_lut = np.array(g.bg_lut, np.uint8)
        char_lut = np.arange(16)
        for row in range(28):
            for col in range(36):
                idx = tile_index(row, col)
                code = g.bgmap[idx | (bg_select << 10)]
                color = (0xf if bg_disable else code >> 4) | bank
                bmp[row * 8:row * 8 + 8, col * 8:col * 8 + 8] = bg_lut[color * 4:color * 4 + 4][g.bgtiles[code]]
        for row in range(28):
            for col in range(36):
                code = ram[tile_index(row, col)]
                color = (code & 0x0f) if tx_mode else (((code >> 4) & 0x0e) | ((code >> 3) & 2))
                pix = g.chars[(code & 0x7f) | (0x80 if flip else 0)]
                if flip:
                    pix = pix[:, ::-1]
                blk = bmp[row * 8:row * 8 + 8, col * 8:col * 8 + 8]
                blk[pix != 0] = color
        # sprites (clipped to x 16-271)
        s1, s2, s3 = 0x0b80, 0x1380, 0x1b80
        for offs in range(0, 0x80, 2):
            sprite = ram[s1 + offs]
            color = ram[s1 + offs + 1] & 0x3f
            sx = ram[s2 + offs + 1] - 40 + 1
            sy = 256 - ram[s2 + offs] + 1
            flipx, flipy = ram[s3 + offs] & 1, (ram[s3 + offs] >> 1) & 1
            size = (sprite & 0x80) >> 7
            if size:
                sprite = (sprite & 0xc0) | ((sprite & ~0xc0) << 2)
            sy -= 16 * size
            sy = (sy & 0xff) - 32
            if flip:
                flipx ^= 1
                flipy ^= 1
            lut = g.sprite_lut[color * 4:color * 4 + 4]
            for y in range(size + 1):
                for x in range(size + 1):
                    code = (sprite + [[0, 1], [2, 3]][y ^ (size * flipy)][x ^ (size * flipx)]) & 0xff
                    tile = g.sprites[code]
                    if flipx: tile = tile[:, ::-1]
                    if flipy: tile = tile[::-1, :]
                    for px0 in (((sx + 16 * x) & 0xff, ((sx + 16 * x) & 0xff) + 0x100) if wrap else ((sx + 16 * x) & 0xff,)):
                        py0 = sy + 16 * y
                        for yy in range(16):
                            ry = py0 + yy
                            if not 0 <= ry < 224:
                                continue
                            for xx in range(16):
                                rx = px0 + xx
                                if not 16 <= rx < 272:
                                    continue
                                p = lut[tile[yy, xx]]
                                if p != 0x1f:
                                    bmp[ry, rx] = p
        return bmp

    def render_rgb(self):
        bmp = self.render_raw()
        rgb = self.gfx.rgb[bmp]          # [y][x][3], 224 x 288
        return rgb.transpose(1, 0, 2)[:, ::-1]   # ROT90: 288 tall, 224 wide


def save_png(arr, path, scale=2):
    from PIL import Image
    im = Image.fromarray(arr)
    if scale != 1:
        im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    im.save(path)


if __name__ == "__main__":
    import time
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    out = sys.argv[2] if len(sys.argv) > 2 else "digdug.png"
    m = DigDug()
    t0 = time.time()
    for f in range(frames):
        m.run_frame()
        if f % 60 == 0:
            print("frame", f, "pc", "%04X %04X %04X" % tuple(c.pc for c in m.cpus),
                  "held", m.held[1:], "latch", m.latch, "vlatch", m.vlatch)
    print("%.1f s, %.1f frames/s" % (time.time() - t0, frames / (time.time() - t0)))
    print("51xx log (first 30):", m.n51.log[:30])
    print("53xx reads:", len(m.n53.log), m.n53.log[:8])
    print("unknown writes:", m.io_log[:20])
    save_png(m.render_rgb(), out)
    print("wrote", out)
