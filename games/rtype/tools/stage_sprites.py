"""Whole sprites for R-Type's stage renderer (src/stage.s): one image per object definition (the user's idea,
2026-10-29: an object's entries composed once, at build time).

    venv/bin/python games/rtype/tools/stage_sprites.py STATES.pkl ...   -> build/rtype/stage_sprites.s, stage_sstream.bin

The definitions are the ones the recorded object lists show (tools/logic_test.py --record: m72_objs, src/natives.s):
an object (definition BW at ROM $10000 + BW, entry count n, colour, x, y) is n entries of 6 bytes (x offset, y offset
signed; the code; the attribute: flips bits 11 / 10, w bit 14, h bits 12-13).  The entries are composed into one
pen image (the first entry on top, as the arcade's list), cropped to its opaque pixels, and cut into 16-pixel strips
from its left edge; each strip is a shape for engine/sprite_programs.py (its rows' masks; shared by content).  The
colours are not in the data: the renderer colours a (definition, colour) once into its cache from the pens stored
here (per strip its opaque rows in the shape's order, 16 pens a row as 8 bytes, high nibble first, already shifted
left by the row's empty columns: sprite_programs.align_of).

Position: an entry is at screen x (x + dx) - 256 and y 384 - (y + dy) - 16 h in MAME's bitmap (the arcade masks x with
$3FF and y with $1FF; inside the visible area the unmasked values are the same).  The composite's top left corner is
at (x - 256 + OX, 384 - y + OY).

Star definitions (every entry's code in stage_model.STAR_SPRITES) are marked, not built: the renderer skips them.

The output (assembler, included by src/stage.s): the generated code and the shape records (sprite_programs: table
st_shapes), and
    st_defs:   per definition: dc.w BW, dc.l its record (0: a star) ... dc.w 0 (the renderer makes its lookup)
    a record:  dc.w OX, OY, H (rows), NS (strips), then per strip: dc.w its x (pixels from the left), its shape,
               the opaque rows R, dc.l its pens (R x 8 bytes)
"""
import argparse
import pickle
import struct
import sys
import zlib
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
import m72
import sprite_programs as SP
from m72board import load_regions
from paths import build_dir
import stage_model as SM

LB = 512                    # the renderer's buffer: bytes a line (src/stage.s ST_LB)


def definitions(paths):
    """{(bw, n)} of the recorded object lists"""
    defs = set()
    for p in paths:
        for f, item in pickle.load(open(p, "rb")):
            st = pickle.loads(zlib.decompress(item))
            o, end = st["objs"], st["objs_end"]
            for slot in list(range(0xC0, min(end, 0x3C0), 8)) + list(range(0x3C0, 0x400, 8)):
                bw, n = struct.unpack(">HB", o[slot:slot + 3])
                if bw:
                    defs.add((bw, n))
    return defs


def entries(rom, bw, n):
    out = []
    for e in range(n):
        a = 0x10000 + bw + 6 * e
        dx, dy = struct.unpack("<bb", rom[a:a + 2])
        code, attr = struct.unpack("<HH", rom[a + 2:a + 6])
        out.append((dx, dy, code, attr))
    return out


def compose(sprites, ents):
    """(pens [H, W], OX, OY) cropped to the opaque pixels, or None when nothing is opaque"""
    pieces = []
    for dx, dy, code, attr in ents:
        w, h = 1 << ((attr >> 14) & 3), 1 << ((attr >> 12) & 3)
        fx, fy = attr & 0x800, attr & 0x400
        for cx in range(w):
            for cy in range(h):
                c = code + (8 * (w - 1 - cx) if fx else 8 * cx) + (h - 1 - cy if fy else cy)
                src = sprites[c % len(sprites)]
                if fx:
                    src = src[:, ::-1]
                if fy:
                    src = src[::-1, :]
                pieces.append((dx + 16 * cx, -dy - 16 * h + 16 * cy, src))
    x0 = min(p[0] for p in pieces)
    y0 = min(p[1] for p in pieces)
    x1 = max(p[0] for p in pieces) + 16
    y1 = max(p[1] for p in pieces) + 16
    img = np.zeros((y1 - y0, x1 - x0), np.uint8)
    done = np.zeros(img.shape, bool)
    for px, py, src in pieces:                  # (the first entry on top)
        d = img[py - y0:py - y0 + 16, px - x0:px - x0 + 16]
        dn = done[py - y0:py - y0 + 16, px - x0:px - x0 + 16]
        show = (src != 0) & ~dn
        d[show] = src[show]
        dn |= src != 0
    if not done.any():
        return None
    ys, xs = np.flatnonzero(done.any(1)), np.flatnonzero(done.any(0))
    img = img[ys[0]:ys[-1] + 1, xs[0]:xs[-1] + 1]
    return img, x0 + xs[0], y0 + ys[0]


