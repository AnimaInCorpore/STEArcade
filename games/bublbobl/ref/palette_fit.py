"""The fixed palette (render.s STATICPAL): 13 colours for the pens, fitted to the game's own colours; colour 0 is the
background (palette entry 255), colours 14 and 15 are lent to flashing palette entries; both set at run time.

    python ref/palette_fit.py [frames] [pens]       -> docs/palette_static.json (pens: default 13)

The colours: every pixel of the reference picture in frames 300.. of the logic test's input script (attract, coin,
start, play), sampled every 15 frames, and every pixel of docs/attract_collage_64.png (64 MAME attract frames, 68
colours).  Each set's colour histogram is normalised and square-rooted (rare colours count more than their pixels),
then a weighted k-means in Oklab picks 15 colours, each snapped to the nearest colour that occurs (the arcade's
4-bit-per-channel values, which the STE shows exactly).  The best of 30 seeded starts is kept.  The pens map to the
nearest of them in Oklab (tools/assets.py: the 4096-entry table).

For comparison it prints the error of DawnBringer 16 (black instead of its #140c1c) and docs/palette16.json.
"""
import collections, json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "..", "tools"), os.path.join(HERE, "..", "..", "..", "engine")]

DOCS = os.path.join(HERE, "..", "docs")
DB16 = "#000000 #442434 #30346d #4e4a4e #854c30 #346524 #d04648 #757161 #597dce #d27d2c #8595a1 #6daa2c #d2aa99 " \
       "#6dc2ca #dad45e #deeed6"


def oklab(c):
    c = np.asarray(c, float) / 255
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929], [0.2119034982, 0.6806995451, 0.1073969566],
                   [0.0883024619, 0.2817188376, 0.6299787005]])
    m2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468], [1.9779984951, -2.4285922050, 0.4505937099],
                   [0.0259707400, 0.7827717716, -0.8086757660]])
    return np.cbrt(lin @ m1.T) @ m2.T


def nearest(cols, pal):
    """index of the nearest palette colour (Oklab) for each colour"""
    return ((oklab(cols)[:, None] - oklab(pal)[None]) ** 2).sum(2).argmin(1)


def histogram_frames(frames):
    from machine import Bublbobl
    import logic_test as lt
    m = Bublbobl()
    h = collections.Counter()
    for f in range(frames):
        m.in0, m.in1, m.in2 = lt.inputs(f)
        m.run_frame_port()
        if f >= 300 and f % 15 == 0:
            q = m.render_rgb().reshape(-1, 3).astype(int) // 17
            u, c = np.unique(q[:, 0] * 256 + q[:, 1] * 16 + q[:, 2], return_counts=True)
            h.update(dict(zip(u.tolist(), c.tolist())))
    return h


def histogram_png(path):
    from PIL import Image
    q = np.round(np.array(Image.open(path).convert("RGB")).reshape(-1, 3) / 17).astype(int)
    u, c = np.unique(q[:, 0] * 256 + q[:, 1] * 16 + q[:, 2], return_counts=True)
    return collections.Counter(dict(zip(u.tolist(), c.tolist())))


def arrays(h):
    return np.array([[k >> 8, (k >> 4) & 15, k & 15] for k in h], float) * 17, np.array(list(h.values()), float)


def error(pal, h):
    """mean absolute error per channel (0..255) and the share of exact pixels"""
    cols, w = arrays(h)
    pal = np.asarray(pal, float)
    d = np.abs(cols - pal[nearest(cols, pal)])
    return (d.mean(1) * w).sum() / w.sum(), w[d.sum(1) == 0].sum() / w.sum()


def fit(h, k=15, starts=30):
    cols, w = arrays(h)
    lab = oklab(cols)
    rng = np.random.default_rng(2)
    best = None
    for _ in range(starts):
        cen = lab[rng.choice(len(lab), k, replace=False, p=w / w.sum())]
        for _ in range(80):
            a = ((lab[:, None] - cen[None]) ** 2).sum(2).argmin(1)
            for j in range(k):
                if (a == j).any():
                    cen[j] = (lab[a == j] * w[a == j, None]).sum(0) / w[a == j].sum()
        pal = np.unique(np.array([cols[((lab - c) ** 2).sum(1).argmin()] for c in cen]), axis=0)
        cost = (np.sqrt(((lab[:, None] - oklab(pal)[None]) ** 2).sum(2).min(1)) * w).sum()
        if len(pal) == k and (best is None or cost < best[0]):
            best = (cost, pal)
    return sorted(best[1].astype(int).tolist(), key=lambda c: oklab([c])[0][0])


def main():
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    npens = int(sys.argv[2]) if len(sys.argv) > 2 else 13
    game = histogram_frames(frames)
    attract = histogram_png(os.path.join(DOCS, "attract_collage_64.png"))
    union = collections.Counter()
    for h in (game, attract):
        total = sum(h.values())
        for key, n in h.items():
            union[key] += np.sqrt(n / total)
    pal = fit(union, npens)
    hx = lambda s: [int(s[i:i + 2], 16) for i in (1, 3, 5)]
    oklab16 = [hx(p["rgb"]) for p in json.load(open(os.path.join(DOCS, "palette16.json")))["palette"]]
    rows = [("DawnBringer 16 (black)", [hx(s) for s in DB16.split()]), ("docs/palette16.json", oklab16),
            ("fitted (%d + background)" % npens, [[0, 0, 0]] + pal)]
    result = {"name": "bublbobl fixed palette (render.s STATICPAL)",
              "origin": "ref/palette_fit.py: weighted k-means in Oklab over the colours of %d frames of the logic test's "
                        "inputs and docs/attract_collage_64.png" % frames,
              "pens": ["#%02x%02x%02x" % tuple(c) for c in pal], "error": {}}
    for name, p in rows:
        eg, xg = error(p, game)
        ea, xa = error(p, attract)
        print("%-26s gameplay: error %5.2f/255, %4.1f%% exact | attract collage: error %5.2f/255, %4.1f%% exact"
              % (name, eg, 100 * xg, ea, 100 * xa))
        result["error"][name] = {"gameplay": [round(eg, 2), round(xg, 3)], "attract": [round(ea, 2), round(xa, 3)]}
    print("pens:", " ".join(result["pens"]))
    json.dump(result, open(os.path.join(DOCS, "palette_static.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
