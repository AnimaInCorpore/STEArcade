"""Gauntlet (MAME `gauntlet`, rev 14): the reference renderer, MAME 0.289's atari/gauntlet.cpp screen_update with
atari/atarimo.cpp's motion objects, pixel-exact on MAME's memory (ref/mame_cmp_gauntlet.py).

    v = Video()
    pens = v.render_raw(vram, xscroll, yscroll)           # int16 [240, 336], pens 0-1023
    rgb = v.render_rgb(vram, palette_ram, xscroll, yscroll)
    v.render_raw(vram, xs, ys, 0, 99, out=bm); v.render_raw(vram, xs2, ys, 100, 239, out=bm)   # partial updates
vram: the bytes of $900000-$905FFF (big-endian words); palette_ram: $910000-$9107FF; xscroll: the write-only
register $930000; yscroll: the RAM word $905F6E.

Screen: 7.159 MHz pixel clock, htotal 456, vtotal 262 (59.92 Hz), visible 336 x 240 (lines 0-239), drawn
VIDEO_UPDATE_BEFORE_VBLANK.  MAME draws in partial updates: before every change of the x scroll ($930000) or of
$905F6E (yscroll_w), at the beam's line v (lines <= v with the old value), and atarimo's force_update timer at lines
63, 127, 191 (no visible effect: everything else is read at the update).  render_raw(..., y0, y1, out) draws such a
range: the motion objects are clipped to it per band as draw_async(cliprect) does.

Video RAM:
    $900000-$901FFF playfield 64 x 64 tiles of 8x8 (512 x 512, TILEMAP_SCAN_COLS: word col * 64 + row):
                    bit 15 flip x, bits 12-14 palette, bits 0-11 tile; code = (bank * $1000 + tile) ^ $800
                    (bank = $905F6E bits 0-1), colour $18 + palette: pens $280-$2FF (gfx 0's base $100,
                    playfield colour bank 1 for Gauntlet), opaque.  Screen (x, y) shows (x + xscroll, y + yscroll)
                    mod 512, xscroll = $930000, yscroll = $905F6E >> 7.
    $902000-$903FFF motion objects, 1024 entries in four 1 KB planes (split): word 0 ($902000) code (bits 0-14;
                    looked up ^ $800), word 1 ($902800) x (bits 7-15) and palette (bits 0-3), word 2 ($903000)
                    y (bits 7-15), flip x (bit 6), width - 1 (bits 3-5) and height - 1 (bits 0-2) in tiles of 8x8,
                    word 3 ($903800) link (bits 0-9).  Pens $100 + palette * 16 + pixel, pixel 0 transparent.
    $905000-$905F7F alphanumerics 64 x 31 chars of 8x8 2 bpp (SCAN_ROWS, not scrolled): bit 15 opaque (pixel 0
                    drawn too), bits 10-13 + bit 14 (-> $20) colour, bits 0-9 char: pens colour * 4 + pixel
                    (0-63 and 128-191), pixel 0 transparent unless opaque.
    $905F6E         y scroll (bits 7-15) / playfield tile bank (bits 0-1)
    $905F80-$905FFF SLIP table: 64 words, the first motion object (bits 0-9) of each band of 8 lines.
Motion objects (atarimo, slipheight 8, slipoffset 1): screen line y lies in band ((y + yscroll - 1) & 511) >> 3;
for each band MAME walks the linked list from its SLIP entry until an entry repeats (at most 1024) and draws every
object in list order, clipped to the band's lines, into a bitmap of 0xFFFF (later objects over earlier ones).  An
object's top-left: x = xpos - (xscroll & 511), y = -ypos - yscroll - height * 8, both & 511, then -512 if x >= 336
or y >= the update's last line + 1; its tiles are code, code + 1, ... row by row (flip x: mirrored order and
pixels).  Tile graphics: 8192 tiles of gfx_8x8x4_planar (planes at 3/4, 2/4, 1/4, 0/4 of the region), the ROMs
inverted (ROMREGION_INVERT); codes modulo 8192.
Picture (back to front): the playfield; the motion object merge: a pixel of pen 1 (pixel & $F == 1) flips the
playfield pen's bit 7 ($280-$2FF -> $200-$27F: the shadows), any other drawn pixel replaces it; the alphanumerics.
Palette: 1024 pens IRGB_4444 ($910000 + pen * 2; $000-$0FF alpha, $100-$1FF MO, $200-$2FF playfield, $300-$3FF
unused): i = I * $11, r = i * (R * $11) >> 8 (MAME's standard_irgb_decoder).
"""
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from paths import EXTRACTED
import mamegfx as G

