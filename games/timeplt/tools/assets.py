"""The STE port's graphics and colours (build/timeplt/, ROM-derived: never committed).

    python tools/assets.py

The picture is turned as MAME's ROT90 turns it: picture pixel (X, Y), X 0-223, Y 0-255, is the arcade's raw pixel
(x = Y, y = 239 - X); a turned image T[row][col] = raw[15 - col][row] (8 - 1 - col for tiles).
* tp_spr.bin: the 256 sprites turned, unflipped: 16 rows, a row two words (the pens' bit 0, then bit 1; the leftmost
  pixel the MSB), then the same 16 rows with the bits reversed (MAME's flip y): 128 bytes a sprite.  MAME's flip x
  (attribute bit 6 clear) reverses the rows.
* tp_tiles.bin: the 512 tiles turned, unflipped: 8 rows, a row two bytes (the pens' bit 0, then bit 1): 16 bytes a
  tile.  Raw flip x (colour bit 6) reverses the rows, raw flip y (bit 7) the columns.
* tp_assets.s: tp_pal (16 STE colours), tp_spen (256 bytes: sprite colour * 4 + pen -> colour index), tp_tpen (128
  bytes: tile colour * 4 + pen -> colour index).

Colours: black and 15 fitted by a weighted k-means in Oklab (Gyruss's tools/assets.py) to the reference pictures' pens
of the coverage runs (ref/cover.py's `pens`), snapped to the STE's 4 bits a gun; every pen maps to the nearest (black
only for black).  The arcade shows up to 22 colours in a stage (25 in all).
"""
from pathlib import Path
import collections
import pickle
import sys
import numpy as np
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[2] / 'gyruss' / 'tools'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import Video
from paths import build_dir
import importlib.util
import sprite_programs as sp

_spec = importlib.util.spec_from_file_location('gy_assets', Path(__file__).resolve().parents[2] / 'gyruss' / 'tools' /
                                               'assets.py')
gy = importlib.util.module_from_spec(_spec)
sys.modules['gy_assets'] = gy
_saved = sys.modules.get('machine')
_spec.loader.exec_module(gy)               # (its fit / pen_map / ste_word / oklab; it imports Gyruss's machine)
if _saved is not None:
    sys.modules['machine'] = _saved

BUILD = build_dir('timeplt')


def histogram():
    h = collections.Counter()
    for f in sorted(BUILD.glob('cover[0-9]*.pkl')):
        d = pickle.loads(f.read_bytes())
        h.update(d['pens'])
    return h


def palette(v=None):
    """-> (16 colours, pen map [384])"""
    v = v or Video()
    cols = [(0, 0, 0)] + gy.fit(histogram(), v.pens)
    return cols, gy.pen_map(cols, v.pens)


def turned(img):
    """T[row][col] = img[n - 1 - col][row]"""
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


def turned_sprites(v):
    out = bytearray()
    for code in range(256):
        t = turned(v.sprites[code])
        for img in (t, t[:, ::-1]):
            for w0, w1 in rows_bits(img, 16):
                out += w0.to_bytes(2, 'big') + w1.to_bytes(2, 'big')
    return bytes(out)


def turned_tiles(v):
    """4 variants (colour bits 6, 7: rows reversed, bits reversed) x 512 tiles x 8 rows x (pen bit 0, pen bit 1)"""
    out = bytearray()
    for var in range(4):
        for code in range(512):
            t = turned(v.tiles[code])
            if var & 1:
                t = t[::-1]
            if var & 2:
                t = t[:, ::-1]
            for w0, w1 in rows_bits(t, 8):
                out += bytes((w0, w1))
    return bytes(out)


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


def tile_converters(pmap):
    """tp_tconv: per tile colour (32) a routine that draws a tile's 8 rows (a0: its variant's rows, a1: the cell's first
    byte in the clean screen, a byte of each plane at 0, 2, 4, 6) in the colour's 4 STE colours"""
    lines, names, seen = [], [], {}
    for c in range(32):
        cols = tuple(int(pmap[4 * c + p]) for p in range(4))
        if cols not in seen:
            n = 'tconv_%d' % len(seen)
            seen[cols] = n
            lines.append(n + ':')
            for r in range(8):
                lines += ['\tmove.b (a0)+,d0', '\tmove.b (a0)+,d1']
                for pl in range(4):
                    tt = sum(1 << pen for pen in range(4) if cols[pen] >> pl & 1)
                    ops = PLANE_OPS[tt]
                    dst = '%d(a1)' % (2 * pl + 160 * r) if 2 * pl + 160 * r else '(a1)'
                    if ops is None:
                        lines.append('\tclr.b ' + dst)
                    elif ops == 'st':
                        lines.append('\tst ' + dst)
                    else:
                        lines += ['\t' + o for o in ops] + ['\tmove.b d2,' + dst]
            lines.append('\trts')
        names.append(seen[cols])
    return ['tp_tconv:\tdc.l ' + ','.join(names)] + lines


