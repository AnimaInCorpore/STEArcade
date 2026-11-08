"""The STE port's graphics and colours (build/rocnrope/, ROM-derived: never committed).

    python tools/assets.py

The picture is turned as MAME's ROT270 turns it: picture pixel (X, Y), X 0-223, Y 0-255, is the arcade's raw pixel
(x = 255 - Y, y = X + 16); a turned image T[row][col] = raw[col][n - 1 - row] (np.rot90(raw, 1)).  Raw flip x is the
picture's flip of the rows, raw flip y the picture's flip of the columns (src/render.s keys use the picture's flips).
* rr_spr.bin: the 256 sprites turned (16 x 16, 4 bpp), unflipped: 16 rows of 8 bytes, two pens a byte (the left pixel
  in the high nibble): 128 bytes a sprite.
* rr_tiles.bin: the 512 tiles turned (8 x 8, 4 bpp), unflipped: 8 rows of 4 bytes, two pens a byte: 32 bytes a tile.
* rr_assets.s: rr_pal (16 STE colours), rr_spen (256 bytes: sprite colour * 16 + pen -> colour index, $FF where the
  lookup PROM's entry is 0: transparent), rr_tpen (256 bytes: tile colour * 16 + pen -> colour index), rr_tclass (per
  sprite colour its transparency class), the sprite shapes' generated code (engine/sprite_programs.py: a shape is
  (transparency class, code, flips), the coverage's shapes; docs/sprite-preparation.md).
* rr_sstream.bin: the end mask streams.  The rows' order (grouped by mask: engine/sprite_programs.py shape_order)
  is computed again where a sprite is baked (src/render.s bake_sprite), so no table is needed.

Colours: black and 15 fitted by a weighted k-means in Oklab (Gyruss's tools/assets.py) to the reference pictures' pens
of the coverage runs (ref/cover.py's `pens`), snapped to the STE's 4 bits a gun; every pen maps to the nearest.  The
arcade shows 24 colours in the coverage (a 32-byte palette PROM).

Current colour default (2026-11-05): engine/palette_native.py; see docs/palette-defaults.md.
Earlier fitting descriptions in this module refer to the previous palette.
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

BUILD = build_dir('rocnrope')
CODES = 256                                 # sprite codes (the key: code << 8 | colour << 2 | flip x << 1 | flip y)
PREFIX = 'rr'
SHARE = 1.0                                 # code for the most drawn shapes up to this share of the
                                            # coverage's draws (the load budget: tools/release.py MAX_LOAD)


def histogram():
    h = collections.Counter()
    for f in sorted(BUILD.glob('cover[0-9]*.pkl')):
        h.update(pickle.loads(f.read_bytes())['pens'])
    return h


def palette(v=None):
    """-> (16 colours, pen map [512])"""
    v = v or Video()
    import palette_native as pn
    cols, pairs = pn.prom('rocnrope', histogram(), v.pens, lambda p: p < 256)
    return [tuple(map(int, c)) for c in cols], pairs >> 4


def turned(img):
    """T[row][col] = img[col][n - 1 - row]: the picture's orientation (MAME's ROT270)"""
    return np.rot90(img, 1)


def nibbles(img):
    out = bytearray()
    for row in img:
        for c in range(0, len(row), 2):
            out.append((int(row[c]) << 4) | int(row[c + 1]))
    return bytes(out)


def transparency(v):
    """-> (per sprite colour its class, per class the transparent pens' set): a pen is transparent where the colour's
    lookup entry is 0"""
    sets, cls = [], []
    for c in range(16):
        t = frozenset(p for p in range(16) if v.lut[16 * c + p] == 0)
        if t not in sets:
            sets.append(t)
        cls.append(sets.index(t))
    return cls, sets


def shape_masks(v, code, fx, fy, tset):
    """the sprite's 16 row masks (bit 15 the leftmost pixel) for MAME's flips (flip x: the columns reversed, flip y:
    the rows), the pens in tset transparent"""
    t = turned(v.sprites[code % len(v.sprites)])
    if fx:                                  # (the picture's flips: columns / rows)
        t = t[:, ::-1]
    if fy:
        t = t[::-1]
    return [sum(1 << (15 - c) for c in range(16) if int(t[r, c]) not in tset) for r in range(16)]


def shape_id(k, code, fx, fy):
    return (k * CODES + code) << 2 | int(fx) << 1 | int(fy)


def coverage_shapes(cls, share=1.0):
    """the coverage's shapes, the most drawn first, up to `share` of the draws"""
    seen = collections.Counter()
    for f in sorted(BUILD.glob('cover[0-9]*.pkl')):
        for (code, colour, fx, fy), n in pickle.loads(f.read_bytes())['sprites'].items():
            seen[(cls[colour], code % CODES, bool(fy), bool(fx))] += n      # (raw flip y = the picture's columns, raw flip x its rows)
    total, acc, out = sum(seen.values()), 0, []
    for k, n in seen.most_common():
        if share < 1 and acc >= share * total:
            break
        out.append(k)
        acc += n
    return sorted(out), acc / max(total, 1)


def sprite_programs(v):
    """-> (assembler lines: the class table, the generated code and records; the streams)"""
    cls, sets = transparency(v)
    keys, got = coverage_shapes(cls, SHARE)
    shapes = {shape_id(k, code, fx, fy): shape_masks(v, code, fx, fy, sets[k]) for k, code, fx, fy in keys}
    progs, stream, st = sp.programs(shapes, len(sets) * CODES * 4, table=PREFIX + '_shapes',
                                    stream_sym=PREFIX + '_sstream')
    print('transparency classes: %d %s; generated code: %%(routines)d routines (%%(code_lines)d lines) for %%(shapes)d '
          'shapes x 16 shifts x 3 clips (%.1f%%%% of the draws); stream blocks %%(stream_blocks)d, %%(stream_bytes)d '
          'bytes' % (len(sets), cls, 100 * got) % st)
    lines = ['%s_tclass:\tdc.b %s' % (PREFIX, ','.join(str(k) for k in cls)), '\teven'] + progs + ['\tsection data,data']
    return lines, stream


def build():
    v = Video()
    cols, pmap = palette(v)
    assert v.sprites.shape[0] == 256 and v.tiles.shape[0] == 512, (v.sprites.shape, v.tiles.shape)
    (BUILD / 'rr_spr.bin').write_bytes(b''.join(nibbles(turned(v.sprites[c])) for c in range(256)))
    (BUILD / 'rr_tiles.bin').write_bytes(b''.join(nibbles(turned(v.tiles[c])) for c in range(512)))
    spen = [0xFF if v.lut[i] == 0 else int(pmap[i]) for i in range(256)]
    tpen = [int(pmap[256 + i]) for i in range(256)]
    lines = ['; generated by games/rocnrope/tools/assets.py: the colours and pen maps', '\tsection data,data',
             'rr_pal:\tdc.w ' + ','.join('$%03X' % gy.ste_word(c) for c in cols), 'rr_spen:']
    lines += ['\tdc.b ' + ','.join(str(x) for x in spen[i:i + 16]) for i in range(0, 256, 16)]
    lines += ['rr_tpen:']
    lines += ['\tdc.b ' + ','.join(str(x) for x in tpen[i:i + 16]) for i in range(0, 256, 16)]
    lines += ['\teven']
    progs, stream = sprite_programs(v)
    lines += progs
    (BUILD / 'rr_sstream.bin').write_bytes(stream)
    (BUILD / 'rr_assets.s').write_text('\n'.join(lines) + '\n')
    (BUILD / 'rr_penmap.bin').write_bytes(bytes(int(x) for x in pmap))
    (BUILD / 'rr_colours.bin').write_bytes(bytes(c for col in cols for c in col))
    err = np.abs(np.array(cols, float)[pmap] - v.pens.astype(float))
    h = histogram()
    w = np.array([h.get(p, 0) for p in range(512)], float)
    print('colours', cols)
    print('mean error a channel (weighted by pixels): %.1f' % ((err.mean(1) * w).sum() / max(w.sum(), 1)))
    worst = sorted(((err[p].max(), p) for p in range(512) if w[p] > 0), reverse=True)[:8]
    print('worst pens (max channel error, pen, rgb -> ste):', [(int(e), p, tuple(int(x) for x in v.pens[p]),
                                                               cols[pmap[p]]) for e, p in worst])


if __name__ == '__main__':
    build()
