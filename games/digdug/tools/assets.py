"""Dig Dug graphics for the STE: build/digdug/digdug_assets.s + binaries.

The arcade raster (288 x 224, x right, y down) is shown rotated 90 degrees clockwise (as Galaga's): display x = 223 - raw y,
display y = raw x; 224 pixels wide (chunk 3 of the 320 pixel line, GAME_X = 24 bytes), 288 lines in a screen buffer of
384 lines.

The picture is a background of 36 x 28 tiles of 2 bits (dd1.10b names the tile of each cell for the picture the video
latch selects, the colour comes from the tile code and the latch's colour bank), the 1-bit characters of the tile RAM over
it (pixel 0 transparent, pixel 1 one of 16 colours chosen by the character code), and the sprites.  A cell of the STE's
background screen is the tile's image (per bank / disable configuration: dd_bg_img, 4 planes x 8 rows, rotated) with the
character's pixels written over it (dd_fg_mask: a mask long per row, dd_fg_col: the colour's planes).  Sprites as in
Galaga (sprites.s, after Donkey Kong's): per (code, flip y, skew) the two end masks of every line, per (code, flip y,
colour quad) the four plane words of every line, the span of lines that are not empty; 256 codes.

Colours: the PROM has 23 different colours; one frame shows at most 15 of them (ref/pens.py counted them over play),
16 STE colours are fitted with engine/palette_quantize.py (the default fitter: sprite and tile counts compressed
separately, black fixed, flat mapping, no checker pairs), docs/colours.md.
"""
import json
import os, sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import numpy as np
from sprite_codegen import emit as emit_sprite_code
import palette_quantize as pq
from machine import Gfx

from paths import build_dir
BUILD = str(build_dir("digdug"))
NCODES = 256


def ste_word(c):
    r, g, b = c
    n = lambda v: ((v & 1) << 3) | (v >> 1)
    return (n(r) << 8) | (n(g) << 4) | n(b)


def pen_histograms(g, frames=7000):
    """{sprites, tiles}: pixels of each original RGB over a scripted game of the reference machine (cached)"""
    path = os.path.join(BUILD, "pen_hist.json")
    if os.path.exists(path):
        h = json.load(open(path))
        return [{tuple(map(int, k.split(","))): n for k, n in h[name].items()} for name in ("sprites", "tiles")]
    import random
    from collections import Counter
    from machine import DigDug
    m = DigDug(skip_tests=True, mcu_events=True)
    m.gfx = g
    rnd = random.Random(2)
    joy = 0
    spr, til = Counter(), Counter()
    for f in range(frames):
        m.in0 = m.in1 = 0xff
        if 600 <= f < 605: m.in1 &= ~0x10
        if 640 <= f < 645: m.in1 &= ~0x04
        if f >= 700:
            if f % 12 == 0: joy = rnd.choice([0, 1, 2, 4, 8])
            if joy: m.in0 &= ~joy
            if rnd.random() < 0.1: m.in1 &= ~0x01
        m.run_frame_port()
        if f % 5 == 0:
            full = m.render_raw()
            saved = bytes(m.ram[0x0b80:0x0c00])
            m.ram[0x0b80:0x0c00] = bytes(0x80)            # (no sprites: the tile layers only)
            tiles = m.render_raw()
            m.ram[0x0b80:0x0c00] = saved
            for pen, n in zip(*np.unique(tiles, return_counts=True)):
                til[tuple(g.palette[pen])] += int(n)
            for pen, n in zip(*np.unique(full[full != tiles], return_counts=True)):
                spr[tuple(g.palette[pen])] += int(n)
    json.dump({"sprites": {",".join(map(str, k)): n for k, n in spr.items()},
               "tiles": {",".join(map(str, k)): n for k, n in til.items()}}, open(path, "w"))
    return [spr, til]


