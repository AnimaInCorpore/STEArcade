"""The 16 colour palettes of the port, one per background palette bank (the arcade has 256 palette entries: 16 of the
background bank, 16 sprite colours, 16 character colours, ...; the STE shows 16 at a time).

    python palettes.py             quantize (docs/palette_stats.json) -> docs/palettes.json, prints a report
Library: load_palettes() -> {"palette": [bank][16] STE words, "rgb": [bank][16][3], "map": [bank][256] STE index}

Weighted k-means in Oklab over the distinct colours of the entries that matter for a bank (its background entries, the
sprite entries, the character entries), weight = (pixel count over the sampled frames) ** 0.6 + a small floor so
that rare colours (text, small sprites) are not swallowed, index 0 = black (the screen border, the margins).  The STE
colour is the nearest of its 4096 and every arcade entry is mapped to the nearest palette colour of its bank.
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "docs")
sys.path.insert(0, HERE)
from machine import Gfx

K = 16


def srgb_to_linear(v):
    v = v / 255.0
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def rgb_to_oklab(rgb):
    rgb = np.asarray(rgb, np.float64)
    r, g, b = (srgb_to_linear(rgb[..., i]) for i in range(3))
    l = np.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m = np.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s = np.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    return np.stack([0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
                     1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
                     0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s], axis=-1)


def ste_level(c8):
    """arcade 8 bit level -> STE 4 bit level 0..15 (an STE channel shows level * 17)"""
    return int(min(15, max(0, round(c8 / 17.0))))


def ste_nibble(level):
    """the STE palette nibble of a level: bit 3 = the low bit of the level, bits 0-2 = the upper three"""
    return ((level & 1) << 3) | (level >> 1)


def ste_word(rgb):
    r, g, b = (ste_level(c) for c in rgb)
    return (ste_nibble(r) << 8) | (ste_nibble(g) << 4) | ste_nibble(b)


def kmeans(rgbs, weights, k, seed=1):
    """rgbs [N,3], weights [N] -> centroid rgb [k,3] (floats), weighted Lloyd in Oklab with a farthest point start"""
    lab = rgb_to_oklab(rgbs)
    n = len(rgbs)
    k = min(k, n)
    black = int(np.argmin(lab[:, 0]))
    cent = [black]
    d = ((lab - lab[black]) ** 2).sum(axis=1)
    while len(cent) < k:
        i = int(np.argmax(d * weights))
        cent.append(i)
        d = np.minimum(d, ((lab - lab[i]) ** 2).sum(axis=1))
    c = lab[cent].copy()
    for _ in range(100):
        dist = ((lab[:, None, :] - c[None, :, :]) ** 2).sum(axis=2)
        a = dist.argmin(axis=1)
        new = c.copy()
        for j in range(k):
            sel = a == j
            if sel.any():
                new[j] = (lab[sel] * weights[sel, None]).sum(axis=0) / weights[sel].sum()
        new[0] = lab[black]                         # the black cluster stays black
        if np.allclose(new, c):
            break
        c = new
    return c


def oklab_to_rgb(lab):
    lab = np.asarray(lab, np.float64)
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bl = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    lin = np.stack([r, g, bl], axis=-1)
    lin = np.clip(lin, 0, 1)
    srgb = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * lin ** (1 / 2.4) - 0.055)
    return np.clip(np.round(srgb * 255), 0, 255)


def build(stats, gfx):
    pal = gfx.palette                                # 256 entries, (r, g, b)
    out = {"palette": [], "rgb": [], "map": [], "error": []}
    for bank in range(4):
        entries = {}                                 # arcade entry -> weight
        for i in range(16):
            entries[bank * 16 + i] = stats["bg"][i]
            entries[64 + i] = stats["sprites"][i]
            entries[128 + i] = stats["chars"][i]
        # distinct colours (several entries show the same colour)
        colour = {}
        for e, w in entries.items():
            colour[pal[e]] = colour.get(pal[e], 0) + w
        colour.setdefault((0, 0, 0), 1)
        cols = sorted(colour)
        rgbs = np.array(cols, np.float64)
        w = np.array([colour[c] ** 0.6 + 40.0 for c in cols])
        cent = kmeans(rgbs, w, K)
        steps = [ste_word(tuple(oklab_to_rgb(c))) for c in cent]
        steps[0] = 0
        ste_rgb = np.array([[(((v >> s) & 15) >> 0) for s in (8, 4, 0)] for v in steps])
        # nibble -> level -> 8 bit
        def level(nib):
            return ((nib & 7) << 1) | (nib >> 3)
        pal_rgb = np.array([[level(n) * 17 for n in row] for row in ste_rgb], np.uint8)
        plab = rgb_to_oklab(pal_rgb)
        emap = []
        err = 0.0
        tot = 0.0
        for e in range(256):
            d = ((plab - rgb_to_oklab(np.array(pal[e], np.float64))) ** 2).sum(axis=1)
            j = int(d.argmin())
            emap.append(j)
            if e in entries:
                err += float(np.sqrt(d[j])) * entries[e]
                tot += entries[e]
        out["palette"].append(steps)
        out["rgb"].append(pal_rgb.tolist())
        out["map"].append(emap)
        out["error"].append(err / max(tot, 1))
    return out


def load_palettes():
    return json.load(open(os.path.join(DOCS, "palettes.json")))


def main():
    stats = json.load(open(os.path.join(DOCS, "palette_stats.json")))
    gfx = Gfx()
    out = build(stats, gfx)
    json.dump(out, open(os.path.join(DOCS, "palettes.json"), "w"), indent=1)
    for b in range(4):
        print("bank", b, "mean Oklab error %.4f" % out["error"][b])
        print("  palette", " ".join("%03X" % v for v in out["palette"][b]))
        print("  rgb    ", " ".join("%02x%02x%02x" % tuple(c) for c in out["rgb"][b]))
        for name, rng in (("bg", range(b * 16, b * 16 + 16)), ("spr", range(64, 80)), ("chr", range(128, 144))):
            print("  %s -> %s" % (name, " ".join("%x" % out["map"][b][e] for e in rng)))


if __name__ == "__main__":
    main()
