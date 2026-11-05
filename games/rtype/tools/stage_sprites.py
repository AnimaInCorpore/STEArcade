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

The definitions: the recordings (logic_test.py --record) and the (definition, entries) pairs of longer lock-step
runs (logic_test.py --snap --list --defs build/rtype/defs_SEED.json on a STAGE build), e.g.
    venv/bin/python games/rtype/tools/stage_sprites.py build/rtype/stage_states_1.pkl build/rtype/stage_states_8.pkl \
        build/rtype/defs_1.json build/rtype/defs_4.json build/rtype/defs_8.json build/rtype/defs_9.json \
        build/rtype/defs_10.json            (2026-10-30: 767 definitions; seed 8 to 8000: none missing)

Pre-coloured sprites (2026-10-31, the 14 MB development system): every (definition, colouring) of the recordings and
of logic_test.py --colours files (the same long runs: --snap --list --colours build/rtype/cols_SEED.json) is coloured
here (st_precol, stage_precol.bin; st_cidtab: a scene's sprite target -> its colouring's id, the renderer's cache
key); the renderer colours at run time only pairs no run recorded.  2026-10-31: the recordings above + cols_1/4/8/9/10
(seeds 1:3000 4:8000 8:20000 9:26000 10:25800): 1524 pairs, 499 KB.
"""
import argparse
import json
import pickle
import struct
import sys
import zlib
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
import m72
from m72board import load_regions
from paths import build_dir
import stage_model as SM

LB = 512                    # the renderer's buffer: bytes a line (src/stage.s ST_LB)


def definitions(paths, colourings=None):
    """{(bw, n)} of the recorded object lists; colourings (a dict) gets {bw: {colouring}} - a colouring the 16 STE
    indices of the object's colour row (pen 0: 0) - from the recordings and logic_test.py --colours files"""
    import stage_assets as SA
    scenes = SA.load_scenes()
    defs = set()
    cols = colourings if colourings is not None else {}
    migration_path = build_dir('rtype') / 'stage_colour_migration.json'
    migration = json.loads(migration_path.read_text()) if migration_path.exists() else {}
    for p in paths:
        if p.endswith(".json"):                  # (logic_test.py --defs: the pairs; --colours: the triples)
            for d in json.load(open(p)):
                defs.add((d[0], d[1]))
                if len(d) > 2:
                    if isinstance(d[2], dict):
                        rows = [scenes[d[2]['scene']][3][d[2]['target']]]
                    else:
                        old = bytes.fromhex(d[2]); key = (bytes([0]) + old[1:]).hex()
                        rows = [bytes.fromhex(v) for v in migration.get(key, [])] if max(old) <= 15 else [old]
                    for row in rows:
                        cols.setdefault(d[0], set()).add((0,) + tuple(row[1:]))
            continue
        cur = tiles = None
        for f, item in pickle.load(open(p, "rb")):
            st = pickle.loads(zlib.decompress(item))
            t = list(st["recs"])
            if tiles != t[16:]:
                cur = SA.choose_scene(t[16:], [sc[0] for sc in scenes], cur)
                tiles = t[16:]
            spm = scenes[cur][3]
            o, end = st["objs"], st["objs_end"]
            for slot in list(range(0xC0, min(end, 0x3C0), 8)) + list(range(0x3C0, 0x400, 8)):
                bw, n, col = struct.unpack(">HBB", o[slot:slot + 4])
                if bw:
                    defs.add((bw, n))
                    cols.setdefault(bw, set()).add((0,) + tuple(int(v) for v in spm[t[col & 15]][1:]))
    return defs


def colouring_ids():
    """{colouring: id} over every scene's sprite targets (id 0: all pens index 0) and the table src/stage.s reads
    (st_cidtab: per scene 256 words, a target's id)"""
    import stage_assets as SA
    ids = {(0,) * 16: 0}
    table = []
    for sc in SA.load_scenes():
        for t in range(256):
            c = (0,) + tuple(int(v) for v in sc[3][t][1:])
            table.append(ids.setdefault(c, len(ids)))
    return ids, table


