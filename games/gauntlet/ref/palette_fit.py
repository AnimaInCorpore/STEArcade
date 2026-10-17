"""The fixed STE palette (docs/palette.json; tools/assets.py: the 16 STE colours and the 65536-entry IRGB table):
colour 0 black (the panel's background, the borders), 15 colours fitted to the game's own colours (Double Dragon's
method).

    venv/bin/python games/gauntlet/ref/palette_fit.py [frames]       -> docs/palette.json

The colours: every pixel of the reference picture (tools/machine.py, tools/video.py) of the attract mode (frames 300..,
every 20th) and of play in levels 1-16 and 20, 30 (tools/render_test.py scenario: one player at random, the level
poked into the game's RAM; frames 800.., every 20th).  The pens' IRGB_4444 colours (MAME's standard_irgb_decoder: 8
bits a channel); each scenario's histogram normalised (every scenario weighs the same), then a weighted k-means in
Oklab picks 11 colours (a colour weighs its share's square root) around the panel's four player colours (kept), each snapped to the nearest STE colour (4 bits a channel) of the nearest colour that occurs;
the best of 30 seeded starts.  Every IRGB word maps to the nearest of the 16 in Oklab.  Reported per scenario: the
mean absolute error per channel (0-255) and the share of exact pixels.
"""
import collections
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "tools"), str(HERE.parents[2] / "engine")]

LEVELS = list(range(1, 17)) + [20, 30]
PLAYERS = [[255, 0, 0], [0, 136, 255], [255, 255, 0], [0, 255, 0]]   # (the panel's warrior, valkyrie, wizard, elf:
                                                                      #  kept as they are, the rest fitted around them)
WEIGHT_POWER = 0.5                   # (a colour's weight: its share of the pixels to this power: the few pixels of
                                     # the players' colours in the panel and on the sprites still get colours)


def oklab(c):
    c = np.asarray(c, float) / 255
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929], [0.2119034982, 0.6806995451, 0.1073969566],
                   [0.0883024619, 0.2817188376, 0.6299787005]])
    m2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468], [1.9779984951, -2.4285922050, 0.4505937099],
                   [0.0259707400, 0.7827717716, -0.8086757660]])
    return np.cbrt(lin @ m1.T) @ m2.T


def irgb_rgb(words):
    """IRGB_4444 words -> [n, 3] RGB bytes (tools/video.py Video.pens)"""
    w = np.asarray(words, np.int64)
    i = ((w >> 12) & 15) * 0x11
    rgb = np.stack([(w >> 8) & 15, (w >> 4) & 15, w & 15], axis=1) * 0x11
    return ((i[:, None] * rgb) >> 8).astype(np.int64)


def histogram(seed, level, frames, first, every=20):
    from render_test import scenario
    from video import Video
    video = Video()
    h = collections.Counter()
    for f, m in scenario(seed, level, frames):
        if f >= first and f % every == 0:
            raw = video.render_raw(m.vram(), m.xscroll, (int(m.cpu.mem[0x905F6E]) << 8) | int(m.cpu.mem[0x905F6F]))
            pens = np.frombuffer(m.palette(), ">u2").astype(np.int64)
            rgb = irgb_rgb(pens[raw.ravel()])
            key = (rgb[:, 0] << 16) | (rgb[:, 1] << 8) | rgb[:, 2]
            u, c = np.unique(key, return_counts=True)
            h.update(dict(zip(u.tolist(), c.tolist())))
    return h


def key_rgb(keys):
    k = np.asarray(keys, np.int64)
    return np.stack([(k >> 16) & 255, (k >> 8) & 255, k & 255], axis=1)


def ste_snap(c):
    return (np.round(np.asarray(c, float) / 17) * 17).astype(int)


