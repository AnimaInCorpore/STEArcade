"""Galaga graphics for the STE: build/galaga_assets.s + binaries.

The arcade raster (288 x 224, x right, y down) is shown rotated 90 degrees clockwise:
display x = 223 - raw y, display y = raw x; 224 pixels wide (chunk 3 of the 320 pixel
line, GAME_X = 24 bytes), 288 lines in a screen buffer of 384 lines (the top CROP_TOP
lines are not shown, the STE shows 277).

Characters: 8 x 8, 2 bits per pixel, 64 colour codes through a lookup PROM to the
palette; pen 0 is transparent (and black in the background screen), so a character cell
holds its pixels (4 planes, 8 rows, one byte each, rotated) per colour quad and its
opacity mask.  Sprites as in Donkey Kong (sprites.s): per (code, flip y, skew) the two
endmasks of every line, per (code, flip y, colour quad) the four plane words of every
line, the span of lines that are not empty.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from galaga import Gfx, Starfield

HERE = os.path.dirname(os.path.abspath(__file__))
STE = os.path.abspath(os.path.join(HERE, ".."))
BUILD = os.path.join(STE, "build")


def ste_word(c):
    r, g, b = c
    n = lambda v: ((v & 1) << 3) | (v >> 1)
    return (n(r) << 8) | (n(g) << 4) | n(b)


def dist(a, b):
    return 3 * (a[0] - b[0]) ** 2 + 4 * (a[1] - b[1]) ** 2 + 2 * (a[2] - b[2]) ** 2


def build_palette(g):
    """16 STE colours: black, the game's colours, two for the stars.  Returns the colours
    (4 bit per channel) and the map from the 96 arcade palette entries to them."""
    # the palette entries the game draws with (ref/galaga4.py over attract mode and play:
    # sprites 0-14, characters 16-29); the lookup PROMs name three more, which get the
    # nearest of these
    used = [0, 1, 2, 3, 5, 6, 7, 8, 9, 11, 12, 13, 14, 16, 17, 18, 22, 27, 29]
    cols = sorted(set(tuple(v >> 4 for v in g.palette[i]) for i in used) - {(0, 0, 0)})
    assert len(cols) <= 13, cols
    pal = [(0, 0, 0)] + cols
    while len(pal) < 14:
        pal.append((0, 0, 0))
    pal += [(4, 4, 4), (9, 9, 9)]                 # stars: dim and bright grey
    pmap = []
    for i in range(96):
        c = tuple(v >> 4 for v in g.palette[i])
        pmap.append(min(range(16), key=lambda k: dist(c, pal[k])))
    return pal, pmap


def rotate_char(tile):
    """8x8 [raw y][raw x] -> [display line][display x]: line = raw x, x = 7 - raw y."""
    return tile.T[:, ::-1]


def build_chars(g, pmap):
    """Per colour quad the 128 characters (rotated, 4 planes x 8 rows), and the opacity
    masks.  A quad = the STE colour of pens 1-3 (pen 0 transparent)."""
    quads, quad_of = [], []
    for c in range(64):
        q = tuple(pmap[g.char_lut[c * 4 + p]] if g.char_lut[c * 4 + p] != 0x1f else 0 for p in (1, 2, 3))
        if q not in quads:
            quads.append(q)
        quad_of.append(quads.index(q))
    data = bytearray()
    for q in quads:
        lut = np.array([0, q[0], q[1], q[2]], np.uint8)
        for code in range(128):
            disp = rotate_char(g.chars[code])
            idx = lut[disp]
            for v in range(8):
                row = idx[v]
                for p in range(4):
                    byte = 0
                    for u in range(8):
                        byte |= ((int(row[u]) >> p) & 1) << (7 - u)
                    data.append(byte)
    masks = bytearray()
    for code in range(128):
        disp = rotate_char(g.chars[code])
        for v in range(8):
            byte = 0
            for u in range(8):
                if disp[v, u]:
                    byte |= 1 << (7 - u)
            masks.append(byte)
    blank = [code for code in range(128) if not g.chars[code].any()]
    return quads, quad_of, bytes(data), bytes(masks), blank


def sprite_lines(g, code, flipy):
    """16 display lines of a sprite: line i = raw column i, pixel k = raw row 15 - k
    (flip y reverses the pixels)."""
    s = g.sprites[code]
    lines = []
    for i in range(16):
        col = [int(s[15 - k, i]) for k in range(16)]
        if flipy:
            col = col[::-1]
        lines.append(col)
    return lines


def build_sprites(g, pmap):
    quads, quad_of = [], []
    for c in range(64):
        q = tuple(pmap[g.sprite_lut[c * 4 + p]] if g.sprite_lut[c * 4 + p] != 0x0f else 0 for p in (1, 2, 3))
        trans = tuple(p for p in range(4) if g.sprite_lut[c * 4 + p] == 0x0f)
        # the shape's opaque pens must be exactly 1-3 (pen 0 transparent): true for every
        # colour code the game shows (ref/galaga4.py); others get all pens opaque = black
        if trans != (0,):
            q = (0, 0, 0)
        if q not in quads:
            quads.append(q)
        quad_of.append(quads.index(q))
    masks = bytearray()
    spans = []
    for code in range(128):
        for flipy in range(2):
            lines = sprite_lines(g, code, flipy)
            outline = [sum(1 << (15 - k) for k in range(16) if pens[k]) for pens in lines]
            drawn = [i for i, m in enumerate(outline) if m]
            spans.append((drawn[0], drawn[-1] - drawn[0] + 1) if drawn else (0, 0))
            for skew in range(16):
                for m in outline:
                    if skew == 0:
                        e1, e3 = m, 0
                    else:
                        e1, e3 = m >> skew, (m << (16 - skew)) & 0xFFFF
                    masks += e1.to_bytes(2, "big") + e3.to_bytes(2, "big")
    data = bytearray()
    for code in range(128):
        for flipy in range(2):
            lines = sprite_lines(g, code, flipy)
            for q in quads:
                for pens in lines:
                    for plane in range(4):
                        word = 0
                        for k in range(16):
                            pv = pens[k]
                            if pv and (q[pv - 1] >> plane) & 1:
                                word |= 1 << (15 - k)
                        data += word.to_bytes(2, "big")
    return quads, quad_of, bytes(masks), bytes(data), spans


def build():
    g = Gfx()
    pal, pmap = build_palette(g)
    cquads, cquad_of, cdata, cmasks, blank = build_chars(g, pmap)
    squads, squad_of, smasks, sdata, spans = build_sprites(g, pmap)
    os.makedirs(BUILD, exist_ok=True)
    open(os.path.join(BUILD, "ga_chars.bin"), "wb").write(cdata)
    open(os.path.join(BUILD, "ga_spr_masks.bin"), "wb").write(smasks)
    open(os.path.join(BUILD, "ga_spr_data.bin"), "wb").write(sdata)
    lines = ["; generated by galaga_assets.py", "\tsection data,data", "\tcnop 0,2", "ga_palette:"]
    for i in range(0, 16, 8):
        lines.append("\tdc.w " + ",".join("$%03X" % ste_word(c) for c in pal[i:i + 8]))
    lines.append("ga_star_colour:\t\t; 64 star colours -> STE colour")
    for i in range(0, 64, 16):
        lines.append("\tdc.b " + ",".join(str(pmap[32 + k]) for k in range(i, i + 16)))
    lines.append("CHAR_QUADS = %d" % len(cquads))
    lines.append("ga_char_quad:\t\t; colour code -> byte offset of its quad's 128 characters (32 bytes each)")
    for i in range(0, 64, 8):
        lines.append("\tdc.l " + ",".join(str(cquad_of[c] * 128 * 32) for c in range(i, i + 8)))
    lines.append("ga_char_blank:\t\t; 1 if the character has no opaque pixel")
    bl = [1 if c in blank else 0 for c in range(128)]
    for i in range(0, 128, 32):
        lines.append("\tdc.b " + ",".join(str(x) for x in bl[i:i + 32]))
    lines.append("\tcnop 0,2")
    lines.append("ga_char_masks:\t\t; character -> 8 bytes of opacity (rotated)")
    for i in range(0, 1024, 16):
        lines.append("\tdc.b " + ",".join(str(x) for x in cmasks[i:i + 16]))
    # the tile map: 36 x 28 display cells -> video RAM index (tilemap_scan) and screen offset
    lines.append("\tcnop 0,2")
    lines.append("ga_map_index:\t\t; display cell (36 rows of 28) -> video RAM index of the character")
    idx = []
    off = []
    for drow in range(36):          # display row = raw column
        for dcol in range(28):      # display column = 27 - raw row
            col, row = drow, 27 - dcol
            r, c = row + 2, col - 2
            i = (r + ((c & 0x1f) << 5)) if (c & 0x20) else (c + (r << 5))
            idx.append(i)
            x = dcol * 8
            off.append(drow * 8 * 256 + 24 + (x >> 4) * 8 + ((x >> 3) & 1))
    for i in range(0, len(idx), 14):
        lines.append("\tdc.w " + ",".join(str(x) for x in idx[i:i + 14]))
    lines.append("ga_cell_of_index:\t\t; video RAM index -> display cell (-1: not shown)")
    cell = [-1] * 1024
    for n, i in enumerate(idx):
        cell[i] = n
    for i in range(0, 1024, 16):
        lines.append("\tdc.w " + ",".join(str(x) for x in cell[i:i + 16]))
    lines.append("ga_cell_off:\t\t; display cell -> byte offset of its character in the screen")
    for i in range(0, len(off), 8):
        lines.append("\tdc.l " + ",".join("$%X" % x for x in off[i:i + 8]))
    # the cell marks (galaga_sprites.s): 8 bytes per display row, bit 7 of byte 0 is cell
    # column 0 = display x -32 (the game area starts at cell column 4)
    mb, mbit = [], []
    for n in range(36 * 28):
        row, dcol = n // 28, n % 28
        cc = dcol + 4
        mb.append((row + 8) * 8 + (cc >> 3))        # MARK_TOP = 8 rows above the display
        mbit.append(7 - (cc & 7))
    lines.append("ga_cell_mark_byte:\t\t; display cell -> byte offset of its bit in tile_marks")
    for i in range(0, len(mb), 16):
        lines.append("\tdc.w " + ",".join(str(x) for x in mb[i:i + 16]))
    lines.append("ga_cell_mark_bit:\t\t; display cell -> the bit")
    for i in range(0, len(mbit), 32):
        lines.append("\tdc.b " + ",".join(str(x) for x in mbit[i:i + 32]))
    # and the way back: per mark bit (MARK_ROWS rows of 40 cell columns) the display cell
    lines.append("\tcnop 0,2")
    lines.append("ga_mark_cell:\t\t; mark row * 40 + cell column -> display cell (-1: not shown)")
    mc = []
    for row in range(8 + 36 + 8):
        for cc in range(40):
            drow, dcol = row - 8, cc - 4
            mc.append(drow * 28 + dcol if 0 <= drow < 36 and 0 <= dcol < 28 else -1)
    for i in range(0, len(mc), 20):
        lines.append("\tdc.w " + ",".join(str(x) for x in mc[i:i + 20]))
    lines.append("\tcnop 0,2")
    lines.append("SPR_VARIANT = %d\t\t; bytes of colour data of one (code, flip y): %d quads of 16 lines of 4 words" % (len(squads) * 128, len(squads)))
    lines.append("\tcnop 0,2")
    lines.append("ga_spr_quad:\t\t; colour code -> byte offset of its colour quad in a sprite's data")
    for i in range(0, 64, 16):
        lines.append("\tdc.w " + ",".join(str(squad_of[c] * 128) for c in range(i, i + 16)))
    lines.append("ga_spr_span:\t\t; (code, flip y) -> first line drawn, number of lines (0: blank)")
    for i in range(0, 256, 8):
        lines.append("\tdc.b " + ",".join("%d,%d" % s for s in spans[i:i + 8]))
    lines.append("\tcnop 0,2")
    lines.append("ga_chars:\tincbin \"ga_chars.bin\"")
    lines.append("\tcnop 0,2")
    lines.append("ga_spr_masks:\tincbin \"ga_spr_masks.bin\"")
    lines.append("\tcnop 0,2")
    lines.append("ga_spr_data:\tincbin \"ga_spr_data.bin\"")
    open(os.path.join(BUILD, "galaga_assets.s"), "w").write("\n".join(lines) + "\n")
    return pal, pmap, cquads, squads


if __name__ == "__main__":
    pal, pmap, cq, sq = build()
    print("palette:", pal)
    print("char quads:", len(cq), "sprite quads:", len(sq))
    print("sizes: chars %d KB, sprite masks 256 KB, sprite data %d KB" % (len(cq) * 4, len(sq) * 32))
