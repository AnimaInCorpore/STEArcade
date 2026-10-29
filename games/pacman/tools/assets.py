"""The STE port's graphics and colours (build/pacman/, ROM-derived: never committed).

    python tools/assets.py

The picture is turned as MAME's ROT90 turns it: picture column X (0-223) is the arcade's raw y = 223 - X, the picture's
line is the raw x; a turned image T[row][col] = raw[n - 1 - col][row] (np.rot90(raw, -1)).

Colours: the STE pixel is the arcade's colour index (0-15, the palette PROM's first 16: the colour lookup PROM never
selects 16-31, nor the black duplicates 4, 8 and 10).  pm_pal holds the 16 colours on the STE's 4 bits a gun.

* pm_spr.bin: the 64 sprites turned, unflipped: 16 rows, a row two words (the pens' bit 0, then bit 1; the leftmost
  pixel the MSB), then the same 16 rows with the bits reversed (MAME's flip y): 128 bytes a sprite.  MAME's flip x
  reverses the rows.
* pm_tiles.bin: the 256 tiles turned: 8 rows, a row two bytes (the pens' bit 0, then bit 1): 16 bytes a tile.
* pm_assets.s: pm_pal, pm_cpen (32 colours x 4 pens: the colour index), pm_cpat (per colour: its transparency pattern,
  0-2, or -1: every pen black, nothing drawn), pm_cells (per video RAM cell: its first drawn byte in a buffer, -1 when
  not shown; pm_ckind: the tile lines it draws, KINDS), the tile converters (pm_tconv: per colour and kind a routine
  drawing a cell's lines), the sprite programs (pm_shapes: engine/sprite_programs.py, shape = pattern << 8 |
  code << 2 | flip x << 1 | flip y; made for the shapes the coverage drew, the others draw through the row path),
  pm_order.bin (per shape its opaque rows in bake order), pm_sstream.bin.

A pen is transparent where its colour is black (MAME's transpen_mask of colour 0): the patterns are {0}, {0, 2} and
{0, 3}.

The buffer (render.s): 288 lines of 160 bytes; buffer line = arcade line for the maze (24-271) and the sprites.  The
display starts at buffer line 10; Hatari shows 274 lines with both borders open (games/pacman/README.md, measured):
the HUD rows sit at row 0 lines 0-6 -> buffer 10-16, row 1 lines 9-15 -> 17-23, rows 34-35 lines 275-286 -> 272-283.
Lines 7, 8 and 272 are never drawn, 273 and row 2 (lines 16-23) only on the level-256 split screen, 287 hardly ever;
274 is the top line of the life and fruit icons: not shown.
"""
from pathlib import Path
import pickle
import sys
import numpy as np
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import Gfx
from paths import build_dir
import sprite_programs as sp

BUILD = build_dir('pacman')
LB = 160
LEFT = 48
PATTERNS = [(0,), (0, 2), (0, 3)]          # the transparent pens of the drawable colours


