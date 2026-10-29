"""The STE port's graphics and colours (build/pooyan/, ROM-derived: never committed).

    python tools/assets.py

The picture is turned as MAME's ROT90 turns it: picture pixel (X, Y), X 0-223, Y 0-255, is the arcade's raw pixel
(x = Y, y = 239 - X); a turned image T[row][col] = raw[n - 1 - col][row].
* py_spr.bin: the 64 sprites turned, unflipped: 16 rows, a row four words (the pens' bits 0-3; the leftmost pixel the
  MSB), then the same 16 rows with the bits reversed (MAME's flip y): 256 bytes a sprite.  MAME's flip x (attribute
  bit 6 clear) reverses the rows.
* py_tiles.bin: the 256 tiles turned, in 4 variants (colour RAM bits 6-7: raw flip x reverses the rows, raw flip y the
  columns): 8 rows, a row four bytes (the pens' bits 0-3): 32 bytes a tile, variant * 256 + code.
* py_assets.s: py_pal (16 STE colours), py_spen (256 bytes: sprite colour * 16 + pen -> colour index, $FF where the
  pen is transparent: its lookup entry is colour 0), py_tpen (256 bytes: tile colour * 16 + pen -> colour index),
  py_tclass (16 bytes: sprite colour -> its transparency class), the generated sprite code (engine/sprite_programs.py:
  py_shapes, shape = class << 8 | code << 2 | flip x << 1 | flip y), py_order.bin (per shape the opaque rows grouped
  by mask, 16 bytes), py_sstream.bin (the end mask streams).

Colours: Pooyan's PROM has 19 colours and the pictures show 17 (ref/cover.py's pens): colour 0 is black (the side
bands and the borders), 1-15 the 15 most frequent; every pen maps to the nearest in Oklab (the two left out are drawn
on 0.003% of the pixels).
"""
from pathlib import Path
import collections
import pickle
import sys
import numpy as np
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import Video
from paths import build_dir
import sprite_programs as sp

BUILD = build_dir('pooyan')


def histogram():
    h = collections.Counter()
    for f in sorted(BUILD.glob('cover[0-9]*.pkl')):
        h.update(pickle.loads(f.read_bytes())['pens'])
    return h


def oklab(rgb):
    c = np.asarray(rgb, float) / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929], [0.2119034982, 0.6806995451, 0.1073969566],
                   [0.0883024619, 0.2817188376, 0.6299787005]])
    m2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468], [1.9779984951, -2.4285922050, 0.4505937099],
                   [0.0259040371, 0.7827717662, -0.8086757660]])
    return np.cbrt(c @ m1.T) @ m2.T


def ste4(v):
    """an 8-bit gun -> the STE's 4 bits (0-15)"""
    return int(round(v * 15 / 255))


def ste_word(rgb):
    """the STE palette word: per gun its 4 bits, the lowest bit as bit 3 (the STE's order)"""
    w = 0
    for v in rgb:
        n = ste4(v)
        w = (w << 4) | ((n >> 1) | ((n & 1) << 3))
    return w


def palette(v=None):
    """-> (16 colours (8-bit RGB, as the STE shows them), pen map [512])"""
    v = v or Video()
    h = histogram()
    by_rgb = collections.Counter()
    for p, n in h.items():
        by_rgb[tuple(int(x) for x in v.pens[p])] += n
    seen = [c for c, _ in by_rgb.most_common() if c != (0, 0, 0)]
    cols = [(0, 0, 0)] + seen[:15]
    while len(cols) < 16:
        cols.append((0, 0, 0))
    shown = [tuple(ste4(x) * 17 for x in c) for c in cols]
    lab = oklab(shown)
    pens = oklab(v.pens)
    pmap = np.array([int(np.argmin(((lab - pens[p]) ** 2).sum(1))) for p in range(len(v.pens))])
    return shown, pmap, cols


def turned(img):
    """T[row][col] = img[n - 1 - col][row]"""
    return np.rot90(img, -1)


def plane_words(img, width):
    """per row the 4 pen bit planes, the leftmost pixel the most significant bit"""
    out = []
    for r in range(img.shape[0]):
        w = [0, 0, 0, 0]
        for c in range(width):
            for bit in range(4):
                w[bit] |= ((int(img[r, c]) >> bit) & 1) << (width - 1 - c)
        out.append(w)
    return out


def turned_sprites(v):
    out = bytearray()
    for code in range(64):
        t = turned(v.sprites[code])
        for img in (t, t[:, ::-1]):
            for w in plane_words(img, 16):
                out += b''.join(x.to_bytes(2, 'big') for x in w)
    return bytes(out)


