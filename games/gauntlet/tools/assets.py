"""The renderer's data (build/gauntlet/, never committed: ROM-derived), for src/render.s.

    palette.bin      16 STE colour words (docs/palette.json, ref/palette_fit.py)
    palette_rgb.bin  the 16 colours as RGB bytes
    irgb_map.bin     65536 bytes: an IRGB_4444 palette word -> the nearest of the 16 in Oklab (its RGB as MAME decodes it)
    tile_px.bin      8192 tiles x 32 bytes (gfx 0, the playfield's and the motion objects' 8x8 tiles): 8 rows of 8
                     pixels, two a byte (the first in the high nibble)
    tile_pens.bin    8192 words: bit p set when the tile has a pixel p
    tile_masks.bin   8192 x 8 rows x 2 bytes: the pixels that are neither 0 nor 1 (drawn by a motion object), the
                     pixels 1 (its shadow); bit 7 the first pixel
    char_rows.bin    1024 alphanumerics x 8 rows x 2 bytes: the pixels 0-3 and 4-7, 2 bits each (the first highest)
    char_pens.bin    1024 bytes: bit p set when the character has a pixel p
    char_blank.bin   1024 bytes: 1 when every pixel of the character is 0
    nz4.bin          256 bytes: per byte of four 2-bit pixels, the pixels not 0 (bit 3 the first)
    bitrev.bin       256 bytes: a byte's bits reversed (a mirrored mask)
    sprite_code.s    the motion objects' draw routine (render.s includes it)
"""
from pathlib import Path
import json
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[2] / "engine")]
from paths import build_dir

DOCS = HERE.parent / "docs"


def oklab(c):
    c = np.asarray(c, float) / 255
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929], [0.2119034982, 0.6806995451, 0.1073969566],
                   [0.0883024619, 0.2817188376, 0.6299787005]])
    m2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468], [1.9779984951, -2.4285922050, 0.4505937099],
                   [0.0259707400, 0.7827717716, -0.8086757660]])
    return np.cbrt(lin @ m1.T) @ m2.T


def irgb_rgb(words):
    w = np.asarray(words, np.int64)
    i = ((w >> 12) & 15) * 0x11
    rgb = np.stack([(w >> 8) & 15, (w >> 4) & 15, w & 15], axis=1) * 0x11
    return ((i[:, None] * rgb) >> 8).astype(np.int64)


def palette():
    """-> (the 16 colours [16, 3], the 65536-entry IRGB map, the 16 STE words)"""
    doc = json.loads((DOCS / "palette.json").read_text())
    colours = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for c in doc["colours"]], np.uint8)
    assert len(colours) == 16 and not colours[0].any() and not (colours % 17).any()
    rgb = irgb_rgb(np.arange(65536))
    key = (rgb[:, 0] << 16) | (rgb[:, 1] << 8) | rgb[:, 2]
    u, inv = np.unique(key, return_inverse=True)
    ur = np.stack([(u >> 16) & 255, (u >> 8) & 255, u & 255], axis=1)
    near = ((oklab(ur)[:, None] - oklab(colours)[None]) ** 2).sum(2).argmin(1).astype(np.uint8)
    mapping = near[inv.ravel()]
    regs = []
    for r, g, b in colours // 17:
        conv = lambda n: ((int(n) >> 1) & 7) | ((int(n) & 1) << 3)
        regs.append((conv(r) << 8) | (conv(g) << 4) | conv(b))
    return colours, mapping, np.array(regs, ">u2")


def sprite_code():
    return ""


def build():
    from video import Video
    dest = build_dir("gauntlet")
    v = Video()
    colours, mapping, regs = palette()
    (dest / "palette_rgb.bin").write_bytes(colours.tobytes())
    (dest / "irgb_map.bin").write_bytes(mapping.tobytes())
    (dest / "palette.bin").write_bytes(regs.tobytes())
    t = v.tiles.astype(np.uint8)                                          # [8192, 8, 8]
    (dest / "tile_px.bin").write_bytes(((t[..., ::2] << 4) | t[..., 1::2]).tobytes())
    pens = np.zeros(len(t), np.int64)
    for p in range(16):
        pens |= (t == p).any((1, 2)).astype(np.int64) << p
    (dest / "tile_pens.bin").write_bytes(pens.astype(">u2").tobytes())
    weights = 1 << np.arange(7, -1, -1)
    opaque = ((t > 1) * weights).sum(2)
    shadow = ((t == 1) * weights).sum(2)
    (dest / "tile_masks.bin").write_bytes(np.stack([opaque, shadow], 2).astype(np.uint8).tobytes())
    c = v.chars.astype(np.uint8)                                          # [1024, 8, 8], 0-3
    rows = np.stack([(c[..., 0] << 6) | (c[..., 1] << 4) | (c[..., 2] << 2) | c[..., 3],
                     (c[..., 4] << 6) | (c[..., 5] << 4) | (c[..., 6] << 2) | c[..., 7]], 2)
    (dest / "char_rows.bin").write_bytes(rows.astype(np.uint8).tobytes())
    (dest / "char_pens.bin").write_bytes(bytes(sum(int((ch == v).any()) << v for v in range(4)) for ch in c))
    (dest / "char_blank.bin").write_bytes(bytes(int(not ch.any()) for ch in c))
    (dest / "nz4.bin").write_bytes(bytes(sum(int((b >> (6 - 2 * i)) & 3 != 0) << (3 - i) for i in range(4))
                                         for b in range(256)))
    (dest / "bitrev.bin").write_bytes(bytes(int("{:08b}".format(b)[::-1], 2) for b in range(256)))
    (dest / "sprite_code.s").write_text(sprite_code())
    print("renderer assets: %s" % dest, flush=True)


class Oracle:
    """the reference picture through the fixed palette: [240, 320] colour indices (the arcade's x 8-231 and 240-335)"""

    def __init__(self):
        from video import Video
        dest = build_dir("gauntlet")
        self.mapping = np.frombuffer((dest / "irgb_map.bin").read_bytes(), np.uint8)
        self.rgb = np.frombuffer((dest / "palette_rgb.bin").read_bytes(), np.uint8).reshape(16, 3)
        self.video = Video()

    def indices(self, raw, palette_ram):
        pens = np.frombuffer(bytes(palette_ram[:0x800]), ">u2").astype(np.int64)
        return self.mapping[pens[raw]]

    def picture(self, m):
        return self.picture_raw(m.vram(), m.palette(), m.xscroll)

    def picture_raw(self, vram, palette, xscroll):
        vram = bytes(vram)
        raw = self.video.render_raw(vram, xscroll, (vram[0x5F6E] << 8) | vram[0x5F6F])
        idx = self.indices(raw, palette)
        return np.hstack((idx[:, 8:232], idx[:, 240:336]))


if __name__ == "__main__":
    build()