def precolour(pens, shape, c, phases=None):
    """Plane words of packed colouring pairs, with source parity per reordered piece.

    A 16-pixel piece has four plane words; wider pieces store the planes in order.
    The native miss path consumes the same parity deltas in the record metadata.
    """
    def half(b, phase):
        px = []
        for v in b:
            px += [c[v >> 4], c[v & 15]]
        px = [((v >> 4) if (x + phase) % 2 == 0 else (v & 15)) for x, v in enumerate(px)]
        return [sum(((px[x] >> p) & 1) << (15 - x) for x in range(16)) for p in range(4)]
    out, k, row = [], 0, 0
    for cls, rows in shape:
        for _ in range(rows):
            phase = phases[row] if phases is not None else 0
            row += 1
            if cls:
                hs = [half(pens[k + 8 * j:k + 8 * j + 8], phase) for j in range(cls + 1)]
                out += [h[p] for p in range(4) for h in hs]
                k += 8 * (cls + 1)
            else:
                out += half(pens[k:k + 8], phase)
                k += 8
    return struct.pack(">%dH" % len(out), *out)


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


WIDE_MAX = 112          # (a wide run's pixels a pass at most: 7 source words, 8 with NFSR x 4 planes = 32 words)


def cls_of(w):
    """a piece's class: its source words - 1 (0: <= 16 pixels, 1: <= 32, 2-6: a wide run)"""
    return 0 if w <= 16 else 1 if w <= 32 else (w + 15) // 16 - 1


def pieces_greedy(img):
    """the opaque pixels of a whole sprite's rows as pieces: [(y, x0, width, aligned mask)].  A contiguous opaque run
    wider than 32 pixels is a wide piece (stedaimakaimura's sprite_compiler.js, the user 2026-11-01: END2 $FFFF - its
    inner words are opaque), at most WIDE_MAX pixels; the rest of a row split greedily: a piece takes the opaque
    pixels of up to 32 columns from its first one.  The mask's bit 16 * (class + 1) - 1 is the piece's first pixel"""
    out = []
    for y in range(img.shape[0]):
        cols = np.flatnonzero(img[y])
        if len(cols):
            brk = np.flatnonzero(np.diff(cols) > 1)
            rest = []
            for a, b in zip(np.r_[cols[0], cols[brk + 1]], np.r_[cols[brk], cols[-1]]):
                a, b = int(a), int(b)
                if b - a + 1 <= 32:
                    rest += range(a, b + 1)
                    continue
                while b - a + 1 > 32:                   # (a remainder of <= 32 pixels: the greedy pieces)
                    w = min(WIDE_MAX, b - a + 1)
                    n = 16 * (cls_of(w) + 1)
                    out.append((y, a, w, ((1 << w) - 1) << (n - w)))
                    a += w
                rest += range(a, b + 1)
            cols = np.array(sorted(rest), dtype=int)
        i = 0
        while i < len(cols):
            a = cols[i]
            j = i
            while j + 1 < len(cols) and cols[j + 1] <= a + 31:
                j += 1
            b = cols[j]
            w = b - a + 1
            n = 16 if w <= 16 else 32
            m = 0
            for c in cols[i:j + 1]:
                m |= 1 << (n - 1 - (c - a))
            out.append((y, int(a), int(w), m))
            i = j + 1
    return out


def pass_bus(cls2, m, w):
    """a piece's Blitter bus cycles over the 16 shifts (4 planes: reads, writes, a read-modify-write for every end
    mask other than $FFFF - 0 too), or None when it cannot be drawn at some shift (a wide piece's inner word not
    opaque)"""
    total = 0
    for k in range(16):
        try:
            xc, dyi, e1, e2, e3, ctl = pass_values(cls2, m, w, k)
        except AssertionError:
            return None
        masks = [e1] if xc == 1 else [e1] + [e2] * (xc - 2) + [e3]
        total += 16 * (xc - bool(ctl & 0x40) + xc + sum(v != 0xFFFF for v in masks))
    return total


