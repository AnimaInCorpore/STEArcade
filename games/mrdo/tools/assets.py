"""The STE port's graphics and colours (build/mrdo/, ROM-derived: never committed).

    python tools/assets.py

The picture is turned as MAME's ROT270 turns it (machine.MrDo.render_rgb): picture pixel (X, Y), X 0-191, Y 0-239,
is the arcade's raw pixel (x = 247 - Y, y = 32 + X); a turned image T[row][col] = raw[col][n - 1 - row] (np.rot90 by
+90 degrees).
* md_tiles.bin: the 1024 characters turned (the foreground's 512, then the background's): 8 rows, a row two longs (the
  pens' bit 0 in each of the four bytes, then bit 1; the leftmost pixel the MSB of each byte): 64 bytes a character,
  so a row's four STE planes come from long operations (render.s tile_conv).
* md_spr.bin: the 128 sprites turned, unflipped: 16 rows, a row two words (the pens' bit 0, then bit 1), then the same
  16 rows with the bits reversed (raw flip y, attribute bit 5): 128 bytes a sprite.  Raw flip x (bit 4) reverses the
  rows.
* md_assets.s: md_pal (16 STE colours), md_cpen (256 bytes: character pen -> colour index), md_spen (64 bytes: sprite
  colour * 4 + pen -> colour index), the sprite shapes' generated code (engine/sprite_programs.py).
* md_order.bin, md_sstream.bin: the shapes' row orders and end mask streams.

Colours: black and 15 fitted by a weighted k-means in Oklab (Gyruss's tools/assets.py) to the reference's pens
(ref/pens.py: the title, intermissions, every scene), the pixel counts' square roots as weights (with the counts
themselves the rare pure blue of the sprites goes to a dull blue and orange to ochre; with lower powers the two reds
merge).  The arcade shows 26 colours in all, at most 15 in a picture.
"""
from pathlib import Path
import collections
import importlib.util
import pickle
import sys
import numpy as np
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import Gfx
from paths import build_dir
import sprite_programs as sp

BUILD = build_dir('mrdo')
WEIGHT_POWER = 0.5


def _gyruss_assets():
    """Gyruss's fit / pen_map / ste_word (its module imports its own machine.py)"""
    gdir = Path(__file__).resolve().parents[2] / 'gyruss' / 'tools'
    spec = importlib.util.spec_from_file_location('gy_assets', gdir / 'assets.py')
    mod = importlib.util.module_from_spec(spec)
    saved = sys.modules.pop('machine', None)
    sys.path.insert(0, str(gdir))
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(gdir))
        sys.modules.pop('machine', None)
        if saved is not None:
            sys.modules['machine'] = saved
    return mod


gy = _gyruss_assets()


def histogram():
    h = collections.Counter()
    files = sorted(BUILD.glob('pens[0-9]*.pkl'))
    if not files:
        raise SystemExit('no build/mrdo/pens<seed>.pkl: run ref/pens.py for seeds 7, 10, 11, 12')
    for f in files:
        h.update(pickle.loads(f.read_bytes())['pens'])
    return h


def palette(g=None):
    """-> (16 colours, pen map [320])"""
    g = g or Gfx()
    pens = g.rgb[:320].astype(int)
    h = histogram()
    cols = [(0, 0, 0)] + gy.fit(collections.Counter({p: int(n ** WEIGHT_POWER) + 1 for p, n in h.items()}), pens)
    return cols, gy.pen_map(cols, pens)


def turned(img):
    """T[row][col] = img[col][n - 1 - row] (ROT270)"""
    return np.rot90(img, 1)


def rows_bits(img, width):
    out = []
    for r in range(img.shape[0]):
        w = [0, 0]
        for c in range(width):
            for bit in (0, 1):
                w[bit] |= ((int(img[r, c]) >> bit) & 1) << (width - 1 - c)
        out.append(w)
    return out


def turned_tiles(g):
    """the foreground's 512 characters, then the background's: 8 rows of (bit 0 in 4 bytes, bit 1 in 4 bytes)"""
    out = bytearray()
    for chars in (g.fg_chars, g.bg_chars):
        for code in range(512):
            for b0, b1 in rows_bits(turned(chars[code]), 8):
                out += bytes((b0,) * 4 + (b1,) * 4)
    return bytes(out)


