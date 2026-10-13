"""Sprites of the Irem M72 renderer (engine/rt/m72render.s) at the window's edges, in all 16 shifts, flipped, with
transparent holes, over tiles with pixels over the sprites, in the guard lines, across a 64 KB boundary of a buffer.

    venv/bin/python games/rtype/tools/sprite_test.py [--game rtype|mrheli] [-v]

A recorded play state (tools/render_test.py's states) with its sprite list replaced by a test entry: a 16 x 16 piece with
holes (and a 2 x 2 entry) at buffer x = every shift 0-15 in the middle, across the left and right clip groups' edges (CL
= W & ~15, CR = (W + 335) & ~15: the inner word only there, culled when wholly outside) at a window that is
group-aligned (W & 15 = 0: the window's edges are the clip edges) and at one that is not, at the top and the bottom
(whole into the guard lines), in lines that cross a 64 KB boundary of each buffer.  Each case: the picture shown is
exact (render_test.check: the renderer's mapping of the reference's pens), and in the buffer nothing outside the clip
groups changed (the columns < CL and >= CR compared with the same buffer's previous picture without the sprite).
"""
import argparse
import pickle
import sys
import zlib
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[2] / "engine")]
import render_test as T
import m72

BASE = {"rtype": ("play", 2000), "mrheli": ("attract", 2000)}


def entry(code, colour, px, py, w=1, h=1, flipx=False, flipy=False):
    """the 4 words of a sprite entry whose top left is at picture x px (0-383 of MAME's picture, bitmap x - 64... here
    the window's x: bitmap x = px + 96), picture line py"""
    sx = px + 96                        # bitmap x
    x = (sx + 256) & 0x3FF
    y = (384 - 16 * h - py) & 0x1FF
    lw = {1: 0, 2: 1, 4: 2, 8: 3}
    a = (colour & 15) | (0x800 if flipx else 0) | (0x400 if flipy else 0) | (lw[h] << 12) | (lw[w] << 14)
    return [y, code, a, x]


def with_sprites(st, entries):
    w = np.zeros(512, np.uint16)
    k = 0
    for e in entries:
        w[4 * k:4 * k + 4] = e
        k += 1 << ((e[2] >> 14) & 3)
    out = dict(st)
    out["spr"] = w.astype("<u2").tobytes()
    return out


def with_fg_x(st, sx):
    """the state with the main band's FG x scroll sx (the window follows FG: W = (96 + sx) & 511)"""
    out = dict(st)
    bands = []
    for y0, y1, (fx, bx), sy, off in st["bands"]:
        if y1 - y0 > 100:
            fx = sx
        bands.append((y0, y1, (fx, bx), sy, off))
    out["bands"] = bands
    return out


def pick_code(game):
    """a piece with transparent holes inside its opaque area (a hole: a pen-0 pixel with opaque pixels left and right
    in its row and above and below in its column), opaque in most of its rows"""
    v = m72.Video(game)
    best, score = 0, -1
    for c, px in enumerate(v.sprites):
        op = px != 0
        rows = op.any(1).sum()
        if rows < 14:
            continue
        holes = 0
        for y in range(1, 15):
            for x in range(1, 15):
                if not op[y, x] and op[y, :x].any() and op[y, x + 1:].any() and op[:y, x].any() and op[y + 1:, x].any():
                    holes += 1
        if holes and op.sum() + 4 * holes > score:
            best, score = c, op.sum() + 4 * holes
    return best


def run(game, verbose=False, defines=()):
    which, frame = BASE[game]
    states = dict(T.load_states(game, which))
    base = pickle.loads(zlib.decompress(states[frame]))
    code = pick_code(game)
    colour = 3
    h = T.Harness(game, defines)
    nbuf = 2
    cases = []
    for sx in (0, 5):                   # the window group-aligned (W & 15 = 0) and not
        st0 = with_fg_x(base, (sx - 96) & 511)
        empty = with_sprites(st0, [])
        W = (96 + ((sx - 96) & 511)) & 511
        # every shift in the middle, flipped and not
        for k in range(16):
            px = 150 + k
            cases.append((empty, [entry(code, colour, px, 100, flipx=k & 1, flipy=k & 2)], "shift %d W%d" % (k, W)))
        # across the left and the right edge: picture x from -17 to 3 and 316 to 336
        for px in list(range(-18, 4)) + list(range(314, 338)):
            cases.append((empty, [entry(code, colour, px, 60, flipx=px & 1)], "edge x %d W%d" % (px, W)))
        # a 2 x 2 entry across each edge
        for px in (-20, -9, 300, 311):
            cases.append((empty, [entry(code, colour, px, 140, 2, 2)], "2x2 x %d W%d" % (px, W)))
        # top and bottom: whole into the guard lines
        for py in (-15, -8, -1, 241, 248, 255):
            cases.append((empty, [entry(code, colour, 100, py)], "line %d W%d" % (py, W)))
    fails = 0
    done = 0
    # a 64 KB boundary in each buffer's picture lines: the line it falls in
    cross = []
    for b in range(nbuf):
        buf = h.r32("m72r_buf", 4 * b)
        for line in range(T.G, T.G + 256):
            a0 = buf + line * T.LB
            if (a0 >> 16) != ((a0 + T.LB) >> 16):
                cross.append((b, line - T.G))
                break
    for b, line in cross:
        st0 = with_fg_x(base, (0 - 96) & 511)
        cases.append((with_sprites(st0, []), [entry(code, colour, 120 + 3 * b, line - 7)], "64 KB buffer %d" % b))
        cases.append((with_sprites(st0, []), [entry(code, colour, 160, line - 8, flipy=True)], "64 KB flip y %d" % b))
    for empty, ents, name in cases:
        st = with_sprites(empty, ents)
        # empty pictures until the buffer the case will use has the empty picture too
        for _ in range(nbuf):
            h.put_state(empty)
            h.frame()
        nxt = [b for b in range(nbuf) if b not in (h.r16("m72r_shown"),)][0]
        before = h.buffer(nxt)
        h.put_state(st)
        if h.frame() is None:
            print("%s: no buffer free" % name)
            fails += 1
            continue
        bad, mid, err, sat, notes = T.check(h, game, st, "edge_%d" % done)
        b = h.r16("m72r_shown")
        after = h.buffer(b)
        W = h.s16("m72r_W")
        cl, cr = W & ~15, (W + 320 + 15) & ~15
        outside = np.ones(1024, bool)
        outside[cl:cr] = False
        band = int(np.count_nonzero((after != before)[:, outside])) if b == nxt else -1
        ok = bad == 0 and band == 0 and not notes
        if not ok:
            fails += 1
            print("%s: %d pixels differ, %d pixels outside the clip groups changed (W %d, CL %d, CR %d)%s" % (
                name, bad, band, W, cl, cr, "; " + "; ".join(notes) if notes else ""))
        elif verbose:
            print("%s: exact" % name)
        done += 1
    print("sprites: %d cases (piece %d with holes; shifts, edges at W & 15 = 0 and 5, guard lines, 64 KB crossings), "
          "%d failed" % (done, code, fails))
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", default="rtype", choices=["rtype", "mrheli"])
    ap.add_argument("-v", action="store_true")
    ap.add_argument("-D", dest="defines", action="append", default=[])
    a = ap.parse_args()
    f = run(a.game, a.v, a.defines)
    print("FAIL" if f else "PASS")
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())
