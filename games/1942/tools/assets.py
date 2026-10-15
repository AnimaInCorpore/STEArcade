"""1942 renderer assets (build/1942/): the arcade graphics in the orientation of the screen (rotated 270 degrees, see machine.py
render_rgb) as one-hot pen masks (for every pen the 16 bit mask of the pixels of a row that have it), from which the runtime bakes
STE bitplane data once a palette bank is known (an STE plane is the OR of the masks of the pens whose colour has that bit
set).  The tiles are kept as bit planes (a word a plane a row) and get their masks row by row as they are baked
(engine/rt/penmasks.s): 96 KB instead of 256 KB.  The sprites keep their masks: as planes they would save 196 KB, but the
sprite bakes made the 99th percentile tick 12% slower (the tiles' 1.5%).

  tile_planes.bin 512 tiles x 2 (flip y of the tile attribute) x 16 rows x 3 planes (pens 0-7);
                  row j of a tile is the ring line 15 - x of the tile (the background is drawn into a ring buffer whose lines
                  run down the tilemap's x axis), pixel i = raw y, the leftmost pixel in bit 15.  Flip x is the row order
                  (row j of the flipped tile is row 15 - j): bake_tile writes the rows from the end
  spr_masks.bin   512 sprites x 16 reordered rows x 16 words (pens 0-15, pen 15 = transparent)
  spr_opaque.bin  512 sprites x 16 words: the mask of the opaque pixels of a row (pen != 15)
  chr_masks.bin   512 characters x 8 rows x 4 bytes: M1 M2 M3 (pens 1-3, 8 pixels, leftmost in bit 7) and the opaque mask M1|M2|M3
  luts.bin        sb-4.d6 tile lookup (256 bytes), sb-8.k3 sprite lookup (256), sb-0.f1 character lookup (256), all & 15
  palmap.bin      4 banks x 256 bytes: arcade palette entry -> STE colour index (palettes.py)
  palette.bin     4 banks x 16 words: the STE palette registers
"""
import os
import sys
import numpy as np

sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from machine import Gfx, load, Machine1942
import palettes
from paths import build_dir


def tile_screen(g, code, flip):
    """[16 rows j][16 pixels i] pens of a tile as the ring shows it"""
    t = g.tiles[code]                      # [y][x]
    fx, fy = flip & 1, (flip >> 1) & 1
    out = np.zeros((16, 16), np.uint8)
    for j in range(16):
        for i in range(16):
            out[j, i] = t[15 - i if fy else i][j if fx else 15 - j]
    return out


def sprite_screen(g, code):
    s = g.sprites[code]                    # [y][x]
    out = np.zeros((16, 16), np.uint8)
    for j in range(16):
        for i in range(16):
            out[j, i] = s[i][15 - j]
    return out


def char_screen(g, code):
    c = g.chars[code]                      # [y][x] 8 x 8
    out = np.zeros((8, 8), np.uint8)
    for j in range(8):
        for i in range(8):
            out[j, i] = c[i][7 - j]
    return out


def one_hot(pens, npens):
    """pens [..., 16] (pixel 0 = leftmost) -> [..., npens] masks: bit 15 - i set where pixel i has the pen"""
    out = np.zeros(pens.shape[:-1] + (npens,), np.uint32)
    for p in range(npens):
        acc = np.zeros(pens.shape[:-1], np.uint32)
        sel = pens == p
        for i in range(16):
            acc |= sel[..., i].astype(np.uint32) << (15 - i)
        out[..., p] = acc
    return out


def planes(pens, nplanes):
    """pens [..., 16] -> [..., nplanes] words: bit 15 - i of plane b = bit b of pixel i (penmasks.s makes the masks)"""
    out = np.zeros(pens.shape[:-1] + (nplanes,), np.uint32)
    for b in range(nplanes):
        for i in range(16):
            out[..., b] |= ((pens[..., i] >> b) & 1).astype(np.uint32) << (15 - i)
    return out


def sprite_orders(opaque):
    """The order in which the rows of every sprite are baked and blitted: equal opaque masks adjacent, transparent rows last"""
    return [sorted(range(16), key=lambda row: (int(opaque[c, row]) == 0, int(opaque[c, row]), row)) for c in range(len(opaque))]


