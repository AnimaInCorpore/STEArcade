"""The renderer's data (build/trojan/, never committed: ROM-derived): the fixed STE palette, the packed graphics, the
tiles' opacity runs, the sprites' row streams (stefastbobs2's preparation, as Black Tiger's assets.programs).

    palette.bin      16 STE colour words (docs/palette.json, ref/palette_fit.py)
    rgb_map.bin      4096 bytes: a 12-bit RGB (R << 8 | G << 4 | B) -> the nearest of the 16 in Oklab
    bg1_pixels.bin   2048 tiles x 128 bytes: 16 rows of 16 pixels, two a byte (the first in the high nibble)
    bg1_class.bin    2048 bytes: 0 no pixel (pen 0 everywhere), 1 opaque, 2 mixed
    bg1_runs.s       per tile x flip (4096): the rows with pixels as runs of equal opacity masks (front: pens 7-11)
    bg2_pixels.bin   512 x 128 bytes; bg2_uniform.bin: 512 bytes, the pen of a one-pen tile, else $FF
    bg2_map.bin      the tile map ROM (tb_23.9n, 32 KB)
    sprite_pixels.bin 2048 x 128; sprite_code.s: the masks for the 16 shifts, the row streams, tr_sprite_draw
    sprite_order.bin 2048 x 16: the rows of a sprite in drawing order (its mirror image draws in the same order)
    sprite_blank.bin 2048 bytes: 1 when every pixel is pen 15
    sprite_rows.bin 2048 x 2: the first drawn line (flipped in y) with a pixel, the lines from it to the last
    char_pixels.bin  1024 x 32 (8 rows of 8 pixels, two a byte); char_blank.bin: 1 when every pixel is pen 3
"""
from pathlib import Path
import json
import sys

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import Video, load
from paths import build_dir

import os
STRIDE = 416
PLAIN = bool(os.environ.get('TR_SPRITE_PLAIN'))    # sprite rows in drawing order, not grouped by mask (a baseline)                # the ring's bytes a line (render.s)
DOCS = Path(__file__).resolve().parents[1] / 'docs'


def packed(pixels):
    p = np.asarray(pixels, np.uint8)
    return ((p[..., ::2] << 4) | p[..., 1::2]).tobytes()


def oklab(c):
    c = np.asarray(c, float) / 255
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929], [0.2119034982, 0.6806995451, 0.1073969566],
                   [0.0883024619, 0.2817188376, 0.6299787005]])
    m2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468], [1.9779984951, -2.4285922050, 0.4505937099],
                   [0.0259707400, 0.7827717716, -0.8086757660]])
    return np.cbrt(lin @ m1.T) @ m2.T


RGB = np.array([[(v >> 8 & 15) * 17, (v >> 4 & 15) * 17, (v & 15) * 17] for v in range(4096)])


def palette():
    """-> (the 16 colours [16, 3], the 4096-entry map, the 16 STE words)"""
    doc = json.loads((DOCS / 'palette.json').read_text())
    colours = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for c in doc['colours']], np.uint8)
    assert len(colours) == 16 and not colours[0].any() and not (colours % 17).any()
    mapping = ((oklab(RGB)[:, None] - oklab(colours)[None]) ** 2).sum(2).argmin(1).astype(np.uint8)
    regs = []
    for r, g, b in colours // 17:
        conv = lambda n: ((int(n) >> 1) & 7) | ((int(n) & 1) << 3)
        regs.append((conv(r) << 8) | (conv(g) << 4) | conv(b))
    return colours, mapping, np.array(regs, '>u2')


def masks(tile, test):
    return [sum(int(bool(test(p))) << (15 - x) for x, p in enumerate(row)) for row in tile]


def runs(m):
    """[(first row, rows, mask)] of the rows with a nonzero mask, consecutive equal masks together"""
    out = []
    for y, v in enumerate(m):
        if not v:
            continue
        if out and out[-1][2] == v and out[-1][0] + out[-1][1] == y:
            out[-1] = (out[-1][0], out[-1][1] + 1, v)
        else:
            out.append((y, 1, v))
    return out


