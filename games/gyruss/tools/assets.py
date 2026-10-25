"""The STE port's graphics and colours (build/gyruss/, ROM-derived: never committed).

    python tools/assets.py

The picture is turned as MAME's ROT90 turns it: picture pixel (X, Y), X 0-223, Y 0-255, is the arcade's raw pixel
(x = Y, y = 239 - X).  So a sprite (raw 8 x 16) is 16 pixels wide and 8 high on the STE, a tile 8 x 8 (rows of the
picture are raw columns):
* gy_spr.bin: the 512 sprites (bank * 256 + code) turned, unflipped: 8 rows of 16 pixels, a nibble a pixel (the high
  nibble first, the leftmost pixel first): 64 bytes a sprite.  Raw flip x reverses the rows, raw flip y the columns.
* gy_tiles.bin: the 512 tiles turned, unflipped: 8 rows, a row two bytes (the pens' bit 0, then bit 1; the leftmost
  pixel the MSB): 16 bytes a tile.  Raw flip x (colour bit 6) reverses the rows, raw flip y (bit 7) the columns.
* gy_assets.s: gy_pal (16 STE colours), gy_spen (256 bytes: sprite pen colour * 16 + pen -> colour index),
  gy_tpen (64 bytes: tile pen colour * 4 + pen -> colour index).

Colours: black and 15 fitted by a weighted k-means in Oklab (as Kung-Fu Master's tools/assets.py) to the reference pictures' pens
of the coverage runs (ref/cover.py's `pens`), snapped to the STE's 4 bits a gun; every pen maps to the nearest (black
only for black).  The arcade shows 28 colours (a 32-entry PROM).
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

BUILD = build_dir('gyruss')


def oklab(c):
    """sRGB 0-255 -> Oklab"""
    c = np.asarray(c, float) / 255
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929], [0.2119034982, 0.6806995451, 0.1073969566],
                   [0.0883024619, 0.2817188376, 0.6299787005]])
    m2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468], [1.9779984951, -2.4285922050, 0.4505937099],
                   [0.0259707400, 0.7827717716, -0.8086757660]])
    return np.cbrt(lin @ m1.T) @ m2.T


GRID = np.array([[r * 17, g * 17, b * 17] for r in range(16) for g in range(16) for b in range(16)])
GRID_LAB = oklab(GRID)


def fit(counter, pens, k=15, starts=20):
    """15 colours (4 bits a gun) for the pens' pixel counts, besides black: weighted k-means in Oklab"""
    cols = {}
    for p, n in counter.items():
        c = tuple(int(x) for x in pens[p])
        if c != (0, 0, 0):
            cols[c] = cols.get(c, 0) + n
    if not cols:
        return [(0, 0, 0)] * k
    rgb = np.array(list(cols), float)
    w = np.array(list(cols.values()), float)
    lab = oklab(rgb)
    if len(rgb) <= k:
        cen = lab.copy()
    else:
        rng = np.random.default_rng(3)
        best = None
        for _ in range(starts):
            c = lab[rng.choice(len(lab), k, replace=False, p=w / w.sum())]
            for _ in range(60):
                a = ((lab[:, None] - c[None]) ** 2).sum(2).argmin(1)
                for j in range(k):
                    if (a == j).any():
                        c[j] = (lab[a == j] * w[a == j, None]).sum(0) / w[a == j].sum()
            cost = (np.sqrt(((lab[:, None] - c[None]) ** 2).sum(2).min(1)) * w).sum()
            if best is None or cost < best[0]:
                best = (cost, c.copy())
        cen = best[1]
    out = []
    for c in cen:                            # snapped to the STE's grid (not black: that is colour 0)
        d = ((GRID_LAB - c) ** 2).sum(1)
        d[0] = 1e9
        g = tuple(int(x) for x in GRID[d.argmin()])
        if g not in out:
            out.append(g)
    while len(out) < k:
        out.append(out[-1])
    return sorted(out, key=lambda c: oklab([c])[0][0])


def pen_map(colours, pens):
    """each pen -> the nearest colour index (Oklab); black pens -> 0"""
    lab = oklab(np.array(colours, float))
    pl = oklab(np.asarray(pens, float))
    idx = ((pl[:, None] - lab[None]) ** 2).sum(2).argmin(1)
    idx[np.all(np.asarray(pens) == 0, axis=1)] = 0
    return idx.astype(np.uint8)


