"""The stage renderers' build-time data (tools/stage_model.py's picture): per stage a fixed STE palette for the playfield
and one for the status bar, and a fixed STE index for every arcade pen.

    venv/bin/python games/rtype/tools/stage_assets.py [--png]      -> build/rtype/stage<N>_pal.bin (+ preview pictures)

The colours: the model's pictures of the stage's recorded frames (render_test's states), each pen weighted by its
pixels (sprites x SPRITE_WEIGHT), at the STE's 4 bits a channel; index 0 black, the others colours the arcade shows
(medoids: no averages, so red and orange do not blend into brown), chosen for the least weighted Oklab error with
saturated colours weighted up (SAT_BOOST).  A pen's colour is the one it shows most often in those frames (fades are left out, colour cycles
are left out: the colours as the game sets them).

A pen's index is looked up by its current colour (the game reloads palette rows during a stage: a pen shows other
things later), so the renderer keeps a pen -> index table and redoes a palette row's entries when the game writes the
row.  stage<N>_pal.bin (big-endian): 16 words the playfield's STE colours, 16 words the status bar's, 4096 bytes the
playfield index of each 12-bit colour (r << 8 | g << 4 | b), 4096 bytes the status bar's, a word the reserved indices
R, R words their pens (indices 16 - R .. 15 in order: the pens' current colours each picture, faded by the renderer).
"""
import argparse
import collections
import pickle
import sys
import zlib
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
import m72
import m72_palettes as MP
from paths import build_dir
import stage_model as SM

# the stages: the recorded frames (render_test's sets) that show them
STAGES = {1: [("play", 500, 7000)]}
# reserved indices (the user's idea, 2026-10-29): pens whose colour changes in the stage (a fade-in, blinking lights)
# get playfield indices of their own; the renderer sets those indices to the pens' current colours each picture (and
# makes the fades itself: FADE_SNAP jumps the palette RAM to the target).  Stage 1: the wall's pens (grey 371, light
# grey 373, the lights 369 and 370; 372 stays black), faded in at frames ~4100-4750.
RESERVED = {1: [371, 373, 369, 370]}
SAT_BOOST = 40              # weights x (1 + SAT_BOOST * chroma): saturated colours pull centres
SPRITE_WEIGHT = 8           # a sprite pixel counts this many tile pixels (small saturated sprites keep their colours)
STEP = 10


def ste12(c12):
    """12-bit r << 8 | g << 4 | b (4 bits a channel) -> the STE's palette word (its 4 bits: bit 3 the lowest)"""
    out = 0
    for sh in (8, 4, 0):
        v = (c12 >> sh) & 15
        out |= (((v >> 1) | ((v & 1) << 3)) & 15) << sh
    return out


def pen_colours(st):
    """the 512 pens' 12-bit colours (4 bits a channel, as engine/m72_palettes.py)"""
    p = m72.pens(st["pal0"], st["pal1"])[:512]
    q = np.round(p.astype(float) / 17).astype(np.int32)
    return (q[:, 0] << 8) | (q[:, 1] << 4) | q[:, 2]


def medoids(keys, weight, n, rounds=8):
    """n colours (black first) chosen among keys (12-bit) to minimise the sum of weight' x Oklab L1 distance to the
    nearest, weight' = sqrt(pixels) x (1 + SAT_BOOST x chroma): greedy additions, then swaps"""
    lab = MP.lab12(keys).astype(float)
    chroma = np.hypot(lab[:, 1] - 128, lab[:, 2] - 128) / 128
    w = np.sqrt(weight) * (1 + SAT_BOOST * chroma)
    d = np.abs(lab[:, None, :] - lab[None]).sum(2)              # (keys x keys)
    black = np.abs(lab - MP.lab12([0])[0]).sum(1)
    chosen = []
    best = black.copy()
    for _ in range(n - 1):
        gain = (w[:, None] * np.maximum(best[:, None] - d, 0)).sum(0)
        gain[chosen] = -1
        j = int(gain.argmax())
        chosen.append(j)
        best = np.minimum(best, d[:, j])
    def cost(ch):
        return (w * np.minimum(black, d[:, ch].min(1))).sum()
    c0 = cost(chosen)
    for _ in range(rounds):
        improved = False
        for i in range(len(chosen)):
            for j in np.argsort(-w)[:200]:
                if j in chosen:
                    continue
                trial = chosen[:i] + [int(j)] + chosen[i + 1:]
                c = cost(trial)
                if c < c0 - 1e-9:
                    chosen, c0, improved = trial, c, True
        if not improved:
            break
    return np.array([0] + [int(keys[j]) for j in chosen], np.int32), chosen