def build(paths):
    rom = load_regions("rtype")["main"]
    sprites = m72.Video("rtype").sprites
    defs = sorted(definitions(paths))
    shapes, shape_of = {}, {}
    recs, data = [], []
    stars = 0
    maxh = 0
    for bw, n in defs:
        ents = entries(rom, bw, n)
        if all((c & 0xFFF) in SM.STAR_SPRITES for _, _, c, _ in ents):
            recs.append((bw, None))
            stars += 1
            continue
        r = compose(sprites, ents)
        if r is None:
            recs.append((bw, None))
            continue
        img, ox, oy = r
        h, w = img.shape
        maxh = max(maxh, h)
        strips = []
        for s in range((w + 15) // 16):
            part = np.zeros((h, 16), np.uint8)
            seg = img[:, 16 * s:16 * s + 16]
            part[:, :seg.shape[1]] = seg
            masks = [int("".join("1" if v else "0" for v in row), 2) for row in (part != 0)]
            key = tuple(masks)
            if not any(masks):
                continue
            if key not in shape_of:
                shape_of[key] = len(shapes)
                shapes[len(shapes)] = list(masks)
            pens = bytearray()
            for g in SP.shape_order(masks):
                for row in g:
                    lz = SP.align_of(masks[row])
                    p = list(part[row, lz:]) + [0] * lz
                    pens += bytes((p[2 * k] << 4) | p[2 * k + 1] for k in range(8))
            strips.append((16 * s, shape_of[key], len(pens) // 8, bytes(pens)))
        recs.append((bw, (ox, oy, h, strips)))
    lines, stream, stats = SP.programs(shapes, len(shapes), line=LB, prefix="sts", table="st_shapes", record="str",
                                       stream_sym="st_sstream", xc_sym="BLT_XC", stream_mode=True, long_dst=True)
    out = ["; generated by games/rtype/tools/stage_sprites.py (%d definitions, %d stars, %d shapes; %s)" % (
        len(defs), stars, len(shapes), ", ".join("%s %s" % kv for kv in stats.items()))]
    out += lines
    out += ["\tsection data,data", "\teven", "st_defs:"]
    for bw, rec in recs:
        out.append("\tdc.w $%04X\n\tdc.l %s" % (bw, ("std_%04x" % bw) if rec else "0"))
    out.append("\tdc.w 0")
    for bw, rec in recs:
        if not rec:
            continue
        ox, oy, h, strips = rec
        out.append("std_%04x:\tdc.w %d,%d,%d,%d" % (bw, ox, oy, h, len(strips)))
        for x, sid, nr, _ in strips:
            out.append("\tdc.w %d,%d,%d\n\tdc.l stp_%04x_%d" % (x, sid, nr, bw, x))
    for bw, rec in recs:
        if not rec:
            continue
        for x, sid, nr, pens in rec[3]:
            out.append("stp_%04x_%d:" % (bw, x))
            for k in range(0, len(pens), 16):
                out.append("\tdc.b " + ",".join("$%02X" % b for b in pens[k:k + 16]))
    out.append("ST_MAXH = %d" % maxh)
    b = build_dir("rtype")
    (b / "stage_sprites.s").write_text("\n".join(out) + "\n")
    (b / "stage_sstream.bin").write_bytes(stream)
    pen_bytes = sum(len(s[3]) for _, r in recs if r for s in r[3])
    print("%d definitions (%d stars), %d shapes, the tallest %d rows; %s; stream %d bytes, pens %d bytes" % (
        len(defs), stars, len(shapes), maxh, stats, len(stream), pen_bytes))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("states", nargs="+")
    args = ap.parse_args()
    build(args.states)


if __name__ == "__main__":
    main()
