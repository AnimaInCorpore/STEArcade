"""Super Xevious (Namco, 1984; MAME set `sxevious`, a clone of `xevious`) arcade machine model around the reference Z80.

Three Z80s at 3.072 MHz on Galaga's board family with Xevious's memory map (MAME galaga.cpp xevious_map, xevious.cpp
video):
  0000-3FFF ROM (own per CPU: 16 KB main, 8 KB sub, 4 KB sound)      writes there are ignored
  6800-6807 DIP switches, 6800-681F sound registers, 6820-6827 latch (IRQ1/IRQ2 enable, CPU3 NMI enable, resets)
  6830 watchdog, 7000-70FF / 7100 Namco 06XX data / control (51XX inputs, 50XX protection, 54XX sound)
  7800-7FFF shared work RAM, 8000-87FF / 9000-97FF / A000-A7FF work RAM with the sprite registers at +780
  B000 fg colour, B800 bg colour, C000 fg code, C800 bg code (2 KB each), D000-D07F scroll / flip latch (write)
  F000-FFFF the background pattern ROM logic (BS write, BB read)
Interrupts: IRQ to CPU1 and CPU2 at the vertical blank (scanline 224) if enabled, NMI to CPU3 at scanlines 64 and 192
if enabled, NMI to CPU1 from the 06XX clock while a transfer is running.  The 50XX, 51XX and 54XX run their real
programs (namco50.zip, namco51.zip, namco54.zip) on the MB88 core (engine/mb88.py) behind an exact model of the 06XX's
clock edges, as the Galaga reference does.

Provides scripted inputs and the reference renderer (render_raw: two tile layers with scroll, 3-bit sprites with the
colour look-up PROMs), checked against MAME's picture (ref/mame_cmp_xevious.py).
"""
import os
import sys
import numpy as np

sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from z80 import Z80
from mb88 import MB88

from paths import EXTRACTED
ROMDIR = str(EXTRACTED / "xevious")

CYCLES_PER_LINE = 192           # 3.072 MHz / (6.144 MHz / 384)
LINES = 264
CYCLES_PER_FRAME = CYCLES_PER_LINE * LINES   # 50688, 60.606 Hz
VBLANK_LINE = 224
CPU3_NMI_LINES = (64, 192)
CLOCK_06XX = 3072000 // 64     # 48 kHz


Z80_PER_MCU = 12              # the custom chips' MB88s: 1.536 MHz / 6 = 256 kHz machine cycles
DEFER51 = 200                 # event-driven 51XX: an edge's handler runs after the main CPU's access, at the latest here


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


def load_mcu(zipname, member, crc):
    """an MCU program from its own MAME set in assets/roms (checked)"""
    import zipfile, zlib
    from paths import ROMS
    with zipfile.ZipFile(os.path.join(ROMS, zipname)) as z:
        data = z.read(member)
    if zlib.crc32(data) != crc:
        raise ValueError("%s/%s: crc %08x, expected %08x" % (zipname, member, zlib.crc32(data), crc))
    return data


def load(name):
    with open(os.path.join(ROMDIR, name), "rb") as f:
        return f.read()


def decode_gfx(data, width, height, planes, xoffs, yoffs, size, count=None):
    """MAME gfx layout decode: bit offsets count from the MSB of each byte, the first plane is the
    most significant bit of the pixel (until 2026-10-08 it was the least: pens 1 and 2 swapped)."""
    n = count if count is not None else len(data) // size
    out = np.zeros((n, height, width), np.uint8)
    for i in range(n):
        base = i * size * 8
        for y in range(height):
            for x in range(width):
                v = 0
                for p, po in enumerate(planes):
                    off = base + po + xoffs[x] + yoffs[y]
                    bit = (data[off >> 3] >> (7 - (off & 7))) & 1
                    v |= bit << (len(planes) - 1 - p)     # the first plane is the most significant (MAME)
                out[i, y, x] = v
    return out

