"""Measure stage_sprites.py's two layouts of every whole sprite - mask groups (stefastbobs2) and blocks
(stedaimakaimura's sprite_compiler.js) - on Musashi with the STE Blitter model (engine/sim.py), instead of
stage_sprites.units_cost's estimate.

Per definition and layout: the generated word-mode code (stage_sprites.sprite_code) assembled with vasm, its
16 shift streams, its source baked in the units' order; every shift drawn over a random background as src/stage.s
st_sprites / st_obj2 call it (a1 END1, a6 END3, a5 YC, a2 CTRL, d1 4, d2 the start, d4 a line, a3 DYI, a4 the
destination's low word, d0 its value, a0 the stream).  Every picture is checked against the composed image.
Cycles: the CPU's (Musashi) plus the Blitter's bus cycles, summed over the 16 shifts.

    venv/bin/python games/rtype/tools/sprite_layout_bench.py build/rtype/stage_states_*.pkl build/rtype/defs_*.json \
        build/rtype/cols_*.json

Weighted totals count each definition by its draws in the .pkl recordings.  Result 2026-11-03 (928 definitions):
the estimate's choice 4539.4 cycles a sprite, the measured best 4537.6 (-0.04%, weighted -0.05%; 38 differ):
the estimate stays (docs/sprite-preparation.md).  --dp 32 (rows cut by least cost, blitter_sprite_compiler.js):
4539.4 -> 4503.7 (-0.79%, weighted -0.54%).  Layout x (blocks with an X count a row): 4666.8, +2.8%; dropped.
"""
import argparse
import pickle
import random
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
import m72
from m72board import load_regions
from machine68k import Register as R
from paths import VASM
from sim import Sim
import stage_model as SM
import stage_sprites as S

CODE = 0x20000
STOP = 0x700
STREAM = 0x300000
SOURCE = 0x400000
SCREEN = 0x810000           # (the low word starts at 0: no 64 KB crossing in the word-mode code)
LB = S.LB


class Bench(Sim):
    def __init__(self, binary):
        super().__init__(binary, ram_kib=16384)

    def load_prg(self, path):
        self.base = CODE
        self.mem.w_block(CODE, Path(path).read_bytes())
        self.mem.w16(STOP, 0x60FE)
        self.cpu.pulse_reset()

    def hw(self, off, value, size=2):
        value &= (1 << (size * 8)) - 1
        self.io[0xA00 + off:0xA00 + off + size] = value.to_bytes(size, "big")
        self.mem.w_block(0xFF8A00 + off, value.to_bytes(size, "big"))

    def draw(self, code, stream):
        self.mem.w_block(STREAM, stream)
        for off, v in ((0x20, 2), (0x22, 2), (0x2A, 0xFFFF), (0x2E, 8), (0x3A, 0x0203)):
            self.hw(off, v)
        self.hw(0x24, SOURCE, 4)
        self.hw(0x32, SCREEN, 4)
        self.hw(0x3C, 0)
        for reg, v in ((R.A0, STREAM), (R.A1, 0xFF8A28), (R.A2, 0xFF8A3C), (R.A3, 0xFF8A30), (R.A4, 0xFF8A34),
                       (R.A5, 0xFF8A38), (R.A6, 0xFF8A2C), (R.D0, SCREEN & 0xFFFF), (R.D1, 4),
                       (R.D2, 0xFFFFFFC0), (R.D4, LB)):
            self.cpu.w_reg(reg, v)
        self.cpu.w_sr(0x2700)
        self.cpu.w_reg(R.A7, 0x8000)
        self.mem.w32(0x8000, STOP)
        self.cpu.w_pc(code)
        self.blitter.cycles = 0
        cpu = 0
        for _ in range(200000):
            if self.cpu.r_pc() == STOP:
                return cpu, self.blitter.cycles
            cpu += self.cpu.execute(1).cycles
        raise AssertionError("no return: %x" % self.cpu.r_pc())


