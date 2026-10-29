"""Donkey Kong Junior (US set F-2) arcade machine model around the reference Z80.

The board is Donkey Kong's (games/dkong/tools/machine.py) with these differences (MAME nintendo/dkong.cpp,
dkongjr_map and dkongjr ROM_START):
  - the CPU ROMs are scrambled across three 8 KB chips (tools/prepare.py puts them back: cpu.rom, $0000-$5FFF);
  - 512 tiles: a write to $7C80 bit 0 selects the tile bank (tile code + 256 * bank, dkongjr_gfxbank_w);
  - its own PROMs: 2e/2f palette (tools/dkongjr_pens.py, MAME's circuit), 2n column colour codes;
  - the sound board latches: $7C00 tune, $7C81-$7C87 and $7D00-$7D07 effect bits, $7D80 the 8035 IRQ;
  - DIP switches: bonus life 10000/15000/20000/25000 (bits 2-3), IN2 bit 6 low (no MCU line).
Provides: memory map + I/O, vblank NMI, 8257 sprite DMA, scripted inputs and a reference renderer
(tiles + sprites -> RGB, the same orientation as the Donkey Kong reference).
"""
import os
import sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "..", "..", "..", "engine")]
from z80 import Z80
from dkongjr_pens import junior_pens

from paths import EXTRACTED
ROMDIR = str(EXTRACTED / "dkongjr")

CYCLES_PER_FRAME = 50688  # 3.072 MHz / 60.606 Hz


def load(name):
    with open(os.path.join(ROMDIR, name), "rb") as f:
        return f.read()


class Gfx:
    """Decoded arcade graphics + palette."""

    def __init__(self):
        g1 = load("djr1-v.3n") + load("djr1-v.3p")
        g2 = load("djr1-v_7c.7c") + load("djr1-v_7d.7d") + load("djr1-v_7e.7e") + load("djr1-v_7f.7f")
        # tiles: 512 x 8x8, 2bpp.  MAME dkong_charlayout: planes RGN_FRAC(1,2) (msb), RGN_FRAC(0,2)
        a = np.frombuffer(g1, np.uint8)
        lo = np.unpackbits(a[:0x1000].reshape(512, 8, 1), axis=2)
        hi = np.unpackbits(a[0x1000:].reshape(512, 8, 1), axis=2)
        self.tiles = (hi << 1 | lo).astype(np.uint8)
        # sprites: 128 x 16x16.  left half bytes n*16+y, right half at +0x800; msb plane at +0x1000
        self.sprites = np.zeros((128, 16, 16), np.uint8)
        for n in range(128):
            for y in range(16):
                for half in range(2):
                    off = n * 16 + y + half * 0x800
                    hi_b = g2[0x1000 + off]
                    lo_b = g2[off]
                    for x in range(8):
                        self.sprites[n, y, half * 8 + x] = (((hi_b >> (7 - x)) & 1) << 1) | ((lo_b >> (7 - x)) & 1)
        self.colcodes = load("djr1-v-2n.2n")
        self.pens = [(c >> 16, (c >> 8) & 255, c & 255) for c in junior_pens()]


class I8257:
    """The 8257's registers as the Z80 writes them: one first/last flip-flop for all address and count registers
    (reset by a mode write), channel n address at 2n, count (14 bits + 2 mode bits) at 2n+1, mode at 8."""

    def __init__(self):
        self.addr = [0] * 4
        self.count = [0] * 4
        self.mode = 0
        self.ff = 0
        self.raw = [0] * 16

    def write(self, reg, v):
        self.raw[reg] = v
        if reg == 8:
            self.mode = v
            self.ff = 0
            return
        if reg > 8:
            return
        ch, is_count = reg >> 1, reg & 1
        tab = self.count if is_count else self.addr
        if self.ff:
            tab[ch] = (tab[ch] & 0x00FF) | (v << 8)
        else:
            tab[ch] = (tab[ch] & 0xFF00) | v
        self.ff ^= 1

    def read(self, reg):
        return self.raw[reg]


