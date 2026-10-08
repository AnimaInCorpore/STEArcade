"""Galaga (Namco, rev. B) arcade machine model around the reference Z80.

Three Z80s at 3.072 MHz with a shared memory map (MAME galaga.cpp):
  0000-3FFF ROM (own per CPU: 16 KB main, 4 KB sub, 4 KB sound)
  6800-6807 DIP switches (read, one bit of each switch bank per address)
  6800-681F sound registers (WSG, ignored here), 6820-6827 latch (IRQ1/IRQ2 enable,
  CPU3 NMI enable, reset of CPU2/3 and the custom chips), 6830 watchdog
  7000-70FF / 7100 Namco 06XX data / control (51XX: coins, credits, joysticks; 54XX noise)
  8000-87FF video RAM (36x28 tiles, code + colour), 8800-8BFF, 9000-93FF, 9800-9BFF RAM
  (the sprite table lives at the end of each: code/colour, x/y, flags)
  A000-A007 video latch (starfield control, flip)
Interrupts: IRQ to CPU1 and CPU2 at the vertical blank (scanline 224) if enabled, NMI
to CPU3 at scanlines 64 and 192 if enabled, NMI to CPU1 from the 06XX clock while a
transfer is running.  The 51XX is simulated (the MCU program is not in the ROM set).

Provides scripted inputs and a reference renderer (tiles + sprites, rotated 90) without
the starfield for now.
"""
import os
import sys
import numpy as np

sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from z80 import Z80

from paths import EXTRACTED
ROMDIR = str(EXTRACTED / "galaga")

CYCLES_PER_LINE = 192           # 3.072 MHz / (6.144 MHz / 384)
LINES = 264
CYCLES_PER_FRAME = CYCLES_PER_LINE * LINES   # 50688, 60.606 Hz
VBLANK_LINE = 224
CPU3_NMI_LINES = (64, 192)
CLOCK_06XX = 3072000 // 64     # 48 kHz


def load(name):
    with open(os.path.join(ROMDIR, name), "rb") as f:
        return f.read()


def decode_gfx(data, width, height, planes, xoffs, yoffs, size):
    """MAME gfx layout decode: bit offsets count from the MSB of each byte, the first plane is the
    most significant bit of the pixel (until 2026-10-08 it was the least: pens 1 and 2 swapped)."""
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
                    v |= bit << (len(planes) - 1 - p)     # the first plane is the most significant (MAME)
                out[i, y, x] = v
    return out


class Gfx:
    """Decoded characters, sprites, palette and colour lookup PROMs."""

    def __init__(self):
        step4 = lambda s: [s, s + 1, s + 2, s + 3]
        step8 = lambda s, d: [s + d * i for i in range(8)]
        self.chars = decode_gfx(load("gg1_9.4l"), 8, 8, (0, 4), step4(64) + step4(0), step8(0, 8), 16)
        self.sprites = decode_gfx(load("gg1_11.4d") + load("gg1_10.4f"), 16, 16, (0, 4),
                                  step4(0) + step4(64) + step4(128) + step4(192),
                                  step8(0, 8) + step8(256, 8), 64)
        prom = load("prom-5.5n")
        self.palette = []
        for i in range(32):
            c = prom[i]
            r = 0x21 * (c & 1) + 0x47 * ((c >> 1) & 1) + 0x97 * ((c >> 2) & 1)
            g = 0x21 * ((c >> 3) & 1) + 0x47 * ((c >> 4) & 1) + 0x97 * ((c >> 5) & 1)
            # blue has two resistors only; MAME's colours reach 255 (0x51 + 0xAE), not 0xDE (checked against a
            # MAME snapshot, ref/mame_cmp_galaga.py; the old source of galaga_v.cpp says 0x47 + 0x97)
            b = 0x51 * ((c >> 6) & 1) + 0xAE * ((c >> 7) & 1)
            self.palette.append((r, g, b))
        for i in range(64):              # the stars
            m = (0x00, 0x47, 0x97, 0xde)
            mb = (0x00, 0x51, 0xAE, 0xFF)
            self.palette.append((m[i & 3], m[(i >> 2) & 3], mb[(i >> 4) & 3]))
        self.char_lut = [(v & 0x0f) | 0x10 for v in load("prom-4.2n")]     # colour*4+pen -> palette
        self.sprite_lut = [v & 0x0f for v in load("prom-3.1c")]
        self.rgb = np.array(self.palette + [(0, 0, 0)], np.uint8)        # index 96: black fill


