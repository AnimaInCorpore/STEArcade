"""The motion objects on the STE (src/render.s in its SIM harness) against the reference renderer (tools/video.py)
through the fixed palette, pixel for pixel: objects placed by the test in a real playfield and panel.

    venv/bin/python games/gauntlet/tools/sprite_test.py [--nobuild] [--save DIR]

Cases (consecutive pictures, the two rings in turn, so every picture also restores the damage of the one before
last):
  edges   objects swept over the maze's left edge (the display window's: whole into the hidden margin), its right edge
          (the panel's: whole, the panel drawn over them), the top and bottom (whole into the guard lines), at every x
          and with the fine scroll stepped, so all 16 shifts of 1-4 tile wide strips and both flips are drawn;
  wide    5-8 tiles wide objects (two strips) and 1 x 1 ones;
  holes   objects with transparent holes and shadow pixels (pen 1: the playfield's shadow colour from P') over each
          other (later over earlier, a shadow over an earlier object shows the playfield's shadow);
  bands   a band list that starts after an object (MAME draws it only in the bands whose lists hold it) and lists that
          merge in a tree (the general way);
  panel   the panel's characters transparent (the title's and the high scores' way): objects at the arcade's x 240-335;
  64k     the ring's 64 KB boundaries: the scroll set so that objects straddle them (checked: the test fails when no
          drawn row crossed one).
"""
from pathlib import Path
import argparse
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[2] / "engine"), str(HERE.parent / "ref")]
import render_test
import assets
from paths import build_dir

OBJECTS = [(436, 3, 3, 2), (445, 3, 3, 5), (764, 2, 2, 0), (5540, 2, 4, 1), (382, 3, 3, 9), (5694, 1, 1, 3)]