class DKongJr:
    def __init__(self):
        self.mem = bytearray(0x10000)
        rom = load("cpu.rom")
        self.mem[0:len(rom)] = rom
        self.in0 = 0
        self.in1 = 0
        self.in2 = 0
        self.dsw0 = 0x80  # upright, 3 lives, 10000 bonus, 1 coin/1 credit
        self.nmi_mask = 0
        self.flip = 0
        self.sprite_bank = 0
        self.palette_bank = 0
        self.gfx_bank = 0
        self.sound_latch = 0
        self.sound_bits = [0] * 16       # $7C80-$7C87 (bit 0 of $7C80 is the tile bank), $7D00-$7D07
        self.sound_irq = 0
        self.dma = I8257()
        self.dma_log = []
        self.io_writes = {}
        self.cpu = Z80(self.rd8, self.wr8)
        self.cpu.afmask = 0xC1
        self.frame = 0
        self.gfx = None

    # ---- bus -----------------------------------------------------------
    def rd8(self, a):
        if a < 0x7800:
            return self.mem[a]
        if a == 0x7C00: return self.in0
        if a == 0x7C80: return self.in1
        if a == 0x7D00: return self.in2 & ~0x40   # no MCU line: IN2 bit 6 reads low
        if a == 0x7D80: return self.dsw0
        if 0x7800 <= a <= 0x780F: return self.dma.read(a & 15)
        # the rest reads 0 in MAME: $8000-$9FFF and $B000-$BFFF are ROM regions of the bootlegs, empty in this set,
        # the others unmapped.  The game reads there: its loop at $24F3 steps IX by $1010 instead of $10, so four of
        # its five objects are $85A0-$B5F8 and must read 0 (skipped)
        return 0

    def wr8(self, a, v):
        if a < 0x6000:
            return
        if a < 0x7800:
            self.mem[a] = v
            return
        if 0x7800 <= a <= 0x780F:
            self.dma.write(a & 15, v)
            self.dma_log.append((self.frame, a, v))
            return
        self.io_writes[a] = self.io_writes.get(a, 0) + 1
        if a == 0x7C00:
            self.sound_latch = v
        elif a == 0x7C80:
            self.gfx_bank = v & 1
        elif 0x7C81 <= a <= 0x7C87:
            self.sound_bits[a & 7] = v & 1
        elif 0x7D00 <= a <= 0x7D07:
            self.sound_bits[8 + (a & 7)] = v & 1
        elif a == 0x7D80:
            self.sound_irq = v & 1
        elif a == 0x7D82: self.flip = v & 1
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
        """Channel 0 reads memory, channel 1 writes it (the DK boards wire DACK0 -> DACK1); the count register's
        low 14 bits are the length - 1."""
        d = self.dma
        src, dst = d.addr[0], d.addr[1]
        n = (d.count[0] & 0x3FFF) + 1
        if not (d.mode & 3) == 3 or n > 0x400:
            # not both channels enabled: nothing moves (logged for the bring-up)
            self.dma_log.append((self.frame, "skip", d.mode, src, dst, n))
            return
        for i in range(n):
            self.mem[(dst + i) & 0xFFFF] = self.mem[(src + i) & 0xFFFF]

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
            code = vram[idx] + 256 * self.gfx_bank
            cc = g.colcodes[col + 32 * (row >> 2)] & 0x0F
            color = cc + 0x10 * self.palette_bank
            bmp[row * 8:row * 8 + 8, col * 8:col * 8 + 8] = color * 4 + g.tiles[code]
        base = 0x7000 + (self.sprite_bank << 9)
        spr = self.mem
        for i in range(0, 0x200, 4):
            y = spr[base + i]
            code_b = spr[base + i + 1]
            attr = spr[base + i + 2]
            x = spr[base + i + 3]
            code = (code_b & 0x7F) + ((attr & 0x40) << 1)
            color = (attr & 0x0F) + 16 * self.palette_bank
            flipx = attr & 0x80
            flipy = code_b & 0x80
            sx = (x + 0xF8) & 0xFF
            top = (247 - y) & 0xFF   # MAME draw_sprites (see the Donkey Kong reference)
            s = g.sprites[code & 0x7F]
            if flipx: s = s[:, ::-1]
            if flipy: s = s[::-1, :]
            for yy in range(16):
                ry = (top + yy) & 0xFF
                row = s[yy]
                for xx in range(16):
                    p = row[xx]
                    if p:
                        bmp[ry, (sx + xx) & 0xFF] = color * 4 + p
        return bmp

    def render_rgb(self):
        bmp = self.render_raw()
        pens = np.array(self.gfx.pens, np.uint8)
        rgb = pens[bmp]
        arr = rgb[16:240, :, :]
        disp = arr.transpose(1, 0, 2)[::-1]
        if self.flip:
            disp = disp[::-1, ::-1]
        return disp


def save_png(arr, path, scale=2):
    from PIL import Image
    im = Image.fromarray(arr)
    if scale != 1:
        im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    im.save(path)