def pieces_dp(img, overhead):
    """stefastbobs2's blitter_sprite_compiler.js: a row cut into the pieces of the least cost over the 16 shifts
    (pass_bus + overhead CPU cycles a pass), a piece of up to 32 pixels with any gaps, a wider one (up to WIDE_MAX)
    with gaps only where its passes' inner words stay opaque - as stage_sprites.pieces: [(y, x0, width, mask)]"""
    out = []
    cache = {}
    for y in range(img.shape[0]):
        cols = np.flatnonzero(img[y]).tolist()
        opaque = set(cols)
        best = [None] * len(cols) + [(0, None)]
        for i in range(len(cols) - 1, -1, -1):
            a = cols[i]
            for j in range(i, len(cols)):
                b = cols[j]
                w = b - a + 1
                if w > WIDE_MAX:
                    break
                cls2 = cls_of(w)
                n = 16 * (cls2 + 1)
                m = 0
                for c in cols[i:j + 1]:
                    m |= 1 << (n - 1 - (c - a))
                key = (cls2, m, w)
                if key not in cache:
                    cache[key] = pass_bus(cls2, m, w)
                c = cache[key]
                if c is None:
                    continue
                c += 16 * overhead + best[j + 1][0]
                if best[i] is None or c < best[i][0]:
                    best[i] = (c, j)
        i = 0
        while i < len(cols):
            j = best[i][1]
            a, b = cols[i], cols[j]
            w = b - a + 1
            n = 16 * (cls_of(w) + 1)
            m = 0
            for c in cols[i:j + 1]:
                m |= 1 << (n - 1 - (c - a))
            out.append((y, a, w, m))
            i = j + 1
    return out


DP_OVERHEAD = 32           # (CPU cycles a pass in pieces_dp's cost; 16 or 64 give the same within 0.1%)


def pieces(img):
    """the pieces of a whole sprite's rows: pieces_dp (the default since 2026-11-04), or pieces_greedy when DP_OVERHEAD is None"""
    return pieces_greedy(img) if DP_OVERHEAD is None else pieces_dp(img, DP_OVERHEAD)


def groups_of(pcs):
    """pieces with the same class (<= 16 / 17-32 pixels), aligned mask and position in their 16-pixel word: the same
    Blitter values at every shift (one setup a group: stefastbobs2's mask order) - in order of their first row"""
    g = {}
    for y, x0, w, m in pcs:
        g.setdefault((cls_of(w), m, x0 & 15, w), []).append((y, x0))
    return sorted(g.items(), key=lambda kv: kv[1][0])


def pass_values(cls2, m, w, k):
    """(XC, DYI, END1, END2, END3, control) of a piece (aligned mask m, width w, class cls2) at skew k (stefastbobs2:
    a <= 16 piece one word when it fits, else two with NFSR; a 17-32 piece two words, or three with NFSR; a wide run
    of n words n, or n + 1 with NFSR, END2 $FFFF: its inner words are opaque)"""
    if cls2 >= 2:
        nw = cls2 + 1
        xc = nw if k + w <= 16 * nw else nw + 1
        mm = (m << (16 * (xc - nw))) >> k               # (the mask over the pass's xc destination words)
        words = [(mm >> (16 * (xc - 1 - j))) & 0xFFFF for j in range(xc)]
        assert all(x == 0xFFFF for x in words[1:-1]), (m, w, k)
        return xc, (2 - 8 * (xc - 1)) & 0xFFFF, words[0], 0xFFFF, words[-1], (0xC040 if xc > nw else 0xC000) | k
    if not cls2:
        if k + w <= 16:
            xc, e1, e2, e3, ctl = 1, m >> k, 0xFFFF, 0, 0xC000 | k
        else:
            xc, e1, e2, e3, ctl = 2, m >> k, 0xFFFF, (m << (16 - k)) & 0xFFFF, 0xC040 | k
    else:
        if k + w <= 32:
            xc, e1, e2, e3, ctl = 2, (m >> (16 + k)) & 0xFFFF, 0xFFFF, (m >> k) & 0xFFFF, 0xC000 | k
        else:
            xc, e1, e2, e3 = 3, (m >> (16 + k)) & 0xFFFF, (m >> k) & 0xFFFF, (m << (16 - k)) & 0xFFFF
            ctl = 0xC040 | k
    return xc, (2 - 8 * (xc - 1)) & 0xFFFF, e1, e2, e3, ctl


