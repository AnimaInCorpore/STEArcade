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
STAGES = {1: [("play", 500, 7000)],
          2: [("build/rtype/stage_states_1.pkl", 430, 2260)]}     # (the attract mode's first demo: the green cave)
# reserved indices (the user's idea, 2026-10-29): pens whose colour changes in the stage (a fade-in, blinking lights)
# get playfield indices of their own; the renderer sets those indices to the pens' current colours each picture (and
# makes the fades itself: FADE_SNAP jumps the palette RAM to the target).  Stage 1: the wall's pens (grey 371, light
# grey 373, the lights 369 and 370; 372 stays black), faded in at frames ~4100-4750.
RESERVED = {1: [371]}
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
        src = [(i, it) for i, (_, it) in enumerate(pickle.load(open(which, "rb")))] if which.endswith(".pkl") \
            else T.load_states("rtype", which)              # (a recording: frames by position)
        for f, item in src:
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


# ---- scenes: the screens told apart by their tile palette (the renderer picks one when the game changes the palette)
SCENE_RECORDINGS = ["build/rtype/stage_states_1.pkl", "build/rtype/stage_states_8.pkl"]
SCENE_DIFF = 24             # a frame belongs to the first scene whose tile palette differs in fewer pens
SCENE_STEP = 5
SCENE_MATCH = 192           # the renderer switches to the best scene only when it matches this many tile pens
RES_SHARE = 0.05            # a pen fading in from black over this share of a scene's pixels gets a reserved index


def choose_scene(tile_cols, refs, current):
    """the renderer's choice (src/stage.s st_scene): the scene whose reference tile palette has the most pens equal to
    the current one (the first of equals); kept unless that one matches SCENE_MATCH pens"""
    counts = [int((tile_cols == r).sum()) for r in refs]
    best = max(range(len(refs)), key=lambda k: (counts[k], -k))
    if current is None or (best != current and counts[best] >= SCENE_MATCH):
        return best
    return current


def load_scenes():
    """[(reference tile colours [256], playfield palette [16], status bar palette [16], ctab [4096], hctab [4096],
    reserved pens)] from build/rtype/stage_scenes.bin"""
    d = (build_dir("rtype") / "stage_scenes.bin").read_bytes()
    n = int.from_bytes(d[:2], "big")
    out, o = [], 2
    for _ in range(n):
        ref = np.frombuffer(d[o:o + 512], ">u2").astype(np.int32)
        o += 512
        pal = d[o:o + 32]
        hpal = d[o + 32:o + 64]
        o += 64
        ctab = np.frombuffer(d[o:o + 4096], np.uint8).astype(np.int32)
        htab = np.frombuffer(d[o + 4096:o + 8192], np.uint8).astype(np.int32)
        o += 8192
        nres = int.from_bytes(d[o:o + 2], "big")
        res = [int.from_bytes(d[o + 2 + 2 * j:o + 4 + 2 * j], "big") for j in range(nres)]
        o += 2 + 2 * SCENE_MAXRES
        flags = int.from_bytes(d[o:o + 2], "big")
        o += 2
        out.append((ref, pal, hpal, ctab, htab, res, flags))
    return out


SCENE_MAXRES = 2
# scenes whose sprites are squeezed toward the centre (the user, 2026-10-30: the title's R-TYPE logo, 384 pixels wide
# on the arcade, fits the STE's 320): an object's x moves by -(its picture x - 192) / 10 (stage_model.squeeze_x)
SQUEEZE_SCENES = {0}        # (scene 0: the title - the recordings start with it)