def ste_word(c):
    """an RGB colour on the STE's 4 bits a gun (the STE's bit order: the LSB is the gun's bit 3; Gyruss's ste_word)"""
    conv = lambda n: ((n >> 1) & 7) | ((n & 1) << 3)
    r, g, b = (int(v) // 17 for v in c)
    return (conv(r) << 8) | (conv(g) << 4) | conv(b)


def colour_pattern(g, c):
    pens = g.lut[4 * c:4 * c + 4]
    tr = tuple(p for p in range(4) if pens[p] == 0)
    return -1 if len(tr) == 4 else PATTERNS.index(tr)


def turned(img):
    return np.rot90(img, -1)


def rows_bits(img, width):
    out = []
    for r in range(img.shape[0]):
        w = [0, 0]
        for c in range(width):
            for bit in (0, 1):
                w[bit] |= ((int(img[r, c]) >> bit) & 1) << (width - 1 - c)
        out.append(w)
    return out


def turned_sprites(g):
    out = bytearray()
    for code in range(64):
        t = turned(g.sprites[code])
        for img in (t, t[:, ::-1]):
            for w0, w1 in rows_bits(img, 16):
                out += w0.to_bytes(2, 'big') + w1.to_bytes(2, 'big')
    return bytes(out)


def turned_tiles(g):
    out = bytearray()
    for code in range(256):
        for w0, w1 in rows_bits(turned(g.chars[code]), 8):
            out += bytes((w0, w1))
    return bytes(out)


KINDS = [(0, 7), (0, 6), (1, 7), (3, 7)]     # the tile lines a cell draws: the maze, rows 0 and 35, row 1, row 34
SHOWN = list(range(0, 7)) + list(range(9, 16)) + list(range(24, 272)) + list(range(275, 287))   # the 274 lines


def hud_line(row, line):
    """the buffer line of a tile row's line (row: the raw x / 8, 0-35), None: not shown"""
    L = 8 * row + line
    return SHOWN.index(L) + 10 if L in SHOWN else None


def cells():
    """per video RAM cell (0-1023): (the first drawn line's byte offset in a buffer or -1, kind: 0 lines 0-7, 1 lines
    0-6, 2 lines 1-7)"""
    out = [(-1, 0)] * 1024
    for R in range(28):                     # raw y / 8
        for C in range(36):                 # raw x / 8: the picture's tile row
            r, c = R + 2, C - 2
            idx = r + ((c & 0x1f) << 5) if c & 0x20 else c + (r << 5)
            lines = [hud_line(C, k) for k in range(8)]
            if all(v is None for v in lines):
                continue
            drawn = [k for k in range(8) if lines[k] is not None]
            assert len(drawn) == drawn[-1] - drawn[0] + 1
            kind = KINDS.index((drawn[0], drawn[-1]))
            first = lines[drawn[0]]
            x = LEFT + 8 * (27 - R)         # the cell's screen x: picture X = 223 - raw y - 7
            off = first * LB + (x >> 4) * 8 + ((x >> 3) & 1)
            out[idx] = (off, kind)
    return out


# a plane's byte from the row's pen bits b0 (d0), b1 (d1): the pens (0-3) whose colour has the plane's bit -> code
PLANE_OPS = {
    0b0000: None, 0b1111: 'st',
    0b1010: ['move.b d0,d2'], 0b1100: ['move.b d1,d2'], 0b1000: ['move.b d0,d2', 'and.b d1,d2'],
    0b1110: ['move.b d0,d2', 'or.b d1,d2'], 0b0010: ['move.b d1,d2', 'not.b d2', 'and.b d0,d2'],
    0b0100: ['move.b d0,d2', 'not.b d2', 'and.b d1,d2'], 0b0110: ['move.b d0,d2', 'eor.b d1,d2'],
    0b0001: ['move.b d0,d2', 'or.b d1,d2', 'not.b d2'], 0b1001: ['move.b d0,d2', 'eor.b d1,d2', 'not.b d2'],
    0b0011: ['move.b d1,d2', 'not.b d2'], 0b0101: ['move.b d0,d2', 'not.b d2'],
    0b1011: ['move.b d1,d2', 'not.b d2', 'or.b d0,d2'], 0b1101: ['move.b d0,d2', 'not.b d2', 'or.b d1,d2'],
    0b0111: ['move.b d0,d2', 'and.b d1,d2', 'not.b d2'],
}


def tile_converters(g):
    """pm_tconv: per tile colour (32) a routine that draws a tile's lines (a0: its rows, a1: the first drawn line's
    byte in the clean screen, a byte of each plane at 0, 2, 4, 6) in the colour's 4 STE colours: an entry per kind
    (KINDS: 4 longs a colour; a1 is the kind's first line)."""
    lines, table, seen = [], [], {}
    for c in range(32):
        cols = tuple(g.lut[4 * c + p] for p in range(4))
        if cols not in seen:
            n = 'tconv_%d' % len(seen)
            seen[cols] = n

            def body(name, first, last, base):
                out = [name + ':']
                if first:
                    out.append('\taddq.l #%d,a0' % (2 * first))
                for r in range(first, last + 1):
                    out += ['\tmove.b (a0)+,d0', '\tmove.b (a0)+,d1']
                    for pl in range(4):
                        tt = sum(1 << pen for pen in range(4) if cols[pen] >> pl & 1)
                        ops = PLANE_OPS[tt]
                        o = 2 * pl + LB * (r - base)
                        dst = '%d(a1)' % o if o else '(a1)'
                        if ops is None:
                            out.append('\tclr.b ' + dst)
                        elif ops == 'st':
                            out.append('\tst ' + dst)
                        else:
                            out += ['\t' + x for x in ops] + ['\tmove.b d2,' + dst]
                return out + ['\trts']
            for k, (first, last) in enumerate(KINDS):
                lines += body('%s_%d' % (n, k), first, last, first)
        n = seen[cols]
        table.append(','.join('%s_%d' % (n, k) for k in range(len(KINDS))))
    return ['pm_tconv:'] + ['\tdc.l ' + t for t in table] + lines


def shape_masks(g, pattern, code, fx, fy):
    """the turned sprite's 16 row masks for MAME's flips (flip x: the rows reversed, flip y: the bits)"""
    t = turned(g.sprites[code])
    if fx:
        t = t[::-1]
    if fy:
        t = t[:, ::-1]
    tr = PATTERNS[pattern]
    return [sum(1 << (15 - c) for c in range(16) if int(t[r, c]) not in tr) for r in range(16)]


def all_shapes(g):
    return {p << 8 | code << 2 | fx << 1 | fy: shape_masks(g, p, code, fx, fy)
            for p in range(len(PATTERNS)) for code in range(64) for fx in (0, 1) for fy in (0, 1)}


def coverage_shapes(g):
    """the shapes of the sprite entries the coverage drew (ref/cover.py `sprites`): the generated code is made for
    these; the others are drawn by render.s' row path"""
    seen = set()
    for f in sorted(BUILD.glob('cover[0-9]*.pkl')):
        for code, colour, fx, fy in pickle.loads(f.read_bytes()).get('sprites', ()):
            p = colour_pattern(g, colour)
            if p >= 0:
                seen.add(p << 8 | code << 2 | fx << 1 | fy)
    return seen


def build():
    g = Gfx()
    (BUILD / 'pm_spr.bin').write_bytes(turned_sprites(g))
    (BUILD / 'pm_tiles.bin').write_bytes(turned_tiles(g))
    shapes = all_shapes(g)
    nshapes = len(PATTERNS) << 8
    gen = {sid: shapes[sid] for sid in coverage_shapes(g)}
    progs, stream, stats = sp.programs(gen, nshapes, table='pm_shapes', stream_sym='pm_sstream')
    print('generated code: %(routines)d routines (%(code_lines)d lines) for %(shapes)d shapes x 16 shifts x 3 clips; '
          'stream blocks %(stream_blocks)d, %(stream_bytes)d bytes' % stats)
    (BUILD / 'pm_sstream.bin').write_bytes(stream)
    (BUILD / 'pm_order.bin').write_bytes(sp.order_table([shapes[s] for s in range(nshapes)], 16))
    lines = ['; generated by games/pacman/tools/assets.py: colours, cells, tile converters, sprite programs',
             '\tsection data,data',
             'pm_pal:\tdc.w ' + ','.join('$%03X' % ste_word(c) for c in g.palette[:16]),
             'pm_cpen:']
    lines += ['\tdc.b ' + ','.join(str(v) for v in g.lut[i:i + 16]) for i in range(0, 128, 16)]
    lines += ['pm_cpat:\tdc.b ' + ','.join(str(colour_pattern(g, c)) for c in range(32)), '\teven', 'pm_cells:']
    cl = cells()
    lines += ['\tdc.l ' + ','.join(str(o) for o, k in cl[i:i + 16]) for i in range(0, 1024, 16)]
    lines += ['pm_ckind:'] + ['\tdc.b ' + ','.join(str(k) for o, k in cl[i:i + 32]) for i in range(0, 1024, 32)]
    lines += ['\teven', '\tsection text,code'] + tile_converters(g) + progs + ['\tsection data,data']
    (BUILD / 'pm_assets.s').write_text('\n'.join(lines) + '\n')
    shown = sum(1 for o, k in cl if o >= 0)
    print('cells shown: %d; colours: %s' % (shown, ['$%03X' % ste_word(c) for c in g.palette[:16]]))


if __name__ == '__main__':
    build()
