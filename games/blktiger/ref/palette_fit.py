"""The fixed STE palette (docs/palette.json, tools/assets.py: the 16 STE colours and the 4096-entry pen table):
colour 0 black (the backdrop and the blank background), 15 colours fitted to the game's own colours.

    python ref/palette_fit.py [frames] [stage frames]       -> docs/palette.json

The colours: every pixel of the reference picture (lines 16-239) of
  * the logic test's input script (attract, coin, start, the first stage), frames 300.. every 15th;
  * each stage 0-7 with ref/cover.py's cheats (the stage number $f3a1 forced while the game sets up, the lives kept),
    walking right and attacking, frames 1100.. every 15th.
Each of these nine sets' 12-bit colour histogram is normalised (every set weighs the same; within a set the
pixels count, so a stage's sky or wall gets its colour), then a weighted k-means in Oklab picks 15 colours, each
snapped to the nearest colour that occurs (4 bits a channel, which the STE shows exactly); the best of 30 seeded
starts.  The pens map to the nearest colour in Oklab.

For comparison: the palette before (a median cut of the script's colours, mapped by RGB distance weighted 2/4/1),
the square-rooted weights of Bubble Bobble's ref/palette_fit.py, and its layout of 13 colours + 2 lent to flashing
entries (here without them: the error of its 13).  Reported per set: the mean absolute error per channel (0-255) and
the share of exact pixels.
"""
import collections
import json
import os
import sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, '..', 'tools'), os.path.join(HERE, '..', '..', '..', 'engine')]
from machine import BlackTiger
from logic_test import inputs
from assets import oklab, RGB


def frame_hist(m, h):
    values = np.frombuffer(m.mem, np.uint8)
    pal = values[0xd800:0xdc00].astype(np.uint16) | values[0xdc00:0xe000].astype(np.uint16) << 8
    u, c = np.unique(pal[m.render_raw()[16:240]] & 4095, return_counts=True)
    h.update(dict(zip(u.tolist(), c.tolist())))


def script_hist(frames):
    m, h = BlackTiger(), collections.Counter()
    for f in range(frames):
        m.inputs[:3] = inputs(f)
        m.run_frame_port()
        if f >= 300 and f % 15 == 0:
            frame_hist(m, h)
    return h


def stage_hist(stage, frames):
    m, h = BlackTiger(), collections.Counter()
    write0, setup = m.cpu.wr8, [True]

    def wr8(a, v):
        return write0(a, stage if setup[0] and a == 0xf3a1 else v)
    m.cpu.wr8 = wr8
    for f in range(frames):
        if f < 1000:
            m.inputs[:3] = inputs(f)
        else:
            m.mem[0xf3a0] = 3
            m.inputs[1] = 255 ^ 1 ^ 16 ^ (32 if f % 90 < 15 else 0)
        if f == 1060:
            setup[0] = False
        try:
            m.run_frame_port()
        except RuntimeError:
            break
        if f >= 1100 and f % 15 == 0:
            frame_hist(m, h)
    return h


def arrays(h):
    keys = np.array(list(h), int)
    return RGB[keys], np.array(list(h.values()), float)


def error(h, mapping, pal):
    """mean absolute error per channel (0..255) and the share of exact pixels; mapping: palette word -> index"""
    keys = np.array(list(h), int)
    w = np.array(list(h.values()), float)
    d = np.abs(RGB[keys] - np.asarray(pal, float)[mapping[keys]])
    return (d.mean(1) * w).sum() / w.sum(), w[d.sum(1) == 0].sum() / w.sum()


def nearest_map(pal):
    return ((oklab(RGB)[:, None] - oklab(pal)[None]) ** 2).sum(2).argmin(1)


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


BEFORE = ('#000000 #eedd99 #ffcc88 #ddaa77 #aaaa77 #55aadd #bb7755 #998855 #777777 #996644 #776633 #555544 '
          '#991100 #552200 #224477 #331122')       # (the median cut before 2026-10-10)


def hexes(pal):
    return ['#%02x%02x%02x' % tuple(int(v) for v in c) for c in pal]


def union_of(sets, power):
    union = collections.Counter()
    for h in sets.values():
        total = sum(h.values())
        for key, n in h.items():
            if key:                                      # (black is colour 0)
                union[key] += (n / total) ** power
    return union


def main():
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
    stage_frames = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
    sets = {'script': script_hist(frames)}
    for s in range(8):
        sets[f'stage {s}'] = stage_hist(s, stage_frames)
    print('colours that occur:', len(set().union(*sets.values())))
    before = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for c in BEFORE.split()])
    before_map = (((RGB[:, None] - before[None]) ** 2) * np.array([2, 4, 1])).sum(2).argmin(1)
    pal = np.array([[0, 0, 0]] + fit(union_of(sets, 1.0), 15))
    rows = [('before: median cut, RGB map', before, before_map),
            ('fitted: Oklab k-means 15 + black', pal, nearest_map(pal))]
    root = np.array([[0, 0, 0]] + fit(union_of(sets, 0.5), 15))
    rows.append(('square-rooted weights', root, nearest_map(root)))
    lent = np.array([[0, 0, 0]] + fit(union_of(sets, 1.0), 13))
    rows.append(('13 + black (+2 lent)', lent, nearest_map(lent)))
    result = {'name': 'Black Tiger fixed palette (tools/assets.py)',
              'origin': f'ref/palette_fit.py: weighted k-means in Oklab over the colours of {frames} frames of the logic '
                        f'test\'s inputs and {stage_frames} frames of each stage 0-7 (cover.py\'s cheats)',
              'colours': hexes(pal), 'error': {}}
    for name, p, mapping in rows:
        errors = {k: error(h, mapping, p) for k, h in sets.items()}
        mean = np.mean([e for e, _ in errors.values()]), np.mean([x for _, x in errors.values()])
        print(f'{name:34s} mean of the sets: error {mean[0]:5.2f}/255, {100 * mean[1]:4.1f}% exact')
        print('    ' + '  '.join(f'{k} {e:4.1f} {100 * x:4.1f}%' for k, (e, x) in errors.items()))
        print('    ' + ' '.join(hexes(p)))
        result['error'][name] = {k: [round(e, 2), round(x, 3)] for k, (e, x) in errors.items()}
        result['error'][name]['mean'] = [round(mean[0], 2), round(mean[1], 3)]
    json.dump(result, open(os.path.join(HERE, '..', 'docs', 'palette.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