def put_objects(vram, objs, xs, ys, slips=None, links=None):
    """objs: [(code, w, h, palette, flip, x, y)] (the arcade's screen x / y of the top left) as entries 1.. linked in
    that order (the last to itself); every band's SLIP entry 1 unless slips gives {band: entry}"""
    v = bytearray(vram)
    mo = np.zeros((4, 1024), np.int64)
    for k, (code, w, h, pal, flip, x, y) in enumerate(objs, 1):
        mo[0, k] = (code ^ 0x800) & 0x7FFF
        mo[1, k] = (((x + xs) & 511) << 7) | pal
        mo[2, k] = (((-y - (ys >> 7) - h * 8) & 511) << 7) | (flip << 6) | ((w - 1) << 3) | (h - 1)
        mo[3, k] = k + 1 if k < len(objs) else k
    mo[3, 0] = 0
    for k, n in (links or {}).items():
        mo[3, k] = n
    v[0x2000:0x4000] = mo.astype(">u2").tobytes()
    slip = np.full(64, 1 if objs else 0, np.int64)
    for b, e in (slips or {}).items():
        slip[b & 63] = e
    v[0x5F80:0x6000] = slip.astype(">u2").tobytes()
    v[0x5F6E:0x5F70] = ys.to_bytes(2, "big")
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nobuild", action="store_true")
    ap.add_argument("--save", default=None)
    args = ap.parse_args()
    prg = build_dir("gauntlet") / "render_test.prg" if args.nobuild else render_test.build_harness()
    h = render_test.Harness(prg)
    oracle = assets.Oracle()
    for f, m in render_test.scenario(1, 2, 1200):          # (a maze: level 2 in play)
        pass
    vram0, pal, xs0 = m.vram(), m.palette(), m.xscroll
    ys0 = (vram0[0x5F6E] << 8) | vram0[0x5F6F]
    save = Path(args.save) if args.save else None
    if save:
        save.mkdir(parents=True, exist_ok=True)
    state = dict(bad=0, n=0, crossed=0)

    def check(name, objs, xs, ys, slips=None, vram=vram0, links=None):
        v = put_objects(vram, objs, xs, ys, slips, links)
        h.put_raw(v, pal, xs)
        h.draw()
        got = h.picture()
        want = oracle.picture_raw(v, pal, xs)
        state["n"] += 1
        # the rows' 64 KB crossings: the ring's address of each object's lines
        mem, sym = h.sim.mem, h.sym
        base = mem.r32(sym["flip_addr"])
        for o in objs:
            a0 = base + o[6] * render_test.STRIDE
            a1 = base + (o[6] + 8 * o[2] - 1) * render_test.STRIDE + 64
            if a0 >> 16 != a1 >> 16:
                state["crossed"] += 1
        n = int((got != want).sum())
        if n:
            state["bad"] += 1
            if state["bad"] <= 10:
                ys_, xs_ = np.nonzero(got != want)
                print("%s (picture %d): %d pixels differ (first at x %d y %d: %d / %d)" % (
                    name, state["n"], n, xs_[0], ys_[0], got[ys_[0], xs_[0]], want[ys_[0], xs_[0]]), flush=True)
            if save:
                from PIL import Image
                rgb = oracle.rgb
                diff = rgb[want].copy()
                diff[got != want] = (255, 0, 255)
                Image.fromarray(np.hstack((rgb[got], rgb[want], diff))).save(save / ("%s_%04d.png" % (name, state["n"])))

    # edges: left / right, every x (and the fine scroll moving), both flips, 1-4 tile wide strips
    for i, x in enumerate(range(-70, 250, 3)):
        xs = (xs0 + i) & 511
        objs = []
        for j, (code, w, hh, pal_) in enumerate(OBJECTS[:4]):
            objs.append((code, w, hh, pal_, (i + j) & 1, x + 7 * j, 20 + 50 * j))
        check("edges_x", objs, xs, ys0)
    # top / bottom (the guards), the y scroll moving
    for i, y in enumerate(list(range(-70, 5, 3)) + list(range(220, 245, 2))):
        ys = (ys0 + (i << 7)) & 0xFFFF
        objs = [(code, w, hh, pal_, i & 1, 30 + 45 * j, y + (j & 1)) for j, (code, w, hh, pal_) in enumerate(OBJECTS)]
        check("edges_y", objs, (xs0 + 3 * i) & 511, ys)
    # wide objects (two strips), 1 x 1
    for i in range(24):
        objs = [(436, 5 + (i & 3), 2, 4, i & 1, -40 + 11 * i, 60), (5694, 1, 1, 3, 0, 5 * i, 150),
                (382, 8, 1, 9, (i >> 1) & 1, 200 - 9 * i, 200)]
        check("wide", objs, (xs0 + i) & 511, ys0)
    # holes, shadows, priority: a crowd
    for i in range(32):
        objs = [(OBJECTS[k % 5][0], OBJECTS[k % 5][1], OBJECTS[k % 5][2], k & 15, (k + i) & 1,
                 60 + ((k * 13 + i * 3) % 70), 50 + ((k * 7 + i * 2) % 90)) for k in range(24)]
        check("crowd", objs, (xs0 + 2 * i) & 511, (ys0 + (i << 7)) & 0xFFFF)
    # bands: the list of the bands from 10 on starts at entry 2 (entry 1 drawn in bands 0-9 only); a tree
    for i in range(16):
        ys = (ys0 + (5 * i << 7)) & 0xFFFF
        b0 = (((ys >> 7) - 1) & 511) >> 3
        objs = [(436, 3, 3, 2, 0, 50 + i, 60 + i), (445, 3, 3, 5, 1, 60, 70), (764, 2, 2, 0, 0, 120, 90 - i)]
        check("bands", objs, xs0, ys, {b0 + k: 2 for k in range(10, 40)})
        tree = {b0 + k: (1 if (k >> 1) & 1 else 2) for k in range(0, 40)}  # lists 1, 3 and 2, 3: they merge
        check("tree", objs, xs0, ys, tree, links={1: 3, 2: 3})
    # the panel transparent: objects at the arcade's x 232-335 too
    v = bytearray(vram0)
    for row in range(30):
        for col in range(30, 42):
            a = 0x5000 + 2 * (row * 64 + col)
            w = (v[a] << 8) | v[a + 1]
            w &= 0x7FFF
            v[a:a + 2] = w.to_bytes(2, "big")
    for i in range(24):
        objs = [(code, w, hh, pal_, i & 1, 200 + 6 * i + 5 * j, 30 + 40 * j) for j, (code, w, hh, pal_) in
                enumerate(OBJECTS)]
        check("panel", objs, (xs0 + i) & 511, ys0, vram=v)
    # 64 KB: every T (the y scroll) of a range: objects across the ring's line 146 multiples
    for i in range(48):
        ys = (ys0 + ((7 * i) << 7)) & 0xFFFF
        objs = [(436, 3, 3, 2, i & 1, 10 + 4 * i, 5 * k) for k in range(0, 48, 1)][:20]
        check("64k", objs, (xs0 + i) & 511, ys)
    print("%d pictures compared, %d differ; rows across a 64 KB boundary: %d objects" % (
        state["n"], state["bad"], state["crossed"]))
    return int(state["bad"] != 0 or state["crossed"] == 0)


if __name__ == "__main__":
    sys.exit(main())
