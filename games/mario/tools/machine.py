"""Mario Bros. (Nintendo, 1983; MAME nintendo/mario.cpp, US revision E) arcade machine model around the reference Z80.

One Z80 at 4 MHz (8 MHz / 2); the screen is 384 x 264 pixel clocks at 6 MHz: 256 CPU cycles a line, 67584 a frame,
59.185 Hz.  Visible area 256 x 224 (lines 16..239), horizontal (ROT0).  Memory map (mario_map):
  0000-5FFF ROM (tma1-c-7f/7e/7d), F000-FFFF ROM (7c)
  6000-67FF RAM, 6800-6FFF RAM (battery backed in the driver, cleared at power-on), 7000-73FF sprite RAM (256 x 4:
  y, attribute, code, x), 7400-77FF video RAM (32 x 32 tile codes)
  7C00 IN0 (read) / Mario's walk sample (write), 7C80 IN1 (read) / Luigi's walk sample (write), 7D00 scroll (write),
  7E00 sound latch (write), 7E80-7E87 LS259 latch (write, D0): 0 gfx bank, 1 -, 2 flip, 3 palette bank, 4 NMI enable,
  5 DMA ready, 6 coin counter 2, 7 coin counter 1;  7F00-7F07 sample triggers (write), 7F80 DSW (read)
  I/O port 00: the Z80 DMA (the game copies $6900 -> $7000, $180 + 1 bytes, while latch bit 5 is high)
Interrupt: NMI at the start of the vertical blank (line 240) while latch bit 4 is set.

Reference renderer: a 32 x 32 tile map scrolled in y (register + 17), tiles 8 x 8, 2 bits, colour 8 + (code >> 5) +
16 * palette bank, 8 pens a colour; 256 sprites of 16 x 16, 3 bits, pen 0 transparent (MAME draw_sprites).
"""
import os
import sys
import numpy as np

sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from z80 import Z80

from paths import EXTRACTED
ROMDIR = str(EXTRACTED / "mario")

CYCLES_PER_LINE = 256           # 4 MHz / (6 MHz / 384)
LINES = 264
CYCLES_PER_FRAME = CYCLES_PER_LINE * LINES   # 67584, 59.185 Hz
VBLANK_LINE = 240

# Inputs (active high).  IN0: right 01, left 02, jump 10, start1 20, start2 40, service 80.  IN1: player 2 as IN0's
# 01 02 10, coin1 20, coin2 40.
RIGHT, LEFT, JUMP = 0x01, 0x02, 0x10
START1, START2, SERVICE = 0x20, 0x40, 0x80
COIN1, COIN2 = 0x20, 0x40
DSW_DEFAULT = 0x00              # 3 lives, 1 coin 1 credit, bonus at 20000, easy


def load(name):
    with open(os.path.join(ROMDIR, name), "rb") as f:
        return f.read()


def decode_gfx(data, width, height, planes, xoffs, yoffs, size, count):
    """MAME gfx layout decode: bit offsets count from the MSB of each byte, the first plane is the most significant bit
    of the pixel (as games/pacman/tools/machine.py)."""
    n = count
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
    """Decoded characters (512, two banks of 256) and sprites (256)."""

    def __init__(self):
        g1 = load("tma1-v-3f.3f") + load("tma1-v-3j.3j")
        self.chars = decode_gfx(g1, 8, 8, (512 * 8 * 8, 0), list(range(8)), [y * 8 for y in range(8)], 8, 512)
        g2 = b"".join(load(n) for n in ("tma1-v.7m.7m", "tma1-v-7n.7n", "tma1-v-7p.7p", "tma1-v.7s.7s",
                                        "tma1-v-7t.7t", "tma1-v.7u.7u"))
        self.sprites = decode_gfx(g2, 16, 16, (2 * 256 * 16 * 16, 256 * 16 * 16, 0),
                                  list(range(8)) + [256 * 16 * 8 + i for i in range(8)],
                                  [y * 8 for y in range(16)], 16, 256)
        self.pens = None            # filled by pens() (MAME's palette dump, mario_pens.py)


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


