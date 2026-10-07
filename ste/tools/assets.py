"""Graphics assets for the STE port: global 16 colour palette and expanded tiles.

    python assets.py          -> build/dk_assets.s, build/dk_tiles.bin, build/palette.json

The arcade has 256 pens (bank * 64 + colour code * 4 + pixel).  A whole play-through
only ever shows 17 distinct colours, so one fixed STE palette (16 entries, 4 bit per
channel) is used and never changes: bank/colour code only select how the 2 bit
pixels are mapped to palette indices when a tile or sprite is drawn.
"""
import glob
import json
import os
import pickle
import sys
from collections import Counter

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dkong import Gfx

HERE = os.path.dirname(os.path.abspath(__file__))
STE = os.path.abspath(os.path.join(HERE, ".."))
BUILD = os.path.join(STE, "build")


def ste_word(c):
    r, g, b = c
    n = lambda v: ((v & 1) << 3) | (v >> 1)
    return (n(r) << 8) | (n(g) << 4) | n(b)


def pen_ste(gfx, pen):
    return tuple(v >> 4 for v in gfx.pens[pen])


def dist(a, b):
    # weighted distance on 4 bit channels
    return 3 * (a[0] - b[0]) ** 2 + 4 * (a[1] - b[1]) ** 2 + 2 * (a[2] - b[2]) ** 2


def build_palette(gfx):
    used = Counter()
    for f in glob.glob(os.path.join(STE, "pens_*.pkl")):
        for pen, c in pickle.load(open(f, "rb")).items():
            used[pen_ste(gfx, pen)] += c
    black = (0, 0, 0)
    used.pop(black, None)
    cols = [c for c, _ in used.most_common()]
    weights = dict(used)
    # merge nearest pairs until 15 colours remain (index 0 = black)
    while len(cols) > 15:
        best = None
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                d = dist(cols[i], cols[j]) * min(weights[cols[i]], weights[cols[j]]) ** 0.5
                if best is None or d < best[0]:
                    best = (d, i, j)
        _, i, j = best
        keep, drop = (i, j) if weights[cols[i]] >= weights[cols[j]] else (j, i)
        weights[cols[keep]] += weights[cols[drop]]
        del cols[drop]
    # sort by brightness for a stable layout
    cols.sort(key=lambda c: (c[0] * 3 + c[1] * 5 + c[2] * 2, c))
    palette = [black] + cols
    palette += [black] * (16 - len(palette))
    return palette


def sprite_quads(penmap):
    """Colour combos (bank * 16 + colour code) -> the pen values (1-3, bit 0-2) that set each
    of the four screen planes; combos with the same four masks share their sprite data."""
    quads, index = [], []
    for combo in range(64):
        q = tuple(sum(((penmap[combo * 4 + pv] >> k) & 1) << (pv - 1) for pv in (1, 2, 3))
                  for k in range(4))
        if q not in quads:
            quads.append(q)
        index.append(quads.index(q))
    return quads, index


def build_sprites(gfx, quads):
    """Sprite data for the Blitter, see rt/sprites.s.

    The screen is the arcade raster rotated, so a sprite pixel (column xx, row yy) lands on
    display line xx (flip x = lines drawn in the other direction) and display column
    15 - yy (flip y = bit order reversed, baked here).  v = code * 2 + flip y.

    masks: the endmasks of every line, for every skew u0 & 15: the outline of the line
    (holes included) shifted to the two screen words, [END1, END3] per line.
    Index: ((v * 16 + skew) * 16 + line) * 4.
    data: the 4 plane words of every line for a colour quad (the pixels of the line whose
    pen sets that plane), the source of the blits.  Index: ((v * Q + quad) * 16 + line) * 8.
    """
    masks = bytearray()
    data = bytearray()
    lines = {}
    for code in range(128):
        shape = gfx.sprites[code]
        for flipy in range(2):
            rows = []
            for r in range(16):
                pens = [int(shape[du if flipy else 15 - du][r]) for du in range(16)]
                rows.append(pens)
            lines[(code, flipy)] = rows
    for code in range(128):
        for flipy in range(2):
            rows = lines[(code, flipy)]
            outline = [sum(1 << (15 - du) for du in range(16) if pens[du]) for pens in rows]
            for skew in range(16):
                for m in outline:
                    if skew == 0:
                        e1, e3 = m, 0
                    else:
                        e1, e3 = m >> skew, (m << (16 - skew)) & 0xFFFF
                    masks += e1.to_bytes(2, "big") + e3.to_bytes(2, "big")
    for code in range(128):
        for flipy in range(2):
            rows = lines[(code, flipy)]
            for q in quads:
                for pens in rows:
                    for plane in range(4):
                        word = 0
                        for du in range(16):
                            pv = pens[du]
                            if pv and (q[plane] >> (pv - 1)) & 1:
                                word |= 1 << (15 - du)
                        data += word.to_bytes(2, "big")
    return bytes(masks), bytes(data)