def units_of_groups(grps):
    """the groups (one mask a group) as units: (cls2, width, [(y, x0, mask)])"""
    return [(cls, w, [(y, x0, m) for y, x0 in rows]) for (cls, m, k15, w), rows in grps]


def units_of_blocks(pcs):
    """sprite_compiler.js's blocks (stedaimakaimura): the pieces that fit one 16- or 32-pixel window of the sprite, each
    row aligned to the block's left (one XC, DYI, control word a block at every shift), the rows sorted by their mask
    (an end mask written again only where it changes) - as units (cls2, the block's width, [(y, block left, mask)])"""
    blocks = []
    wide = [p for p in pcs if p[2] > 32]
    for y, x0, w, m in [p for p in pcs if p[2] <= 32]:
        mw = 16 if w <= 16 else 32
        for blk in blocks:
            if blk["mw"] == mw and blk["R"] - mw + 1 <= x0 and blk["L"] + mw - 1 >= x0 + w - 1:
                blk["L"], blk["R"] = min(blk["L"], x0), max(blk["R"], x0 + w - 1)
                blk["rows"].append((y, x0, w, m))
                break
        else:
            blocks.append(dict(mw=mw, L=x0, R=x0 + w - 1, rows=[(y, x0, w, m)]))
    units = []
    for blk in blocks:
        n = blk["mw"]
        rows = []
        for y, x0, w, m in blk["rows"]:
            pw = 16 if w <= 16 else 32
            full = m << (n - pw) if n >= pw else m      # (the piece's mask, its first pixel at bit n - 1 ...)
            rows.append((y, blk["L"], full >> (x0 - blk["L"])))   # (... moved to the block's left)
        rows.sort(key=lambda r: (r[2], r[0]))
        units.append((1 if n == 32 else 0, blk["R"] - blk["L"] + 1, rows))
    units += units_of_groups(groups_of(wide))
    units.sort(key=lambda u: u[2][0][0])
    return units


def unit_rows(u, s):
    """a unit's rows' pass values at shift s: [(dst, (xc, dyi, e1, e2, e3, ctl))]"""
    cls2, w, rows = u
    return [(y * LB + ((s + x0) >> 4) * 8, pass_values(cls2, m, w, (s + x0) & 15)) for y, x0, m in rows]


def unit_changes(u):
    """per row after the first: (END1 [+ END2] written again, END3 written again) - when they differ at any shift"""
    cls2, w, rows = u
    vals = [unit_rows(u, s) for s in range(16)]
    out = []
    for i in range(1, len(rows)):
        e12 = any(vals[s][i][1][2:4] != vals[s][i - 1][1][2:4] if cls2 else vals[s][i][1][2] != vals[s][i - 1][1][2]
                  for s in range(16))
        e3 = any(vals[s][i][1][4] != vals[s][i - 1][1][4] for s in range(16))
        out.append((e12, e3))
    return out


def units_cost(units):
    """the estimated cycles of drawing them (the CPU's register writes, the Blitter's words), mean over the shifts"""
    cpu = blit = 0
    for u in units:
        cls2, w, rows = u
        cpu += 100 + 34 * (len(rows) - 1)
        for e12, e3 in unit_changes(u):
            cpu += (16 if cls2 else 12) * e12 + 12 * e3
        for s in range(16):
            for dst, (xc, *_rest) in unit_rows(u, s):
                blit += (32 * xc + 16) / 16
    return cpu + blit


