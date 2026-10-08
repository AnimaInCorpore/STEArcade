"""Bubble Bobble reference renderer: char ROM decode + sprite-list ("objectram") renderer.

Layout facts (HYP until noted; see docs/hardware.md for evidence state):
  * The board has no tilemap.  Everything on screen is a list of vertical strips (objectram
    $DD00-$DFFF, 4 bytes each: Y, strip/PROM-line, X, attr).  A strip is two columns of up to
    32 8x8 tiles whose codes live in videoram ($C000-$DCFF, 0x80 bytes per strip).
  * Char ROMs: a78-09..14 (planes 0/1) and a78-15..20 (planes 2/3), 4bpp, data inverted.
  * Palette RAM $F800-$F9FF: 256 x 16-bit big-endian RGBx4444.
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from bubble import load  # noqa: E402

PLANE1 = ["a78-09.12", "a78-10.13", "a78-11.14", "a78-12.15", "a78-13.16", "a78-14.17"]
PLANE2 = ["a78-15.30", "a78-16.31", "a78-17.32", "a78-18.33", "a78-19.34", "a78-20.35"]


def build_gfx_region():
    r = bytearray(b"\x00" * 0x80000)
    for i, n in enumerate(PLANE1):
        r[i * 0x8000:(i + 1) * 0x8000] = load(n)
    for i, n in enumerate(PLANE2):
        r[0x40000 + i * 0x8000:0x40000 + (i + 1) * 0x8000] = load(n)
    return np.frombuffer(bytes(r), np.uint8) ^ 0xFF       # ROMREGION_INVERT


def decode_chars(region=None):
    """-> uint8 array [16384, 8, 8] of 4-bit pixels."""
    if region is None:
        region = build_gfx_region()
    bits = np.unpackbits(region)            # MSB-first == MAME bit numbering
    half = 0x40000 * 8
    xoff = np.array([3, 2, 1, 0, 11, 10, 9, 8])
    code = np.arange(16384)[:, None, None]
    y = np.arange(8)[None, :, None]
    x = xoff[None, None, :]
    base = code * 128 + y * 16 + x
    out = np.zeros((16384, 8, 8), np.uint8)
    for p, po in enumerate((0, 4, half, half + 4)):
        out |= (bits[base + po] << (3 - p)).astype(np.uint8)
    return out


def palette_rgb(palram):
    """256 RGB triples from the 512-byte palette RAM (RGBx4444, big-endian word)."""
    pal = np.zeros((256, 3), np.uint8)
    for i in range(256):
        hi, lo = palram[2 * i], palram[2 * i + 1]
        pal[i] = ((hi >> 4) * 17, (hi & 15) * 17, (lo >> 4) * 17)
    return pal


class Renderer:
    def __init__(self):
        self.chars = decode_chars()
        self.prom = load("a71-25.41")

    def sprites(self, m):
        """Yield decoded draw records: (x, y, code, color, flipx, flipy) for every tile drawn."""
        vram = m.vram
        obj = vram[0x1D00:0x2000]
        out = []
        prev_sx = 0
        for offs in range(0, 0x300, 4):
            e = obj[offs:offs + 4]
            if e[0] == 0 and e[1] == 0 and e[2] == 0 and e[3] == 0:
                continue
            gfx_num, gfx_attr = e[1], e[3]
            line = 0x80 + ((gfx_num & 0xE0) >> 1)
            base = (gfx_num & 0x1F) * 0x80
            if (gfx_num & 0xA0) == 0xA0:
                base |= 0x1000
            sy = -e[0]
            if self.prom[line + 15] & 0x04:      # HYP: PROM bit 2 = continue X from the previous strip
                sx = prev_sx + 16
            else:
                sx = e[2]
                if gfx_attr & 0x40:
                    sx -= 256
            prev_sx = sx
            for yc in range(32):
                pv = self.prom[line + yc // 2]
                if pv & 0x08:
                    continue
                for xc in range(2):
                    goffs = base + xc * 0x40 + (yc & 7) * 2 + (pv & 3) * 0x10
                    lo, hi = vram[goffs], vram[goffs + 1]
                    code = lo + 256 * (hi & 3) + 1024 * (gfx_attr & 0x0F)
                    out.append((sx + xc * 8, (sy + yc * 8) & 0xFF, code, (hi & 0x3C) >> 2,
                                bool(hi & 0x40), bool(hi & 0x80)))
        return out

    def render_index(self, m):
        """256x256 array of palette indices (0..255); 255 = background fill."""
        bmp = np.full((256, 256), 255, np.uint8)
        for (x, y, code, color, fx, fy) in self.sprites(m):
            t = self.chars[code & 0x3FFF]
            if fx:
                t = t[:, ::-1]
            if fy:
                t = t[::-1, :]
            for yy in range(8):
                ry = (y + yy) & 0xFF
                for xx in range(8):
                    rx = x + xx
                    if 0 <= rx < 256:
                        p = t[yy, xx]
                        if p != 15:
                            bmp[ry, rx] = color * 16 + p
        return bmp

    def render_q16(self, m):
        """Frame in the port's 16-colour palette (docs/palette16.json): (index map [224,256] 0..15, rgb)."""
        import bbpalette
        lut = bbpalette.lut_from_palette_ram(m.palram)
        idx16 = lut[self.render_index(m)[16:240]]
        return idx16, bbpalette.load_palette16()[1][idx16]

    def render_rgb(self, m):
        idx = self.render_index(m)
        pal = palette_rgb(m.palram)
        return pal[idx][16:240]


def save_png(arr, path, scale=2):
    from PIL import Image
    im = Image.fromarray(arr)
    if scale != 1:
        im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    im.save(path)