def build():
    gfx = Gfx()
    palette = build_palette(gfx)
    # arcade pen -> palette index
    penmap = []
    for pen in range(256):
        c = pen_ste(gfx, pen)
        if c == (0, 0, 0):
            penmap.append(0)
            continue
        best = min(range(1, 16), key=lambda i: dist(c, palette[i]))
        penmap.append(best)
    # tiles: one 256-tile block per distinct (idx1, idx2, idx3)
    triples = {}
    combo_block = []
    for combo in range(64):                     # combo = bank * 16 + colour code
        t = tuple(penmap[combo * 4 + p] for p in (1, 2, 3))
        if t not in triples:
            triples[t] = len(triples)
        combo_block.append(triples[t])
    blocks = []
    for t in triples:
        lut = np.array([0, t[0], t[1], t[2]], np.uint8)
        data = bytearray()
        for code in range(256):
            tile = gfx.tiles[code]                  # raw [y][x] 2 bit
            disp = tile.T[::-1][::-1, ::-1]         # displayed [v][u] (cabinet flip bit = 1)
            idx = lut[disp]                         # [8][8] palette indices
            for v in range(8):
                row = idx[v]
                for p in range(4):
                    byte = 0
                    for u in range(8):
                        byte |= ((int(row[u]) >> p) & 1) << (7 - u)
                    data.append(byte)
        blocks.append(bytes(data))
    os.makedirs(BUILD, exist_ok=True)
    open(os.path.join(BUILD, "dk_tiles.bin"), "wb").write(b"".join(blocks))
    quads, quad_of = sprite_quads(penmap)
    spr_masks, spr_data = build_sprites(gfx, quads)
    open(os.path.join(BUILD, "dk_spr_masks.bin"), "wb").write(spr_masks)
    open(os.path.join(BUILD, "dk_spr_data.bin"), "wb").write(spr_data)
    colcodes = bytes(c & 0x0F for c in gfx.colcodes)
    lines = ["; generated by assets.py", "\tsection data,data", "\tcnop 0,2", "dk_palette:"]
    for i in range(0, 16, 8):
        lines.append("\tdc.w " + ",".join("$%03X" % ste_word(c) for c in palette[i:i + 8]))
    lines.append("dk_penmap:")
    for i in range(0, 256, 16):
        lines.append("\tdc.b " + ",".join(str(x) for x in penmap[i:i + 16]))
    lines.append("dk_colcodes:")
    for i in range(0, 256, 16):
        lines.append("\tdc.b " + ",".join(str(x) for x in colcodes[i:i + 16]))
    lines.append("SPR_VARIANT = %d\t\t; bytes of the colour data of one (code, flip y): %d quads of 16 lines of 4 words" % (len(quads) * 128, len(quads)))
    lines.append("\tcnop 0,2")
    lines.append("dk_spr_quad:\t\t; combo (bank*16+colour code) -> byte offset of its colour quad in a sprite's data")
    for i in range(0, 64, 16):
        lines.append("\tdc.w " + ",".join(str(quad_of[c] * 128) for c in range(i, i + 16)))
    lines.append("\tcnop 0,2")
    lines.append("dk_tile_combo:\t\t; combo (bank*16+colour code) -> offset of its 8 KiB block in dk_tiles")
    for i in range(0, 64, 8):
        lines.append("\tdc.l " + ",".join("%d" % (combo_block[c] * 8192) for c in range(i, i + 8)))
    lines.append("tile_cc:")
    cc = []
    off = []
    for idx in range(1024):
        col, row = idx & 31, idx >> 5
        cc.append(colcodes[col + 32 * (row >> 2)])
        if 2 <= row <= 29:
            tc, tr = 29 - row, col
            off.append(tr * 8 * 256 + 24 + (tc >> 1) * 8 + (tc & 1))
        else:
            off.append(-1)
    for i in range(0, 1024, 16):
        lines.append("\tdc.b " + ",".join(str(x) for x in cc[i:i + 16]))
    lines.append("\tcnop 0,2")
    lines.append("tile_mark_cell:\t\t; tile -> byte offset of its cell in tile_marks (40 per row, tile column + 4), -1: not shown")
    cells = []
    for idx in range(1024):
        col, row = idx & 31, idx >> 5
        cells.append(((col * 40 + (29 - row) + 4) * 2) if 2 <= row <= 29 else -1)
    for i in range(0, 1024, 16):
        lines.append("\tdc.w " + ",".join(str(x) for x in cells[i:i + 16]))
    lines.append("tile_off:")
    for i in range(0, 1024, 8):
        lines.append("\tdc.l " + ",".join(("$%X" % x) if x >= 0 else "-1" for x in off[i:i + 8]))
    lines.append("\tcnop 0,4")
    lines.append("dk_tiles:\tincbin \"dk_tiles.bin\"")
    lines.append("\tcnop 0,2")
    lines.append("dk_spr_masks:\tincbin \"dk_spr_masks.bin\"")
    lines.append("\tcnop 0,2")
    lines.append("dk_spr_data:\tincbin \"dk_spr_data.bin\"")
    open(os.path.join(BUILD, "dk_assets.s"), "w").write("\n".join(lines) + "\n")
    json.dump({"palette": palette, "penmap": penmap, "blocks": len(blocks), "combo_block": combo_block},
              open(os.path.join(BUILD, "palette.json"), "w"))
    return palette, penmap, blocks


if __name__ == "__main__":
    pal, pm, blocks = build()
    print("palette:", pal)
    print("tile blocks:", len(blocks), "x 8 KiB")
