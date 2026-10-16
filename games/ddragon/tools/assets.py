"""The renderer's data (build/ddragon/, never committed: ROM-derived): the fixed STE palette, the packed graphics, the
sprites' row streams (stefastbobs2's preparation, as Trojan's and Black Tiger's assets).

    palette.bin       16 STE colour words (docs/palette.json, ref/palette_fit.py)
    palette_rgb.bin   the 16 colours as RGB bytes
    rgb_map.bin       4096 bytes: a 12-bit RGB (R << 8 | G << 4 | B) -> the nearest of the 16 in Oklab
    bg_pixels.bin     2048 tiles x 128 bytes: 16 rows of 16 pixels, two a byte (the first in the high nibble)
    bg_slot.bin       1024 words: the bg RAM's entry i (MAME's background_scan) -> its cell col * 32 + row
    sprite_pixels.bin 4096 x 128; sprite_code.s: the masks for the 16 shifts, the row streams of every sprite in its
                      four orientations (code + 4096 flip x + 8192 flip y), dd_sprite_draw
    sprite_order.bin  4096 x 8: the rows of a sprite in drawing order, two a byte (the first in the high nibble; its
                      mirror and flipped images in the same)
    sprite_blank.bin  4096 bytes: 1 when every pixel is pen 0
    char_pixels.bin   1024 x 32 (8 rows of 8 pixels, two a byte); char_blank.bin: 1 when every pixel is pen 0,
                      $80 + the pen when every pixel is that pen (a solid character: render.s fills it)
    nz2.bin           per byte: (the first pixel not 0) << 1 | (the second not 0)
"""
from pathlib import Path
import json
import os
import sys

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
from machine import Video
from paths import build_dir

STRIDE = 416                # the ring's bytes a line (render.s)
PLAIN = bool(os.environ.get("DD_SPRITE_PLAIN"))    # sprite rows in drawing order, not grouped by mask (a baseline)
DOCS = Path(__file__).resolve().parents[1] / "docs"
RGB = np.array([[(v >> 8 & 15) * 17, (v >> 4 & 15) * 17, (v & 15) * 17] for v in range(4096)])


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


def palette():
    """-> (the 16 colours [16, 3], the 4096-entry map, the 16 STE words)"""
    doc = json.loads((DOCS / "palette.json").read_text())
    colours = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for c in doc["colours"]], np.uint8)
    assert len(colours) == 16 and not colours[0].any() and not (colours % 17).any()
    mapping = ((oklab(RGB)[:, None] - oklab(colours)[None]) ** 2).sum(2).argmin(1).astype(np.uint8)
    regs = []
    for r, g, b in colours // 17:
        conv = lambda n: ((int(n) >> 1) & 7) | ((int(n) & 1) << 3)
        regs.append((conv(r) << 8) | (conv(g) << 4) | conv(b))
    return colours, mapping, np.array(regs, ">u2")


def masks(tile, test):
    return [sum(int(bool(test(p))) << (15 - x) for x, p in enumerate(row)) for row in tile]


def bg_slot():
    """MAME's background_scan: (col, row) -> RAM entry; here the inverse, the entry -> col * 32 + row"""
    out = [0] * 1024
    for col in range(32):
        for row in range(32):
            i = (col & 0x0F) | ((row & 0x0F) << 4) | ((col & 0x10) << 4) | ((row & 0x10) << 5)
            out[i] = col * 32 + row
    return np.array(out, ">u2").tobytes()


