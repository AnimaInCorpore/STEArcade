"""The graphics ROMs turned for the STE's picture (src/render.s).

    from assets import build; build()     -> build/dspirit/ren_chr.bin, ren_mask.bin, ren_spr.bin, tables

The picture is the arcade's turned upright (ROT90, no flip): picture row r = x, column c = 223 - y (tools/stemodel.py).
That is the geometry of Galaga '88's picture (ROT270 with its screen flip), so the turned forms are its
(games/galaga88/tools/assets.py):
  * a character T[y][x] shows as the cell R[dr][dc] = T[7 - dc][dr]
  * a sprite's 32 x 32 image I[y][x] as S[dr][dc] = I[dc][31 - dr] (render.s' ren_convert, Galaga '88's, reads the
    part's rows 31 - ix and its columns iy forwards or backwards by the flips: exactly Dragon Spirit's pixels)
Files:
  ren_chr.bin   16384 characters x 64 bytes: R[dr][dc] (8 bit pens), row by row
  ren_mask.bin  16384 x 8 bytes: per row dr the opaque pixels, bit 7 = column 0
  ren_spr.bin   1152 sprites x 512 bytes: S[dr][dc] (4 bit pens, two a byte, the left one high), row by row.  The
                region: obj-0..3 (codes 0-1023) and ds1_o4 loaded twice (1024-1151 = 1152-1279); codes from 1280 on are
                zeros in MAME's region (pen 0, opaque): render.s ren_spr_image
  ren_lab.bin   4096 x 4 bytes: the Oklab colour (L, a, b bytes, 0) of each 4 bit colour
  ren_q8.bin    256 bytes: an 8 bit channel -> its 4 bit level (round(v / 17))
  ren_sqrt.bin  4096 bytes: the integer square root (the histogram's weights)
"""
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
from m72_assets import lab_table
from namcos1 import NamcoS1
from paths import build_dir

NCHR = 16384
NSPR = 1152


def turned():
    """(chr pens [n,8,8], mask [n,8,8] bool, sprites [n,32,32]) in the STE's orientation"""
    m = NamcoS1("dspirit", cpus=False)
    chr_, mask, spr = m.gfx()
    rc = np.ascontiguousarray(chr_[:NCHR].transpose(0, 2, 1)[:, :, ::-1])
    rm = np.ascontiguousarray(mask[:NCHR].transpose(0, 2, 1)[:, :, ::-1])
    assert (spr[1024:1152] == spr[1152:1280]).all(), "ds1_o4 is not loaded twice"
    assert (spr[1280:] == 0).all()
    rs = np.ascontiguousarray(spr[:NSPR][:, :, ::-1].transpose(0, 2, 1))
    return rc, rm, rs


def build(out=None):
    out = out or build_dir("dspirit")
    rc, rm, rs = turned()
    (out / "ren_chr.bin").write_bytes(rc.astype(np.uint8).tobytes())
    (out / "ren_mask.bin").write_bytes(np.packbits(rm, axis=2).tobytes())
    s = rs.astype(np.uint8).reshape(NSPR, 32, 16, 2)
    (out / "ren_spr.bin").write_bytes(((s[..., 0] << 4) | s[..., 1]).astype(np.uint8).tobytes())
    (out / "ren_lab.bin").write_bytes(lab_table().tobytes())
    (out / "ren_q8.bin").write_bytes(np.round(np.arange(256) / 17).astype(np.uint8).tobytes())
    (out / "ren_sqrt.bin").write_bytes(np.floor(np.sqrt(np.arange(4096))).astype(np.uint8).tobytes())
    return rc, rm, rs


if __name__ == "__main__":
    build()
    print("written")
