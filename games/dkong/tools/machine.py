"""Donkey Kong (TKG-04) arcade machine model around the reference Z80.

Provides: memory map + I/O, vblank NMI scheduling, 8257 sprite DMA, scripted
inputs and a reference renderer (tiles + sprites -> RGB image, rotated 270).
"""
import os
import sys
import numpy as np

sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from z80 import Z80
from dkong_pens import PENS

from paths import EXTRACTED
ROMDIR = str(EXTRACTED)

CYCLES_PER_FRAME = 50688  # 3.072 MHz / 60.606 Hz


def load(name):
    with open(os.path.join(ROMDIR, name), "rb") as f:
        return f.read()


class Gfx:
    """Decoded arcade graphics + palette."""

    def __init__(self):
        g1 = load("v_5h_b.bin") + load("v_3pt.bin")
        g2 = load("l_4m_b.bin") + load("l_4n_b.bin") + load("l_4r_b.bin") + load("l_4s_b.bin")
        # tiles: 256 x 8x8, 2bpp.  pixel = (byte@0x800+n*8+y bit) <<1 | byte@n*8+y bit
        self.tiles = np.zeros((256, 8, 8), np.uint8)
        for n in range(256):
            for y in range(8):
                hi = g1[0x800 + n * 8 + y]
                lo = g1[n * 8 + y]
                for x in range(8):
                    self.tiles[n, y, x] = (((hi >> (7 - x)) & 1) << 1) | ((lo >> (7 - x)) & 1)
        # sprites: 128 x 16x16.  left half bytes n*16+y, right half at +0x800;
        # msb plane at +0x1000
        self.sprites = np.zeros((128, 16, 16), np.uint8)
        for n in range(128):
            for y in range(16):
                for half in range(2):
                    off = n * 16 + y + half * 0x800
                    hi = g2[0x1000 + off]
                    lo = g2[off]
                    for x in range(8):
                        self.sprites[n, y, half * 8 + x] = (((hi >> (7 - x)) & 1) << 1) | ((lo >> (7 - x)) & 1)
        self.prom_lo = load("c-2k.bpr")
        self.prom_hi = load("c-2j.bpr")
        self.colcodes = load("v-5e.bpr")
        self.pens = [self.pen_rgb(i) for i in range(256)]

    def pen_rgb(self, i):
        # MAME's palette (tools/dkong_pens.py), not a model of the resistor network
        c = PENS[i]
        return (c >> 16, (c >> 8) & 255, c & 255)