def sprite_programs(sprites):
    """The sprites' row streams: the rows of a sprite sorted by their opacity mask (equal masks together, blank rows
    last), its pixels baked in that order (sprite_order; its mirror image and the flipped ones use the same order).  The
    masks for every shift: END1 / END3 of a shifted row.  A stream (index code + 4096 flip x + 8192 flip y): the groups
    - 1, per group the mask's offset, the rows - 1 and per row the destination step (a flipped one draws its row r at
    line 15 - r).  dd_sprite_draw: the stream at a0, the masks of the shift at a1, the Blitter's registers in a2
    (END1), a3 (END3), a4 (the destination), a5 (Y count), a6 (control), d6 = the control word."""
    n = len(sprites)
    base = [masks(px, lambda p: p != 0) for px in sprites]
    mirror = [masks(px[:, ::-1], lambda p: p != 0) for px in sprites]
    mask_values = sorted({m for ms in base + mirror for m in ms})
    mask_index = {v: i for i, v in enumerate(mask_values)}
    streams, pointers, orders, blanks = {}, [], [], []
    for code in range(n):
        key = base[code]
        order = sorted(range(16), key=lambda y: (key[y] == 0, key[y], y))
        if PLAIN:
            order = sorted(range(16), key=lambda y: (key[y] == 0, y))
        orders.extend(order)
        blanks.append(int(not any(key)))
    for fy in (0, 1):
        for fx in (0, 1):
            for code in range(n):
                opaque = mirror[code] if fx else base[code]
                order = orders[16 * code:16 * code + 16]
                groups = []
                for row in order:
                    m = opaque[row]
                    if not m:
                        break
                    if not groups or groups[-1][0] != m:
                        groups.append((m, []))
                    groups[-1][1].append(row)
                values = [("w", len(groups) - 1)]
                pos = 0
                for m, rows in groups:
                    values += [("w", mask_index[m] * 4), ("w", len(rows) - 1)]
                    for row in rows:
                        draw_row = 15 - row if fy else row
                        values.append(("l", draw_row * STRIDE - pos))
                        pos = draw_row * STRIDE + 8
                stream = tuple(values)
                if stream not in streams:
                    streams[stream] = len(streams)
                pointers.append(streams[stream])
    out = ["\tsection data,data", "\teven", "DD_MASK_STRIDE = %d" % (len(mask_values) * 4), "dd_sprite_masks:"]
    for shift in range(16):
        for m in mask_values:
            out.append("\tdc.w $%04x,$%04x" % (m >> shift, ((m << (16 - shift)) & 65535) if shift else 0))
    out += ["dd_sprite_streams:"]
    for i in range(0, len(pointers), 64):
        out.append("\tdc.l " + ",".join("dds%d" % p for p in pointers[i:i + 64]))
    for stream, index in streams.items():
        out.append("dds%d:" % index)
        out.append("\tdc.%s " % stream[0][0] + ",".join(str(v) for k, v in stream[:1]))
        rest = stream[1:]
        i = 0
        while i < len(rest):
            kind = rest[i][0]
            j = i
            while j < len(rest) and rest[j][0] == kind and j - i < 16:
                j += 1
            out.append("\tdc.%s %s" % (kind, ",".join(str(v) for k, v in rest[i:j])))
            i = j
    out += ["\tsection text,code", "dd_sprite_draw:",
            "\tmove.w (a0)+,d2", "\tbmi.s .done", ".group:",
            "\tmove.w (a0)+,d0", "\tmove.l (a1,d0.w),d0",
            "\tmove.w d0,(a3)", "\tswap d0", "\tmove.w d0,(a2)",
            "\tmove.w (a0)+,d3", ".row:", "\tmove.l (a0)+,d1",
            "\tadd.l d1,(a4)", "\tmove.w #4,(a5)", "\tmove.w d6,(a6)",
            "\tdbf d3,.row", "\tdbf d2,.group", ".done:", "\trts"]
    return "\n".join(out) + "\n", bytes(orders), bytes(blanks), len(streams)


def build():
    dest = build_dir("ddragon")
    v = Video()
    colours, mapping, regs = palette()
    (dest / "palette_rgb.bin").write_bytes(colours.tobytes())
    (dest / "rgb_map.bin").write_bytes(mapping.tobytes())
    (dest / "palette.bin").write_bytes(regs.tobytes())
    (dest / "bg_pixels.bin").write_bytes(packed(v.tiles))
    (dest / "bg_slot.bin").write_bytes(bg_slot())
    spr = v.sprites.astype(np.uint8)
    text, order, blank, nstreams = sprite_programs(spr)
    (dest / "sprite_code.s").write_text(text)
    (dest / "sprite_order.bin").write_bytes(bytes(order[i] << 4 | order[i + 1] for i in range(0, len(order), 2)))
    (dest / "sprite_blank.bin").write_bytes(blank)
    (dest / "sprite_pixels.bin").write_bytes(packed(spr))
    (dest / "char_pixels.bin").write_bytes(packed(v.chars))
    (dest / "char_blank.bin").write_bytes(bytes(1 if not c.any() else 0x80 | int(c.flat[0]) if (c == c.flat[0]).all()
                                                else 0 for c in v.chars))
    (dest / "nz2.bin").write_bytes(bytes(((b >> 4 != 0) << 1) | (b & 15 != 0) for b in range(256)))
    print("renderer assets: %s (%d sprite streams)" % (dest, nstreams), flush=True)


class Oracle:
    """the reference picture through the fixed palette: [240, 256] colour indices"""

    def __init__(self):
        dest = build_dir("ddragon")
        self.mapping = np.frombuffer((dest / "rgb_map.bin").read_bytes(), np.uint8)
        self.rgb = np.frombuffer((dest / "palette_rgb.bin").read_bytes(), np.uint8).reshape(16, 3)
        self.video = Video()

    def frame(self, m):
        raw = self.video.render_raw(m.mem, m.scrollx, m.scrolly)
        lo = np.frombuffer(bytes(m.mem[0x1000:0x1200]), np.uint8).astype(int)
        hi = np.frombuffer(bytes(m.mem[0x1200:0x1400]), np.uint8).astype(int)
        word = ((lo & 15) << 8) | ((lo >> 4) << 4) | (hi & 15)
        return self.mapping[word[raw]]


if __name__ == "__main__":
    build()