class Mario:
    def __init__(self, dsw=DSW_DEFAULT, frame_line=VBLANK_LINE):
        """frame_line: the screen line a frame starts at.  240, the start of the vertical blank, is MAME's phase: the
        frame ends where MAME draws the screen."""
        self.frame_line = frame_line
        self.rom = load("cpu.rom")
        self.rom_hi = load("tma1-c-7c_e-3.7c")
        self.ram = bytearray(0x1800)          # 6000-77FF: RAM, sprite RAM (7000-73FF), video RAM (7400-77FF)
        self.in0 = 0
        self.in1 = 0
        self.dsw = dsw
        self.latch = [0] * 8
        self.scroll = 0
        self.sound_latch = 0
        self.sound_log = []                   # (frame, address, value) of the sound writes
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
        if a >= 0xF000:
            return self.rom_hi[a - 0xF000]
        if a == 0x7C00: return self.in0
        if a == 0x7C80: return self.in1
        if a == 0x7F80: return self.dsw
        return 0xFF

    def wr8(self, a, v):
        if a < 0x6000:
            return
        if a < 0x7800:
            self.ram[a - 0x6000] = v
            return
        if a >= 0xF000:
            return
        self.io_writes[a] = self.io_writes.get(a, 0) + 1
        if a == 0x7D00:
            self.scroll = v
        elif a == 0x7E00:
            self.sound_latch = v
            self.sound_log.append((self.frame, a, v))
        elif 0x7E80 <= a <= 0x7E87:
            n = a - 0x7E80
            self.latch[n] = v & 1
            if n == 5:
                self.dma.set_rdy(v & 1)
        elif a in (0x7C00, 0x7C80) or 0x7F00 <= a <= 0x7F07:
            self.sound_log.append((self.frame, a, v))

    def io_in(self, port):
        return 0xFF

    def io_out(self, port, v):
        if (port & 0xFF) == 0:
            self.dma.write(v)

    # properties of the latch
    gfx_bank = property(lambda s: s.latch[0])
    flip = property(lambda s: s.latch[2])
    palette_bank = property(lambda s: s.latch[3])
    nmi_mask = property(lambda s: s.latch[4])

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
        self.in0 = (p1 & 0x13) | (START1 if start1 else 0) | (START2 if start2 else 0) | (SERVICE if service else 0)
        self.in1 = (p2 & 0x13) | (COIN1 if coin else 0)

    # ---- rendering -----------------------------------------------------
    def render_raw(self, scroll_sign=1, layers=False):
        """256 x 256 (y, x) bitmap of pens as MAME's screen bitmap (the visible lines are 16..239)."""
        if self.gfx is None:
            self.gfx = Gfx()
        g = self.gfx
        bmp = np.zeros((256, 256), np.uint8)
        vram = self.ram[0x1400:0x1800]
        bank = 256 * self.gfx_bank
        pb = 16 * self.palette_bank
        tilemap = np.zeros((256, 256), np.uint8)
        for idx in range(1024):
            col, row = idx & 31, idx >> 5
            code = vram[idx]
            color = 8 + (code >> 5) + pb
            tilemap[row * 8:row * 8 + 8, col * 8:col * 8 + 8] = color * 8 + g.chars[code + bank]
        sy = (self.scroll + 17) & 0xFF
        # tilemap_t: screen y shows map row y - scroll
        rows = (np.arange(256) - scroll_sign * sy) & 0xFF
        bmp[:, :] = tilemap[rows]
        if self.flip:
            bmp = bmp[::-1, ::-1].copy()          # flip_screen_set flips the tilemap; the sprites below are physical
        issp = np.zeros((256, 256), bool)
        spr = self.ram[0x1000:0x1400]
        flip = 0xFF if self.flip else 0
        for offs in range(0, 0x400, 4):
            if not spr[offs]:
                continue
            y = (spr[offs] + (0xF7 if flip else 0xF9) + 1) & 0xFF
            x = spr[offs + 3]
            y = 240 - y
            y ^= flip
            x ^= flip
            code = spr[offs + 2]
            color = (spr[offs + 1] & 0x0F) + pb
            flipx = spr[offs + 1] & 0x80
            flipy = spr[offs + 1] & 0x40
            if flip:
                y -= 14
                x -= 7
                flipx, flipy = not flipx, not flipy
            else:
                y += 1
                x -= 8
            s = g.sprites[code]
            if flipx: s = s[:, ::-1]
            if flipy: s = s[::-1, :]
            for yy in range(16):
                ry = y + yy
                if not 16 <= ry < 240:
                    continue
                for xx in range(16):
                    rx = x + xx
                    p = s[yy, xx]
                    if p and 0 <= rx < 256:
                        bmp[ry, rx] = color * 8 + p
                        issp[ry, rx] = True
        return (bmp, issp) if layers else bmp

    def render_rgb(self):
        from mario_pens import PENS
        bmp = self.render_raw()
        pens = np.array([((c >> 16) & 255, (c >> 8) & 255, c & 255) for c in PENS], np.uint8)
        return pens[bmp][16:240]              # 224 x 256


def save_png(arr, path, scale=2):
    from PIL import Image
    im = Image.fromarray(arr)
    if scale != 1:
        im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    im.save(path)
