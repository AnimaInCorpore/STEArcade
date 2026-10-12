"""Irem M72 video (MAME irem/m72.cpp, m72_v.cpp): the reference renderer of R-Type and Mr. HELI (and the other M72
games on the same video board), 384 x 256 as MAME shows it.

Screen: 8 MHz pixel clock (32 MHz / 4), 512 x 284 total, visible x 64-447 and y 0-255: 55.017 Hz.  MAME's scanline
timer runs every line: line 256 asserts the VBLANK interrupt (uPD71059C IR0), line (port $06 word & $1FF) - 128 the
raster interrupt (IR2), and at that line MAME first draws the screen up to and including it (update_partial): the
lines above use the scroll registers, video RAM and sprite buffer of that moment, the rest is drawn at the frame's end.
The palette is not banded: MAME's bitmap holds pens, the colours are looked up when the frame is shown.

Main CPU (V30) video map, the same on every M72 game:
    $C0000-$C03FF  sprite RAM: 128 entries of 4 words; port $04 (any write) copies it to the sprite chip's buffer
                   (MAME's buffered_spriteram16 copy()), which is what is drawn
    $C8000-$C8BFF  palette 0 (pens 0-255, the sprites): words $000-$0FF red, $200-$2FF green, $400-$4FF blue, 5 bits
                   each (pal5bit: v << 3 | v >> 2); A9 is not decoded, so words $100-$1FF mirror $000-$0FF etc.
    $CC000-$CCBFF  palette 1 (pens 256-511, the tiles), the same layout
    $D0000-$D3FFF  FG video RAM ("A" tile ROMs), $D8000-$DBFFF BG video RAM ("B" tile ROMs): 64 x 64 tiles of 8x8,
                   two words each: code (bits 0-13 tile, 14 flip x, 15 flip y), attr (bits 0-3 colour, 6-7 group)
Ports: $02 bit 3 display off (black), bit 2 flip screen (not modelled: no cocktail cabinet), bit 4 sound CPU reset;
$04 sprite DMA; $06 raster line; $80/$82 FG scroll y/x, $84/$86 BG scroll y/x (16 bits each; the 512 x 512 maps
wrap): screen pixel (x, y) (MAME's bitmap coordinates, x 64-447) shows map pixel (x + scrollx, y + scrolly + 128).

Tile/tile and tile/sprite priority (screen_update): per tile group, which pens are "layer 0" (over the sprites) and
"layer 1" (under them):
    FG: group 0 pens 1-15 under;  group 1 pens 1-7 under, 8-15 over;  groups 2, 3 pens 1-15 over
    BG: group 0 pens 0-15 under;  group 1 pens 0-7 under, 8-15 over;  group 2 pen 0 under, 1-15 over (but drawn in the
        under pass, below FG's under pixels);  group 3 pen 0 under, 1-15 over
The picture is FG over, else BG over (group 3), else FG under, else BG; a sprite pixel shows only where neither FG
nor BG (groups 1-3) has an over pixel.  Sprites: 16x16 pieces, w x h of 1/2/4/8 (bits 14-15 / 12-13 of word 2), code +
8 per column + 1 per row, colour word 2 bits 0-3, flips bits 11 (x) / 10 (y), x = (word 3 & $3FF) - 256 and
y = 384 - (word 0 & $1FF) - 16 h in bitmap coordinates; a w-wide entry takes the next w - 1 entries' slots.  The list
is drawn from the last entry to the first, each pixel only once (MAME's priority bitmap): the first entry is on top.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import EXTRACTED
import mamegfx as G

PIXEL_HZ = 8000000
HTOTAL, VTOTAL = 512, 284
VISIBLE = (64, 447, 0, 255)                 # MAME's visible area (min_x, max_x, min_y, max_y)
VBLANK_LINE = 256
BLACK = 512                                 # the pen of a switched-off display
SPRITE_RAM, PAL0, PAL1, FG_RAM, BG_RAM = 0xC0000, 0xC8000, 0xCC000, 0xD0000, 0xD8000

# The graphics ROMs of each game: (file, offset, size) per region, in our archive's names (prepare.py's MAME_NAMES
# maps them to MAME's), from m72.cpp's ROM_START; a file shorter than its slot is reloaded (ROM_RELOAD).
GAMES = {
    "rtype": {
        "sprites": (0x80000, [("rt_r-00.1h", 0x00000), ("rt_r-01.1j", 0x10000), ("rt_r-01.1j", 0x18000),
                              ("rt_r-10.1k", 0x20000), ("rt_r-11.1l", 0x30000), ("rt_r-11.1l", 0x38000),
                              ("rt_r-20.3h", 0x40000), ("rt_r-21.3j", 0x50000), ("rt_r-21.3j", 0x58000),
                              ("rt_r-30.3k", 0x60000), ("rt_r-31.3l", 0x70000), ("rt_r-31.3l", 0x78000)]),
        "tiles0": (0x20000, [("rt_b-a0.3c", 0x00000), ("rt_b-a1.3d", 0x08000), ("rt_b-a2.3a", 0x10000),
                             ("rt_b-a3.3e", 0x18000)]),
        "tiles1": (0x20000, [("rt_b-b0.3j", 0x00000), ("rt_b-b1.3k", 0x08000), ("rt_b-b2.3h", 0x10000),
                             ("rt_b-b3.3f", 0x18000)]),
    },
    "mrheli": {
        "sprites": (0x80000, [("mh-c-00.bin", 0x00000), ("mh-c-10.bin", 0x20000), ("mh-c-20.bin", 0x40000),
                              ("mh-c-30.bin", 0x60000)]),
        "tiles0": (0x40000, [("mh-b-a0.bin", 0x00000), ("mh-b-a1.bin", 0x10000), ("mh-b-a2.bin", 0x20000),
                             ("mh-b-a3.bin", 0x30000)]),
        "tiles1": (0x40000, [("b-b0-.rom", 0x00000), ("b-b1-.rom", 0x10000), ("b-b2-.rom", 0x20000),
                             ("b-b3-.rom", 0x30000)]),
    },
}


def region(game, name):
    size, files = GAMES[game][name]
    out = bytearray(size)
    for f, off in files:
        data = (EXTRACTED / game / f).read_bytes()
        n = min(len(data), size - off)
        out[off:off + n] = data[:n]
    return bytes(out)


def decode(rom, size):
    """tilelayout (8x8) / spritelayout (16x16): 4 planes at RGN_FRAC(3,4) .. (0,4), the first the most significant."""
    q = len(rom) * 8 // 4
    planes = [3 * q, 2 * q, q, 0]
    if size == 8:
        return G.decode_gfx(rom, 8, 8, len(rom) // 4 // 8, planes, list(range(8)), list(range(0, 64, 8)), 64)
    return G.decode_gfx(rom, 16, 16, len(rom) // 4 // 32, planes, list(range(8)) + list(range(128, 136)),
                        list(range(0, 128, 8)), 256)


class VideoState:
    """What the video hardware draws from at one moment: the two video RAMs (0x4000 bytes each, little-endian words),
    the sprite buffer (0x400 bytes, the last DMA's copy), the scroll registers [FG, BG] and the display-off bit."""
    def __init__(self, fg, bg, sprites, scrollx=(0, 0), scrolly=(0, 0), video_off=False):
        self.fg, self.bg, self.sprites = bytes(fg), bytes(bg), bytes(sprites)
        self.scrollx, self.scrolly = list(scrollx), list(scrolly)
        self.video_off = video_off


def pens(pal0, pal1):
    """The 512 pens' RGB (+ BLACK) from the two palette RAMs (0xC00 bytes each)."""
    out = np.zeros((513, 3), np.uint8)
    for n, ram in enumerate((pal0, pal1)):
        w = np.frombuffer(bytes(ram), "<u2").astype(np.int32)
        for c in range(3):
            v = w[c * 0x200:c * 0x200 + 0x100] & 0x1F
            out[n * 256:n * 256 + 256, c] = (v << 3) | (v >> 2)
    return out


class Video:
    def __init__(self, game):
        self.game = game
        self.sprites = decode(region(game, "sprites"), 16)
        self.tiles = [decode(region(game, "tiles0"), 8), decode(region(game, "tiles1"), 8)]
        self._cache = {}

    def _layer(self, n, ram):
        """Map n (0 FG, 1 BG) as [512, 512] pen values, colours and groups (cached by the RAM's contents)."""
        key = (n, ram)
        if key not in self._cache:
            if len(self._cache) > 8:
                self._cache.clear()
            w = np.frombuffer(ram, "<u2").reshape(64, 64, 2)
            code, attr = w[:, :, 0].astype(np.int32), w[:, :, 1].astype(np.int32)
            pix, raw = G.tile_pixmap(self.tiles[n], code & 0x3FFF, attr & 15, (code >> 14) & 1, (code >> 15) & 1,
                                     64, 64, 0, 16)
            group = np.repeat(np.repeat((attr >> 6) & 3, 8, 0), 8, 1)
            self._cache[key] = (raw, pix >> 4, group)
        return self._cache[key]

    def _tiles(self, st, y0, y1):
        """Lines y0..y1 of the tile picture (pens, [lines, 512] bitmap columns, x 64-447 valid) and the sprite
        mask (True: an over pixel hides sprites)."""
        ys = np.arange(y0, y1 + 1)
        xs = np.arange(VISIBLE[0], VISIBLE[1] + 1)
        out = []
        for n, ram in enumerate((st.fg, st.bg)):
            raw, col, grp = self._layer(n, ram)
            my = ((ys + st.scrolly[n] + 128) & 511)[:, None]
            mx = ((xs + st.scrollx[n]) & 511)[None, :]
            out.append((raw[my, mx], col[my, mx], grp[my, mx]))
        (fp, fc, fg), (bp, bc, bg) = out
        f_over = ((fg == 1) & (fp >= 8)) | ((fg >= 2) & (fp >= 1))
        f_under = ((fg == 0) & (fp >= 1)) | ((fg == 1) & (fp >= 1) & (fp <= 7))
        b_over = ((bg == 1) & (bp >= 8)) | ((bg >= 2) & (bp >= 1))       # the priority pass (group 2 as group 3)
        b_over_draw = ((bg == 1) & (bp >= 8)) | ((bg == 3) & (bp >= 1))  # the drawing pass (group 2 all under)
        fpen = 256 + fc * 16 + fp
        bpen = 256 + bc * 16 + bp
        pic = np.where(f_over, fpen, np.where(b_over_draw, bpen, np.where(f_under, fpen, bpen)))
        bm = np.zeros((y1 - y0 + 1, HTOTAL), np.int32)
        pri = np.ones((y1 - y0 + 1, HTOTAL), bool)
        bm[:, VISIBLE[0]:VISIBLE[1] + 1] = pic
        pri[:, VISIBLE[0]:VISIBLE[1] + 1] = f_over | b_over
        return bm, pri

    def _sprites(self, bm, pri, spr, y0, y1):
        w16 = np.frombuffer(spr, "<u2").astype(np.int32)
        order = []
        i = 0
        while i < len(w16):
            order.append(i)
            i += 4 * (1 << ((w16[i + 2] & 0xC000) >> 14))
        n = len(self.sprites)
        for offs in reversed(order):
            code, a = int(w16[offs + 1]), int(w16[offs + 2])
            color = a & 15
            sx = -256 + (int(w16[offs + 3]) & 0x3FF)
            w, h = 1 << ((a & 0xC000) >> 14), 1 << ((a & 0x3000) >> 12)
            sy = 384 - (int(w16[offs]) & 0x1FF) - 16 * h
            flipx, flipy = a & 0x800, a & 0x400
            for x in range(w):
                for y in range(h):
                    c = code + (8 * (w - 1 - x) if flipx else 8 * x) + (h - 1 - y if flipy else y)
                    px, py = sx + 16 * x, sy + 16 * y
                    ax0, ax1 = max(px, VISIBLE[0]), min(px + 15, VISIBLE[1])
                    ay0, ay1 = max(py, y0), min(py + 15, y1)
                    if ax0 > ax1 or ay0 > ay1:
                        continue
                    src = self.sprites[c % n]
                    if flipx:
                        src = src[:, ::-1]
                    if flipy:
                        src = src[::-1, :]
                    s = src[ay0 - py:ay1 - py + 1, ax0 - px:ax1 - px + 1]
                    d = bm[ay0 - y0:ay1 - y0 + 1, ax0:ax1 + 1]
                    p = pri[ay0 - y0:ay1 - y0 + 1, ax0:ax1 + 1]
                    opaque = s != 0
                    show = opaque & ~p
                    d[show] = color * 16 + s[show]
                    p[opaque] = True

    def render_raw(self, bands):
        """The screen's pens [256, 512] (MAME's bitmap; x 64-447 visible) from [(first line, last line, VideoState)]
        (or one VideoState for all lines)."""
        if isinstance(bands, VideoState):
            bands = [(VISIBLE[2], VISIBLE[3], bands)]
        out = np.full((VISIBLE[3] + 1, HTOTAL), BLACK, np.int32)
        for y0, y1, st in bands:
            if st.video_off:
                continue
            bm, pri = self._tiles(st, y0, y1)
            self._sprites(bm, pri, st.sprites, y0, y1)
            out[y0:y1 + 1] = bm
        return out

    def render_rgb(self, bands, pens_rgb):
        """The visible picture [256, 384, 3] as MAME's snapshot shows it; pens_rgb: pens(pal0, pal1)."""
        raw = self.render_raw(bands)[VISIBLE[2]:VISIBLE[3] + 1, VISIBLE[0]:VISIBLE[1] + 1]
        return pens_rgb[raw]


def bands(start, end, writes, ports0):
    """MAME's partial updates of one frame: [(first line, last line, VideoState)].
    start, end: dict(fg=, bg=, sprites=, sprites_end=) at the previous / this frame's end (sprite buffers: the DMA copy
    at the previous frame's end and this one's); writes: [(line, space, address, byte)] in time order since the
    previous frame's end (line >= 256: still the previous vertical blank; space "io" or "program"); ports0:
    {port: byte} at the previous frame's end.  The raster interrupt line (port $06) cuts a band at the line it fires,
    that line included."""
    fg, bg = bytearray(start["fg"]), bytearray(start["bg"])
    ports = dict(ports0)
    spr = start["sprites"]
    out = []
    top = 0
    k = 0
    timed = [(l - VTOTAL if l >= VBLANK_LINE else l, s, a, v) for l, s, a, v in writes]

    def state():
        p = lambda a: ports.get(a, 0) | ports.get(a + 1, 0) << 8
        return VideoState(fg, bg, spr, (p(0x82), p(0x86)), (p(0x80), p(0x84)), bool(ports.get(2, 0) & 8))

    def apply_until(t):
        nonlocal k, spr
        while k < len(timed) and timed[k][0] < t:
            _, s, a, v = timed[k]
            if s == "io":
                ports[a] = v
                if a in (4, 5):
                    spr = end["sprites"]            # (one DMA a frame: its copy is the one at the frame's end)
            elif FG_RAM <= a < FG_RAM + 0x4000:
                fg[a - FG_RAM] = v
            elif BG_RAM <= a < BG_RAM + 0x4000:
                bg[a - BG_RAM] = v
            k += 1

    for line in range(VISIBLE[2], VISIBLE[3] + 1):
        apply_until(line)
        raster = ((ports.get(6, 0) | ports.get(7, 0) << 8) & 0x1FF) - 128
        if raster == line and line < VISIBLE[3]:
            out.append((top, line, state()))
            top = line + 1
    apply_until(VBLANK_LINE)
    out.append((top, VISIBLE[3], state()))
    return out, (bytes(fg), bytes(bg))