class Namco51MCU:
    """The real 51XX: MAME's namco51.cpp around the MB8843.  K = the 06XX's R/W line (bit 3) and the low three bits of
    the shared latch (portO: the main CPU's writes, the MCU's O output, read back by the main CPU), R0-R3 = IN0 low,
    IN0 high, IN1 low, IN1 high; P = lamps and coin counters (logged)."""

    def __init__(self, machine):
        self.m = machine
        self.mcu = MB88(load_mcu("namco51.zip", "51xx.bin", 0xc2f57ef8), 64,
                        read_k=lambda: (self.rw << 3) | (self.port_o & 7),
                        read_r=self.read_r, write_o=self.write_o, write_p=self.write_p)
        self.port_o = 0
        self.rw = 0
        self.held = True
        self.mode = None          # (the simulation's state, for the old printouts)
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


class Namco54MCU:
    """The real 54XX (MB8844): K = the command's high nibble, R0 its low nibble; the outputs (O nibbles, R1) go to the
    discrete explosion circuit and are logged as (frame, MCU cycle, port, value)."""

    def __init__(self, machine):
        self.m = machine
        self.mcu = MB88(load_mcu("namco54.zip", "54xx.bin", 0xee7357e0), 64,
                        read_k=lambda: self.cmd >> 4, read_r=lambda n: self.cmd & 0x0f if n == 0 else 0,
                        write_r=self.write_r, write_o=self.write_o)
        self.cmd = 0
        self.held = True
        self.log = []
        self.out = []

    def write_o(self, v, mask):
        self.out.append((self.m.frame, self.mcu.cycles, "o0" if mask == 0x0f else "o1", (v & mask) >> (0 if mask == 0x0f else 4)))

    def write_r(self, n, v):
        if n == 1:
            self.out.append((self.m.frame, self.mcu.cycles, "r1", v & 0x0f))

    def reset(self):
        self.mcu.reset()

    def write(self, v):
        self.log.append((self.m.frame, v))
        self.cmd = v



Z80_PER_MCU = 12              # the custom chips' MB88s: 1.536 MHz / 6 = 256 kHz machine cycles


class Namco50MCU:
    """The real 50XX (MB8842, 2 KB, 128 nibbles of RAM): MAME's namco50.cpp.  K = the command's high nibble, R0 its low
    nibble, R2 = the R/W line; O = the answer byte the main CPU reads.  Xevious only uses it for the protection check
    at start-up."""

    def __init__(self, machine):
        self.m = machine
        self.mcu = MB88(load_mcu("namco50.zip", "50xx.bin", 0xa0acbaf7), 128,
                        read_k=lambda: self.cmd >> 4, read_r=self.read_r, write_o=self.write_o)
        self.cmd = 0
        self.rw = 0
        self.port_o = 0
        self.held = True
        self.log = []

    def read_r(self, n):
        return self.cmd & 0x0f if n == 0 else (self.rw & 1 if n == 2 else 0)

    def write_o(self, v, mask):
        self.port_o = v & 0xff

    def reset(self):
        self.mcu.reset()

    def write(self, v):
        self.log.append(("w", self.m.frame, v))
        self.cmd = v

    def read(self):
        self.log.append(("r", self.m.frame, self.port_o))
        return self.port_o


def skip_ram_test(rom):
    """The boot RAM test, if the program has a long one (found by tools/probe_boot.py): identity until measured."""
    return rom


def unpack_gfx3():
    """MAME init_xevious: the sprite ROM region (0xa000 bytes): 0000 sets 1-3 planes 0/1, 5000 plane 2 of sets 1 and 2
    (xvi_18), 7000 = the same bytes' high nibbles (plane 2 of the second set), 9000 zero (set 3's plane 2)."""
    r = bytearray(0xa000)
    r[0x0000:0x2000] = load("xvi_15.4m")
    r[0x2000:0x4000] = load("xvi_17.4p")
    r[0x4000:0x5000] = load("xvi_16.4n")
    r[0x5000:0x7000] = load("xvi_18.4r")
    for i in range(0x2000):
        r[0x7000 + i] = r[0x5000 + i] >> 4
    return bytes(r)


