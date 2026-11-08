"""Donkey Kong 3 (Nintendo, 1983; MAME nintendo/dkong.cpp `dkong3`, TKG-04 video hardware) arcade machine model around the reference Z80.

One Z80 at 4 MHz (8 MHz / 2); the screen is 384 x 264 pixel clocks at 6.144 MHz: 250 CPU cycles a line, 66000 a frame,
60.606 Hz.  Visible area 256 x 224 (raw lines 16..239), shown turned (ROT90): 224 wide, 256 tall.  Memory map (dkong3_map):
  0000-5FFF ROM (dk3c.7b/7c/7d), 8000-9FFF ROM (dk3c.7e), 6000-6FFF RAM, 7000-73FF sprite RAM (256 x 4: y, code | flip y,
  colour | bank | flip x, x), 7400-77FF video RAM (32 x 32 tile codes)
  7C00 IN0 (read) / sound latch 1 (write), 7C80 IN1 / latch 2, 7D00 DSW0 / latch 3, 7D80 DSW1 (read) / the two sound
  CPUs' reset (write, bit 0), 7E80 coin counters, 7E81 gfx bank (inverted), 7E82 flip, 7E83 sprite bank, 7E84 NMI mask,
  7E85 DMA ready, 7E86-7E87 palette bank (bits 0, 1)
  I/O port 00: the Z80 DMA (the game copies $6900 -> $7000 while 7E85 is high)
Interrupt: NMI at the start of the vertical blank (line 240) while 7E84 bit 0 is set.  The two sound CPUs (N2A03s) take the
vblank NMI too; their commands are the three latches.

Reference renderer: a 32 x 32 tile map (tile code + 256 * gfx bank, colour from the PROM per 4 rows of a column + 16 * the
palette bank, 4 pens a colour), 128 sprites of 16 x 16 (the bank selects 128 of the 256 entries; MAME draw_sprites),
256 pens from the resistor network (dkong3_pens.py).
"""
import os
import sys
import numpy as np

sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from z80 import Z80

from paths import EXTRACTED
ROMDIR = str(EXTRACTED / "dkong3")

CYCLES_PER_LINE = 250           # 4 MHz / (6.144 MHz / 384)
LINES = 264
CYCLES_PER_FRAME = CYCLES_PER_LINE * LINES   # 66000, 60.606 Hz
VBLANK_LINE = 240

# Inputs (active high).  IN0: right 01, left 02, up 04, down 08, jump/fire 10, start1 20, start2 40, service 80.  IN1: the
# cocktail player's controls, coin1 20, coin2 40.
RIGHT, LEFT, UP, DOWN, FIRE = 0x01, 0x02, 0x04, 0x08, 0x10
START1, START2, SERVICE = 0x20, 0x40, 0x80
COIN1, COIN2 = 0x20, 0x40
DSW0_DEFAULT = 0x00             # 1 coin 1 credit, upright
DSW1_DEFAULT = 0x00             # 3 lives, bonus at 30000 and 30000, difficulty 1


def load(name):
    with open(os.path.join(ROMDIR, name), "rb") as f:
        return f.read()


class Gfx:
    """Decoded characters (512, two banks of 256) and sprites (256)."""

    def __init__(self):
        g1 = load("dk3v.3n") + load("dk3v.3p")
        # tile n, row y: first half byte = low plane, second half = high plane (gfx_8x8x2_planar)
        self.chars = np.zeros((512, 8, 8), np.uint8)
        for n in range(512):
            for y in range(8):
                lo, hi = g1[n * 8 + y], g1[0x1000 + n * 8 + y]
                for x in range(8):
                    self.chars[n, y, x] = (((hi >> (7 - x)) & 1) << 1) | ((lo >> (7 - x)) & 1)
        g2 = b"".join(load(n) for n in ("dk3v.7c", "dk3v.7d", "dk3v.7e", "dk3v.7f"))
        # sprite n: the left half's rows at n * 16 + y, the right half 0x1000 further, the high plane 0x2000 further
        self.sprites = np.zeros((256, 16, 16), np.uint8)
        for n in range(256):
            for y in range(16):
                for half in range(2):
                    off = n * 16 + y + half * 0x1000
                    hi, lo = g2[0x2000 + off], g2[off]
                    for x in range(8):
                        self.sprites[n, y, half * 8 + x] = (((hi >> (7 - x)) & 1) << 1) | ((lo >> (7 - x)) & 1)
        self.colcodes = load("dkc1-v.2n")      # per column and 4 rows: the tile colour code (low nibble)
        self.pens = None            # filled by render_rgb (MAME's palette dump, dkong3_pens.py)


