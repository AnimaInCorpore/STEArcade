"""A stage's BG as one long strip (the user's choice for R-Type's stage 2, 2026-10-30): the arcade scrolls the tunnel's
BG at half the FG's speed through a 64-column ring that the game refills ahead of its window; the STE draws the BG locked
to the FG (no parallax), so it needs the whole BG as the game shows it, column by column.  The BG is decorative there (no
BG tile code below 7D0h: the game's tile tests never see a wall in it).

The reference board (the port's schedule, a lock-step seed's inputs: ref/cover.py) runs over the frames; with the
playfield's BG scroll unwrapped, every absolute BG column that comes into the 320-pixel window is taken from the ring the
first time it is seen (64 rows of (code, attribute) words).  Output build/rtype/stage_bg_<name>.bin: a header (columns,
first absolute column, BG y) and the columns (64 rows x 2 little-endian words each), and a PNG of the strip.

    venv/bin/python games/rtype/tools/stage_bg.py --seed 10 --frames 10300-14600 --name s2
"""
import argparse
import random
import struct
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / "ref"),
                str(Path(__file__).resolve().parents[3] / "engine")]
import cover
import m72
from machine import RType, VBL_VECTOR
from paths import build_dir

X0, W = 96, 320


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=10)
    ap.add_argument("--frames", default="10300-14600")
    ap.add_argument("--name", default="s2")
    args = ap.parse_args()
    f0, f1 = (int(x) for x in args.frames.split("-"))
    m = RType()
    m.boot()
    rng, state = random.Random(args.seed), dict(hold=0, bits=0)
    if args.seed >= 8:
        m.dsw &= ~0x4000
    cap = {}
    orig = m.run_irq

    def run_irq(vec, limit=5000000):
        orig(vec, limit)
        if vec == VBL_VECTOR:                           # (the playfield's registers: before the raster interrupt)
            cap["s"] = (m.scrollx[1], m.scrolly[1])
    m.run_irq = run_irq
    cols, prev, absx, ys = {}, None, None, set()
    for f in range(f1):
        cover.press(m, f, args.seed, rng, state)
        m.run_frame_port()
        if f < f0:
            continue
        bx, by = cap["s"]
        absx = bx if prev is None else absx + (bx - prev + 256) % 512 - 256     # (unwrapped: absx & 511 = bx)
        prev = bx
        ys.add(by)
        ram = np.frombuffer(bytes(m.videoram[1]), "<u2").reshape(64, 64, 2)
        first = (absx + X0) >> 3                        # (the window's columns: picture x 32-351 = map x + 96 ..)
        for a in range(first, first + W // 8 + 1):
            if a not in cols:
                cols[a] = ram[:, a & 63].copy()
    a0, a1 = min(cols), max(cols)
    missing = [a for a in range(a0, a1 + 1) if a not in cols]
    if missing:
        sys.exit("columns never seen: %s" % missing[:10])
    strip = np.stack([cols[a] for a in range(a0, a1 + 1)])            # [n, 64 rows, 2]
    out = build_dir("rtype") / ("stage_bg_%s.bin" % args.name)
    out.write_bytes(struct.pack(">HhH", len(strip), a0, sorted(ys)[0]) + strip.astype("<u2").tobytes())
    print("%s: %d columns from absolute %d (BG y %s)" % (out, len(strip), a0, sorted(ys)))
    # the strip as the BG layer draws it (the frame's palette at the end)
    v = m72.Video("rtype")
    tiles = v.tiles[1]
    pens = m72.pens(m.palette[0], m.palette[1])
    img = np.zeros((64 * 8, len(strip) * 8), np.int32)
    for c in range(len(strip)):
        for r in range(64):
            code, attr = int(strip[c, r, 0]), int(strip[c, r, 1])
            t = tiles[(code & 0x3FFF) % len(tiles)]
            if code & 0x4000:
                t = t[:, ::-1]
            if code & 0x8000:
                t = t[::-1, :]
            img[r * 8:r * 8 + 8, c * 8:c * 8 + 8] = 256 + (attr & 15) * 16 + t.astype(np.int32)
    from PIL import Image
    png = build_dir("rtype") / ("stage_bg_%s.png" % args.name)
    Image.fromarray(pens[img].astype(np.uint8)).save(png)
    print(png)


if __name__ == "__main__":
    main()