def ste_word(c):
    conv = lambda n: ((n >> 1) & 7) | ((n & 1) << 3)
    r, g, b = (int(v) // 17 for v in c)
    return (conv(r) << 8) | (conv(g) << 4) | conv(b)



def histogram():
    h = collections.Counter()
    for f in sorted(BUILD.glob('cover[0-9]*.pkl')):
        d = pickle.loads(f.read_bytes())
        if d.get('seed', 0) < 90:
            h.update(d['pens'])
    return h


def palette(v=None):
    """-> (16 colours, pen map [320])"""
    v = v or Video()
    cols = [(0, 0, 0)] + fit(histogram(), v.pens)
    return cols, pen_map(cols, v.pens)


def turned_sprites(v):
    out = bytearray()
    for bank in (0, 1):
        for code in range(256):
            img = np.rot90(v.sprites[bank][code], -1)          # [8 rows][16]
            assert img.shape == (8, 16)
            for r in range(8):
                for c in range(0, 16, 2):
                    out.append(int(img[r, c]) << 4 | int(img[r, c + 1]))
    return bytes(out)


def turned_tiles(v):
    out = bytearray()
    for code in range(512):
        img = np.rot90(v.tiles[code], -1)
        assert img.shape == (8, 8)
        for r in range(8):
            for bit in (0, 1):
                b = 0
                for c in range(8):
                    b |= ((int(img[r, c]) >> bit) & 1) << (7 - c)
                out.append(b)
    return bytes(out)


def shape_masks(v, bank, code, fx, fy):
    """the turned sprite's 8 row masks (16 bits) for the raw flips (flip x: the rows reversed, flip y: the bits)"""
    t = np.rot90(v.sprites[bank][code], -1)
    if fx:
        t = t[::-1]
    if fy:
        t = t[:, ::-1]
    return [sum(1 << (15 - c) for c in range(16) if t[r, c]) for r in range(8)]


def coverage_shapes():
    """the shapes (bank, code, raw flip x, raw flip y) the coverage drew"""
    seen = set()
    for f in sorted(BUILD.glob('cover[0-9]*.pkl')):
        d = pickle.loads(f.read_bytes())
        if d.get('seed', 0) < 90:
            for bank, code, colour, fx, fy in d['sprites']:
                seen.add((bank, code, bool(fx), bool(fy)))
    return sorted(seen)


def sprite_programs(v):
    """engine/sprite_programs.py for the coverage's shapes (shape = the cache key >> 4: bank << 10 | code << 2 |
    flip x << 1 | flip y): gy_shapes, the generated code, the records; the end mask streams -> gy_sstream.bin"""
    shapes = {b << 10 | c << 2 | fx << 1 | fy: shape_masks(v, b, c, fx, fy) for b, c, fx, fy in coverage_shapes()}
    lines, stream, stats = sp.programs(shapes, 2048, prefix='gshp', table='gy_shapes', record='gshr',
                                       stream_sym='gy_sstream')
    print('generated code: %(routines)d routines (%(code_lines)d lines) for %(shapes)d shapes x 16 shifts x 3 clips; '
          'stream blocks %(stream_blocks)d, %(stream_bytes)d bytes' % stats)
    order = sp.order_table([shape_masks(v, b, c, fx, fy) for b in (0, 1) for c in range(256) for fx in (0, 1)
                            for fy in (0, 1)], 8)
    return lines, stream, order


def build():
    v = Video()
    cols, pmap = palette(v)
    (BUILD / 'gy_spr.bin').write_bytes(turned_sprites(v))
    (BUILD / 'gy_tiles.bin').write_bytes(turned_tiles(v))
    lines = ['; generated by games/gyruss/tools/assets.py: the colours and pen maps', '\tsection data,data',
             'gy_pal:\tdc.w ' + ','.join('$%03X' % ste_word(c) for c in cols),
             'gy_spen:']
    lines += ['\tdc.b ' + ','.join(str(int(x)) for x in pmap[i:i + 16]) for i in range(0, 256, 16)]
    lines += ['gy_tpen:']
    lines += ['\tdc.b ' + ','.join(str(int(x)) for x in pmap[256 + i:256 + i + 16]) for i in range(0, 64, 16)]
    lines += ['\teven']
    progs, stream, order = sprite_programs(v)
    (BUILD / 'gy_sstream.bin').write_bytes(stream)
    (BUILD / 'gy_order.bin').write_bytes(order)
    lines += progs + ['\tsection data,data']
    (BUILD / 'gy_assets.s').write_text('\n'.join(lines) + '\n')
    (BUILD / 'gy_penmap.bin').write_bytes(bytes(int(x) for x in pmap))
    err = np.abs(np.array(cols, float)[pmap] - v.pens.astype(float))
    h = histogram()
    w = np.array([h.get(p, 0) for p in range(320)], float)
    print('colours', cols)
    print('mean error a channel (weighted by pixels): %.1f' % ((err.mean(1) * w).sum() / max(w.sum(), 1)))


if __name__ == '__main__':
    build()