def build_palette(g):
    """16 STE colours (4 bits a channel) and the map from the 32 palette entries to them"""
    os.makedirs(BUILD, exist_ok=True)
    inputs = sorted(set(tuple(c) for c in g.palette))
    pal, _ = pq.fit(pen_histograms(g), inputs, count=16, cache=os.path.join(BUILD, "palette_cache"), dither=False)
    idx = pq.flat_map(pal, inputs)
    pmap = [int(idx[inputs.index(tuple(c))]) for c in g.palette]
    return [tuple(int(v) // 17 for v in c) for c in pal], pmap


def rotate_char(tile):
    """8x8 [raw y][raw x] -> [display line][display x]: line = raw x, x = 7 - raw y."""
    return tile.T[:, ::-1]


def planes(idx, rows=8):
    """rows of 8 pixels (STE colours) -> per row 4 plane bytes"""
    data = bytearray()
    for v in range(rows):
        for p in range(4):
            byte = 0
            for u in range(8):
                byte |= ((int(idx[v][u]) >> p) & 1) << (7 - u)
            data.append(byte)
    return data


BG_CONFIGS = [(bank, dis) for bank in (0, 16, 32, 48) for dis in (0, 1)]


def build_bg(g, pmap):
    """dd_bg_img: per configuration (bank, disable) and tile code the image: 4 plane bytes x 8 rows"""
    out = bytearray()
    for bank, dis in BG_CONFIGS:
        for code in range(256):
            color = (0xF if dis else code >> 4) | bank
            lut = np.array([pmap[g.bg_lut[color * 4 + p]] for p in range(4)], np.uint8)
            out += planes(lut[rotate_char(g.bgtiles[code])])
    return bytes(out)


def build_fg(g, pmap):
    """masks: 128 characters x 8 rows, a long (the row's byte four times); colours: per code byte the four plane bytes of
    its colour (pixel 1); blank flags per character"""
    masks = bytearray()
    for code in range(128):
        pix = rotate_char(g.chars[code])
        for v in range(8):
            b = sum(1 << (7 - u) for u in range(8) if pix[v][u])
            masks += bytes([b] * 4)
    cols = bytearray()
    for code in range(256):
        c = pmap[((code >> 4) & 0x0e) | ((code >> 3) & 2)]
        cols += bytes([0xFF if (c >> p) & 1 else 0 for p in range(4)])
    blank = [1 if not g.chars[code].any() else 0 for code in range(128)]
    return bytes(masks), bytes(cols), blank


FLAME = 176                                  # shapes 248-251 are the flame's 72-75 with pen 2 transparent (colour 9)


def sprite_lines(g, code, flipy):
    """16 display lines of a sprite: line i = raw column i, pixel k = raw row 15 - k (flip y reverses the pixels)."""
    if code >= 256 - 8 and code - FLAME in range(72, 76):
        s = np.where(g.sprites[code - FLAME] == 2, 0, g.sprites[code - FLAME])
    else:
        s = g.sprites[code]
    lines = []
    for i in range(16):
        col = [int(s[15 - k, i]) for k in range(16)]
        if flipy:
            col = col[::-1]
        lines.append(col)
    return lines


USED_COLOURS = set(range(0, 13)) | set(range(24, 29)) | {50}      # the sprite colour codes seen in play (ref/pens.py)


def build_sprites(g, pmap):
    quads, quad_of = [(0, 0, 0)], []
    for c in range(64):
        if c not in USED_COLOURS:                # (never in the sprite RAM of any play: 29-63 are all-black pens)
            quad_of.append(0)
            continue
        q = tuple(pmap[g.sprite_lut[c * 4 + p]] if g.sprite_lut[c * 4 + p] != 0x1f else 0 for p in (1, 2, 3))
        trans = tuple(p for p in range(4) if g.sprite_lut[c * 4 + p] == 0x1f)
        # the shape's opaque pens must be exactly 1-3 (pen 0 transparent): true for the colour codes the game shows
        # except colour 9 (the flame: pens 0 and 2 transparent, shapes 248-251 below); the others (29-63: all pens
        # black and opaque, never on the screen) get a black silhouette
        if trans != (0,) and c != 9:
            q = (0, 0, 0)
        if q not in quads:
            quads.append(q)
        quad_of.append(quads.index(q))
    masks = bytearray()
    spans = []
    for code in range(NCODES):
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
    for code in range(NCODES):
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
    bgimg = build_bg(g, pmap)
    fgmask, fgcol, blank = build_fg(g, pmap)
    squads, squad_of, smasks, sdata, spans = build_sprites(g, pmap)
    os.makedirs(BUILD, exist_ok=True)
    open(os.path.join(BUILD, "dd_bg.bin"), "wb").write(bgimg)
    open(os.path.join(BUILD, "dd_fg_mask.bin"), "wb").write(fgmask)
    open(os.path.join(BUILD, "dd_fg_col.bin"), "wb").write(fgcol)
    open(os.path.join(BUILD, "dd_bgmap.bin"), "wb").write(g.bgmap)
    open(os.path.join(BUILD, "dd_spr_masks.bin"), "wb").write(smasks)
    open(os.path.join(BUILD, "dd_spr_data.bin"), "wb").write(sdata)
    lines = ["; generated by assets.py", "\tsection data,data", "\tcnop 0,2", "dd_palette:"]
    for i in range(0, 16, 8):
        lines.append("\tdc.w " + ",".join("$%03X" % ste_word(c) for c in pal[i:i + 8]))
    lines.append("dd_fg_blank:\t\t; 1 if the character has no pixel")
    for i in range(0, 128, 32):
        lines.append("\tdc.b " + ",".join(str(x) for x in blank[i:i + 32]))
    # the tile map: 36 x 28 display cells -> video RAM index (tilemap_scan) and screen offset
    lines.append("\tcnop 0,2")
    lines.append("dd_map_index:\t\t; display cell (36 rows of 28) -> video RAM index of the character")
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
    lines.append("dd_cell_of_index:\t\t; video RAM index -> display cell (-1: not shown)")
    cell = [-1] * 1024
    for n, i in enumerate(idx):
        cell[i] = n
    for i in range(0, 1024, 16):
        lines.append("\tdc.w " + ",".join(str(x) for x in cell[i:i + 16]))
    lines.append("dd_cell_off:\t\t; display cell -> byte offset of its character in the screen")
    for i in range(0, len(off), 8):
        lines.append("\tdc.l " + ",".join("$%X" % x for x in off[i:i + 8]))
    # the cell marks (sprites.s): 8 bytes per display row, bit 7 of byte 0 is cell column 0 = display x -32
    mb, mbit = [], []
    for n in range(36 * 28):
        row, dcol = n // 28, n % 28
        cc = dcol + 4
        mb.append((row + 8) * 8 + (cc >> 3))        # MARK_TOP = 8 rows above the display
        mbit.append(7 - (cc & 7))
    lines.append("dd_cell_mark_byte:\t\t; display cell -> byte offset of its bit in tile_marks")
    for i in range(0, len(mb), 16):
        lines.append("\tdc.w " + ",".join(str(x) for x in mb[i:i + 16]))
    lines.append("dd_cell_mark_bit:\t\t; display cell -> the bit")
    for i in range(0, len(mbit), 32):
        lines.append("\tdc.b " + ",".join(str(x) for x in mbit[i:i + 32]))
    lines.append("\tcnop 0,2")
    lines.append("dd_mark_cell:\t\t; mark row * 40 + cell column -> display cell (-1: not shown)")
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
    lines.append("dd_spr_quad:\t\t; colour code -> byte offset of its colour quad in a sprite's data")
    for i in range(0, 64, 16):
        lines.append("\tdc.w " + ",".join(str(squad_of[c] * 128) for c in range(i, i + 16)))
    lines.append("dd_spr_span:\t\t; (code, flip y) -> first line drawn, number of lines (0: blank)")
    for i in range(0, 2 * NCODES, 8):
        lines.append("\tdc.b " + ",".join("%d,%d" % s for s in spans[i:i + 8]))
    lines.append("\tcnop 0,2")
    lines.append("dd_spr_vdata:\t\t; (code, flip y) -> its colour data from the first line drawn (+ the quad's offset)")
    for i in range(0, 2 * NCODES, 4):
        lines.append("\tdc.l " + ",".join("dd_spr_data+%d" % (v * len(squads) * 128 + spans[v][0] * 8) for v in range(i, i + 4)))
    # draw_part: per (flags & 15, part) what the flags make of the part, 8 bytes: graphics offset 0-3 of the 2 x 2 sprite
    # (MAME's [[0,1],[2,3]][y ^ size * flip y][x ^ size * flip x]), flip y, 16 * x part (word), 16 * size y, 0, 16 * y part
    lines.append("dd_part_tab:\t\t; (flags & 15) * 4 + part (0 top left, 1 right, 2 below, 3 diagonal)")
    for flags in range(16):
        fx, fy, sx, sy = flags & 1, (flags >> 1) & 1, (flags >> 2) & 1, (flags >> 3) & 1
        row = []
        for part in range(4):
            xp, yp = part & 1, part >> 1
            off = 2 * (yp ^ (sy & fy)) + (xp ^ (sx & fx))
            row.append("%d,%d,0,%d,%d,0,0,%d" % (off, fy, 16 * xp, 16 * sy, 16 * yp))
        lines.append("\tdc.b " + ",".join(row))
    lines.append("dd_bgmap:\tincbin \"dd_bgmap.bin\"")
    lines.append("\tcnop 0,2")
    lines.append("dd_bg_img:\tincbin \"dd_bg.bin\"")
    lines.append("dd_fg_mask:\tincbin \"dd_fg_mask.bin\"")
    lines.append("dd_fg_col:\tincbin \"dd_fg_col.bin\"")
    lines.append("\tcnop 0,2")
    lines.append("dd_spr_masks:\tincbin \"dd_spr_masks.bin\"")
    lines.append("\tcnop 0,2")
    lines.append("dd_spr_data:\tincbin \"dd_spr_data.bin\"")
    lines.extend(emit_sprite_code("dd", smasks, spans))
    open(os.path.join(BUILD, "digdug_assets.s"), "w").write("\n".join(lines) + "\n")
    return pal, pmap, squads


if __name__ == "__main__":
    pal, pmap, sq = build()
    print("palette:", pal)
    print("sprite quads:", len(sq))
    print("sizes: bg %d KB, sprite masks %d KB, sprite data %d KB" % (len(BG_CONFIGS) * 256 * 32 // 1024, NCODES * 2 * 16 * 16 * 4 // 1024, NCODES * 2 * len(sq) * 128 // 1024))