def bits_to_rgb(v0, v1, v2):
    w = (0x0e, 0x1f, 0x43, 0x8f)
    return tuple(sum(w[k] * ((v >> k) & 1) for k in range(4)) for v in (v0, v1, v2))


def load_proms():
    return (load("xvi-8.6a") + load("xvi-9.6d") + load("xvi-10.6e") + load("xvi-7.4h") + load("xvi-6.4f") +
            load("xvi-4.3l") + load("xvi-5.3m"))


class Gfx:
    """Decoded characters, background tiles, sprites, palette and the colour look-up PROMs (MAME xevious.cpp)."""

    def __init__(self):
        step4 = lambda s: [s, s + 1, s + 2, s + 3]
        step8 = lambda s, d: [s + d * i for i in range(8)]
        self.chars = decode_gfx(load("xvi_12.3b"), 8, 8, (0,), list(range(8)), step8(0, 8), 8, 512)          # 512 x 1 bpp
        bg = load("xvi_13.3c") + load("xvi_14.3d")
        self.bg = decode_gfx(bg, 8, 8, (0, 0x1000 * 8), list(range(8)), step8(0, 8), 8, 512)                  # 512 x 2 bpp
        sp = unpack_gfx3()
        half = len(sp) // 2 * 8
        self.sprites = decode_gfx(sp, 16, 16, (half + 4, 0, 4), step4(0) + step4(64) + step4(128) + step4(192),
                                  step8(0, 8) + step8(256, 8), 64, len(sp) // 2 // 64)                 # 320 x 3 bpp
        pr = load_proms()
        self.palette = [bits_to_rgb(pr[i], pr[256 + i], pr[512 + i]) for i in range(128)] + [(0, 0, 0)]
        self.bg_lut = [(pr[0x300 + i] & 0xf) | ((pr[0x500 + i] & 0xf) << 4) for i in range(512)]
        self.sprite_lut = []
        for i in range(512):
            c = (pr[0x700 + i] & 0xf) | ((pr[0x900 + i] & 0xf) << 4)
            self.sprite_lut.append(c & 0x7f if c & 0x80 else 0x80)
        self.rgb = np.array(self.palette, np.uint8)             # index 128: black


class Xevious:
    def __init__(self, skip_tests=False, frame_line=None):
        """frame_line: the screen line a frame starts at; the default 224 (the start of the vertical blank) is MAME's
        phase for its frame_done callbacks (ref/mame_cmp_xevious.py)."""
        self.roms = [load("cpu_3p.rom") + load("cpu_3m.rom") + load("xv3_3.2m") + load("xv3_4.2l"),
                     load("xv3_5.3f") + load("xv3_6.3j"), load("xvi_7.2c")]
        if skip_tests:
            self.roms[0] = skip_ram_test(self.roms[0])
        self.mem = bytearray(0x10000)         # 7800-CFFF are the RAM, the rest unused
        self.sound = bytearray(0x20)
        self.latch = [0] * 8                  # 6820-6827
        self.in0 = 0xff
        self.in1 = 0xff
        self.dswa = 0xff                      # MAME defaults: 1C/1C, 20K 60K 60K, 3 lives, upright
        self.dswb = 0x7f                      # Super Xevious: freeze off, normal, 1C/1C
        self.bs = [0, 0]                      # the BS latches (F000 writes)
        self.scroll = {0: 0, 1: 0, 2: 0, 3: 0}   # bg x, fg x, bg y, fg y
        self.flip = 0
        self.frame_line = VBLANK_LINE if frame_line is None else frame_line
        self.n50 = Namco50MCU(self)
        self.n51 = Namco51MCU(self)
        self.n54 = Namco54MCU(self)
        self.chips = (self.n50, self.n51, self.n54)
        self.t06 = None
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
        r = bytearray(0x4000)                 # the region gfx4
        r[0:0x1000] = load("xvi_9.2a")
        r[0x1000:0x3000] = load("xvi_10.2b")
        r[0x3000:0x4000] = load("xvi_11.2c")
        self.gfx4 = bytes(r)

    # ---- the background pattern logic (xevious_bb_r) -------------------
    def bb_r(self, offset):
        rom2a, rom2b, rom2c = self.gfx4, self.gfx4[0x1000:], self.gfx4[0x3000:]
        bs0, bs1 = self.bs
        adr_2b = ((bs1 & 0x7e) << 6) | ((bs0 & 0xfe) >> 1)
        if adr_2b & 1:
            dat1 = ((rom2a[adr_2b >> 1] & 0xf0) << 4) | rom2b[adr_2b]
        else:
            dat1 = ((rom2a[adr_2b >> 1] & 0x0f) << 8) | rom2b[adr_2b]
        adr_2c = ((dat1 & 0x1ff) << 2) | ((bs1 & 1) << 1) | (bs0 & 1)
        if dat1 & 0x400:
            adr_2c ^= 1
        if dat1 & 0x200:
            adr_2c ^= 2
        if offset & 1:
            return rom2c[adr_2c | 0x800]
        d = rom2c[adr_2c]
        d = (d & 0x3f) | ((d & 0x40) << 1) | ((d & 0x80) >> 1)          # swap bits 6 and 7
        if dat1 & 0x400:
            d ^= 0x40
        if dat1 & 0x200:
            d ^= 0x80
        return d

    # ---- bus -----------------------------------------------------------
    @staticmethod
    def is_ram(a):
        return 0x7800 <= a < 0x8000 or 0x8000 <= a < 0x8800 or 0x9000 <= a < 0x9800 or 0xa000 <= a < 0xa800 or 0xb000 <= a < 0xd000

    def reader(self, n):
        rom = self.roms[n]
        mem = self.mem
        is_ram = self.is_ram

        def rd8(a):
            if a < 0x4000:
                return rom[a] if a < len(rom) else 0
            if is_ram(a):
                return mem[a]
            if 0x6800 <= a <= 0x6807:
                b = a & 7
                return ((self.dswb >> b) & 1) | (((self.dswa >> b) & 1) << 1)
            if 0x7000 <= a <= 0x70ff:
                return self.data06_r()
            if a == 0x7100:
                return self.ctrl06
            if a >= 0xf000:
                return self.bb_r(a - 0xf000)
            return 0xff
        return rd8

    def writer(self, n):
        mem = self.mem
        is_ram = self.is_ram

        def wr8(a, v):
            if a < 0x4000:
                return
            if is_ram(a):
                mem[a] = v
            elif 0xd000 <= a < 0xd080:
                self.vh_latch(a - 0xd000, v)
            elif a >= 0xf000:
                self.bs[(a - 0xf000) & 1] = v
            elif 0x6800 <= a <= 0x681f:
                self.sound[a & 0x1f] = v
            elif 0x6820 <= a <= 0x6827:
                self.latch_w(a & 7, v & 1)
            elif 0x7000 <= a <= 0x70ff:
                self.data06_w(v)
            elif a == 0x7100:
                self.ctrl06_w(v)
            elif a == 0x6830:
                pass
            else:
                self.io_log.append((self.frame, n, a, v))
        return wr8

    def vh_latch(self, offset, data):
        scroll = data + ((offset & 1) << 8)
        reg = (offset & 0xf0) >> 4
        if reg in (0, 1, 2, 3):
            self.scroll[reg] = scroll
        elif reg == 7:
            self.flip = scroll & 1

    def latch_w(self, bit, v):
        self.latch[bit] = v
        if bit == 0 and not v:
            self.irq_pending[0] = False
        elif bit == 1 and not v:
            self.irq_pending[1] = False
        elif bit == 3:
            self.mcu_sync(self.cpus[0].cycles)
            for chip in self.chips:
                if not v:
                    chip.held = True
                elif chip.held:
                    chip.held = False
                    chip.reset()
            if v and self.held[1]:
                self.cpus[1].reset()
                self.cpus[2].reset()
            self.held[1] = self.held[2] = not v

    # ---- the 06XX and the MCUs (MAME's namco06.cpp) ---------------------
    def data06_r(self):
        self.mcu_sync(self.cpus[0].cycles)
        if not (self.ctrl06 & 0x10):
            return 0
        v = 0xff
        if self.ctrl06 & 1: v &= self.n51.read()
        if self.ctrl06 & 4: v &= self.n50.read()
        return v

    def data06_w(self, v):
        if self.ctrl06 & 0x10:
            return
        self.mcu_sync(self.cpus[0].cycles)
        if self.ctrl06 & 1: self.n51.write(v)
        if self.ctrl06 & 4: self.n50.write(v)
        if self.ctrl06 & 8: self.n54.write(v)

    def ctrl06_w(self, v):
        now = self.cpus[0].cycles
        self.mcu_sync(now)
        self.ctrl06 = v
        if (v & 0xe0) == 0:
            self.t06 = None
            self.state06 = False
            for chip in self.chips:
                chip.mcu.set_irq(0)
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
            self.n50.rw = (c >> 4) & 1
        nmi = st and not self.stretch06
        self.stretch06 = False
        self.n51.mcu.set_irq(st and c & 1)
        self.n50.mcu.set_irq(st and c & 4)
        self.n54.mcu.set_irq(st and c & 8)
        self.t06 = t + self.half06
        return nmi

    def mcu_sync(self, t):
        """run the MCUs that are out of reset up to main CPU cycle t"""
        target = t // Z80_PER_MCU
        for chip in self.chips:
            mcu = chip.mcu
            if chip.held:
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

    # ---- running -------------------------------------------------------
    def run_frame(self, slice_cycles=128):
        cpus = self.cpus
        start = cpus[0].cycles
        end = start + CYCLES_PER_FRAME
        at = lambda line: ((line - self.frame_line) % LINES) * CYCLES_PER_LINE
        events = sorted([(at(VBLANK_LINE), "vbl"), (at(0), "vblend")] + [(at(l), "nmi3") for l in CPU3_NMI_LINES])
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
                    self.n51.mcu.set_tc(0)              # the vertical blank starts: the timer counts
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
        self.mcu_sync(end)                      # (the inputs change between frames)
        self.frame += 1

    # ---- rendering -----------------------------------------------------
    def render_raw(self):
        """288 x 224 (x, y) bitmap of palette indices (128 = black), MAME's screen_update_xevious."""
        if self.gfx is None:
            self.gfx = Gfx()
        g = self.gfx
        mem = self.mem
        flip = self.flip
        bgv, bgc = mem[0xc800:0xd000], mem[0xb800:0xc000]
        fgv, fgc = mem[0xc000:0xc800], mem[0xb000:0xb800]
        bgmap = np.zeros((256, 512), np.uint8)
        fgmap = np.full((256, 512), 0x80, np.uint8)
        bg_lut = np.array(g.bg_lut, np.uint8)
        for idx in range(2048):
            ty, tx = idx >> 6, idx & 63
            code, attr = bgv[idx], bgc[idx]
            color = ((attr & 0x3c) >> 2) | ((code & 0x80) >> 3) | ((attr & 3) << 5)
            tile = g.bg[code + ((attr & 1) << 8)]
            if attr & 0x40: tile = tile[:, ::-1]
            if attr & 0x80: tile = tile[::-1, :]
            bgmap[ty * 8:ty * 8 + 8, tx * 8:tx * 8 + 8] = bg_lut[color * 4 + tile.astype(np.int32)]
            code, attr = fgv[idx], fgc[idx]
            color = ((attr & 3) << 4) | ((attr & 0x3c) >> 2)
            tile = g.chars[code | (0x100 if flip else 0)]
            if bool(attr & 0x40) ^ bool(flip): tile = tile[:, ::-1]
            if attr & 0x80: tile = tile[::-1, :]
            fgmap[ty * 8:ty * 8 + 8, tx * 8:tx * 8 + 8] = np.where(tile != 0, color, 0x80)
        sx_ = np.arange(288)
        sy_ = np.arange(224)

        def layer(m, scx, scy, dx, dy, dxf, dyf):
            if not flip:
                tx = (sx_ - dx + scx) % 512
                ty = (sy_ - dy + scy) % 256
                return m[ty][:, tx]
            ex = (288 - 512 - (dxf - scx)) % 512
            ey = (224 - 256 - (dyf - scy)) % 256
            tx = 511 - (sx_ - ex) % 512
            ty = 255 - (sy_ - ey) % 256
            return m[ty][:, tx]
        bmp = layer(bgmap, self.scroll[0], self.scroll[2], -20, -16, 288 + 27, -16).copy()
        sr1, sr2, sr3 = mem[0x8780:0x8800], mem[0x9780:0x9800], mem[0xa780:0xa800]
        lut = g.sprite_lut
        for offs in range(0, 0x80, 2):
            if sr3[offs + 1] & 0x40:
                continue
            flags = sr2[offs]
            code = ((sr3[offs] & 0x3f) + 0x100) if flags & 0x80 else sr3[offs]
            color = (sr3[offs + 1] & 0x7f) % 64
            flipx, flipy = bool(flags & 4), bool(flags & 8)
            sx = sr1[offs + 1] - 40 + 0x100 * (sr2[offs + 1] & 1)
            sy = 28 * 8 - sr1[offs] - 1
            if flip:
                flipx, flipy = not flipx, not flipy
            lt = np.array(lut[color * 8:color * 8 + 8], np.uint8)

            def put(c, x, y):
                tile = g.sprites[c % len(g.sprites)]
                if flipx: tile = tile[:, ::-1]
                if flipy: tile = tile[::-1, :]
                pix = lt[tile.astype(np.int32)]
                for yy in range(16):
                    ry = y + yy
                    if 0 <= ry < 224:
                        row = pix[yy]
                        for xx in range(16):
                            rx = x + xx
                            if 0 <= rx < 288 and row[xx] != 0x80:
                                bmp[ry, rx] = row[xx]
            if flags & 2:
                if flags & 1:
                    code &= ~3
                    put(code + 3, sx if flipx else sx + 16, sy - 16 if flipy else sy)
                    put(code + 1, sx if flipx else sx + 16, sy if flipy else sy - 16)
                code &= ~2
                put(code + 2, sx + 16 if flipx else sx, sy - 16 if flipy else sy)
                put(code, sx + 16 if flipx else sx, sy if flipy else sy - 16)
            elif flags & 1:
                code &= ~1
                put(code, sx + 16 if flipx else sx, sy - 16 if flipy else sy)
                put(code + 1, sx if flipx else sx + 16, sy - 16 if flipy else sy)
            else:
                put(code, sx, sy)
        fg = layer(fgmap, self.scroll[1], self.scroll[3], -32, -18, 288 + 32, -10)
        sel = fg != 0x80
        bmp[sel] = fg[sel]
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
    out = sys.argv[2] if len(sys.argv) > 2 else "xevious.png"
    m = Xevious()
    t0 = time.time()
    for f in range(frames):
        m.run_frame()
        if f % 60 == 0:
            print("frame", f, "pc", "%04X %04X %04X" % tuple(c.pc for c in m.cpus), "held", m.held[1:], "latch", m.latch,
                  "scroll", m.scroll, flush=True)
    print("%.1f s, %.1f frames/s" % (time.time() - t0, frames / (time.time() - t0)))
    print("50xx log (first 20):", m.n50.log[:20])
    print("unknown writes:", m.io_log[:20])
    save_png(m.render_rgb(), out)
    print("wrote", out)