class Starfield:
    """The 05XX: a 16-bit LFSR run over a 256 x 256 field per frame (plus a few steps for
    the scrolling), a star wherever 8 of its bits match (MAME starfield_05xx.cpp).  The
    sequence has period 65535 and is computed once; a frame is a window into it."""
    SEED = 0x7FFF
    PRE = [22, 23, 22, 23, 19, 20, 20, 22]
    POST = [10, 10, 12, 12, 9, 9, 10, 9]
    SPEED_X = [0, 1, 2, 3, -4, -3, -2, -1]
    seq = None
    hits = None

    def __init__(self):
        if Starfield.seq is None:
            seq = []
            l = self.SEED
            for i in range(65535):
                seq.append(l)
                bit = (l ^ (l >> 3) ^ (l >> 5) ^ (l >> 10)) & 1
                l = (l >> 1) | (bit << 15)
            assert l == self.SEED
            Starfield.seq = seq
            hits = []
            for i, l in enumerate(seq):
                if (l & 0xFA14) == 0x7800:
                    star_set = ((l >> 10) & 1) << 1 | ((l >> 8) & 1)
                    color = ((l >> 5) & 7) | ((l << 3) & 0x18) | ((l << 2) & 0x20)
                    hits.append((i, star_set, (~color) & 0x3f))
            Starfield.hits = hits
        self.enable = 0
        self.idx = 0
        self.pre = self.PRE[0] * 256
        self.post = self.POST[0] * 256
        self.set_a = self.set_b = 0
        self.stars = []                 # (x, y, colour) of the frame drawn last

    def set_params(self, speed_x, set_a, set_b, enable):
        self.pre = self.PRE[0] * 256 + self.SPEED_X[speed_x]
        self.post = self.POST[0] * 256
        self.set_a, self.set_b = set_a, set_b
        if not enable:
            self.idx = 0
        self.enable = 1 if enable else 0

    def draw(self):
        """One frame: advance the LFSR and collect the stars (MAME draws then scrolls)."""
        if not self.enable:
            self.stars = []
            return
        import bisect
        n = 65535
        s = (self.idx + self.pre) % n
        stars = []
        window = 224 * 256
        lo = bisect.bisect_left(self.hits, (s, -1, -1))
        i = lo
        while True:
            if i >= len(self.hits):
                i = 0
            h, star_set, color = self.hits[i]
            d = (h - s) % n
            if d >= window:
                break
            if star_set in (self.set_a, self.set_b):
                stars.append((d % 256, d // 256, color))
            i += 1
            if i == lo:
                break
        self.stars = stars
        self.idx = (s + window + self.post) % n


class Namco51:
    """The 51XX I/O MCU as the old MAME simulation did it: coins and credits, start
    buttons, joysticks with the fire button edge."""

    def __init__(self, machine):
        self.m = machine
        self.reset()

    def reset(self):
        self.mode = 0            # 0 switch mode, 1 credit mode, 2 in game
        self.in_count = 0
        self.coincred_mode = 0
        self.coins_per_cred = [1, 1]
        self.creds_per_coin = [1, 1]
        self.coins = [0, 0]
        self.credits = 0
        self.lastcoins = 0
        self.lastbuttons = 0
        self.remap_joy = 0
        self.log = []

    def write(self, data):
        data &= 7
        self.log.append(("w", data))
        if self.coincred_mode:
            k = self.coincred_mode
            self.coincred_mode -= 1
            if k == 4: self.coins_per_cred[0] = data
            elif k == 3: self.creds_per_coin[0] = data
            elif k == 2: self.coins_per_cred[1] = data
            elif k == 1: self.creds_per_coin[1] = data
            return
        if data == 1:
            self.coincred_mode = 4
        elif data == 2:
            self.mode = 1
            self.in_count = 0
        elif data == 3:
            self.remap_joy = 0
        elif data == 4:
            self.remap_joy = 1
        elif data == 5:
            self.mode = 0
            self.in_count = 0

    def read(self):
        m = self.m
        p0, p1 = m.in0 & 0x0f, (m.in0 >> 4) & 0x0f       # joysticks
        p2, p3 = m.in1 & 0x0f, (m.in1 >> 4) & 0x0f       # fire/start, coins/service
        k = self.in_count % 3
        self.in_count += 1
        if self.mode == 0:
            if k == 0: return p0 | (p1 << 4)
            if k == 1: return p2 | (p3 << 4)
            return 0
        if k == 0:
            inp = ~(p2 | (p3 << 4)) & 0xff
            toggle = inp ^ self.lastcoins
            self.lastcoins = inp
            if self.coins_per_cred[0] > 0:
                for i, bit in enumerate((0x10, 0x20)):
                    if toggle & inp & bit:
                        self.coins[i] += 1
                        if self.coins[i] >= self.coins_per_cred[i]:
                            self.credits += self.creds_per_coin[i]
                            self.coins[i] -= self.coins_per_cred[i]
                if toggle & inp & 0x40:
                    self.credits += 1
            else:
                self.credits = 100
            if self.mode == 1:
                if toggle & inp & 0x04:
                    if self.credits >= 1:
                        self.credits -= 1
                        self.mode = 2
                elif toggle & inp & 0x08:
                    if self.credits >= 2:
                        self.credits -= 2
                        self.mode = 2
            if self.credits > 99:
                self.credits = 99
            return (self.credits // 10) * 16 + self.credits % 10
        if k == 1:
            joy = p0
            inp = ~p2 & 0xff
            toggle = inp ^ self.lastbuttons
            self.lastbuttons = (self.lastbuttons & 2) | (inp & 1)
            joy |= ((toggle & inp & 0x01) ^ 1) << 4
            joy |= ((inp & 0x01) ^ 1) << 5
            return joy
        joy = p1
        inp = ~p2 & 0xff
        toggle = inp ^ self.lastbuttons
        self.lastbuttons = (self.lastbuttons & 1) | (inp & 2)
        joy |= (((toggle & inp & 0x02) >> 1) ^ 1) << 4
        joy |= (((inp & 0x02) >> 1) ^ 1) << 5
        return joy


def skip_ram_test(rom):
    """The main CPU's boot RAM test (video RAM x10 passes at $3382, the rest of the RAM at
    $3466, ~700 frames) patched out: the first jumps to the SP setup after the test, the
    second test call becomes nops.  The ROM checksum and the handshake stay (the last byte of the bank is the checksum byte)."""
    orig = rom
    rom = bytearray(rom)
    rom[0x3382:0x3385] = bytes([0xC3, 0x66, 0x34])          # jp $3466
    rom[0x3469:0x346F] = bytes(6)                           # ld de,$8000 / call $3489
    rom[0x3FFF] = (rom[0x3FFF] + sum(orig[0x3000:0x4000]) - sum(rom[0x3000:0x4000])) & 0xFF   # keeps the bank's checksum 0
    return bytes(rom)


class Galaga:
    def __init__(self, skip_tests=False):
        self.roms = [load("gg1_1b.3p") + load("gg1_2b.3m") + load("gg1_3.2m") + load("gg1_4b.2l"),
                     load("gg1_5b.3f"), load("gg1_7b.2c")]
        if skip_tests:
            self.roms[0] = skip_ram_test(self.roms[0])
        self.ram = bytearray(0x2000)          # 8000-9FFF (the gaps are not mapped)
        self.sound = bytearray(0x20)
        self.latch = [0] * 8                  # 6820-6827
        self.vlatch = [0] * 8                 # A000-A007
        self.in0 = 0xff
        self.in1 = 0xff
        self.dswa = 0xf7                      # easy, demo sounds on, upright
        self.dswb = 0x97                      # 1 coin 1 credit, 20K 70K 70K, 3 lives
        self.n51 = Namco51(self)
        self.stars = Starfield()
        self.ctrl06 = 0
        self.nmi06_next = None
        self.nmi06_period = 0
        self.cpus = [Z80(self.reader(i), self.writer(i)) for i in range(3)]
        for c in self.cpus:
            c.afmask = 0xC1
        self.rnd_state = 0x1234
        self.held = [False, True, True]       # CPU2 and CPU3 start in reset
        self.irq_pending = [False, False]
        self.port_mode = False                # the STE runtime's schedule (run_frame_port)
        self.in_nmi06 = False
        self.booted = [True, False, False]    # CPU2/3 reached their idle loops (port mode)
        self.handler_runs = [0, 0, 0]
        self.frame = 0
        self.gfx = None
        self.io_log = []
        self.watch_hook = None

    # ---- bus -----------------------------------------------------------
    def reader(self, n):
        rom = self.roms[n]
        ram = self.ram

        def rd8(a):
            if a < 0x4000:
                return rom[a] if a < len(rom) else 0
            if 0x8000 <= a < 0xa000:
                return ram[a - 0x8000]
            if 0x6800 <= a <= 0x6807:
                b = a & 7
                return ((self.dswb >> b) & 1) | (((self.dswa >> b) & 1) << 1)
            if 0x7000 <= a <= 0x70ff:
                return self.data06_r()
            if a == 0x7100:
                return self.ctrl06
            return 0xff
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
            # CPU2, CPU3 (and the custom chips) held in reset while 0
            if v and self.held[1]:
                self.cpus[1].reset()
                self.cpus[2].reset()
                self.n51.reset()
            self.held[1] = self.held[2] = not v

    # 06XX
    def data06_r(self):
        if not (self.ctrl06 & 0x10):
            return 0
        v = 0xff
        if self.ctrl06 & 1:
            v &= self.n51.read()
        return v

    def data06_w(self, v):
        if self.ctrl06 & 0x10:
            return
        if self.ctrl06 & 1:
            self.n51.write(v)
        # bit 3: 54XX (noise sound), ignored

    def ctrl06_w(self, v):
        self.ctrl06 = v
        if (v & 0xe0) == 0:
            self.nmi06_next = None
            return
        if self.port_mode:
            # the STE runtime runs the NMI handler right here, as often as the program
            # keeps the transfer going
            if self.in_nmi06:
                return
            self.in_nmi06 = True
            cpu = self.cpus[0]
            n = 0
            while self.ctrl06 & 0xe0:
                self.run_handler(cpu, nmi=True)
                n += 1
                if n > 64:
                    raise RuntimeError("06XX transfer does not end")
            self.in_nmi06 = False
            return
        period = (1 << (v >> 5)) * (3072000 // CLOCK_06XX)     # CPU cycles per NMI
        self.nmi06_period = period
        first = period * (2 if v & 0x10 else 1)                # a read suppresses the first pulse
        self.nmi06_next = self.cpus[0].cycles + first

    # ---- running -------------------------------------------------------
    def run_frame(self, slice_cycles=128):
        cpus = self.cpus
        start = cpus[0].cycles
        end = start + CYCLES_PER_FRAME
        events = sorted([(VBLANK_LINE * CYCLES_PER_LINE, "vbl")] +
                        [(l * CYCLES_PER_LINE, "nmi3") for l in CPU3_NMI_LINES])
        ei = 0
        t = start
        while t < end:
            t = min(t + slice_cycles, end)
            while ei < len(events) and start + events[ei][0] < t:
                kind = events[ei][1]
                ei += 1
                if kind == "vbl":
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
                while cpu.cycles < t:
                    if n == 0 and self.nmi06_next is not None and cpu.cycles >= self.nmi06_next:
                        cpu.nmi()
                        self.nmi06_next += self.nmi06_period
                    if n < 2 and self.irq_pending[n] and cpu.iff1:
                        cpu.irq()
                    cpu.step()
        # the starfield of this frame, then the control bits for the next one (as the
        # vertical blank callbacks do it)
        self.stars.draw()
        vl = self.vlatch
        self.stars.set_params(vl[0] | (vl[1] << 1) | (vl[2] << 2), vl[3], vl[4] | 2, vl[5])
        self.frame += 1

    def rnd(self):
        """What the port's z80_rnd gives for `ld a,r`: a 16-bit shift register byte."""
        s = self.rnd_state
        s = (s >> 1) ^ (0xB400 if s & 1 else 0)
        self.rnd_state = s
        return s & 0xFF

    # ---- the STE runtime's schedule ------------------------------------
    IDLE = [0x038D, 0x05B1, 0x00B9]
    # the spin loops of the boot handshake (CPU1 waits for the self-test results of CPU2
    # and CPU3, they wait for CPU1 to clear the flags): a CPU that reaches one gives the
    # other booting CPUs a turn (hooks in the translated code, z80_hook)
    YIELD = [{0x3589, 0x359C}, {0x057F, 0x0596}, {0x008D, 0x00A4}]

    def run_until_yield(self, n):
        """Run cpu n (at a yield point or just released) until it is at a yield point
        again or in its idle loop."""
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

    def run_to_idle(self, n):
        cpu = self.cpus[n]
        idle = self.IDLE[n]
        k = 0
        while cpu.pc != idle:
            cpu.step()
            k += 1
            if k > 20_000_000:
                raise RuntimeError("CPU%d did not reach its idle loop" % (n + 1))

    def run_frame_port(self):
        """One frame as the STE runtime schedules it: CPU1's main thread for the frame, then
        at the vertical blank CPU1's IRQ handler and CPU2's IRQ handler, each to
        completion.  CPU2 and CPU3 run their boot code to the idle loop once they are
        released; CPU3 never runs afterwards.  06XX NMIs are synchronous (ctrl06_w)."""
        self.port_mode = True
        cpu1, cpu2, cpu3 = self.cpus
        cpu1.r_hook = self.rnd
        end = cpu1.cycles + CYCLES_PER_FRAME
        yields = self.YIELD[0]
        while cpu1.cycles < end:
            cpu1.step()
            if cpu1.pc in yields:
                self.boot_turns()
        self.boot_turns()                       # the VBL gives the booting CPUs a turn too
        if self.latch[0] and self.run_handler(cpu1):
            self.handler_runs[0] += 1
        if self.latch[1] and self.booted[1] and self.run_handler(cpu2):
            self.handler_runs[1] += 1
        self.stars.draw()
        vl = self.vlatch
        self.stars.set_params(vl[0] | (vl[1] << 1) | (vl[2] << 2), vl[3], vl[4] | 2, vl[5])
        self.frame += 1

    # ---- rendering -----------------------------------------------------
    def render_raw(self):
        """288 x 224 (x, y) bitmap of palette indices (96 = black)."""
        if self.gfx is None:
            self.gfx = Gfx()
        g = self.gfx
        bmp = np.full((224, 288), 96, np.uint8)
        ram = self.ram
        # stars (x offset 16, only up to x 272)
        for x, y, color in self.stars.stars:
            if x + 16 < 272:
                bmp[y, x + 16] = 32 + color
        # sprites
        s1, s2, s3 = 0x0b80, 0x1380, 0x1b80
        for offs in range(0, 0x80, 2):
            sprite = ram[s1 + offs] & 0x7f
            color = ram[s1 + offs + 1] & 0x3f
            sx = ram[s2 + offs + 1] - 40 + 0x100 * (ram[s3 + offs + 1] & 3)
            sy = 256 - ram[s2 + offs] + 1
            flags = ram[s3 + offs]
            flipx, flipy = flags & 1, (flags >> 1) & 1
            sizex, sizey = (flags >> 2) & 1, (flags >> 3) & 1
            sy -= 16 * sizey
            sy = (sy & 0xff) - 32
            lut = g.sprite_lut[color * 4:color * 4 + 4]
            for y in range(sizey + 1):
                for x in range(sizex + 1):
                    code = sprite + [[0, 1], [2, 3]][y ^ (sizey * flipy)][x ^ (sizex * flipx)]
                    tile = g.sprites[code & 0x7f]
                    if flipx: tile = tile[:, ::-1]
                    if flipy: tile = tile[::-1, :]
                    px, py = sx + 16 * x, sy + 16 * y
                    for yy in range(16):
                        ry = py + yy
                        if not 0 <= ry < 224:
                            continue
                        for xx in range(16):
                            rx = px + xx
                            if not 0 <= rx < 288:
                                continue
                            p = lut[tile[yy, xx]]
                            if p != 0x0f:
                                bmp[ry, rx] = p
        # characters on top (pens that look up 0x1f are transparent)
        for row in range(28):
            for col in range(36):
                r, c = row + 2, col - 2
                if c & 0x20:
                    idx = r + ((c & 0x1f) << 5)
                else:
                    idx = c + (r << 5)
                code = ram[idx] & 0x7f
                color = ram[idx + 0x400] & 0x3f
                lut = np.array(g.char_lut[color * 4:color * 4 + 4], np.uint8)
                pix = lut[g.chars[code]]
                blk = bmp[row * 8:row * 8 + 8, col * 8:col * 8 + 8]
                mask = pix != 0x1f
                blk[mask] = pix[mask]
        return bmp

    def render_rgb(self):
        bmp = self.render_raw()
        rgb = self.gfx.rgb[bmp]          # [y][x][3], 224 x 288
        disp = rgb.transpose(1, 0, 2)[:, ::-1]   # ROT90: 288 tall, 224 wide
        return disp


def save_png(arr, path, scale=2):
    from PIL import Image
    im = Image.fromarray(arr)
    if scale != 1:
        im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    im.save(path)


if __name__ == "__main__":
    import time
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    out = sys.argv[2] if len(sys.argv) > 2 else "galaga.png"
    m = Galaga()
    t0 = time.time()
    for f in range(frames):
        m.run_frame()
        if f % 60 == 0:
            print("frame", f, "pc", "%04X %04X %04X" % tuple(c.pc for c in m.cpus),
                  "held", m.held[1:], "latch", m.latch, "vlatch", m.vlatch, "51xx mode", m.n51.mode)
    print("%.1f s, %.1f frames/s" % (time.time() - t0, frames / (time.time() - t0)))
    print("51xx log (first 40):", m.n51.log[:40])
    print("unknown writes:", m.io_log[:20])
    save_png(m.render_rgb(), out)
    print("wrote", out)
