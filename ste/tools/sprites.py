"""Fast Blitter sprites for the STE (method of FAST_BLITTER_SPRITES.md).

    python sprites.py [--shapes shapes.pkl]  ->  build/dk_sprites.s, build/dk_sprdata.bin

Every sprite shape (code, flip x, flip y) is cut into lines (runs of opaque pixels per
row).  Each line is one Blitter call (Y count 4: one pass per bitplane) whose Endmasks
cut the shape out, so no mask data and no AND/OR passes are needed.  One routine per pixel
shift (x AND 15) holds the skew, masks and counts as constants; the source data (planar,
left aligned, in blit order) exists once per (shape, colour triple).

Display orientation: the arcade screen is rotated and the cabinet flip bit is 1, so the
displayed sprite is D[v][u] = S'[15-u][v] (S' = raw sprite with its own flips applied).
"""
import glob
import os
import pickle
import random
import sys
from collections import OrderedDict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dkong import Gfx

HERE = os.path.dirname(os.path.abspath(__file__))
STE = os.path.abspath(os.path.join(HERE, ".."))
BUILD = os.path.join(STE, "build")
STRIDE = 256
PLANES = 4


def display_bitmap(gfx, code, fx, fy):
    s = gfx.sprites[code]
    if fx:
        s = s[:, ::-1]
    if fy:
        s = s[::-1, :]
    return s.T[:, ::-1]          # [v][u]


def runs_of(D):
    """Lines (v, u0, w) of opaque runs, in blit order."""
    lines = []
    for v in range(16):
        row = D[v] != 0
        u = 0
        while u < 16:
            if row[u]:
                u0 = u
                while u < 16 and row[u]:
                    u += 1
                lines.append((v, u0, u - u0))
            else:
                u += 1
    # group lines that share their blitter parameters after any shift: same width and
    # same x0 modulo 16
    lines.sort(key=lambda l: (l[2], l[1] & 15, l[0], l[1]))
    return lines


def line_params(line, shift):
    v, x0, w = line
    t = x0 + shift
    dw0, k = divmod(t, 16)
    m = (w + 15) // 16
    n = (k + w + 15) // 16
    assert n in (m, m + 1)
    nfsr = n == m + 1
    e = k + w - 1
    mask1 = 0xFFFF >> k
    mask3 = (0xFFFF << (15 - (e - 16 * (n - 1)))) & 0xFFFF
    if n == 1:
        mask1 &= mask3
        mask3 = None
    return dict(n=n, k=k, nfsr=nfsr, m1=mask1, m3=mask3, off=v * STRIDE + dw0 * 8)


def y_increment(n):
    return -8 * (n - 1) + 2


def draw_ops(lines, shift):
    ops = []
    reg_rel = 0
    cur = dict(n=None, m1=None, m3=None, ctrl=None)
    for line in lines:
        p = line_params(line, shift)
        op = dict(line=line, delta=p["off"] - reg_rel, count=None, m1=None, m3=None, ctrl=None, n=p["n"])
        if cur["n"] != p["n"]:
            op["count"] = (p["n"], y_increment(p["n"]))
            cur["n"] = p["n"]
        if cur["m1"] != p["m1"]:
            op["m1"] = p["m1"]
            cur["m1"] = p["m1"]
        if p["m3"] is not None and cur["m3"] != p["m3"]:
            op["m3"] = p["m3"]
            cur["m3"] = p["m3"]
        ctrl = (p["nfsr"], p["k"])
        if cur["ctrl"] != ctrl:
            op["ctrl"] = ctrl
            cur["ctrl"] = ctrl
        reg_rel = p["off"] + 8
        ops.append(op)
    return ops


def add_text(delta):
    if delta == STRIDE - 8:
        return "d4"
    if delta == -STRIDE - 8:
        return "d5"
    return "#%d" % delta


def emit_draw(label, lines, shift):
    ops = draw_ops(lines, shift)
    out = [label + ":", "\tmove\t(sp)+,(a4)+", "\tmove.l\t(sp)+,(a0)"]
    mode = "cnt"          # a4 points to the X count ("cnt") or the address ("addr")
    for op in ops:
        delta = op["delta"]

        def emit_count():
            n, yinc = op["count"]
            assert n in (1, 2)
            out.append("\tmove\td%d,(a1)" % (n - 1))
            out.append("\tmove.l\td%d,(a4)" % (n + 1))

        count_written = False
        if op["count"]:
            if mode == "addr":
                out.append("\tadd\t%s,(a4)+" % add_text(delta))
                mode = "cnt"
                emit_count()
            else:
                emit_count()
                if delta:
                    out.append("\tadd\t%s,-(a4)" % add_text(delta))
                else:
                    out.append("\tsubq\t#2,a4")
                mode = "addr"
            count_written = True
        else:
            if mode == "addr":
                out.append("\tadd\t%s,(a4)" % add_text(delta))
            else:
                out.append("\tadd\t%s,-(a4)" % add_text(delta))
                mode = "addr"
        if op["m1"] is not None:
            out.append("\tmove\t#%%%s,(a2)" % format(op["m1"], "016b"))
        if op["m3"] is not None:
            out.append("\tmove\t#%%%s,(a3)" % format(op["m3"], "016b"))
        if not count_written:
            out.append("\tmove\td6,(a5)")
        if op["ctrl"] is not None:
            nfsr, k = op["ctrl"]
            out.append("\tmove\t#((BUSY+HOG)<<8)%s+%d,(a6)" % ("+NFSR" if nfsr else "", k))
        else:
            out.append("\tmove.b\td7,(a6)")
    if mode == "cnt":
        out.append("\tsubq\t#2,a4")        # the next routine expects a4 at the address register
    out.append("\trts")
    return "\n".join(out)