def error(h, pal):
    keys = np.array(list(h), np.int64)
    w = np.array(list(h.values()), float)
    rgb = key_rgb(keys)
    idx = ((oklab(rgb)[:, None] - oklab(pal)[None]) ** 2).sum(2).argmin(1)
    d = np.abs(rgb - np.asarray(pal, float)[idx])
    return (d.mean(1) * w).sum() / w.sum(), w[d.sum(1) == 0].sum() / w.sum()


def fit(h, k=15, starts=30, fixed=PLAYERS):
    keys = np.array(list(h), np.int64)
    cols, w = key_rgb(keys), np.array(list(h.values()), float)
    lab = oklab(cols)
    fixed = np.array(fixed, int)
    flab = oklab(fixed)
    free = k - len(fixed)
    rng = np.random.default_rng(2)
    best = None
    for _ in range(starts):
        cen = lab[rng.choice(len(lab), free, replace=False, p=w / w.sum())]
        for _ in range(80):
            a = ((lab[:, None] - np.vstack([cen, flab])[None]) ** 2).sum(2).argmin(1)
            for j in range(free):
                if (a == j).any():
                    cen[j] = (lab[a == j] * w[a == j, None]).sum(0) / w[a == j].sum()
        pal = np.unique(np.array([ste_snap(cols[((lab - c) ** 2).sum(1).argmin()]) for c in cen] +
                                 [ste_snap(c) for c in fixed]), axis=0)
        pal = pal[pal.sum(1) > 0]                                  # (black is colour 0)
        while len(pal) < k:                                        # (snapped together: the colour that helps most)
            cands = np.unique(ste_snap(cols), axis=0)
            costs = [(np.sqrt(((lab[:, None] - oklab(np.vstack([[0, 0, 0], pal, [c]]))[None]) ** 2).sum(2).min(1))
                      * w).sum() for c in cands]
            pal = np.vstack([pal, cands[int(np.argmin(costs))]])
        cost = (np.sqrt(((lab[:, None] - oklab(np.vstack([[0, 0, 0], pal]))[None]) ** 2).sum(2).min(1)) * w).sum()
        if best is None or cost < best[0]:
            best = (cost, pal)
    return sorted(best[1].astype(int).tolist(), key=lambda c: oklab([c])[0][0])


def hexes(pal):
    return ["#%02x%02x%02x" % tuple(int(v) for v in c) for c in pal]


def main():
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    from multiprocessing import Pool
    jobs = [(0, 0, 12000, 300)] + [(1 + (lv % 5), lv, frames, 800) for lv in LEVELS]
    names = ["attract"] + ["level %d" % lv for lv in LEVELS]
    import pickle
    from paths import build_dir
    cache = build_dir("gauntlet") / ("palette_hist_%d.pkl" % frames)
    if cache.exists():
        hs = pickle.loads(cache.read_bytes())
    else:
        with Pool(8) as p:
            hs = p.starmap(histogram, jobs)
        cache.write_bytes(pickle.dumps(hs))
    sets = dict(zip(names, hs))
    union = collections.Counter()
    for h in sets.values():
        total = sum(h.values())
        for key, n in h.items():
            if key:
                union[key] += (n / total) ** WEIGHT_POWER
    print("colours that occur:", len(set().union(*sets.values())))
    pal = np.array([[0, 0, 0]] + fit(union, 15))
    result = {"name": "Gauntlet fixed palette (tools/assets.py)",
              "origin": "ref/palette_fit.py: weighted k-means in Oklab over the colours of the attract mode (12000 "
                        "frames) and of play in levels %s (%d frames each)" % (LEVELS, frames),
              "colours": hexes(pal), "error": {}}
    for k, h in sets.items():
        e, x = error(h, pal)
        result["error"][k] = [round(e, 2), round(x, 3)]
        print("%-9s error %5.2f/255, %4.1f%% exact" % (k, e, 100 * x))
    print(" ".join(hexes(pal)))
    (HERE.parent / "docs" / "palette.json").write_text(json.dumps(result, indent=1) + "\n")


if __name__ == "__main__":
    main()
