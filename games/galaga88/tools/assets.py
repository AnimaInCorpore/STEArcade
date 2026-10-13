"""The graphics ROMs turned for the STE's picture (src/render.s).

    from assets import build; build()     -> build/galaga88/ren_chr.bin, ren_mask.bin, ren_spr.bin

The STE picture is the arcade's turned by the cabinet (ROT270) with the game's screen flip (always on): picture row
r = 287 - x, column c = y of MAME's visible area (x 0-287, y 0-223; engine/namcos1.py render_rgb).  Worked out from
render_raw:
  * a layer pixel (tile RAM's logical X, Y; layers 0-3 X = (r - 332 - adj - sx) mod w, Y = (-25 - sy - c) mod h with
    adj 4 2 1 0 and the scroll registers sx, sy; the fixed layers X = r, Y = 223 - c): X grows down the picture, Y
    falls to the right.  So a character T[y][x] shows as the cell R[dr][dc] = T[7 - dc][dr].
  * a sprite (32 x 32 image I[y][x], the entry's sub-rectangle and flips applied in render.s): its arcade dx runs up
    the picture, dy to the right: the turned image S[dr][dc] = I[dc][31 - dr].
Files:
  ren_chr.bin   8192 characters x 64 bytes: R[dr][dc] (8 bit pens), row by row
  ren_mask.bin  8192 x 8 bytes: per row dr the opaque pixels, bit 7 = column 0
  ren_spr.bin   1536 sprites x 512 bytes: S[dr][dc] (4 bit pens, two a byte, the left one high), row by row
  ren_pal.bin   16 STE colour words (index 0 black): a fixed palette from the recorded reference pictures
                (build/galaga88/render_states.pkl; the first milestone, before the colours are chosen per scene)
  ren_lut.bin   4096 bytes: the index of an arcade colour by its 4 bit channels (R << 8 | G << 4 | B), the nearest in
                Oklab (the fixed palette's: the tests' colour quality reference)
  ren_lab.bin   4096 x 4 bytes: the Oklab colour (L, a, b bytes, 0) of each 4 bit colour (render.s chooses its colours
                and maps the arcade's to them there; engine/m72_assets.py lab_table)
  ren_q8.bin    256 bytes: an 8 bit channel -> its 4 bit level (round(v / 17))
  ren_sqrt.bin  4096 bytes: the integer square root (the histogram's weights)
"""
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
from m72_assets import oklab, lab_table
from namcos1 import NamcoS1
from paths import build_dir

NCHR = 8192
NSPR = 1536                      # (the six 128 KB sprite ROMs; render.s draws codes beyond as pen 0)


def turned():
    """(chr pens [n,8,8], mask [n,8,8] bool, sprites [n,32,32]) in the STE's orientation"""
    m = NamcoS1("galaga88", cpus=False)
    chr_, mask, spr = m.gfx()
    chr_, mask = chr_[:NCHR], mask[:NCHR]
    # R[dr][dc] = T[7 - dc][dr]: transpose, then reverse the columns
    rc = np.ascontiguousarray(chr_.transpose(0, 2, 1)[:, :, ::-1])
    rm = np.ascontiguousarray(mask.transpose(0, 2, 1)[:, :, ::-1])
    # S[dr][dc] = I[dc][31 - dr]
    rs = np.ascontiguousarray(spr[:NSPR][:, :, ::-1].transpose(0, 2, 1))
    return rc, rm, rs


def ste_word(rgb4):
    """(r, g, b) 0-15 -> the STE's colour word (bit 3 of a channel's nibble is its lowest bit)"""
    nib = lambda v: ((v >> 1) | ((v & 1) << 3)) & 15
    return int((nib(rgb4[0]) << 8) | (nib(rgb4[1]) << 4) | nib(rgb4[2]))


def static_palette(states=None, k=15, rounds=20):
    """(16 x 3 levels 0-15, lut 4096): k colours + black from the recorded pictures: the 4 bit colours counted, each
    weighted by the root of its count (sprites x 4), k-means in Oklab seeded by the heaviest colours far apart"""
    import pickle
    import stemodel
    states = states or pickle.load(open(build_dir("galaga88") / "render_states.pkl", "rb"))
    w = np.zeros(4096)
    for seq in states.values():
        for st in seq[::10]:
            pens, src = stemodel.ste_pens(st)
            rgb = np.stack([np.frombuffer(p, np.uint8) for p in st["pal"]], 1)
            ok = pens >= 0
            c = rgb[pens[ok]]
            key = (np.round(c / 17).astype(int) * [256, 16, 1]).sum(1)
            wt = np.where(src[ok] >= 100, 4.0, 1.0)
            w += np.bincount(key, wt, 4096)
    w = np.sqrt(w)
    keys = np.nonzero(w)[0]
    lv = np.stack([keys >> 8, (keys >> 4) & 15, keys & 15], 1)
    lab = oklab(lv * 17)
    ww = w[keys]
    # seeds: farthest-point from the heaviest (black excluded: index 0 is black)
    cent = [lab[np.argmax(ww)]]
    for _ in range(k - 1):
        d = np.min([((lab - c) ** 2).sum(1) for c in cent], 0)
        cent.append(lab[np.argmax(d * ww)])
    cent = np.array(cent)
    black = oklab(np.zeros(3))
    for _ in range(rounds):
        allc = np.vstack([black, cent])
        lab_idx = np.argmin(((lab[:, None] - allc[None]) ** 2).sum(2), 1)
        for j in range(k):
            sel = lab_idx == j + 1
            if sel.any():
                cent[j] = (lab[sel] * ww[sel, None]).sum(0) / ww[sel].sum()
    # each centre as the 4 bit colour nearest it
    allk = np.stack([np.arange(4096) >> 8, (np.arange(4096) >> 4) & 15, np.arange(4096) & 15], 1)
    alllab = oklab(allk * 17)
    pal = [np.zeros(3, int)] + [allk[np.argmin(((alllab - c) ** 2).sum(1))] for c in cent]
    pal = np.array(pal)
    plab = oklab(pal * 17)
    lut = np.argmin(((alllab[:, None] - plab[None]) ** 2).sum(2), 1).astype(np.uint8)
    return pal, lut


def build(out=None):
    out = out or build_dir("galaga88")
    rc, rm, rs = turned()
    (out / "ren_chr.bin").write_bytes(rc.astype(np.uint8).tobytes())
    (out / "ren_mask.bin").write_bytes(np.packbits(rm, axis=2).tobytes())
    s = rs.astype(np.uint8).reshape(NSPR, 32, 16, 2)
    (out / "ren_spr.bin").write_bytes(((s[..., 0] << 4) | s[..., 1]).astype(np.uint8).tobytes())
    (out / "ren_lab.bin").write_bytes(lab_table().tobytes())
    (out / "ren_q8.bin").write_bytes(np.round(np.arange(256) / 17).astype(np.uint8).tobytes())
    (out / "ren_sqrt.bin").write_bytes(np.floor(np.sqrt(np.arange(4096))).astype(np.uint8).tobytes())
    if not (out / "ren_lut.bin").exists():
        pal, lut = static_palette()
        (out / "ren_pal.bin").write_bytes(b"".join(ste_word(c).to_bytes(2, "big") for c in pal))
        (out / "ren_lut.bin").write_bytes(lut.tobytes())
    return rc, rm, rs


if __name__ == "__main__":
    build()
    print("written")