def bake(img, units):
    """the source in the units' order: per row and plane its words (16 * (class + 1) pens from the row's x0)"""
    out = bytearray()
    for cls2, uw, rows in units:
        n = 16 * (cls2 + 1)
        for y, x0, m in rows:
            p = [int(v) for v in img[y, x0:x0 + n]] + [0] * n
            for plane in range(4):
                for j in range(cls2 + 1):
                    w = 0
                    for i in range(16):
                        w = (w << 1) | ((p[16 * j + i] >> plane) & 1)
                    out += w.to_bytes(2, "big")
    return bytes(out)


def expected(img, s, background):
    exp = bytearray(background)
    ys, xs = np.nonzero(img)
    for y, x in zip(ys.tolist(), xs.tolist()):
        v = int(img[y, x])
        X = s + x
        bit = 0x8000 >> (X & 15)
        for plane in range(4):
            o = y * LB + (X >> 4) * 8 + plane * 2
            w = int.from_bytes(exp[o:o + 2], "big")
            w = (w | bit) if (v >> plane) & 1 else (w & ~bit)
            exp[o:o + 2] = w.to_bytes(2, "big")
    return bytes(exp)


def pass_bus(cls2, m, w):
    """a piece's Blitter bus cycles over the 16 shifts (4 planes: reads, writes, a read-modify-write for every end
    mask other than $FFFF - 0 too), or None when it cannot be drawn at some shift (a wide piece's inner word not
    opaque)"""
    total = 0
    for k in range(16):
        try:
            xc, dyi, e1, e2, e3, ctl = S.pass_values(cls2, m, w, k)
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
                if w > S.WIDE_MAX:
                    break
                cls2 = S.cls_of(w)
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
            n = 16 * (S.cls_of(w) + 1)
            m = 0
            for c in cols[i:j + 1]:
                m |= 1 << (n - 1 - (c - a))
            out.append((y, a, w, m))
            i = j + 1
    return out


# ---- experiment: blocks with an X count a row (blitter_sprite_compiler.js gives every line its own) ----
# A block's rows keep its left edge (one skew a block at every shift), but each row its own source words (a class of
# its own: up to its last pixel), X count, NFSR and Y increment - written only where they change at some shift.
# units: [(long, [(y, L, cls, w, mask)])], long: END1 + END2 written as a long (a row of 17-32 pixels in the unit)

def units_x(units):
    out = []
    for cls2, uw, rows in units:
        if cls2 >= 2:
            out.append((True, [(y, x0, cls2, uw, m) for y, x0, m in rows]))
            continue
        n = 16 * (cls2 + 1)
        rr = []
        for y, x0, m in rows:
            last = max(i for i in range(n) if m >> (n - 1 - i) & 1)    # (the row's last pixel from the block's left)
            c = 0 if last < 16 else 1
            rr.append((y, x0, c, last + 1, m >> 16 if n == 32 and not c else m))
        rr.sort(key=lambda r: (r[3], r[4], r[0]))      # (equal widths together: the same X count at every shift)
        out.append((any(r[2] for r in rr), rr))
    return out


def x_rows(u, s):
    return [(y * LB + ((s + x0) >> 4) * 8, S.pass_values(c, m, w, (s + x0) & 15)) for y, x0, c, w, m in u[1]]


def x_changes(u):
    """per row after the first: (END1 [+ END2], END3, XC + DYI, the control word) written again"""
    vals = [x_rows(u, s) for s in range(16)]
    out = []
    for i in range(1, len(u[1])):
        ch = lambda f: any(f(vals[s][i][1]) != f(vals[s][i - 1][1]) for s in range(16))
        out.append((ch(lambda v: v[2:4] if u[0] else v[2]), ch(lambda v: v[4]), ch(lambda v: v[0:2]), ch(lambda v: v[5])))
    return out