def build(stage, png=False):
    import render_test as T
    md, lock = SM.Model(), SM.Lock()
    res = RESERVED.get(stage, [])
    hist, hhist = collections.Counter(), collections.Counter()     # 12-bit colour -> weighted pixels
    pics = []
    for which, a, b in STAGES[stage]:
        for f, item in T.load_states("rtype", which):
            if not a <= f <= b:
                continue
            st = pickle.loads(zlib.decompress(item))
            pens = md.picture(st, lock)
            if (f - a) % STEP:
                continue
            col = pen_colours(st)
            for hud, rows, h in ((0, slice(0, SM.HUD_Y), hist), (1, slice(SM.HUD_Y, 256), hhist)):
                v = pens[rows]
                for p, n in zip(*np.unique(v[v < 512], return_counts=True)):
                    if hud or p not in res:
                        h[int(col[p])] += int(n) * (SPRITE_WEIGHT if p < 256 else 1)
            if png and (f - a) % (STEP * 60) == 0:
                pics.append((f, st, pens))
    lab_all = MP.lab12(np.arange(4096)).astype(float)
    pals, tables = [], []
    for hud, h in enumerate((hist, hhist)):
        k = np.array(sorted(h), np.int32)
        nfit = 16 - (0 if hud else len(res))
        cols, _ = medoids(k, np.array([h[x] for x in k.tolist()], float), nfit)
        pal = np.zeros(16, np.int32)
        pal[:len(cols)] = cols
        lab_c = MP.lab12(cols).astype(float)
        tab = np.abs(lab_all[:, None, :] - lab_c[None]).sum(2).argmin(1)     # every 12-bit colour: its index
        pals.append(pal)
        tables.append(tab)
    (pal, hpal), (tab, htab) = pals, tables
    data = bytearray()
    for v in list(pal) + list(hpal):
        data += int(ste12(int(v))).to_bytes(2, "big")
    data += bytes(int(i) for i in tab)
    data += bytes(int(i) for i in htab)
    data += len(res).to_bytes(2, "big")
    for p in res:
        data += p.to_bytes(2, "big")
    path = build_dir("rtype") / ("stage%d_pal.bin" % stage)
    path.write_bytes(bytes(data))
    print("stage %d: %s, playfield %d colours, status bar %d" % (stage, path, len(hist), len(hhist)))
    print("   playfield", " ".join("%03X" % v for v in pal), "| status bar", " ".join("%03X" % v for v in hpal))
    if png:
        from PIL import Image
        rgb4 = lambda c: np.stack([(c >> 8) & 15, (c >> 4) & 15, c & 15], -1) * 17
        for f, st, pens in pics:
            col = pen_colours(st)
            pidx = tab[col]
            cur = pal.copy()
            for j, rp in enumerate(res):
                pidx[rp] = 16 - len(res) + j
                cur[16 - len(res) + j] = col[rp]
            p = np.minimum(pens, 511)
            ste = np.where(np.arange(256)[:, None] >= SM.HUD_Y, hpal[htab[col[p]]], cur[pidx[p]])
            ste = np.where(pens == 512, 0, ste)
            arc = m72.pens(st["pal0"], st["pal1"])[np.minimum(pens, 512)]
            img = np.hstack([rgb4(ste), arc]).astype(np.uint8)
            o = build_dir("rtype") / ("stage%d_colours_%d.png" % (stage, f))
            Image.fromarray(img).resize((img.shape[1] * 2, img.shape[0] * 2), Image.NEAREST).save(o)
            print("   ", o)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--png", action="store_true")
    args = ap.parse_args()
    for stage in STAGES:
        build(stage, args.png)


if __name__ == "__main__":
    main()
