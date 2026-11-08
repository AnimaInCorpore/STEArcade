"""The STE port's graphics and colours (build/sbasketb/, ROM-derived: never committed).

    python tools/assets.py

The picture is turned as MAME's ROT90 turns it: picture pixel (X, Y), X 0-223, Y 0-255, is the arcade's raw pixel
(x = Y, y = 239 - X); a turned image T[row][col] = raw[n - 1 - col][row] (n = 16 for sprites, 8 for tiles).
* sb_spr.bin: the 384 sprites turned and unflipped: 16 rows of 8 bytes, two pens a byte (the left pixel in the high
  nibble): 128 bytes a sprite.  Raw flip x reverses the turned rows, raw flip y the columns.
* sb_tiles.bin: the 512 tiles turned and unflipped: 8 rows of 4 bytes, two pens a byte: 32 bytes a tile.
* sb_assets.s: sb_pal (16 STE colours), sb_spen (4096 bytes: sprite colour set * 16 + pen -> colour index, $FF for pen
  0, MAME's transpen 0: transparent; the colour set is the attribute's colour + 16 * the palette bank), sb_tpen (256
  bytes: tile colour * 16 + pen -> colour index), the sprite shapes' generated code (engine/sprite_programs.py: a shape
  is (code, flips), the coverage's shapes; docs/sprite-preparation.md).
* sb_sstream.bin: the end mask streams.  The rows' order (grouped by mask: engine/sprite_programs.py shape_order) is
  computed again where a sprite is baked (src/render.s bake_sprite), so no table is needed.

Colours: black and 15 by the shared default fitter (engine/palette_native.py, docs/palette-defaults.md) to the reference
pictures' pens of the coverage runs (ref/cover.py's `pens`), every pen mapped to the nearest.
"""
from pathlib import Path
import collections
import pickle
import sys
import numpy as np
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
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

BUILD = build_dir('sbasketb')
CODES = 384                                 # sprite codes (the shape: code << 2 | flip x << 1 | flip y)
PREFIX = 'sb'
SHARE = 1.0                                 # code for the most drawn shapes up to this share of the
                                            # coverage's draws (the load budget: tools/release.py MAX_LOAD)


def histogram():
    h = collections.Counter()
    for f in sorted(BUILD.glob('cover[0-9]*.pkl')):
        h.update(pickle.loads(f.read_bytes())['pens'])
    return h


def palette(v=None):
    """-> (16 colours, pen map [4352])"""
    v = v or Video()
    import palette_native as pn
    cols, pairs = pn.prom('sbasketb', histogram(), v.pens, lambda p: p >= 256)
    return [tuple(map(int, c)) for c in cols], pairs >> 4


def nibbles(img):
    out = bytearray()
    for row in img:
        for c in range(0, len(row), 2):
            out.append((int(row[c]) << 4) | int(row[c + 1]))
    return bytes(out)


def turned(img):
    """T[row][col] = img[n - 1 - col][row]"""
    return np.rot90(img, -1)


def shape_masks(v, code, fx, fy):
    """the turned sprite's 16 row masks (bit 15 the leftmost pixel) for the shape's flips (flip x: the columns reversed,
    flip y: the rows), pen 0 transparent"""
    t = turned(v.sprites[code % len(v.sprites)])
    if fx:
        t = t[:, ::-1]
    if fy:
        t = t[::-1]
    return [sum(1 << (15 - c) for c in range(16) if int(t[r, c]) != 0) for r in range(16)]


def shape_id(code, fx, fy):
    return code << 2 | int(fx) << 1 | int(fy)


def coverage_shapes():
    """the coverage's shapes: raw flip x reverses the turned rows (the shape's flip y), raw flip y the columns"""
    seen = collections.Counter()
    for f in sorted(BUILD.glob('cover[0-9]*.pkl')):
        for (code, colour, rfx, rfy), n in pickle.loads(f.read_bytes())['sprites'].items():
            seen[(code % CODES, bool(rfy), bool(rfx))] += n
    return sorted(seen), len(seen)


def sprite_programs(v):
    """-> (assembler lines: the generated code and records; the streams)"""
    keys, n = coverage_shapes()
    shapes = {shape_id(code, fx, fy): shape_masks(v, code, fx, fy) for code, fx, fy in keys}
    progs, stream, st = sp.programs(shapes, CODES * 4, table=PREFIX + '_shapes', stream_sym=PREFIX + '_sstream', line=296)
    print('generated code: %(routines)d routines (%(code_lines)d lines) for %(shapes)d shapes x 16 shifts x 3 clips; '
          'stream blocks %(stream_blocks)d, %(stream_bytes)d bytes' % st)
    return progs + ['	section data,data'], stream


def build():
    v = Video()
    cols, pmap = palette(v)
    assert v.sprites.shape[0] == 384 and v.tiles.shape[0] == 512, (v.sprites.shape, v.tiles.shape)
    (BUILD / 'sb_spr.bin').write_bytes(b''.join(nibbles(turned(v.sprites[c])) for c in range(384)))
    (BUILD / 'sb_tiles.bin').write_bytes(b''.join(nibbles(turned(v.tiles[c])) for c in range(512)))
    spen = [0xFF if i % 16 == 0 else int(pmap[256 + i]) for i in range(4096)]
    tpen = [int(pmap[i]) for i in range(256)]
    lines = ['; generated by games/sbasketb/tools/assets.py: the colours and pen maps', '	section data,data',
             'sb_pal:	dc.w ' + ','.join('$%03X' % gy.ste_word(c) for c in cols), 'sb_spen:']
    lines += ['	dc.b ' + ','.join(str(x) for x in spen[i:i + 16]) for i in range(0, 4096, 16)]
    lines += ['sb_tpen:']
    lines += ['	dc.b ' + ','.join(str(x) for x in tpen[i:i + 16]) for i in range(0, 256, 16)]
    lines += ['	even']
    progs, stream = sprite_programs(v)
    lines += progs
    (BUILD / 'sb_sstream.bin').write_bytes(stream)
    (BUILD / 'sb_assets.s').write_text(chr(10).join(lines) + chr(10))
    (BUILD / 'sb_penmap.bin').write_bytes(b''.join(int(x).to_bytes(1, 'big') for x in pmap))
    (BUILD / 'sb_colours.bin').write_bytes(bytes(c for col in cols for c in col))
    err = np.abs(np.array(cols, float)[pmap] - v.pens.astype(float))
    h = histogram()
    n = len(v.pens)
    w = np.array([h.get(p, 0) for p in range(n)], float)
    print('colours', cols)
    print('mean error a channel (weighted by pixels): %.1f' % ((err.mean(1) * w).sum() / max(w.sum(), 1)))
    worst = sorted(((err[p].max(), p) for p in range(n) if w[p] > 0), reverse=True)[:8]
    print('worst pens (max channel error, pen, rgb -> ste):', [(int(e), p, tuple(int(x) for x in v.pens[p]),
                                                               cols[pmap[p]]) for e, p in worst])
    print('pens used: %d of %d' % (int((w > 0).sum()), n))


if __name__ == '__main__':
    build()
