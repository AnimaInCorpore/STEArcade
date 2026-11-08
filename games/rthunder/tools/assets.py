"""The graphics ROMs and colour tables for the STE's renderer (src/render.s).

    from assets import build; build()     -> build/rthunder/ren_*.bin

  ren_t0.bin    4096 characters x 64 bytes: the CUS42 pair's tiles, pen 0-7 a pixel (7 = transparent), row by row
  ren_t1.bin    2048 x 64: the CUS43 pair's tiles
  ren_rowmap.bin  256 x 8: per colour row (a tile's attribute byte) the STE index of pens 0-6 (pen 7 = 0)
  ren_hi.bin    2 devices x 2 layers x 4 words: the tile code's bits 8-10 from the attribute's low two bits (the PROM's
                select; the CUS42 pair adds the tile bank, bit 11, at run time)
  ren_bk.bin    256: the STE index of back colour b (pen 7 of colour row b)
  ren_pal.bin   16 words: the STE palette (RGB 4 bits a channel)
The STE index of an indirect colour is the fitted palette's flat map (tools/palfit.py).
"""
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
from machine import Rthunder
from paths import build_dir
import palette_quantize as pq


def tables(m, flat):
    t0, t1, spr = m.gfx()
    lut = m.pen_table()
    rowmap = np.zeros((256, 8), np.uint8)
    for a in range(256):
        for px in range(7):
            rowmap[a, px] = flat[lut[(a * 8 + px) & 0x7FF]]
    pr = m.prom[0x1400:0x1420]
    hi = np.zeros((2, 2, 4), np.uint16)
    for dev in (0, 1):
        for layer in (0, 1):
            for c in range(4):
                if dev == 0:
                    sel = pr[((layer & 1) << 4) + (c << 2)]
                    hi[dev, layer, c] = ((sel & 0x0E) >> 1) << 8
                else:
                    sel = pr[((layer & 1) << 4) + c]
                    hi[dev, layer, c] = ((sel & 0xE0) >> 5) << 8
    bk = np.array([flat[lut[8 * b + 7]] for b in range(256)], np.uint8)
    return t0, t1, spr, rowmap, hi, bk


def build(out=None):
    out = out or build_dir("rthunder")
    d = np.load(out / "palfit.npz")
    flat, palette = d["flat"], d["palette"]
    m = Rthunder(cpus=False)
    t0, t1, spr, rowmap, hi, bk = tables(m, flat)
    (out / "ren_t0.bin").write_bytes(t0.astype(np.uint8).tobytes())
    (out / "ren_t1.bin").write_bytes(t1.astype(np.uint8).tobytes())
    (out / "ren_rowmap.bin").write_bytes(rowmap.tobytes())
    (out / "ren_hi.bin").write_bytes(hi.astype(">u2").tobytes())
    (out / "ren_bk.bin").write_bytes(bk.tobytes())
    (out / "ren_pal.bin").write_bytes(pq.ste_words(palette).tobytes())
    return t0, t1, rowmap, hi, bk


if __name__ == "__main__":
    build()
    print("written")
