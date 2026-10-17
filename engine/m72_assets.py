"""The STE renderer's data for the Irem M72 games (engine/rt/m72render.s), from the MAME sets' graphics ROMs.

    venv/bin/python engine/m72_assets.py rtype|mrheli        -> build/<game>/m72_*.bin

The arcade's colours live in palette RAM (they change per stage, fade, cycle), so nothing here is baked to STE colours:
the renderer maps pens to its 16 indices at run time (m72render.s, "Colours").  Files (big-endian):

    m72_tf.bin / m72_tb.bin   the FG / BG layer's 8 x 8 tiles (engine/m72.py decode: 4096 for R-Type, 8192 for Mr. HELI),
                              32 bytes each: the pen's bit planes, bit 0 first: 8 bytes each (a byte a row, top row
                              first, bit 7 = the left pixel)
    m72_uf.bin / m72_ub.bin   a word a tile: the pens it uses (bit p = pen p)
    m72_bs.bin                10 bytes a BG tile: its few other pixels when all but 1-4 have one pen (the stars:
                              drawn as pixels, engine/rt/m72render.s m72r_stars): the count (0: one pen, 255: not
                              such a tile), the main pen, 4 x (the pixel: y * 8 + x, its pen)
    m72_sp.bin                the 16 x 16 sprite pieces (4096), 128 bytes each: 16 rows of 8 bytes, a byte two pixels
                              (the left one's pen in the high nibble)
    m72_su.bin                a long a piece: the pens it uses (word), the first and the last opaque row (bytes; an
                              empty piece: $FF, 0)
    m72_lab.bin               4096 x 4 bytes: Oklab of the STE colour r g b (4 bits each, index r * 256 + g * 16 + b): L, a,
                              b as bytes (L * 255, a and b * 255 / 0.8 + 128), 0
    m72_q4.bin                32 bytes: a 5-bit channel -> its STE level 0-15 (MAME's pal5bit v << 3 | v >> 2, then the
                              nearest of the STE's 16 levels n * 17)
"""
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import build_dir
import m72


def srgb_to_linear(c):
    c = c / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def oklab(rgb):
    """rgb: (..., 3) 0-255 -> (..., 3) Oklab"""
    r, g, b = [srgb_to_linear(np.asarray(rgb, float)[..., i]) for i in range(3)]
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l, m, s = np.cbrt(l), np.cbrt(m), np.cbrt(s)
    return np.stack([0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
                     1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
                     0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s], -1)


def lab_bytes(rgb):
    """the renderer's integer Oklab (L, a, b bytes) of 0-255 colours"""
    lab = oklab(rgb)
    out = np.empty(lab.shape, np.int32)
    out[..., 0] = np.clip(np.round(lab[..., 0] * 255), 0, 255)
    out[..., 1:] = np.clip(np.round(lab[..., 1:] * 255 / 0.8 + 128), 0, 255)
    return out


def lab_table():
    n = np.arange(16) * 17
    rgb = np.stack(np.meshgrid(n, n, n, indexing="ij"), -1).reshape(-1, 3)
    return np.concatenate([lab_bytes(rgb), np.zeros((4096, 1), np.int32)], 1).astype(np.uint8)


def q4_table():
    """5-bit channel -> STE level (round(v8 / 17))"""
    v = np.arange(32)
    v8 = (v << 3) | (v >> 2)
    return np.round(v8 / 17).astype(np.uint8)


def ste_rgb(q):
    """STE levels (..., 3) 0-15 -> 0-255"""
    return np.asarray(q, np.int32) * 17


def pen_planes(px):
    """[N, h, w] pens -> [N, 4, h] bit planes (rows as integers, bit w-1 = the left pixel)"""
    n, h, w = px.shape
    weights = (1 << np.arange(w - 1, -1, -1)).astype(np.int64)
    return np.stack([((px >> b) & 1).astype(np.int64) @ weights for b in range(4)], 1)


def pens_used(px):
    n = px.shape[0]
    flat = px.reshape(n, -1)
    out = np.zeros(n, np.int64)
    for p in range(16):
        out |= (flat == p).any(1).astype(np.int64) << p
    return out


def tile_data(tiles):
    """(m72_tf/tb bytes, m72_uf/ub bytes)"""
    pl = pen_planes(np.asarray(tiles, np.int64))                 # N x 4 x 8 (bytes)
    return pl.astype(np.uint8).tobytes(), pens_used(np.asarray(tiles)).astype(">u2").tobytes()


def sparse_data(tiles, k=4):
    """m72_bs bytes: per tile the count of pixels other than its main pen (1-k; 0 one pen; 255 more), the main pen,
    k x (y * 8 + x, pen)"""
    out = bytearray()
    for tl in np.asarray(tiles, np.int64):
        dom = int(np.bincount(tl.ravel(), minlength=16).argmax())
        ys, xs = np.nonzero(tl != dom)
        rec = bytearray(2 + 2 * k)
        rec[1] = dom
        if len(ys) <= k:
            rec[0] = len(ys)
            for i, (y, x) in enumerate(zip(ys.tolist(), xs.tolist())):
                rec[2 + 2 * i] = y * 8 + x
                rec[3 + 2 * i] = int(tl[y, x])
        else:
            rec[0] = 255
        out += rec
    return bytes(out)


def sprite_data(spr):
    """(m72_sp bytes, m72_su bytes)"""
    spr = np.asarray(spr, np.int64)
    n = len(spr)
    data = ((spr[:, :, 0::2] << 4) | spr[:, :, 1::2]).astype(np.uint8).tobytes()     # chunky: 2 pixels a byte
    used = pens_used(spr)
    opaque = (spr != 0).any(2)                                    # N x 16
    info = bytearray()
    for i in range(n):
        rows = np.nonzero(opaque[i])[0]
        y0, y1 = (int(rows[0]), int(rows[-1])) if len(rows) else (255, 0)
        info += int(used[i]).to_bytes(2, "big") + bytes([y0, y1])
    return data, bytes(info)


def write(path, data):
    """data into path unless it holds it already; atomically (an assembler may be reading the old file)"""
    if path.exists() and path.read_bytes() == data:
        return
    tmp = path.with_name(path.name + ".%d.tmp" % os.getpid())
    tmp.write_bytes(data)
    os.replace(tmp, path)


def build(game, out=None):
    out = Path(out or build_dir(game))
    v = m72.Video(game)
    for name, t in (("f", v.tiles[0]), ("b", v.tiles[1])):
        d, u = tile_data(t)
        write(out / ("m72_t%s.bin" % name), d)
        write(out / ("m72_u%s.bin" % name), u)
    write(out / "m72_bs.bin", sparse_data(v.tiles[1]))
    d, u = sprite_data(v.sprites)
    write(out / "m72_sp.bin", d)
    write(out / "m72_su.bin", u)
    write(out / "m72_lab.bin", lab_table().tobytes())
    write(out / "m72_q4.bin", q4_table().tobytes())
    return out


def counts(game):
    """(FG tiles, BG tiles, sprite pieces) of a game"""
    v = m72.Video(game)
    return len(v.tiles[0]), len(v.tiles[1]), len(v.sprites)


if __name__ == "__main__":
    for g in sys.argv[1:] or ["rtype"]:
        print("assets in", build(g), "(tiles FG %d, BG %d, sprites %d)" % counts(g))