def stream(D, lines, lut):
    """Planar source words (list of ints) in blit order for a colour lookup `lut` (pixel -> index)."""
    words = []
    for (v, x0, w) in lines:
        m = (w + 15) // 16
        for plane in range(PLANES):
            for j in range(m):
                word = 0
                for c in range(16):
                    col = 16 * j + c
                    if col < w:
                        idx = lut[int(D[v][x0 + col])]
                        if (idx >> plane) & 1:
                            word |= 0x8000 >> c
                words.append(word)
    return words


# ------------------------------------------------------------------------------
# Software model of the blitter for the generated routines (verification)
# ------------------------------------------------------------------------------

def run_ops_model(ops, base, mem, src_words, shift):
    upper = random.randrange(65536)
    lower = random.randrange(65536)
    n = random.randrange(1, 6)
    yinc = 2
    m1 = random.randrange(65536)
    m3 = random.randrange(65536)
    nfsr = random.randrange(2)
    k = random.randrange(16)
    reg = base
    src = 0
    for op in ops:
        reg = (reg + op["delta"]) & 0xFFFF
        if op["count"]:
            n, yinc = op["count"]
        if op["m1"] is not None:
            m1 = op["m1"]
        if op["m3"] is not None:
            m3 = op["m3"]
        if op["ctrl"] is not None:
            nfsr, k = int(op["ctrl"][0]), op["ctrl"][1]
        addr = reg
        for _ in range(4):
            for x in range(n):
                if x < n - 1 or not nfsr:
                    lower = src_words[src]
                    src += 1
                out = (((upper << 16) | lower) >> k) & 0xFFFF
                if n == 1:
                    mask = m1
                elif x == 0:
                    mask = m1
                elif x == n - 1:
                    mask = m3
                else:
                    mask = 0xFFFF
                old = int(mem[addr // 2])
                mem[addr // 2] = (old & ~mask & 0xFFFF) | (out & mask)
                upper = lower
                if x == n - 1:
                    addr += yinc
                else:
                    addr += 8
        reg = addr & 0xFFFF
    assert src == len(src_words), (src, len(src_words))


def expected_into(mem, D, lut, base, shift):
    for v in range(16):
        for u in range(16):
            p = int(D[v][u])
            if not p:
                continue
            idx = lut[p]
            px = shift + u
            for plane in range(PLANES):
                addr = base + v * STRIDE + (px // 16) * 8 + plane * 2
                bit = 0x8000 >> (px % 16)
                if (idx >> plane) & 1:
                    mem[addr // 2] |= bit
                else:
                    mem[addr // 2] &= ~bit & 0xFFFF


def verify_shape(D, lines):
    rng = np.random.default_rng(0)
    for shift in range(16):
        lut = [0] + random.sample(range(1, 16), 3)
        ops = draw_ops(lines, shift)
        words = stream(D, lines, lut)
        base = 4 * STRIDE + 8
        mem = rng.integers(0, 65536, size=65536 // 2, dtype=np.int64)
        want = mem.copy()
        # pixels outside the shape keep their old value, shape pixels get the new index
        expected_into(want, D, lut, base, shift)
        run_ops_model(ops, base, mem, words, shift)
        if not np.array_equal(mem, want):
            bad = np.nonzero(mem != want)[0][:5]
            raise AssertionError("shape verification failed at shift %d, words %s" % (shift, bad))


def load_observed():
    # Checked-in build input; optional local captures extend this baseline.
    import json
    with open(os.path.join(HERE, "sprite_observed.json")) as f:
        observed = json.load(f)
    shapes = {tuple(row) for row in observed["shapes"]}
    combos = {tuple(row) for row in observed["combos"]}
    for f in glob.glob(os.path.join(STE, "sprites_*.pkl")):
        sh, full = pickle.load(open(f, "rb"))
        shapes |= set(sh)
        combos |= {(k[0], k[1], k[2], k[3] + 16 * k[4]) for k in full}
    return shapes, combos


def build(verify=True):
    gfx = Gfx()
    import json
    pal = json.load(open(os.path.join(BUILD, "palette.json")))
    penmap = pal["penmap"]
    combo_triple_t = []
    triples = {}
    for combo in range(64):
        t = tuple(penmap[combo * 4 + p] for p in (1, 2, 3))
        if t not in triples:
            triples[t] = len(triples)
        combo_triple_t.append(triples[t])
    ntr = len(triples)
    triple_list = list(triples)
    shapes, combos = load_observed()
    obs_codes = sorted({c for (c, fx, fy) in shapes})
    code_triples = {}
    for (c, fx, fy, combo) in combos:
        code_triples.setdefault(c, set()).add(combo_triple_t[combo])
    # default triple: the most frequent one among the observed variants
    freq = {}
    for (c, fx, fy, combo) in combos:
        freq[combo_triple_t[combo]] = freq.get(combo_triple_t[combo], 0) + 1
    default_triple = max(freq, key=freq.get)
    wanted = []
    for c in range(128):
        if c in obs_codes:
            flips = [(fx, fy) for fx in (0, 1) for fy in (0, 1)]
        else:
            flips = [(0, 0), (1, 0)]            # never seen: plain and mirrored only
        for fx, fy in flips:
            wanted.append((c, fx, fy))
    out = ["; generated by sprites.py", "	section text,code"]
    stream_blob = bytearray()
    body_label = {}         # routine text -> label
    routine_table = {}      # shape id -> label of its table
    shape_routines = {}
    stream_offsets = {}     # stream bytes -> offset
    data_offsets = {}       # (shape id, triple) -> offset
    n_lines = 0
    for (c, fx, fy) in wanted:
        D = display_bitmap(gfx, c, fx, fy)
        lines = runs_of(D)
        if not lines:
            continue
        sid = c * 4 + fx * 2 + fy
        if verify:
            verify_shape(D, lines)
        n_lines += len(lines)
        labels = []
        for shift in range(16):
            text = emit_draw("@", lines, shift).split(chr(10), 1)[1]
            lab = body_label.get(text)
            if lab is None:
                lab = "spr_%03d_%x" % (sid, shift)
                body_label[text] = lab
                out.append(lab + ":" + chr(10) + text)
            labels.append(lab)
        shape_routines[sid] = labels
        routine_table[sid] = "spr_tab_%03d" % sid
        need = set(code_triples.get(c, set())) | {default_triple}
        for tid in need:
            t = triple_list[tid]
            lut = [0, t[0], t[1], t[2]]
            words = stream(D, lines, lut)
            blob = b"".join(wd.to_bytes(2, "big") for wd in words)
            off = stream_offsets.get(blob)
            if off is None:
                off = len(stream_blob)
                stream_offsets[blob] = off
                stream_blob += blob
            data_offsets[(sid, tid)] = off
    out.append("	section data,data")
    out.append("	cnop 0,4")
    for sid, labels in shape_routines.items():
        out.append("spr_tab_%03d:" % sid)
        for i in range(0, 16, 4):
            out.append("	dc.l " + ",".join(labels[i:i + 4]))
    out.append("spr_shape_table:		; shape id (code*4 + fx*2 + fy) -> 16 routines, or 0")
    for sid in range(512):
        out.append("	dc.l %s" % (routine_table.get(sid, "0")))
    out.append("SPR_TRIPLES = %d" % ntr)
    out.append("spr_data_table:		; shape id * SPR_TRIPLES + triple -> offset into dk_sprdata + 1, or 0")
    for sid in range(512):
        row = []
        for tid in range(ntr):
            o = data_offsets.get((sid, tid))
            if o is None and (sid, default_triple) in data_offsets:
                o = data_offsets[(sid, default_triple)]      # wrong colours beat a missing sprite
            row.append("%d" % (o + 1 if o is not None else 0))
        out.append("	dc.l " + ",".join(row))
    out.append("spr_combo_triple:")
    out.append("	dc.b " + ",".join(str(x) for x in combo_triple_t[:32]))
    out.append("	dc.b " + ",".join(str(x) for x in combo_triple_t[32:]))
    out.append("	cnop 0,2")
    out.append("dk_sprdata:	incbin \"dk_sprdata.bin\"")
    open(os.path.join(BUILD, "dk_sprites.s"), "w").write(chr(10).join(out) + chr(10))
    open(os.path.join(BUILD, "dk_sprdata.bin"), "wb").write(bytes(stream_blob))
    return len(routine_table), len(body_label), n_lines, len(stream_blob), ntr


if __name__ == "__main__":
    ns, nr, nl, nb, ntr = build(verify="--noverify" not in sys.argv)
    txt = open(os.path.join(BUILD, "dk_sprites.s")).read()
    print("shapes", ns, "distinct routines", nr, "of", ns * 16, "lines", nl, "stream bytes", nb, "triples", ntr, "source text bytes", len(txt))