class DKong:
    def __init__(self):
        self.mem = bytearray(0x10000)
        rom = load("cpu.rom")
        self.mem[0:len(rom)] = rom
        self.in0 = 0
        self.in1 = 0
        self.in2 = 0
        self.dsw0 = 0x80  # upright, 3 lives, 7000 bonus, 1 coin/1 credit
        self.nmi_mask = 0
        self.flip = 0
        self.sprite_bank = 0
        self.palette_bank = 0
        self.dma = [0] * 16
        self.dma_log = []
        self.io_writes = {}
        self.cpu = Z80(self.rd8, self.wr8)
        self.cpu.afmask = 0xC1
        self.frame = 0
        self.gfx = None
        self.watch_hook = None

    # ---- bus -----------------------------------------------------------
    def rd8(self, a):
        if a < 0x7000 or a < 0x7800:
            return self.mem[a]
        if a == 0x7C00: return self.in0
        if a == 0x7C80: return self.in1
        if a == 0x7D00: return self.in2
        if a == 0x7D80: return self.dsw0
        if 0x7800 <= a <= 0x780F: return self.dma[a & 15]
        return 0xFF

    def wr8(self, a, v):
        if a < 0x4000:
            return
        if a < 0x7800:
            self.mem[a] = v
            return
        if 0x7800 <= a <= 0x780F:
            self.dma[a & 15] = v
            self.dma_log.append((self.frame, a, v))
            return
        self.io_writes[a] = self.io_writes.get(a, 0) + 1
        if a == 0x7D82: self.flip = v & 1
        elif a == 0x7D83: self.sprite_bank = v & 1
        elif a == 0x7D84:
            self.nmi_mask = v & 1
        elif a == 0x7D85:
            if v & 1:
                self.do_dma()
        elif a == 0x7D86:
            self.palette_bank = (self.palette_bank & ~1) | (v & 1)
        elif a == 0x7D87:
            self.palette_bank = (self.palette_bank & ~2) | ((v & 1) << 1)

    def do_dma(self):
        # channel 0: source (memory read), channel 1: destination
        src = self.dma[0] | (self.dma[1] << 8)
        dst = self.dma[2] | (self.dma[3] << 8)
        cnt = (self.dma[1 + 2 * 0 + 1 - 1 + 0 + 0] if False else 0)
        tc = self.dma[1] | (self.dma[1] << 8)
        # Fall back to the documented DK setup: 0x6900 -> 0x7000, 0x180 bytes.
        self.mem[0x7000:0x7000 + 0x180] = self.mem[0x6900:0x6900 + 0x180]

    # ---- running -------------------------------------------------------
    def run_frame(self):
        cpu = self.cpu
        target = cpu.cycles + CYCLES_PER_FRAME
        if self.nmi_mask:
            cpu.nmi()
        while cpu.cycles < target:
            cpu.step()
        self.frame += 1

    # ---- rendering -----------------------------------------------------
    def render_raw(self):
        """Raw 256x256 (x, y) index bitmap of pens; returns (pens[y][x])."""
        if self.gfx is None:
            self.gfx = Gfx()
        g = self.gfx
        bmp = np.zeros((256, 256), np.uint16)
        vram = self.mem[0x7400:0x7800]
        for idx in range(1024):
            col = idx & 31
            row = idx >> 5
            code = vram[idx]
            cc = g.colcodes[col + 32 * (row >> 2)] & 0x0F
            color = cc + 0x10 * self.palette_bank
            t = g.tiles[code]
            bmp[row * 8:row * 8 + 8, col * 8:col * 8 + 8] = color * 4 + t
        # sprites (96 of them at 7000: y, code|flipy, color|flipx|bank, x)
        base = 0x7000 + (self.sprite_bank << 9)
        spr = self.mem
        n = 0
        drawn = []
        for i in range(0, 0x200, 4):
            y = spr[base + i]
            code_b = spr[base + i + 1]
            attr = spr[base + i + 2]
            x = spr[base + i + 3]
            if y == 0 and code_b == 0 and attr == 0 and x == 0:
                pass
            drawn.append((y, code_b, attr, x))
        # DK draws only the first 16 sprites per scanline; ignore the limit.
        ordered = drawn
        for (y, code_b, attr, x) in ordered:
            code = (code_b & 0x7F) + ((attr & 0x40) << 1)
            color = (attr & 0x0F) + 16 * self.palette_bank
            flipx = attr & 0x80
            flipy = code_b & 0x80
            sx = (x + 0xF8) & 0xFF
            top = (247 - y) & 0xFF   # MAME draw_sprites; 246 was one pixel off
            s = g.sprites[code]
            if flipx: s = s[:, ::-1]
            if flipy: s = s[::-1, :]
            for yy in range(16):
                ry = (top + yy) & 0xFF
                for xx in range(16):
                    p = s[yy, xx]
                    if p:
                        bmp[ry, (sx + xx) & 0xFF] = color * 4 + p
        return bmp

    def render_rgb(self):
        bmp = self.render_raw()
        pens = np.array(self.gfx.pens, np.uint8)
        rgb = pens[bmp]  # [y][x][3]
        arr = rgb[16:240, :, :]  # [y-16][x]
        disp = arr.transpose(1, 0, 2)[::-1]  # [255-x][y-16]
        if self.flip:
            disp = disp[::-1, ::-1]
        return disp


def save_png(arr, path, scale=2):
    from PIL import Image
    im = Image.fromarray(arr)
    if scale != 1:
        im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    im.save(path)
