"""The STE renderer's data for Splatterhouse (src/render.s), from the MAME set's graphics ROMs.

    venv/bin/python games/splatter/tools/assets.py          -> build/splatter/ren_*.bin

The arcade's colours are in palette RAM (they change per stage and in fades), so nothing here is baked to STE colours:
the renderer maps pens to its 16 indices at run time (render.s, "Colours").  Files (big-endian):

    ren_chr.bin      12288 characters (8 x 8, a byte a pixel: the pen in its 256-colour bank), 64 bytes each, row-major
                     (the CHR ROMs as MAME loads them; codes 12288-16383 read the empty part of the region: pens 0)
    ren_chrmask.bin  16384 characters' opacity, 8 bytes each (a byte a row, bit 7 = the left pixel): the mask ROM
    ren_chrflag.bin  16384 bytes: 0 = transparent, 1 = mixed, 2 = opaque
    ren_chruni.bin   16384 words: the pen of a character of one pen only ($00pp), else $FFFF
    ren_spr.bin      2048 sprite cells (32 x 32, 4 bits a pixel, the left pixel in the high nibble, 15 transparent), each
                     only its opaque bounding box: the rows y0-y1, the bytes (pixel pairs) b0-b1 of each, row-major
    ren_spr_idx.bin  2048 x 8 bytes: the box's data offset (long), y0, y1, b0, b1 (an empty cell: y0 = 255)
    ren_lab.bin      4096 x 4 bytes: Oklab of the STE colour r g b (4 bits each, index r * 256 + g * 16 + b): L, a, b as
                     bytes (L * 255, a and b * 255 / 0.8 + 128), 0
    ren_q4.bin       256 bytes: an 8-bit channel -> its nearest 4-bit STE level (round(v / 17))
"""
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[2] / "engine")]
from paths import build_dir

NCHR = 0xC0000 // 64


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


def q4_table():
    return np.round(np.arange(256) / 17).astype(np.uint8)


def lab_table():
    n = np.arange(16) * 17
    rgb = np.stack(np.meshgrid(n, n, n, indexing="ij"), -1).reshape(-1, 3)
    lab = lab_bytes(rgb)
    return np.concatenate([lab, np.zeros((4096, 1), np.int32)], 1).astype(np.uint8)


def sprite_boxes(s):
    """(the boxes' data, the index) of the 2048 cells (see ren_spr.bin)"""
    packed = (s[:, :, 0::2] << 4) | s[:, :, 1::2]          # 2048 x 32 rows x 16 bytes
    data = bytearray()
    idx = bytearray()
    for c in range(2048):
        op = packed[c] != 0xFF
        ys = np.nonzero(op.any(1))[0]
        bs = np.nonzero(op.any(0))[0]
        if not len(ys):
            idx += (0).to_bytes(4, "big") + bytes([255, 0, 0, 0])
            continue
        y0, y1, b0, b1 = ys[0], ys[-1], bs[0], bs[-1]
        idx += len(data).to_bytes(4, "big") + bytes([y0, y1, b0, b1])
        data += packed[c, y0:y1 + 1, b0:b1 + 1].tobytes()
    if len(data) & 1:
        data += b"\xff"
    return bytes(data), bytes(idx)


def load_gfx():
    from namcos1 import NamcoS1
    m = NamcoS1("splatter", cpus=False)
    chr_, mask, spr = m.gfx()
    return np.asarray(chr_), np.asarray(mask), np.asarray(spr), m


def build(out=None):
    out = Path(out or build_dir("splatter"))
    chr_, mask, spr, m = load_gfx()
    (out / "ren_chr.bin").write_bytes(chr_[:NCHR].astype(np.uint8).tobytes())
    (out / "ren_chrmask.bin").write_bytes(bytes(m.mask_rom))
    opaque = mask.reshape(-1, 64)
    flag = np.where(opaque.all(1), 2, np.where(opaque.any(1), 1, 0)).astype(np.uint8)
    (out / "ren_chrflag.bin").write_bytes(flag.tobytes())
    px = chr_.reshape(-1, 64).astype(np.int32)
    uni = np.where((px == px[:, :1]).all(1), px[:, 0], 0xFFFF)
    uni[NCHR:] = 0
    (out / "ren_chruni.bin").write_bytes(uni.astype(">u2").tobytes())
    data, idx = sprite_boxes(spr[:2048].astype(np.uint8))
    (out / "ren_spr.bin").write_bytes(data)
    (out / "ren_spr_idx.bin").write_bytes(idx)
    (out / "ren_lab.bin").write_bytes(lab_table().tobytes())
    (out / "ren_q4.bin").write_bytes(q4_table().tobytes())
    return out


if __name__ == "__main__":
    print("assets in", build())
