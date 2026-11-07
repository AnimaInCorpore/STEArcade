"""The STE port's graphics and colours (build/yiear/, ROM-derived: never committed).

    python tools/assets.py

* ya_spr.bin: the 512 sprites (16 x 16, 4 bpp) unflipped: 16 rows of 8 bytes, two pens a byte (the left pixel in the
  high nibble): 128 bytes a sprite.
* ya_tiles.bin: the 512 tiles (8 x 8, 4 bpp) unflipped: 8 rows of 4 bytes, two pens a byte: 32 bytes a tile.
* ya_assets.s: ya_pal (16 STE colours), ya_pen (32 bytes: the arcade pen 0-15 the sprites', 16-31 the tiles' -> colour
  index), ya_tclass (one transparency class: pen 0 is transparent) and the sprite shapes' generated code
  (engine/sprite_programs.py: a shape is (class, code, flips), the coverage's shapes; docs/sprite-preparation.md).
* ya_sstream.bin: the end mask streams.  The rows' order (grouped by mask) is computed again where a sprite is baked
  (src/render.s bake_sprite).

Colours: black and 15 fitted (engine/palette_quantize.py, the bounded flat fit of docs/colours.md) to the pens of the
coverage's pictures (ref/cover.py's `pens`, sprites and tiles counted apart), every pen mapped to one index; the
arcade's palette PROM has 32 entries, the tiles use 16 of them and the sprites 16.
"""
from pathlib import Path
import collections
import pickle
import sys
import numpy as np
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import Video
from paths import build_dir
import palette_quantize as PQ
import sprite_programs as sp

BUILD = build_dir('yiear')
CODES = 512                                 # sprite codes (the key: code << 8 | colour << 2 | flip x << 1 | flip y)
PREFIX = 'ya'
SHARE = 1.0                                 # code for the most drawn shapes up to this share of the coverage's draws


def coverage():
    pens, shapes = collections.Counter(), collections.Counter()
    files = sorted(BUILD.glob('cover[0-9]*.pkl'))
    if not files:
        sys.exit('no cover*.pkl in %s: python port.py cover yiear' % BUILD)
    for f in files:
        d = pickle.loads(f.read_bytes())
        pens.update(d['pens'])
        shapes.update(d['sprites'])
    return pens, shapes


def ste_word(c):
    conv = lambda n: ((n >> 1) & 7) | ((n & 1) << 3)
    r, g, b = (int(v) // 17 for v in c)
    return (conv(r) << 8) | (conv(g) << 4) | conv(b)


def palette(v):
    """-> (16 colours, pen map [32], the coverage)"""
    pens, shapes = coverage()
    rgb = v.pens
    layers = [collections.Counter(), collections.Counter()]       # sprites (pens 0-15), tiles (16-31)
    for p, n in pens.items():
        layers[0 if p < 16 else 1][tuple(int(x) for x in rgb[p])] += n
    cols, pairs = PQ.fit(layers, rgb, cache=BUILD / 'palette_cache', dither=False)
    return [tuple(int(x) for x in c) for c in cols], (pairs >> 4).astype(np.uint8), (pens, shapes)


def nibbles(img):
    out = bytearray()
    for row in img:
        for c in range(0, len(row), 2):
            out.append((int(row[c]) << 4) | int(row[c + 1]))
    return bytes(out)


def shape_masks(v, code, fx, fy):
    """the sprite's 16 row masks (bit 15 the leftmost pixel) for MAME's flips (flip x: the columns reversed, flip y: the
    rows), pen 0 transparent"""
    t = v.sprites[code % len(v.sprites)]
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
    for (code, fx, fy), n in shapes.items():
        seen[(code % CODES, bool(fx), bool(fy))] += n
    total, acc, out = sum(seen.values()), 0, []
    for k, n in seen.most_common():
        if share < 1 and acc >= share * total:
            break
        out.append(k)
        acc += n
    return sorted(out), acc / max(total, 1)


def sprite_programs(v, shapes_seen):
    """-> (assembler lines: the class table, the generated code and records; the streams)"""
    keys, got = coverage_shapes(shapes_seen, SHARE)
    shapes = {shape_id(0, code, fx, fy): shape_masks(v, code, fx, fy) for code, fx, fy in keys}
    progs, stream, st = sp.programs(shapes, CODES * 4, table=PREFIX + '_shapes', stream_sym=PREFIX + '_sstream')
    print('generated code: %%(routines)d routines (%%(code_lines)d lines) for %%(shapes)d shapes x 16 shifts x 3 clips '
          '(%.1f%%%% of the draws); stream blocks %%(stream_blocks)d, %%(stream_bytes)d bytes' % (100 * got) % st)
    lines = ['%s_tclass:\tdc.b %s' % (PREFIX, ','.join('0' for _ in range(32))), '\teven'] + progs + ['\tsection data,data']
    return lines, stream


def build():
    v = Video()
    cols, pmap, (pens, shapes_seen) = palette(v)
    assert v.sprites.shape[0] == 512 and v.tiles.shape[0] == 512, (v.sprites.shape, v.tiles.shape)
    (BUILD / 'ya_spr.bin').write_bytes(b''.join(nibbles(v.sprites[c]) for c in range(512)))
    (BUILD / 'ya_tiles.bin').write_bytes(b''.join(nibbles(v.tiles[c]) for c in range(512)))
    lines = ['; generated by games/yiear/tools/assets.py: the colours and the pen map', '	section data,data',
             'ya_pal:	dc.w ' + ','.join('$%03X' % ste_word(c) for c in cols), 'ya_pen:']
    lines += ['	dc.b ' + ','.join(str(int(x)) for x in pmap[i:i + 16]) for i in range(0, 32, 16)]
    lines += ['	even']
    progs, stream = sprite_programs(v, shapes_seen)
    lines += progs
    (BUILD / 'ya_sstream.bin').write_bytes(stream)
    (BUILD / 'ya_assets.s').write_text(chr(10).join(lines) + chr(10))
    (BUILD / 'ya_penmap.bin').write_bytes(bytes(int(x) for x in pmap))
    (BUILD / 'ya_colours.bin').write_bytes(bytes(c for col in cols for c in col))
    rgb = v.pens
    err = np.abs(np.array(cols, float)[pmap] - rgb.astype(float))
    w = np.array([pens.get(p, 0) for p in range(32)], float)
    print('colours', cols)
    print('mean error a channel (weighted by pixels): %.1f' % ((err.mean(1) * w).sum() / max(w.sum(), 1)))
    worst = sorted(((err[p].max(), p) for p in range(32) if w[p] > 0), reverse=True)[:8]
    print('worst pens (max channel error, pen, rgb -> ste):', [(int(e), p, tuple(int(x) for x in rgb[p]),
                                                               cols[pmap[p]]) for e, p in worst])


if __name__ == '__main__':
    build()
