"""The fixed STE palette (docs/palette.json; tools/assets.py: the 16 STE colours and the 4096-entry colour table):
colour 0 black (the side bands, the blank text), 15 colours fitted to the game's own colours (Black Tiger's method,
games/blktiger/ref/palette_fit.py).

    python games/trojan/ref/palette_fit.py [frames]       -> docs/palette.json

The colours: every pixel of the reference picture (tools/machine.py, the port schedule) of the attract mode (frames
300.., every 15th) and of each level 1-6 (ref/cover.py seeds 4-9: the starting-level DIP switch, MAME's cheats, the
random play walking right), frames 1100.. every 15th.  Each of the seven sets' 12-bit colour histogram is normalised
(every set weighs the same), then a weighted k-means in Oklab picks 15 colours, each snapped to the nearest colour
that occurs (4 bits a channel: the STE shows it exactly); the best of 30 seeded starts.  Every colour maps to the
nearest of the 16 in Oklab.  Reported per set: the mean absolute error per channel (0-255) and the share of exact
pixels.
"""
import collections
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / 'tools'), str(HERE.parents[2] / 'engine')]
from machine import TrojanPort, DSWA, VISIBLE
import cover

RGB = np.array([[(v >> 8 & 15) * 17, (v >> 4 & 15) * 17, (v & 15) * 17] for v in range(4096)])   # (12-bit RGB)


def oklab(c):
    c = np.asarray(c, float) / 255
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929], [0.2119034982, 0.6806995451, 0.1073969566],
                   [0.0883024619, 0.2817188376, 0.6299787005]])
    m2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468], [1.9779984951, -2.4285922050, 0.4505937099],
                   [0.0259707400, 0.7827717716, -0.8086757660]])
    return np.cbrt(lin @ m1.T) @ m2.T


def colours12(m):
    """the reference picture's colours as 12-bit RGB values"""
    if m.video is None:
        from machine import Video
        m.video = Video()
    raw = m.video.render_raw(m.mem, m.sprites, m.regs)[VISIBLE[2]:VISIBLE[3] + 1]
    hi = np.frombuffer(bytes(m.pal_hi), np.uint8).astype(int)
    lo = np.frombuffer(bytes(m.pal_lo), np.uint8).astype(int)
    word = hi << 4 | lo >> 4
    return word[raw]


def histogram(seed, frames, first):
    level, cheats, inputs = cover.schedule(seed)
    m = TrojanPort(DSWA, 0x1C | cover.LEVEL_DSW[level] if level else 0xFC)
    m.run_to_idle()
    m.booted = True
    h = collections.Counter()
    for f in range(frames):
        m.inputs[0], m.inputs[1] = inputs(f) if seed else (0xFF, 0xFF)
        if cheats and f >= 1000:
            m.mem[0xCDA0] = 3
            m.mem[0xC078] = 0
            m.mem[0xC079] = 0x99
        m.run_frame_port()
        if f >= first and f % 15 == 0 and not m.regs['flip']:
            u, c = np.unique(colours12(m), return_counts=True)
            h.update(dict(zip(u.tolist(), c.tolist())))
    return h


def nearest_map(pal):
    return ((oklab(RGB)[:, None] - oklab(pal)[None]) ** 2).sum(2).argmin(1)


def error(h, mapping, pal):
    keys = np.array(list(h), int)
    w = np.array(list(h.values()), float)
    d = np.abs(RGB[keys] - np.asarray(pal, float)[mapping[keys]])
    return (d.mean(1) * w).sum() / w.sum(), w[d.sum(1) == 0].sum() / w.sum()


def fit(h, k=15, starts=30):
    keys = np.array(list(h), int)
    cols, w = RGB[keys], np.array(list(h.values()), float)
    lab = oklab(cols)
    rng = np.random.default_rng(2)
    best = None
    for _ in range(starts):
        cen = lab[rng.choice(len(lab), min(k, len(lab)), replace=False, p=w / w.sum())]
        for _ in range(80):
            a = ((lab[:, None] - cen[None]) ** 2).sum(2).argmin(1)
            for j in range(len(cen)):
                if (a == j).any():
                    cen[j] = (lab[a == j] * w[a == j, None]).sum(0) / w[a == j].sum()
        pal = np.unique(np.array([cols[((lab - c) ** 2).sum(1).argmin()] for c in cen]), axis=0)
        cost = (np.sqrt(((lab[:, None] - oklab(pal)[None]) ** 2).sum(2).min(1)) * w).sum()
        if len(pal) == k and (best is None or cost < best[0]):
            best = (cost, pal)
    return sorted(best[1].astype(int).tolist(), key=lambda c: oklab([c])[0][0])


def hexes(pal):
    return ['#%02x%02x%02x' % tuple(int(v) for v in c) for c in pal]


def main():
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
    from multiprocessing import Pool
    jobs = [(0, frames, 300)] + [(s, frames, 1100) for s in range(4, 10)]
    with Pool(len(jobs)) as p:
        hs = p.starmap(histogram, jobs)
    sets = dict(zip(['attract'] + ['level %d' % (s - 3) for s in range(4, 10)], hs))
    union = collections.Counter()
    for h in sets.values():
        total = sum(h.values())
        for key, n in h.items():
            if key:
                union[key] += n / total
    print('colours that occur:', len(set().union(*sets.values())))
    pal = np.array([[0, 0, 0]] + fit(union, 15))
    mapping = nearest_map(pal)
    result = {'name': 'Trojan fixed palette (tools/assets.py)',
              'origin': 'ref/palette_fit.py: weighted k-means in Oklab over the colours of %d frames of the attract mode '
                        'and of each level 1-6 (cover.py seeds 4-9)' % frames,
              'colours': hexes(pal), 'error': {}}
    for k, h in sets.items():
        e, x = error(h, mapping, pal)
        result['error'][k] = [round(e, 2), round(x, 3)]
        print('%-9s error %5.2f/255, %4.1f%% exact' % (k, e, 100 * x))
    print(' '.join(hexes(pal)))
    (HERE.parent / 'docs' / 'palette.json').write_text(json.dumps(result, indent=1) + '\n')


if __name__ == '__main__':
    main()