class Z80DMA:
    """The part of the Z80 DMA chip the game uses (MAME z80dma.cpp): WR0..WR6 as the game programs them (transfer port
    A -> port B, memory to memory, addresses incrementing, continuous mode), LOAD, ENABLE, and the READY input."""

    def __init__(self, rd, wr):
        self.rd, self.wr = rd, wr
        self.follow = []                     # (register, ...) bytes still to come
        self.wr0 = self.wr1 = self.wr2 = self.wr4 = self.wr5 = 0
        self.a_addr = self.b_addr = self.blocklen = 0
        self.cur_a = self.cur_b = self.count = 0
        self.enabled = False
        self.rdy = 0
        self.stolen = 0                      # CPU cycles taken by the transfers since the last look
        self.transfers = []

    def write(self, v):
        if self.follow:
            reg = self.follow.pop(0)
            if reg == "AL": self.a_addr = (self.a_addr & 0xFF00) | v
            elif reg == "AH": self.a_addr = (self.a_addr & 0x00FF) | (v << 8)
            elif reg == "NL": self.blocklen = (self.blocklen & 0xFF00) | v
            elif reg == "NH": self.blocklen = (self.blocklen & 0x00FF) | (v << 8)
            elif reg == "BL": self.b_addr = (self.b_addr & 0xFF00) | v
            elif reg == "BH": self.b_addr = (self.b_addr & 0x00FF) | (v << 8)
            return
        if (v & 0x87) == 0x00:               # WR2: port B
            self.wr2 = v
            if v & 0x40: self.follow.append("TB")
        elif (v & 0x87) == 0x04:             # WR1: port A
            self.wr1 = v
            if v & 0x40: self.follow.append("TA")
        elif (v & 0x80) == 0:                # WR0
            self.wr0 = v
            for bit, reg in ((0x08, "AL"), (0x10, "AH"), (0x20, "NL"), (0x40, "NH")):
                if v & bit: self.follow.append(reg)
        elif (v & 0x83) == 0x80:             # WR3
            if v & 0x08: self.follow.append("MASK")
            if v & 0x10: self.follow.append("MATCH")
        elif (v & 0x83) == 0x81:             # WR4
            self.wr4 = v
            for bit, reg in ((0x04, "BL"), (0x08, "BH"), (0x10, "INT")):
                if v & bit: self.follow.append(reg)
        elif (v & 0xC7) == 0x82:             # WR5
            self.wr5 = v
        elif (v & 0x83) == 0x83:             # WR6
            if v == 0xCF:                    # LOAD
                self.cur_a, self.cur_b, self.count = self.a_addr, self.b_addr, 0
            elif v == 0x87:                  # ENABLE DMA
                self.enabled = True
            elif v == 0x83:                  # DISABLE DMA
                self.enabled = False
            elif v == 0xC3:                  # RESET
                self.enabled = False

    def set_rdy(self, v):
        self.rdy = v
        if v and self.enabled:
            self.run()

    def run(self):
        """A -> B, blocklen + 1 bytes (MAME: the last byte is the one with byte counter == blocklen), 6 clocks a byte."""
        if not (self.wr0 & 0x03) == 1:
            return
        a_src = bool(self.wr0 & 0x04)
        a_inc = 1 if self.wr1 & 0x10 else -1
        b_inc = 1 if self.wr2 & 0x10 else -1
        n = self.blocklen + 1
        src, dst = (self.cur_a, self.cur_b) if a_src else (self.cur_b, self.cur_a)
        s_inc, d_inc = (a_inc, b_inc) if a_src else (b_inc, a_inc)
        for _ in range(n):
            self.wr(dst & 0xFFFF, self.rd(src & 0xFFFF))
            src += s_inc
            dst += d_inc
        self.cur_a += a_inc * n
        self.cur_b += b_inc * n
        self.transfers.append((self.a_addr, self.b_addr, n))
        self.stolen += 6 * n
        self.enabled = False                 # the chip stops at the end of the block (no auto restart)


