"""The STE port's graphics and colours (build/mario/, ROM-derived: never committed).

    python tools/assets.py

* tm_spr.bin: the 256 sprites (16 x 16, 3 bpp: the pens 0-7) unflipped: 16 rows of 8 bytes, two pens a byte (the left
  pixel in the high nibble): 128 bytes a sprite.
* tm_tiles.bin: the 512 tiles (8 x 8, 2 bpp: the pens 0-3; two banks of 256) unflipped: 8 rows of 4 bytes, two pens a
  byte: 32 bytes a tile.
* tm_assets.s: tm_pal (16 STE colours), tm_pen (256 bytes: the arcade pen, colour * 8 + pixel, bit 7 the palette
  bank -> colour index), tm_tclass (the sprite colours' transparency class: one, pen 0 of every colour is transparent)
  and the sprite shapes' generated code (engine/sprite_programs.py: a shape is (class, code, flips), the coverage's
  shapes; docs/sprite-preparation.md).
* tm_sstream.bin: the end mask streams.  The rows' order (grouped by mask) is computed again where a sprite is baked
  (src/render.s bake_sprite).

Colours: black and 15 fitted (engine/palette_quantize.py, the bounded flat fit of docs/palette-defaults.md) to the pens
of the coverage's pictures (ref/cover_pens.py: tiles and sprites counted apart), every pen mapped to one index; the
arcade shows up to 25 colours in a picture.
"""
from pathlib import Path
import collections
import pickle
import sys
import numpy as np
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import Gfx
from mario_pens import PENS
from paths import build_dir
import palette_quantize as PQ
import sprite_programs as sp

BUILD = build_dir('mario')
CODES = 256                                 # sprite codes (the key: code << 8 | colour << 2 | flip x << 1 | flip y)
PREFIX = 'tm'
SHARE = 1.0                                 # code for the most drawn shapes up to this share of the coverage's draws


def pens_rgb():
    return np.array([[(c >> 16) & 255, (c >> 8) & 255, c & 255] for c in PENS], np.uint8)


def coverage():
    tiles, sprites, shapes = collections.Counter(), collections.Counter(), collections.Counter()
    files = sorted(BUILD.glob('pens_[0-9]*.pkl'))
    if not files:
        sys.exit('no pens_*.pkl in %s: python games/mario/ref/cover_pens.py <seed> 12000 (seeds 1-6)' % BUILD)
    for f in files:
        d = pickle.loads(f.read_bytes())
        tiles.update(d['tiles'])
        sprites.update(d['sprites'])
        shapes.update(d['shapes'])
    return tiles, sprites, shapes