def build():
    g = Gfx()
    b = str(build_dir("1942"))
    os.makedirs(b, exist_ok=True)
    tiles = np.zeros((512, 2, 16, 16), np.uint8)       # (flip x is the row order: the runtime reverses it as it bakes)
    for code in range(512):
        for fy in range(2):
            tiles[code, fy] = tile_screen(g, code, fy << 1)
    open(os.path.join(b, "tile_planes.bin"), "wb").write(planes(tiles, 3).astype(">u2").tobytes())
    spr = np.zeros((512, 16, 16), np.uint8)
    for code in range(512):
        spr[code] = sprite_screen(g, code)
    opaque = one_hot((spr != 15).astype(np.uint8), 2)[..., 1]            # [512][16]
    open(os.path.join(b, "spr_opaque.bin"), "wb").write(opaque.astype(">u2").tobytes())
    # Group equal opaque masks, as in stefastbobs2: source words then advance
    # sequentially while destination rows jump. Bake directly in that order.
    orders = sprite_orders(opaque)
    spr_masks = one_hot(spr, 16)
    reordered = np.array([spr_masks[c, order] for c, order in enumerate(orders)])
    open(os.path.join(b, "spr_masks.bin"), "wb").write(reordered.astype(">u2").tobytes())
    open(os.path.join(b, "spr_order.bin"), "wb").write(bytes(row * 8 for order in orders for row in order))
    import spritegen
    spritegen.write(b, opaque, orders)
    chars = np.zeros((512, 8, 4), np.uint8)
    for code in range(512):
        c = char_screen(g, code)
        for j in range(8):
            m = [0, 0, 0, 0]
            for i in range(8):
                p = int(c[j, i])
                if p:
                    m[p - 1] |= 1 << (7 - i)
                    m[3] |= 1 << (7 - i)
            chars[code, j] = m
    open(os.path.join(b, "chr_masks.bin"), "wb").write(chars.tobytes())
    luts = bytes(v & 15 for v in load("sb-4.d6")) + bytes(v & 15 for v in load("sb-8.k3")) + bytes(v & 15 for v in load("sb-0.f1"))
    open(os.path.join(b, "luts.bin"), "wb").write(luts)
    # blank flags: 1 = the sprite / character has no opaque pixel
    open(os.path.join(b, "spr_blank.bin"), "wb").write(bytes(1 if not (spr[c] != 15).any() else 0 for c in range(512)))
    open(os.path.join(b, "chr_blank.bin"), "wb").write(bytes(1 if chars[c, :, 3].max() == 0 else 0 for c in range(512)))
    # the baking routines: or_<n> ORs the mask in d7 into the planes (d3-d6) of the bits of the colour index n
    lines = ["; generated by assets.py", "orp_tab:"]
    lines += ["\tdc.l\torp%d" % n for n in range(16)]
    for n in range(16):
        lines.append("orp%d:" % n)
        for k in range(4):
            if n >> k & 1:
                lines.append("\tor.w\td7,d%d" % (3 + k))
        lines.append("\trts")
    lines.append("pair_tab:")                        # the 4 chunk bits of 8 cell bits: bit j = cell 2j or 2j + 1
    for base in range(0, 256, 16):
        lines.append("	dc.b	" + ",".join(str(sum((((v >> (2 * j)) | (v >> (2 * j + 1))) & 1) << j for j in range(4))) for v in range(base, base + 16)))
    open(os.path.join(b, "render_tables.s"), "w").write("\n".join(lines) + "\n")
    pal = palettes.load_palettes()
    open(os.path.join(b, "palmap.bin"), "wb").write(bytes(sum(pal["map"], [])))
    open(os.path.join(b, "palette.bin"), "wb").write(np.array(pal["palette"], ">u2").tobytes())
    return pal


class Oracle:
    """What the STE screen must show: the reference's raw bitmap through the palette map, in the orientation of the screen
    ([256 rows][224 columns] colour indices)."""

    def __init__(self):
        self.pal = palettes.load_palettes()
        self.map = np.array(self.pal["map"], np.uint8)         # [bank][256]

    def frame(self, m):
        bmp = m.render_raw()[16:240]                           # [y - 16][x]
        idx = self.map[m.palette_bank][bmp]
        return idx.transpose(1, 0)[::-1]                       # [255 - x][y - 16]

    def rgb(self, idx, bank):
        pal = np.array(self.pal["rgb"][bank], np.uint8)
        return pal[idx]


if __name__ == "__main__":
    build()
    print("assets written to", build_dir("1942"))