class DK3:
    def __init__(self, dsw0=DSW0_DEFAULT, dsw1=DSW1_DEFAULT):
        self.rom = load("cpu.rom")
        self.rom_hi = load("dk3c.7e")         # $8000-$9FFF
        self.ram = bytearray(0x1800)          # 6000-77FF: RAM, sprite RAM (7000-73FF), video RAM (7400-77FF)
        self.in0 = 0
        self.in1 = 0
        self.dsw0 = dsw0
        self.dsw1 = dsw1
        self.latch = {a: 0 for a in range(0x7E80, 0x7E88)}        # the last value written to each of 7E80-7E87 (bit 0)
        self.gfx_bank = 0                     # (7E81 inverted)
        self.flip = 0
        self.sprite_bank = 0
        self.palette_bank = 0
        self.nmi_mask = 0
        self.sound_cpu_run = 0
        self.snd = {0x7C00: 0, 0x7C80: 0, 0x7D00: 0}      # the latches' last values
        self.sound_log = []                   # (frame, address, value) of the writes to the sound latches (7C00, 7C80, 7D00)
        self.io_writes = {}
        self.dma = Z80DMA(self.rd8, self.wr8)
        self.cpu = Z80(self.rd8, self.wr8, io_in=self.io_in, io_out=self.io_out)
        self.cpu.afmask = 0xC1                # as the translation keeps them (S Z C), like the other Z80 ports
        self.rnd_state = 0xACE1
        self.cpu.r_hook = self.rnd            # `ld a,r` reads the port's random byte (src/natives.s z80_rnd), not the refresh register
        self.frame = 0
        self.gfx = None

    def rnd(self):
        """What the port's z80_rnd gives for `ld a,r`: a 16-bit shift register byte."""
        s = self.rnd_state
        s = (s >> 1) ^ (0xB400 if s & 1 else 0)
        self.rnd_state = s
        return s & 0xFF

    # ---- bus -----------------------------------------------------------
    def rd8(self, a):
        if a < 0x6000:
            return self.rom[a]
        if a < 0x7800:
            return self.ram[a - 0x6000]
        if 0x8000 <= a < 0xA000:
            return self.rom_hi[a - 0x8000]
        if a == 0x7C00: return self.in0
        if a == 0x7C80: return self.in1
        if a == 0x7D00: return self.dsw0
        if a == 0x7D80: return self.dsw1
        return 0xFF

    def wr8(self, a, v):
        if a < 0x6000:
            return
        if a < 0x7800:
            self.ram[a - 0x6000] = v
            return
        if a >= 0x8000:
            return
        self.io_writes[a] = self.io_writes.get(a, 0) + 1
        if a in (0x7C00, 0x7C80, 0x7D00):
            self.snd[a] = v
            self.sound_log.append((self.frame, a, v))
        elif a == 0x7D80:
            self.sound_cpu_run = v & 1
            self.sound_log.append((self.frame, a, v))
        elif 0x7E80 <= a <= 0x7E87:
            self.latch[a] = v & 1
            if a == 0x7E81: self.gfx_bank = ~v & 1
            elif a == 0x7E82: self.flip = v & 1
            elif a == 0x7E83: self.sprite_bank = v & 1
            elif a == 0x7E84:
                self.nmi_mask = v & 1
            elif a == 0x7E85:
                self.dma.set_rdy(v & 1)
            elif a == 0x7E86: self.palette_bank = (self.palette_bank & ~1) | (v & 1)
            elif a == 0x7E87: self.palette_bank = (self.palette_bank & ~2) | ((v & 1) << 1)

    def io_in(self, port):
        return 0xFF

    def io_out(self, port, v):
        if (port & 0xFF) == 0:
            self.dma.write(v)

    # ---- running -------------------------------------------------------
    def run_frame(self):
        cpu = self.cpu
        target = cpu.cycles + CYCLES_PER_FRAME
        if self.nmi_mask:
            cpu.nmi()
        while cpu.cycles < target:
            cpu.step()
            if self.dma.stolen:
                cpu.cycles += self.dma.stolen
                self.dma.stolen = 0
        self.frame += 1

    def set_inputs(self, p1=0, p2=0, coin=False, start1=False, start2=False, service=False):
        self.in0 = (p1 & 0x1F) | (START1 if start1 else 0) | (START2 if start2 else 0) | (SERVICE if service else 0)
        self.in1 = (p2 & 0x1F) | (COIN1 if coin else 0)

    # ---- rendering -----------------------------------------------------
    def render_raw(self, layers=False, wrap=True):
        """256 x 256 (y, x) bitmap of pens as MAME's screen bitmap (the visible lines are 16..239), before the flip is
        applied to the display (the flip is applied here as MAME does: tiles flipped, sprites by their formula).  wrap: MAME's
        wrap-around of sprites across the bitmap's 256-pixel columns (the STE port does not draw the wrapped part)."""
        if self.gfx is None:
            self.gfx = Gfx()
        g = self.gfx
        bmp = np.zeros((256, 256), np.uint8)
        vram = self.ram[0x1400:0x1800]
        bank = 256 * self.gfx_bank
        pb = 16 * self.palette_bank
        for idx in range(1024):
            col, row = idx & 31, idx >> 5
            code = vram[idx]
            color = (g.colcodes[col + 32 * (row >> 2)] & 15) + pb
            bmp[row * 8:row * 8 + 8, col * 8:col * 8 + 8] = color * 4 + g.chars[code + bank]
        if self.flip:
            bmp = bmp[::-1, ::-1].copy()
        issp = np.zeros((256, 256), bool)
        base = 0x1000 + (self.sprite_bank << 9)
        spr = self.ram
        for i in range(0, 0x200, 4):
            y0 = spr[base + i]
            b1 = spr[base + i + 1]
            b2 = spr[base + i + 2]
            code = (b1 & 0x7F) + ((b2 & 0x40) << 1)
            color = (b2 & 0x0F) + pb
            flipx = b2 & 0x80
            flipy = b1 & 0x80
            x = (spr[base + i + 3] + 0xF7 + 1) & 0xFF
            if self.flip:
                x = (x ^ 0xFF) - 15
                flipx = not flipx
                flipy = not flipy        # (MAME's line buffer: with the flip row r of the sprite is on line y0 + 8 - r, so the rows run upward)
            s = g.sprites[code]
            if flipx: s = s[:, ::-1]
            if flipy: s = s[::-1, :]
            # MAME: the sprite's y is the line of its first row; the unflipped screen shows it at 247 - y0 (see games/dkong)
            # (flipped: MAME's formula worked out, equal to MAME's picture in frames 700 and 1500)
            top = ((247 - y0) & 0xFF if not self.flip else (y0 - 7) & 0xFF)
            for yy in range(16):
                ry = (top + yy) & 0xFF
                if not 16 <= ry < 240:
                    continue
                for xx in range(16):
                    p = s[yy, xx]
                    if p:
                        rx = (x + xx) & 0xFF if wrap else x + xx
                        if not 0 <= rx < 256:
                            continue
                        bmp[ry, rx] = color * 4 + p
                        issp[ry, rx] = True
        return (bmp, issp) if layers else bmp

    def render_rgb(self):
        from dkong3_pens import PENS
        bmp = self.render_raw()
        pens = np.array([((c >> 16) & 255, (c >> 8) & 255, c & 255) for c in PENS], np.uint8)
        return pens[bmp][16:240].transpose(1, 0, 2)[::-1]      # 256 x 224: [255 - x][y - 16]


def save_png(arr, path, scale=2):
    from PIL import Image
    im = Image.fromarray(arr)
    if scale != 1:
        im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    im.save(path)