W, H = 336, 240
TILE_ROMS = ["136037-111.1a", "136037-112.1b", "136037-113.1l", "136037-114.1mn",
             "136037-115.2a", "136037-116.2b", "136037-117.2l", "136037-118.2mn"]
CHAR_ROM = "136037-104.6p"
NO_MO = -1                                # (MAME's 0xFFFF)


def load(name):
    return (EXTRACTED / "gauntlet" / name).read_bytes()


def words(b):
    return np.frombuffer(bytes(b), ">u2").astype(np.int32)


class Video:
    def __init__(self):
        tiles = bytes(x ^ 0xFF for x in b"".join(load(n) for n in TILE_ROMS))          # ROMREGION_INVERT
        q = len(tiles) * 8 // 4
        self.tiles = G.decode_gfx(tiles, 8, 8, len(tiles) // 32, [3 * q, 2 * q, q, 0], list(range(8)),
                                  [8 * y for y in range(8)], 64).astype(np.int16)
        chars = load(CHAR_ROM)
        chars = chars + bytes(0x4000 - len(chars))                     # (the 27128's second half is 0x00)
        self.chars = G.decode_gfx(chars, 8, 8, 1024, [0, 4], [0, 1, 2, 3, 8, 9, 10, 11],
                                  [16 * y for y in range(8)], 128).astype(np.int16)
        self.tiles_fx = self.tiles[:, :, ::-1].copy()

    # ---- layers ----------------------------------------------------------------------------------------------
    def playfield(self, vram, bank):
        """The 512 x 512 pixmap of pens."""
        d = words(vram[0:0x2000]).reshape(64, 64).T                    # [row, col] (SCAN_COLS: col * 64 + row)
        code = (((bank & 3) * 0x1000) + (d & 0xFFF)) ^ 0x800
        color = 0x18 + ((d >> 12) & 7)
        zero = np.zeros_like(d)
        pix, _ = G.tile_pixmap(self.tiles, code, color, d >> 15, zero, 64, 64, 0x100, 16)
        return pix.astype(np.int16)

    def alpha(self, vram):
        """The 248 x 512 pixmap of pens and its mask of drawn pixels."""
        d = words(vram[0x5000:0x5000 + 64 * 31 * 2]).reshape(31, 64)
        color = ((d >> 10) & 0x0F) | ((d >> 9) & 0x20)
        zero = np.zeros_like(d)
        pix, raw = G.tile_pixmap(self.chars, d & 0x3FF, color, zero, zero, 31, 64, 0, 4)
        opaque = np.repeat(np.repeat((d & 0x8000) != 0, 8, 0), 8, 1)
        return pix.astype(np.int16), opaque | (raw != 0)

    def motion_objects(self, vram, xscroll, yscroll, y0, y1):
        """MAME's MO bitmap over lines y0..y1 ([y1 + 1, 336], NO_MO where nothing is drawn)."""
        mo = np.full((y1 + 1, W), NO_MO, np.int16)
        ram = words(vram[0x2000:0x4000]).reshape(4, 1024)
        slip = words(vram[0x5F80:0x6000])
        xs, ys = xscroll & 0x1FF, (yscroll >> 7) & 0x1FF
        height_bm = y1 + 1                                             # the wrapped bitmap's height (draw_async)
        y = y0
        while y <= y1:
            band = ((y + ys - 1) & 0x1FF) >> 3
            top = y
            while y <= y1 and ((y + ys - 1) & 0x1FF) >> 3 == band:
                y += 1
            clip = (0, W - 1, top, y - 1)
            link = slip[band & 63] & 0x3FF
            visited = set()
            while link not in visited:                                 # build_active_list
                visited.add(link)
                self._object(mo, clip, ram[:, link], xs, ys, height_bm)
                link = ram[3, link] & 0x3FF
        return mo

    def _object(self, bm, clip, e, xs, ys, height_bm):
        """render_object (no neighbours, no vflip, no special value)."""
        code = (e[0] & 0x7FFF) ^ 0x800
        color = 0x100 + (e[1] & 0x0F) * 16
        hflip = bool(e[2] & 0x40)
        width = ((e[2] >> 3) & 7) + 1
        height = (e[2] & 7) + 1
        xpos = ((e[1] >> 7) - xs) & 0x1FF
        ypos = (-(e[2] >> 7) - ys - height * 8) & 0x1FF
        if xpos >= W:
            xpos -= 0x200
        if ypos >= height_bm:
            ypos -= 0x200
        x0, x1, c0, c1 = clip
        if ypos > c1 or ypos + height * 8 <= c0:                       # (no row in the band)
            return
        xadv = 8
        if hflip:
            xpos += (width - 1) * 8
            xadv = -8
        gfx = self.tiles_fx if hflip else self.tiles
        n = len(gfx)
        for ty in range(height):
            sy = ypos + ty * 8
            if sy <= c0 - 8:
                code += width
                continue
            if sy > c1:
                break
            a0, a1 = max(sy, c0), min(sy + 7, c1)
            for tx in range(width):
                sx = xpos + tx * xadv
                if sx > -8 and sx <= x1:
                    b0, b1 = max(sx, x0), min(sx + 7, x1)
                    s = gfx[code % n, a0 - sy:a1 - sy + 1, b0 - sx:b1 - sx + 1]
                    d = bm[a0:a1 + 1, b0:b1 + 1]
                    keep = s != 0
                    d[keep] = color + s[keep]
                code += 1

    # ---- the picture -----------------------------------------------------------------------------------------
    def render_raw(self, vram, xscroll, yscroll, y0=0, y1=H - 1, out=None):
        """Lines y0..y1 of the picture (one screen_update with that cliprect) into out ([240, 336] int16, a new one
        if None); returns out."""
        if out is None:
            out = np.zeros((H, W), np.int16)
        pf = self.playfield(vram, yscroll & 3)
        rows = (np.arange(y0, y1 + 1) + (yscroll >> 7)) & 0x1FF
        cols = (np.arange(W) + xscroll) & 0x1FF
        bm = pf[np.ix_(rows, cols)]
        mo = self.motion_objects(vram, xscroll, yscroll, y0, y1)[y0:]
        drawn = mo != NO_MO
        shadow = drawn & ((mo & 0x0F) == 1)
        bm[shadow] ^= 0x80
        put = drawn & ~shadow
        bm[put] = mo[put]
        apix, amask = self.alpha(vram)
        apix, amask = apix[y0:y1 + 1, :W], amask[y0:y1 + 1, :W]
        bm[amask] = apix[amask]
        out[y0:y1 + 1] = bm
        return out

    @staticmethod
    def pens(palette_ram):
        """[1024, 3] uint8: IRGB_4444."""
        w = words(palette_ram[:0x800])
        i = ((w >> 12) & 15) * 0x11
        rgb = np.stack([(w >> 8) & 15, (w >> 4) & 15, w & 15], axis=1) * 0x11
        return ((i[:, None] * rgb) >> 8).astype(np.uint8)

    def render_rgb(self, vram, palette_ram, xscroll, yscroll, segments=None):
        """The RGB picture; segments: [(first line, xscroll, yscroll)] of partial updates (ascending first lines,
        the first at 0) instead of one state."""
        if segments is None:
            raw = self.render_raw(vram, xscroll, yscroll)
        else:
            raw = np.zeros((H, W), np.int16)
            for k, (top, xs, ys) in enumerate(segments):
                bot = segments[k + 1][0] - 1 if k + 1 < len(segments) else H - 1
                if bot >= top:
                    self.render_raw(vram, xs, ys, top, bot, out=raw)
        return self.pens(palette_ram)[raw]