def turned_sprites(g):
    out = bytearray()
    for code in range(128):
        t = turned(g.sprites[code])
        for img in (t, t[:, ::-1]):
            for w0, w1 in rows_bits(img, 16):
                out += w0.to_bytes(2, 'big') + w1.to_bytes(2, 'big')
    return bytes(out)


def shape_masks(g, code, fx, fy):
    """the turned sprite's 16 row masks for the raw flips (flip x, attribute bit 4: the rows reversed; flip y, bit 5:
    the bits)"""
    t = turned(g.sprites[code])
    if fx:
        t = t[::-1]
    if fy:
        t = t[:, ::-1]
    return [sum(1 << (15 - c) for c in range(16) if t[r, c]) for r in range(16)]


def coverage_shapes():
    seen = collections.Counter()
    files = sorted(BUILD.glob('cover[0-9]*.pkl'))
    if not files:
        raise SystemExit('no build/mrdo/cover<seed>.pkl: run ref/cover.py first')
    for f in files:
        for (code, attr), n in pickle.loads(f.read_bytes())['sprites'].items():
            seen[(code & 0x7F, attr >> 4 & 1, attr >> 5 & 1)] += n
    return sorted(seen)


def sprite_programs(g):
    """engine/sprite_programs.py for the coverage's shapes (code << 2 | flip x << 1 | flip y): md_shapes, the
    generated code (shp_*), the records (shr_*); the end mask streams -> md_sstream"""
    shapes = {code << 2 | fx << 1 | fy: shape_masks(g, code, fx, fy) for code, fx, fy in coverage_shapes()}
    lines, stream, stats = sp.programs(shapes, 512, table='md_shapes', stream_sym='md_sstream')
    print('generated code: %(routines)d routines (%(code_lines)d lines) for %(shapes)d shapes x 16 shifts x 3 clips; '
          'stream blocks %(stream_blocks)d, %(stream_bytes)d bytes' % stats)
    return lines, stream


def row_orders(g):
    """md_order: per shape 16 bytes: the opaque rows in bake order (grouped by mask), $FF after the last"""
    return sp.order_table([shape_masks(g, code, fx, fy) for code in range(128) for fx in (0, 1) for fy in (0, 1)], 16)


def build():
    g = Gfx()
    cols, pmap = palette(g)
    (BUILD / 'md_tiles.bin').write_bytes(turned_tiles(g))
    (BUILD / 'md_spr.bin').write_bytes(turned_sprites(g))
    (BUILD / 'md_order.bin').write_bytes(row_orders(g))
    progs, stream = sprite_programs(g)
    (BUILD / 'md_sstream.bin').write_bytes(stream)
    lines = ['; generated by games/mrdo/tools/assets.py: the colours and pen maps, the sprite shapes\' code',
             '\tsection data,data',
             'md_pal:\tdc.w ' + ','.join('$%03X' % gy.ste_word(c) for c in cols), 'md_cpen:']
    lines += ['\tdc.b ' + ','.join(str(int(x)) for x in pmap[i:i + 16]) for i in range(0, 256, 16)]
    lines += ['md_spen:']
    lines += ['\tdc.b ' + ','.join(str(int(x)) for x in pmap[256 + i:256 + i + 16]) for i in range(0, 64, 16)]
    lines += ['\teven'] + progs + ['\tsection data,data']
    (BUILD / 'md_assets.s').write_text('\n'.join(lines) + '\n')
    (BUILD / 'md_penmap.bin').write_bytes(bytes(int(x) for x in pmap))
    (BUILD / 'md_colours.bin').write_bytes(bytes(c for col in cols for c in col))
    h = histogram()
    pens = g.rgb[:320].astype(float)
    err = np.abs(np.array(cols, float)[pmap] - pens)
    w = np.array([h.get(p, 0) for p in range(320)], float)
    print('colours', cols)
    print('mean error a channel (weighted by pixels): %.1f' % ((err.mean(1) * w).sum() / max(w.sum(), 1)))
    worst = sorted(((err[p].max(), p) for p in range(320) if w[p] > 0), reverse=True)[:6]
    print('worst pens (max channel error, pen, rgb -> ste):', [(int(e), p, tuple(int(x) for x in pens[p]),
                                                               cols[pmap[p]]) for e, p in worst])


if __name__ == '__main__':
    build()