def x_code(units):
    body = []
    for u in units:
        lg, rows = u
        e12 = "\tmove.l (a0)+,(a1)" if lg else "\tmove (a0)+,(a1)"
        body += ["\tadd (a0)+,d0", "\tmove d0,(a4)", "\tmove (a0)+,BLT_XC.w", "\tmove (a0)+,(a3)", e12,
                 "\tmove (a0)+,(a6)", "\tmove d1,(a5)", "\tmove (a0)+,(a2)"]
        for (ra, rb), (c12, c3, cx, cc) in zip(zip(rows, rows[1:]), x_changes(u)):
            if c12:
                body.append(e12)
            if c3:
                body.append("\tmove (a0)+,(a6)")
            if cx:
                body += ["\tmove (a0)+,BLT_XC.w", "\tmove (a0)+,(a3)"]
            d = (rb[0] - ra[0]) * LB + ((rb[1] - ra[1]) // 16) * 8
            body += ["\tadd d4,d0" if d == LB else "\tadd #%d,d0" % d, "\tmove d0,(a4)", "\tmove d1,(a5)"]
            body.append("\tmove (a0)+,(a2)" if cc else "\tmove.b d2,(a2)")
    return body + ["\trts"]


def x_streams(units):
    out = []
    chg = [x_changes(u) for u in units]
    for s in range(16):
        blk = bytearray()
        prev = 0
        for u, ch in zip(units, chg):
            lg = u[0]
            rv = x_rows(u, s)
            dst, (xc, dyi, e1, e2, e3, ctl) = rv[0]
            vals = [dst - prev, xc, dyi, e1] + ([e2] if lg else []) + [e3, ctl]
            for (d, (fx, fd, f1, f2, f3, fc)), (c12, c3, cx, cc) in zip(rv[1:], ch):
                if c12:
                    vals += [f1, f2] if lg else [f1]
                if c3:
                    vals.append(f3)
                if cx:
                    vals += [fx, fd]
                if cc:
                    vals.append(fc)
            for v in vals:
                blk += (int(v) & 0xFFFF).to_bytes(2, "big")
            prev = rv[-1][0]
        out.append(bytes(blk))
    return out


def x_bake(img, units):
    return bake(img, [(c, w, [(y, x0, m)]) for _, rows in units for y, x0, c, w, m in rows])


def draws(paths):
    """{(bw, n): draws} over the .pkl recordings' frames"""
    cnt = {}
    for p in paths:
        if not p.endswith(".pkl"):
            continue
        for f, item in pickle.load(open(p, "rb")):
            st = pickle.loads(zlib.decompress(item))
            o, end = st["objs"], st["objs_end"]
            for slot in list(range(0xC0, min(end, 0x3C0), 8)) + list(range(0x3C0, 0x400, 8)):
                bw, n = struct.unpack(">HB", o[slot:slot + 3])
                if bw:
                    cnt[(bw, n)] = cnt.get((bw, n), 0) + 1
    return cnt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("states", nargs="+")
    ap.add_argument("--limit", type=int, default=0, help="the first N definitions only")
    ap.add_argument("--dp", type=int, metavar="OVERHEAD",
                    help="experiment: rows cut by least cost (blitter_sprite_compiler.js), OVERHEAD CPU cycles a pass")
    args = ap.parse_args()
    if args.dp is not None:
        S.pieces = lambda img: pieces_dp(img, args.dp)
    rom = load_regions("rtype")["main"]
    sprites = m72.Video("rtype").sprites
    defs = sorted(S.definitions(args.states))
    cases = []
    for bw, n in defs:
        ents = S.entries(rom, bw, n)
        if all((c & 0xFFF) in SM.STAR_SPRITES for _, _, c, _ in ents):
            continue
        r = S.compose(sprites, ents)
        if r is None:
            continue
        img = r[0]
        pcs = S.pieces(img)
        ug, ub = S.units_of_groups(S.groups_of(pcs)), S.units_of_blocks(pcs)
        est = "b" if S.units_cost(ub) < S.units_cost(ug) else "g"
        cases.append(((bw, n), img, {"g": ug, "b": ub, "x": units_x(ub)}, est))
    if args.limit:
        cases = cases[:args.limit]
    gen = {"g": (lambda u: S.sprite_code(u, False), S.sprite_streams, bake),
           "b": (lambda u: S.sprite_code(u, False), S.sprite_streams, bake),
           "x": (x_code, x_streams, x_bake)}
    codes = {}
    for _, _, lay, _ in cases:
        for name, units in lay.items():
            codes.setdefault(tuple(gen[name][0](units)), len(codes))
    lines = ["BLT_XC = $ffff8a36", "BLT_DYI = $ffff8a30", "\torg $%x" % CODE]
    lines += ["\tdc.l c_%d" % i for i in range(len(codes))]
    for body, i in codes.items():
        lines += ["c_%d:" % i] + list(body)
    with tempfile.TemporaryDirectory(prefix="spr-layout-") as d:
        src, out = Path(d) / "c.s", Path(d) / "c.bin"
        src.write_text("\n".join(lines) + "\n")
        r = subprocess.run([VASM, "-Fbin", "-m68000", "-quiet", "-nowarn=2047", "-o", str(out), str(src)],
                           capture_output=True, text=True)
        if r.returncode:
            sys.exit(r.stdout + r.stderr)
        h = Bench(out)
    cnt = draws(args.states)
    rng = random.Random(72)
    res = {}
    tot = {k: [0, 0] for k in ("g", "b", "x", "est", "best", "best3")}
    wtot = {k: 0 for k in tot}
    for i, (key, img, lay, est) in enumerate(cases):
        hgt, wid = img.shape
        size = hgt * LB
        meas = {}
        for name, units in lay.items():
            fcode, fstreams, fbake = gen[name]
            code = h.mem.r32(CODE + 4 * codes[tuple(fcode(units))])
            streams = fstreams(units)
            h.mem.w_block(SOURCE, fbake(img, units))
            c = b = 0
            for s in range(16):
                bg = rng.randbytes(size)
                h.mem.w_block(SCREEN, bg)
                dc, db = h.draw(code, streams[s])
                c += dc
                b += db
                got = h.mem.r_block(SCREEN, size)
                assert got == expected(img, s, bg), (key, name, s)
            meas[name] = (c, b)
        best = min("gb", key=lambda k: (sum(meas[k]), k != est))
        best3 = min("gbx", key=lambda k: (sum(meas[k]), k != est))
        res["%d,%d" % key] = best
        w = cnt.get(key, 0)
        for k, choice in (("g", "g"), ("b", "b"), ("x", "x"), ("est", est), ("best", best), ("best3", best3)):
            tot[k][0] += meas[choice][0]
            tot[k][1] += meas[choice][1]
            wtot[k] += w * sum(meas[choice]) / 16
        if (i + 1) % 100 == 0:
            print("%d / %d" % (i + 1, len(cases)), flush=True)
    n = len(cases)
    print("%d definitions, %d routines; CPU + Blitter cycles a sprite, mean over the 16 shifts:" % (n, len(codes)))
    for k, label in (("g", "mask groups"), ("b", "blocks"), ("x", "blocks, XC a row"), ("est", "the estimate's choice"),
                     ("best", "the measured choice"), ("best3", "best of g, b, x")):
        c, b = tot[k]
        print("  %-22s %8.1f + %7.1f = %8.1f   weighted by draws: %12.0f" % (
            label, c / 16 / n, b / 16 / n, (c + b) / 16 / n, wtot[k]))
    flips = sum(1 for (key, _, _, est) in cases if res["%d,%d" % key] != est)
    print("  the measurement differs from the estimate for %d definitions; blocks chosen for %d" % (
        flips, sum(v == "b" for v in res.values())))


if __name__ == "__main__":
    main()
