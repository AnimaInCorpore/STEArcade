"""The text pens the score panel (tile rows 0-6, opaque) uses: docs/hud_pens.json, read by tools/assets.py.

    python games/mpatrol/ref/hud_pens.py [frames]

Runs the coverage seeds' play (ref/cover.py) in the port's schedule and collects, every 5th frame, the cells of tile
rows 0-6: each cell's pens are its colour * 4 + the pixel values its tile has (pixel 0 too: the panel is opaque).
"""
import json
import random
import sys
from collections import Counter
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / "tools"),
                str(Path(__file__).resolve().parents[3] / "engine")]
import cover
from machine import MoonPatrolPort, Video


def main():
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    v = Video()
    used = [sorted({int(p) for p in t.ravel()}) for t in v.tiles]
    pens, cells = Counter(), set()
    for seed in range(1, 10):
        rnd, st = random.Random(seed), {}
        m = MoonPatrolPort(*cover.dsw(seed))
        for f in range(frames):
            m.in0, m.in1 = cover.inputs(f, rnd, st, seed)
            cover.cheats(seed, f, m, st)
            m.run_frame_port()
            if f % 5:
                continue
            for i in range(7 * 32):
                code = m.mem[0x8000 + i] | (m.mem[0x8400 + i] & 0x80) << 1
                col = m.mem[0x8400 + i] & 0x7F
                cells.add((code, col))
        print("seed %d: %d cells" % (seed, len(cells)), flush=True)
    for code, col in cells:
        for p in used[code]:
            pens[col * 4 + p] += 1
    out = Path(__file__).resolve().parents[1] / "docs" / "hud_pens.json"
    out.write_text(json.dumps({"pens": sorted(pens), "cells": len(cells)}, indent=1) + "\n")
    print(out, len(pens), "pens,", len({tuple(v.pens[p]) for p in pens}), "colours")


if __name__ == "__main__":
    main()
