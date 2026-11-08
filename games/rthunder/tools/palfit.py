"""The STE palette of Rolling Thunder: one fixed set of 16 colours fitted to frames of the reference (attract mode and
random play, seeds 0-5), and the map from the 512 indirect colours (tiles 0-255, sprites 256-511) to its indices.

    python games/rthunder/tools/palfit.py [frames] [--seeds 0,1,...]     -> build/rthunder/palfit.npz, palfit_hist.pkl

Histograms are collected every 20th frame: pixels of tile layers and of sprites separately (palette_quantize.fit
weights them as the other ports do).  The map is a flat nearest-colour map of all 512 indirect colours onto the
fitted palette (no checker pairs yet).
"""
import pickle
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / "ref"),
                str(Path(__file__).resolve().parents[3] / "engine")]
from machine import RthunderRule
import cover
import palette_quantize as pq
from paths import build_dir


def collect(frames, seeds, every=20):
    tiles, sprites = Counter(), Counter()
    counts = Counter()
    for seed in seeds:
        dswa, dswb, inputs = cover.schedule(seed)
        m = RthunderRule()
        m.dsw = [dswa, dswb]
        m.boot()
        for f in range(frames):
            m.in0, m.in1, m.in2 = inputs(f)
            m.run_frame_port()
            if f % every == every - 1:
                raw = m.render_raw()
                counts.update(dict(zip(*np.unique(raw, return_counts=True))))
        print("seed %d done" % seed, flush=True)
    return counts


def main():
    frames = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 3000
    seeds = [0, 1, 2, 3, 4, 5]
    if "--seeds" in sys.argv:
        seeds = [int(x) for x in sys.argv[sys.argv.index("--seeds") + 1].split(",")]
    out = build_dir("rthunder")
    hist = out / "palfit_hist.pkl"
    if hist.exists() and "--again" not in sys.argv:
        counts = pickle.load(open(hist, "rb"))
    else:
        counts = collect(frames, seeds)
        pickle.dump(counts, open(hist, "wb"))
    from machine import Rthunder
    m = Rthunder(cpus=False)
    pal = m.palette(True)
    layers = pq.pen_histograms({int(p): int(n) for p, n in counts.items()}, pal, lambda p: p >= 256)
    inputs = np.unique(pal, axis=0)
    palette, pairs = pq.fit(layers, inputs, 16, cache=out / "fitcache")
    # the map: every indirect colour -> its nearest index
    flat = pq.flat_map(palette, pal)
    np.savez(out / "palfit.npz", palette=palette, flat=flat, pal=pal)
    print("palette", palette.tolist())
    used = np.array(sorted(counts))
    print("colours used %d, mapped onto %d indices" % (len(used), len(set(flat[used].tolist()))))


if __name__ == "__main__":
    main()