def shape_masks(v, code, fx, fy):
    """the turned sprite's 16 row masks for MAME's flips (flip x: the rows reversed, flip y: the bits)"""
    t = turned(v.sprites[code])
    if fx:
        t = t[::-1]
    if fy:
        t = t[:, ::-1]
    return [sum(1 << (15 - c) for c in range(16) if t[r, c]) for r in range(16)]


def coverage_shapes():
    seen = collections.Counter()
    for f in sorted(BUILD.glob('cover[0-9]*.pkl')):
        for (code, colour, fx, fy), n in pickle.loads(f.read_bytes())['sprites'].items():
            seen[(code, bool(fx), bool(fy))] += n
    return sorted(seen)


def sprite_programs(v):
    """engine/sprite_programs.py for the coverage's shapes (code << 2 | flip x << 1 | flip y): tp_shapes, the
    generated code (shp_*), the records (shr_*); the end mask streams -> tp_sstream"""
    shapes = {code << 2 | fx << 1 | fy: shape_masks(v, code, fx, fy) for code, fx, fy in coverage_shapes()}
    lines, stream, stats = sp.programs(shapes, 1024)
    print('generated code: %(routines)d routines (%(code_lines)d lines) for %(shapes)d shapes x 16 shifts x 3 clips; '
          'stream blocks %(stream_blocks)d, %(stream_bytes)d bytes' % stats)
    return lines, stream, stats['shapes']


def row_orders(v):
    """tp_order: per shape 16 bytes: the opaque rows in bake order (grouped by mask), $FF after the last"""
    return sp.order_table([shape_masks(v, code, fx, fy) for code in range(256) for fx in (0, 1) for fy in (0, 1)], 16)


def build():
    v = Video()
    cols, pmap = palette(v)
    (BUILD / 'tp_spr.bin').write_bytes(turned_sprites(v))
    (BUILD / 'tp_tiles.bin').write_bytes(turned_tiles(v))
    lines = ['; generated by games/timeplt/tools/assets.py: the colours and pen maps', '\tsection data,data',
             'tp_pal:\tdc.w ' + ','.join('$%03X' % gy.ste_word(c) for c in cols),
             'tp_spen:']
    lines += ['\tdc.b ' + ','.join(str(int(x)) for x in pmap[128 + i:128 + i + 16]) for i in range(0, 256, 16)]
    lines += ['tp_tpen:']
    lines += ['\tdc.b ' + ','.join(str(int(x)) for x in pmap[i:i + 16]) for i in range(0, 128, 16)]
    progs, stream, nshapes = sprite_programs(v)
    (BUILD / 'tp_sstream.bin').write_bytes(stream)
    (BUILD / 'tp_order.bin').write_bytes(row_orders(v))
    lines += ['\teven', '\tsection text,code'] + tile_converters(pmap) + progs + ['\tsection data,data']
    print('sprite shapes with generated code: %d, streams %d bytes' % (nshapes, len(stream)))
    (BUILD / 'tp_assets.s').write_text('\n'.join(lines) + '\n')
    (BUILD / 'tp_penmap.bin').write_bytes(bytes(int(x) for x in pmap))
    (BUILD / 'tp_colours.bin').write_bytes(bytes(c for col in cols for c in col))
    err = np.abs(np.array(cols, float)[pmap] - v.pens.astype(float))
    h = histogram()
    w = np.array([h.get(p, 0) for p in range(384)], float)
    print('colours', cols)
    print('mean error a channel (weighted by pixels): %.1f' % ((err.mean(1) * w).sum() / max(w.sum(), 1)))
    worst = sorted(((err[p].max(), p) for p in range(384) if w[p] > 0), reverse=True)[:8]
    print('worst pens (max channel error, pen, rgb -> ste):', [(int(e), p, tuple(int(x) for x in v.pens[p]),
                                                               cols[pmap[p]]) for e, p in worst])


if __name__ == '__main__':
    build()