def turned_tiles(v):
    out = bytearray()
    for var in range(4):
        for code in range(256):
            t = turned(v.tiles[code])
            if var & 1:
                t = t[::-1]
            if var & 2:
                t = t[:, ::-1]
            for w in plane_words(t, 8):
                out += bytes(w)
    return bytes(out)


def transparency(v):
    """-> (per sprite colour its class, per class the transparent pens' set)"""
    sets, cls = [], []
    for c in range(16):
        t = frozenset(p for p in range(16) if v.pen_colour[256 + 16 * c + p] == 0)
        if t not in sets:
            sets.append(t)
        cls.append(sets.index(t))
    return cls, sets


def shape_masks(v, code, fx, fy, tset):
    """the turned sprite's 16 row masks for MAME's flips (flip x: the rows reversed, flip y: the bits), the pens in
    tset transparent"""
    t = turned(v.sprites[code])
    if fx:
        t = t[::-1]
    if fy:
        t = t[:, ::-1]
    return [sum(1 << (15 - c) for c in range(16) if int(t[r, c]) not in tset) for r in range(16)]


def coverage_shapes(cls):
    seen = set()
    for f in sorted(BUILD.glob('cover[0-9]*.pkl')):
        for (code, colour, fx, fy) in pickle.loads(f.read_bytes())['sprites']:
            seen.add((cls[colour], code & 63, bool(fx), bool(fy)))
    return sorted(seen)


def shape_id(k, code, fx, fy):
    return k << 8 | code << 2 | int(fx) << 1 | int(fy)


def build():
    v = Video()
    shown, pmap, cols = palette(v)
    cls, sets = transparency(v)
    (BUILD / 'py_spr.bin').write_bytes(turned_sprites(v))
    (BUILD / 'py_tiles.bin').write_bytes(turned_tiles(v))
    spen = [0xFF if v.pen_colour[256 + i] == 0 else int(pmap[256 + i]) for i in range(256)]
    tpen = [int(pmap[i]) for i in range(256)]
    lines = ['; generated by games/pooyan/tools/assets.py: the colours, pen maps and sprite code', '\tsection data,data',
             'py_pal:\tdc.w ' + ','.join('$%03X' % ste_word(c) for c in shown), 'py_spen:']
    lines += ['\tdc.b ' + ','.join(str(x) for x in spen[i:i + 16]) for i in range(0, 256, 16)]
    lines += ['py_tpen:']
    lines += ['\tdc.b ' + ','.join(str(x) for x in tpen[i:i + 16]) for i in range(0, 256, 16)]
    lines += ['py_tclass:\tdc.b ' + ','.join(str(k) for k in cls), '\teven',
              'PY_CLASSES = %d' % len(sets)]
    shapes = {shape_id(k, code, fx, fy): shape_masks(v, code, fx, fy, sets[k])
              for k, code, fx, fy in coverage_shapes(cls)}
    progs, stream, st = sp.programs(shapes, len(sets) * 256, table='py_shapes', stream_sym='py_sstream')
    print('generated code: %(routines)d routines (%(code_lines)d lines) for %(shapes)d shapes x 16 shifts x 3 clips; '
          'stream blocks %(stream_blocks)d, %(stream_bytes)d bytes' % st)
    order = sp.order_table([shape_masks(v, code, fx, fy, sets[k]) for k in range(len(sets)) for code in range(64)
                            for fx in (0, 1) for fy in (0, 1)], 16)
    (BUILD / 'py_order.bin').write_bytes(order)
    (BUILD / 'py_sstream.bin').write_bytes(stream)
    lines += progs + ['\tsection data,data']
    (BUILD / 'py_assets.s').write_text('\n'.join(lines) + '\n')
    (BUILD / 'py_penmap.bin').write_bytes(bytes(int(x) for x in pmap))
    (BUILD / 'py_colours.bin').write_bytes(bytes(c for col in shown for c in col))
    h = histogram()
    w = np.array([h.get(p, 0) for p in range(512)], float)
    err = np.abs(np.array(shown, float)[pmap] - v.pens.astype(float))
    print('transparency classes:', [sorted(s) for s in sets], 'colours ->', cls)
    print('palette (as shown):', shown)
    print('mean error a channel (weighted by pixels): %.2f' % ((err.mean(1) * w).sum() / max(w.sum(), 1)))
    worst = sorted(((err[p].max(), p) for p in range(512) if w[p] > 0), reverse=True)[:5]
    print('worst seen pens (max channel error, pen, rgb -> ste):',
          [(int(e), p, tuple(int(x) for x in v.pens[p]), shown[pmap[p]]) for e, p in worst])


if __name__ == '__main__':
    build()