def bg1_runs(tiles):
    """bg1_runs.s: tr_bg1_runs: a long per tile x flip (flip: + 2048) to its opacity runs, tr_bg1_front the same for its
    front pens (7-11; 0: none).  A run: the destination offset (row * STRIDE), the source offset (row * 8), the mask,
    the rows - 1; a list ends with -1."""
    lists, index_o, index_f = {}, [], []

    def label(rs):
        key = tuple(rs)
        if key not in lists:
            lists[key] = 'trr%d' % len(lists)
        return lists[key]
    for flip in (False, True):
        for t in tiles:
            img = t[:, ::-1] if flip else t
            index_o.append(label(runs(masks(img, lambda p: p != 0))))
            fr = runs(masks(img, lambda p: 7 <= p <= 11))
            index_f.append(label(fr) if fr else '0')
    out = ['\tsection data,data', '\teven', 'tr_bg1_runs:', '\tdc.l ' + ','.join(index_o[:2048]),
           '\tdc.l ' + ','.join(index_o[2048:]), 'tr_bg1_front:']
    for i in range(0, 4096, 256):
        out.append('\tdc.l ' + ','.join(index_f[i:i + 256]))
    for key, name in lists.items():
        out.append(name + ':')
        for y, n, v in key:
            out.append('\tdc.w %d,%d,$%04x,%d' % (y * STRIDE, y * 8, v, n - 1))
        out.append('\tdc.w -1')
    return '\n'.join(out) + '\n'


def sprite_programs(sprites):
    """The sprites' row streams (Black Tiger's assets.programs): the rows of a sprite sorted by their opacity mask
    (equal masks together, blank rows last), its pixels baked in that order (sprite_order; the mirror image uses the
    same order), drawn bottom-up (Trojan's sprites are always flipped in y).  The masks for every shift: END1 / END3
    of a shifted row.  tr_sprite_draw: the stream at a0, the masks of the shift at a1, the Blitter's registers in
    a2 (END1), a3 (END3), a4 (the destination), a5 (Y count), a6 (control), d6 = the control word."""
    mask_values = sorted({m for pixels in sprites for m in masks(pixels, lambda p: p != 15)})
    mask_index = {v: i for i, v in enumerate(mask_values)}
    half = len(sprites) // 2
    base = [masks(pixels, lambda p: p != 15) for pixels in sprites[:half]]
    streams, pointers, orders, blanks = {}, [], [], []
    for index, pixels in enumerate(sprites):
        opaque = masks(pixels, lambda p: p != 15)
        key = base[index % half]
        order = sorted(range(16), key=lambda y: (key[y] == 0, key[y], y))
        if PLAIN:                               # (the measurement's baseline: the rows in their own order)
            order = sorted(range(16), key=lambda y: (key[y] == 0, y))
        if index < half:
            orders.extend(order)
            blanks.append(int(not any(opaque)))
        groups = []
        for row in order:
            m = opaque[row]
            if not m:
                break
            if not groups or groups[-1][0] != m:
                groups.append((m, []))
            groups[-1][1].append(row)
        values = [('w', len(groups) - 1)]
        pos = 0
        for m, rows in groups:
            values += [('w', mask_index[m] * 4), ('w', len(rows) - 1)]
            for row in rows:
                draw_row = 15 - row                 # (flipped in y)
                values.append(('l', draw_row * STRIDE - pos))
                pos = draw_row * STRIDE + 8
        stream = tuple(values)
        if stream not in streams:
            streams[stream] = len(streams)
        pointers.append(streams[stream])
    out = ['\tsection data,data', '\teven', 'TR_MASK_STRIDE = %d' % (len(mask_values) * 4), 'tr_sprite_masks:']
    for shift in range(16):
        for m in mask_values:
            out.append('\tdc.w $%04x,$%04x' % (m >> shift, ((m << (16 - shift)) & 65535) if shift else 0))
    out += ['tr_sprite_streams:']
    for i in range(0, len(pointers), 64):
        out.append('\tdc.l ' + ','.join('trs%d' % p for p in pointers[i:i + 64]))
    for stream, index in streams.items():
        out.append('trs%d:' % index)
        for kind, value in stream:
            out.append('\tdc.%s %d' % (kind, value))
    out += ['\tsection text,code', 'tr_sprite_draw:',
            '\tmove.w (a0)+,d2', '\tbmi.s .done', '.group:',
            '\tmove.w (a0)+,d0', '\tmove.l (a1,d0.w),d0',
            '\tmove.w d0,(a3)', '\tswap d0', '\tmove.w d0,(a2)',
            '\tmove.w (a0)+,d3', '.row:', '\tmove.l (a0)+,d1',
            '\tadd.l d1,(a4)', '\tmove.w #4,(a5)', '\tmove.w d6,(a6)',
            '\tdbf d3,.row', '\tdbf d2,.group', '.done:', '\trts']
    return '\n'.join(out) + '\n', bytes(orders), bytes(blanks)