def scenes(png=False):
    """build/rtype/stage_scenes.bin (big-endian): a word, the scenes; per scene 256 words its reference tile colours
    (12-bit), 16 + 16 words the playfield's and the status bar's STE colours, 4096 + 4096 bytes their colour tables,
    a word R, SCENE_MAXRES words the reserved pens (indices 16 - R .. 15), a word of flags (bit 0: the sprites
    squeezed, SQUEEZE_SCENES)"""
    refs, members = [], []
    for path in SCENE_RECORDINGS:
        for i, (_, it) in enumerate(pickle.load(open(path, "rb"))):
            if i % SCENE_STEP:
                continue
            st = pickle.loads(zlib.decompress(it))
            c = pen_colours(st)[256:]
            if (c == 0).all():
                continue
            for k, r in enumerate(refs):
                if (c != r).sum() < SCENE_DIFF:
                    members[k].append(st)
                    break
            else:
                refs.append(c)
                members.append([st])
    md = SM.Model()
    lab_all = MP.lab12(np.arange(4096)).astype(float)
    data = bytearray(len(refs).to_bytes(2, "big"))
    for k, (ref, frames) in enumerate(zip(refs, members)):
        frames = frames[::max(1, len(frames) // 150)]
        pics = [(st, md.picture(st, SM.Lock())) for st in frames]
        # reserved: a big tile pen that is black in some frames, not in others (a fade-in)
        share = collections.Counter()
        cols = collections.defaultdict(set)
        total = 0
        for st, pens in pics:
            col = pen_colours(st)
            v, n = np.unique(pens[:SM.HUD_Y][pens[:SM.HUD_Y] < 512], return_counts=True)
            for p, c in zip(v.tolist(), n.tolist()):
                share[p] += c
                total += c
            for p in range(256, 512):
                cols[p].add(int(col[p]))
        res = [p for p, c in share.most_common() if p >= 256 and c >= RES_SHARE * total and 0 in cols[p]
               and len(cols[p]) > 1][:1]
        hist, hhist = collections.Counter(), collections.Counter()
        for st, pens in pics:
            col = pen_colours(st)
            for hud, rows, h in ((0, slice(0, SM.HUD_Y), hist), (1, slice(SM.HUD_Y, 256), hhist)):
                v = pens[rows]
                for p, n in zip(*np.unique(v[v < 512], return_counts=True)):
                    if hud or p not in res:
                        h[int(col[p])] += int(n) * (SPRITE_WEIGHT if p < 256 else 1)
        pal_tab = []
        for hud, h in enumerate((hist, hhist)):
            if not h:
                h = collections.Counter({0: 1})
            kk = np.array(sorted(h), np.int32)
            nfit = 16 - (0 if hud else len(res))
            cl, _ = medoids(kk, np.array([h[x] for x in kk.tolist()], float), min(nfit, max(2, len(kk) + 1)))
            pal = np.zeros(16, np.int32)
            pal[:len(cl)] = cl
            lab_c = MP.lab12(cl).astype(float)
            pal_tab.append((pal, np.abs(lab_all[:, None, :] - lab_c[None]).sum(2).argmin(1)))
        (pal, tab), (hpal, htab) = pal_tab
        for v in ref:
            data += int(v).to_bytes(2, "big")
        for v in list(pal) + list(hpal):
            data += int(ste12(int(v))).to_bytes(2, "big")
        data += bytes(int(i) for i in tab) + bytes(int(i) for i in htab)
        data += len(res).to_bytes(2, "big")
        for j in range(SCENE_MAXRES):
            data += (res[j] if j < len(res) else 0).to_bytes(2, "big")
        data += (1 if k in SQUEEZE_SCENES else 0).to_bytes(2, "big")
        print("scene %d: %d frames, reserved %s; playfield %s | bar %s" % (
            k, len(frames) * max(1, len(members[k]) // 150), res, " ".join("%03X" % v for v in pal),
            " ".join("%03X" % v for v in hpal)))
        if png:
            from PIL import Image
            rgb4 = lambda c: np.stack([(c >> 8) & 15, (c >> 4) & 15, c & 15], -1) * 17
            st, pens = pics[len(pics) // 2]
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
            o = build_dir("rtype") / ("scene_%d.png" % k)
            Image.fromarray(img).resize((img.shape[1] * 2, img.shape[0] * 2), Image.NEAREST).save(o)
    (build_dir("rtype") / "stage_scenes.bin").write_bytes(bytes(data))


def tiles():
    """build/rtype/stage_tiles.bin: the FG tiles (rt_b-a*), then the BG tiles (rt_b-b*), 4096 each, 8 rows of 4 bytes
    (8 pens a row, high nibble the left pixel) - the renderer colours them through its tables"""
    v = m72.Video("rtype")
    out = bytearray()
    for t in v.tiles:
        for tile in t:
            for row in tile:
                out += bytes((int(row[2 * k]) << 4) | int(row[2 * k + 1]) for k in range(4))
    (build_dir("rtype") / "stage_tiles.bin").write_bytes(bytes(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--png", action="store_true")
    args = ap.parse_args()
    tiles()
    scenes(args.png)


if __name__ == "__main__":
    main()