def ste_word(c):
    conv = lambda n: ((n >> 1) & 7) | ((n & 1) << 3)
    r, g, b = (int(v) // 17 for v in c)
    return (conv(r) << 8) | (conv(g) << 4) | conv(b)


def palette():
    """-> (16 colours, pen map [256], the coverage)"""
    tiles, sprites, shapes = coverage()
    rgb = pens_rgb()
    layers = [collections.Counter(), collections.Counter()]       # sprites, tiles (palette_quantize.balanced_weights)
    for layer, counts in zip(layers, (sprites, tiles)):
        for p, n in counts.items():
            layer[tuple(int(x) for x in rgb[p])] += n
    cols, pairs = PQ.fit(layers, rgb, cache=BUILD / 'palette_cache', dither=False)
    return [tuple(int(x) for x in c) for c in cols], (pairs >> 4).astype(np.uint8), (tiles, sprites, shapes)


def nibbles(img):
    out = bytearray()
    for row in img:
        for c in range(0, len(row), 2):
            out.append((int(row[c]) << 4) | int(row[c + 1]))
    return bytes(out)


def shape_masks(g, code, fx, fy):
    """the sprite's 16 row masks (bit 15 the leftmost pixel) for MAME's flips (flip x: the columns reversed, flip y: the
    rows), pen 0 transparent"""
    t = g.sprites[code % len(g.sprites)]
    if fx:
        t = t[:, ::-1]
    if fy:
        t = t[::-1]
    return [sum(1 << (15 - c) for c in range(16) if int(t[r, c]) != 0) for r in range(16)]


def shape_id(k, code, fx, fy):
    return (k * CODES + code) << 2 | int(fx) << 1 | int(fy)


def coverage_shapes(shapes, share=1.0):
    """the coverage's shapes (code, flip x, flip y), the most drawn first, up to `share` of the draws"""
    seen = collections.Counter()
    for (code, colour, fx, fy), n in shapes.items():
        seen[(code % CODES, bool(fx), bool(fy))] += n
    total, acc, out = sum(seen.values()), 0, []
    for k, n in seen.most_common():
        if share < 1 and acc >= share * total:
            break
        out.append(k)
        acc += n
    return sorted(out), acc / max(total, 1)


def sprite_programs(g, shapes_seen):
    """-> (assembler lines: the class table, the generated code and records; the streams)"""
    keys, got = coverage_shapes(shapes_seen, SHARE)
    shapes = {shape_id(0, code, fx, fy): shape_masks(g, code, fx, fy) for code, fx, fy in keys}
    progs, stream, st = sp.programs(shapes, CODES * 4, table=PREFIX + '_shapes', stream_sym=PREFIX + '_sstream')
    print('generated code: %%(routines)d routines (%%(code_lines)d lines) for %%(shapes)d shapes x 16 shifts x 3 clips '
          '(%.1f%%%% of the draws); stream blocks %%(stream_blocks)d, %%(stream_bytes)d bytes' % (100 * got) % st)
    lines = ['%s_tclass:\tdc.b %s' % (PREFIX, ','.join('0' for _ in range(32))), '\teven'] + progs + ['\tsection data,data']
    return lines, stream


def build():
    g = Gfx()
    cols, pmap, (tiles, sprites, shapes_seen) = palette()
    assert g.sprites.shape[0] == 256 and g.chars.shape[0] == 512, (g.sprites.shape, g.chars.shape)
    (BUILD / 'tm_spr.bin').write_bytes(b''.join(nibbles(g.sprites[c]) for c in range(256)))
    (BUILD / 'tm_tiles.bin').write_bytes(b''.join(nibbles(g.chars[c]) for c in range(512)))
    lines = ['; generated by games/mario/tools/assets.py: the colours and the pen map', '\tsection data,data',
             'tm_pal:\tdc.w ' + ','.join('$%03X' % ste_word(c) for c in cols), 'tm_pen:']
    lines += ['\tdc.b ' + ','.join(str(int(x)) for x in pmap[i:i + 16]) for i in range(0, 256, 16)]
    lines += ['\teven']
    progs, stream = sprite_programs(g, shapes_seen)
    lines += progs
    (BUILD / 'tm_sstream.bin').write_bytes(stream)
    (BUILD / 'tm_assets.s').write_text('\n'.join(lines) + '\n')
    (BUILD / 'tm_penmap.bin').write_bytes(bytes(int(x) for x in pmap))
    (BUILD / 'tm_colours.bin').write_bytes(bytes(c for col in cols for c in col))
    rgb = pens_rgb()
    err = np.abs(np.array(cols, float)[pmap] - rgb.astype(float))
    w = np.array([tiles.get(p, 0) + sprites.get(p, 0) for p in range(256)], float)
    print('colours', cols)
    print('mean error a channel (weighted by pixels): %.1f' % ((err.mean(1) * w).sum() / max(w.sum(), 1)))
    worst = sorted(((err[p].max(), p) for p in range(256) if w[p] > 0), reverse=True)[:8]
    print('worst pens (max channel error, pen, rgb -> ste):', [(int(e), p, tuple(int(x) for x in rgb[p]),
                                                               cols[pmap[p]]) for e, p in worst])


if __name__ == '__main__':
    build()