def build():
    dest = build_dir('trojan')
    v = Video()
    colours, mapping, regs = palette()
    (dest / 'palette_rgb.bin').write_bytes(colours.tobytes())
    (dest / 'rgb_map.bin').write_bytes(mapping.tobytes())
    (dest / 'palette.bin').write_bytes(regs.tobytes())
    (dest / 'bg1_pixels.bin').write_bytes(packed(v.tiles))
    cls = [0 if not t.any() else 1 if t.all() else 2 for t in v.tiles]
    (dest / 'bg1_class.bin').write_bytes(bytes(cls))
    (dest / 'bg1_runs.s').write_text(bg1_runs(v.tiles))
    (dest / 'bg2_pixels.bin').write_bytes(packed(v.bg2tiles))
    (dest / 'bg2_uniform.bin').write_bytes(bytes(int(t[0, 0]) if (t == t[0, 0]).all() else 255 for t in v.bg2tiles))
    (dest / 'bg2_map.bin').write_bytes(load('tb23.bin'))
    spr = v.sprites.astype(np.uint8)
    text, order, blank = sprite_programs(np.concatenate((spr, spr[:, :, ::-1])))
    (dest / 'sprite_code.s').write_text(text)
    (dest / 'sprite_order.bin').write_bytes(order)
    (dest / 'sprite_blank.bin').write_bytes(blank)
    rows = []                                   # the drawn rows (flipped in y) a sprite's stream covers: first, count
    for pixels in spr:
        drawn = [15 - y for y in range(16) if (pixels[y] != 15).any()]
        rows += [min(drawn), max(drawn) - min(drawn) + 1] if drawn else [0, 1]
    (dest / 'sprite_rows.bin').write_bytes(bytes(rows))
    (dest / 'sprite_pixels.bin').write_bytes(packed(spr))
    (dest / 'char_pixels.bin').write_bytes(packed(v.chars))
    (dest / 'nz2.bin').write_bytes(bytes(((b >> 4 != 0) << 1) | (b & 15 != 0) for b in range(256)) +
                                   bytes(((b & 15 != 0) << 1) | (b >> 4 != 0) for b in range(256)))
    (dest / 'char_blank.bin').write_bytes(bytes(int((c == 3).all()) for c in v.chars))
    print('renderer assets:', dest, flush=True)


class Oracle:
    """the reference picture through the fixed palette: [240, 256] colour indices"""

    def __init__(self):
        dest = build_dir('trojan')
        self.mapping = np.frombuffer((dest / 'rgb_map.bin').read_bytes(), np.uint8)
        self.rgb = np.frombuffer((dest / 'palette_rgb.bin').read_bytes(), np.uint8).reshape(16, 3)
        self.video = Video()

    def frame(self, m):
        from machine import VISIBLE
        raw = self.video.render_raw(m.mem, m.sprites, m.regs)[VISIBLE[2]:VISIBLE[3] + 1]
        hi = np.frombuffer(bytes(m.mem[0xF000:0xF400]), np.uint8).astype(int)
        lo = np.frombuffer(bytes(m.mem[0xF400:0xF800]), np.uint8).astype(int)
        return self.mapping[(hi << 4 | lo >> 4)[raw]]


if __name__ == '__main__':
    build()