def sprite_code(units, long_dst):
    """the drawing code of a whole sprite for every shift (its units' values from the stream at a0): word mode
    d0 = the destination's low word (a4 = DST low word, a3 = DYI), long mode a3 = the destination (a4 = DST)"""
    body = []
    for u in units:
        cls2, w, rows = u
        if long_dst:
            body += ["\tadda.w (a0)+,a3", "\tmove.l a3,(a4)", "\tmove (a0)+,BLT_XC.w", "\tmove (a0)+,BLT_DYI.w"]
        else:
            body += ["\tadd (a0)+,d0", "\tmove d0,(a4)", "\tmove (a0)+,BLT_XC.w", "\tmove (a0)+,(a3)"]
        body += ["\tmove.l (a0)+,(a1)" if cls2 else "\tmove (a0)+,(a1)", "\tmove (a0)+,(a6)", "\tmove d1,(a5)",
                 "\tmove (a0)+,(a2)"]
        for ((ya, xa, ma), (yb, xb, mb)), (e12, e3) in zip(zip(rows, rows[1:]), unit_changes(u)):
            if e12:
                body.append("\tmove.l (a0)+,(a1)" if cls2 else "\tmove (a0)+,(a1)")
            if e3:
                body.append("\tmove (a0)+,(a6)")
            d = (yb - ya) * LB + ((xb - xa) // 16) * 8
            if long_dst:
                body += ["\tadda.w d4,a3" if d == LB else "\tlea %d(a3),a3" % d, "\tmove.l a3,(a4)"]
            else:
                body += ["\tadd d4,d0" if d == LB else "\tadd #%d,d0" % d, "\tmove d0,(a4)"]
            body += ["\tmove d1,(a5)", "\tmove.b d2,(a2)"]
    return body + ["\trts"]


def sprite_streams(units):
    """per shift 0-15: each unit's first row's values (destination step, XC, DYI, END1, [END2 for 32-pixel units],
    END3, control), then its further rows' changed end masks"""
    out = []
    chg = [unit_changes(u) for u in units]
    for s in range(16):
        blk = bytearray()
        prev = 0
        for u, ch in zip(units, chg):
            cls2 = u[0]
            rv = unit_rows(u, s)
            dst, (xc, dyi, e1, e2, e3, ctl) = rv[0]
            vals = [dst - prev, xc, dyi, e1] + ([e2] if cls2 else []) + [e3, ctl]
            for (d, (_, _, f1, f2, f3, _)), (e12, e3c) in zip(rv[1:], ch):
                if e12:
                    vals += [f1, f2] if cls2 else [f1]
                if e3c:
                    vals.append(f3)
            for v in vals:
                blk += (int(v) & 0xFFFF).to_bytes(2, "big")
            prev = rv[-1][0]
        out.append(bytes(blk))
    return out


def build(paths):
    rom = load_regions("rtype")["main"]
    sprites = m72.Video("rtype").sprites
    cols = {}
    defs = sorted(definitions(paths, cols))
    cids, cidtab = colouring_ids()
    codes, streams = {}, {}
    code_lines, stream = [], bytearray()
    recs, pens_out = [], []
    stars = maxh = npieces = ngroups = nblocks = 0
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
        pcs = pieces(img)
        ug, ub = units_of_groups(groups_of(pcs)), units_of_blocks(pcs)
        units = ub if units_cost(ub) < units_cost(ug) else ug
        nblocks += units is ub
        npieces += sum(len(rows) for _, _, rows in units)
        ngroups += len(units)
        labels = []
        for long_dst in (False, True):
            body = sprite_code(units, long_dst)
            key = tuple(body)
            if key not in codes:
                codes[key] = "stc_%d" % len(codes)
                code_lines += [codes[key] + ":"] + body
            labels.append(codes[key])
        offs = []
        for blk in sprite_streams(units):
            if blk not in streams:
                streams[blk] = len(stream)
                stream += blk
            offs.append(streams[blk])
        # the pens a piece: 8 bytes (16 pixels) or 16 (32), left-aligned, in the groups' order
        pens = bytearray()
        shape, phases = [], []
        for cls2, uw, rows in units:
            shape.append((cls2, len(rows)))
            for y, x0, m in rows:
                phases.append((ox + oy + x0 + y) & 1)
                n_px = 16 * (cls2 + 1)
                p = [int(v) for v in img[y, x0:x0 + n_px]] + [0] * n_px
                p = p[:n_px]
                pens += bytes((p[2 * k] << 4) | p[2 * k + 1] for k in range(n_px // 2))
        recs.append((bw, (ox, oy, h, w, labels, offs, shape, len(pens) // 8, phases)))
        pens_out.append((bw, bytes(pens)))
    out = ["; generated by games/rtype/tools/stage_sprites.py (%d definitions, %d stars; %d pieces in %d groups; "
           "%d routines, %d stream bytes)" % (len(defs), stars, npieces, ngroups, len(codes), len(stream)),
           "\tsection text,code"] + code_lines
    out += ["\tsection data,data", "\teven", "st_defs:"]
    for bw, rec in recs:
        out.append("\tdc.w $%04X\n\tdc.l %s" % (bw, ("std_%04x" % bw) if rec else "0"))
    out.append("\tdc.w 0")
    pens_of = dict(pens_out)
    for bw, rec in recs:
        if not rec:
            continue
        ox, oy, h, w, labels, offs, shape, n8, phases = rec
        out.append("std_%04x:\tdc.w %d,%d,%d,%d,%d,%d" % (bw, ox, oy, h, w, n8, len(shape)))
        out.append("\tdc.l %s,%s,stp_%04x" % (labels[0], labels[1], bw))
        out.append("\tdc.l " + ",".join("st_sstream+%d" % o for o in offs))
        row = previous = 0
        for cls, count in shape:
            out.append("\tdc.b %d,%d" % (cls, count))
            deltas = []
            for phase in phases[row:row + count]:
                deltas.append((phase - previous) * 16384)
                previous = phase
            out.append("\tdc.w " + ",".join(map(str, deltas)))
            row += count
        out.append("\teven")
    for bw, pens in pens_out:
        out.append("stp_%04x:" % bw)
        for k in range(0, len(pens), 16):
            out.append("\tdc.b " + ",".join("$%02X" % b for b in pens[k:k + 16]))
    # pre-coloured (the 14 MB development system): every recorded (definition, colouring); st_preins puts them into
    # the colour cache, so the renderer colours nothing it has seen recorded
    pre, data, unknown = [], bytearray(), 0
    for bw, rec in recs:
        if not rec:
            continue
        shape = rec[6]
        for c in sorted(cols.get(bw, ())):
            if c not in cids:
                unknown += 1
                continue
            pre.append((bw, cids[c], len(data)))
            data += precolour(pens_of[bw], shape, c, rec[8])
    out.append("\tsection data,data\n\teven\nst_cidtab:")
    for k in range(0, len(cidtab), 16):
        out.append("\tdc.w " + ",".join("%d" % v for v in cidtab[k:k + 16]))
    out.append("st_precol:")
    for bw, cid, off in pre:
        out.append("\tdc.w $%04X,%d\n\tdc.l st_pcdata+%d" % (bw, cid, off))
    out.append("\tdc.w 0\nst_pcdata:\tincbin\t\"stage_precol.bin\"\n\teven")
    out.append("ST_MAXH = %d" % maxh)
    b = build_dir("rtype")
    (b / "stage_precol.bin").write_bytes(bytes(data))
    print("pre-coloured: %d (definition, colouring) pairs, %d KB; %d colourings; %d colourings not in a scene" % (
        len(pre), len(data) // 1024, len(cids), unknown))
    (b / "stage_sprites.s").write_text("\n".join(out) + "\n")
    (b / "stage_sstream.bin").write_bytes(bytes(stream))
    print("%d definitions (%d stars, %d in blocks), the tallest %d rows; %d pieces in %d units (%.1f a unit); %d "
          "routines (%d lines), stream %d bytes" % (len(defs), stars, nblocks, maxh, npieces, ngroups,
                                                    npieces / max(1, ngroups), len(codes), len(code_lines),
                                                    len(stream)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("states", nargs="+")
    ap.add_argument("--overhead", type=int, default=DP_OVERHEAD, help="CPU cycles a pass in pieces_dp's cost (0: greedy)")
    args = ap.parse_args()
    globals()["DP_OVERHEAD"] = args.overhead or None
    build(args.states)


if __name__ == "__main__":
    main()
