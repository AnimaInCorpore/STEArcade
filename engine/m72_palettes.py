"""The STE colours of the Irem M72 games' scenes, chosen offline (engine/rt/m72render.s, "Colours").

    venv/bin/python engine/m72_palettes.py rtype|mrheli        -> build/<game>/m72_pal.bin

A scene is a tile palette (palette 1, the pens 256-511 at the STE's 4 bits a channel): the recorded states of
games/rtype/tools/render_test.py (attract and play, from the reference board) are grouped by it (a frame belongs to the
first scene whose palette differs in fewer than SCENE_DIFF pens; frames of one colour are skipped), and scenes seen in
at least MIN_FRAMES recorded frames are kept.  Per scene the window's pixels of up to SAMPLES of its frames (the reference
picture, sprites included) give the colours' weights; the colours are chosen the renderer's way (index 0 black, 15
centres seeded by the farthest colour by Oklab L1 x the square root of the weight, k-means rounds), separately for the HUD
bar's lines when the game has one (R-Type 240-255, Mr. HELI 0-31) and the picture's other lines.  m72r_p0 (the neutral
BG index) is the index most of the window's BG pixels map to.  Key pens (pens of a stable, not black colour in all the
scene's frames) identify the scene at run time.

m72_pal.bin (big-endian): a word, the scenes; per scene SCENE_BYTES:
    +0    256 words: the reference tile palette (pens 256-511: r << 8 | g << 4 | b); the scene whose reference has the
                     most pens equal to the current palette's (at least MATCH) is the one
    +512  16 x 4 bytes: the centres' Oklab (L, a, b bytes as engine/m72_assets.lab_bytes, 0); index 0 black
    +576  word   centres
    +578  16 x 4 bytes: the HUD's centres
    +642  word   the HUD's centres (0: none)
    +644  word   m72r_p0
"""
import pickle
import sys
import zlib
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import build_dir
import m72
import m72_assets

SCENE_DIFF = 24
MIN_FRAMES = 60
SAMPLES = 48
NKEYS = 48
SCENE_BYTES = 648
MATCH = 256 - SCENE_DIFF
HUD = {"rtype": (240, 256), "mrheli": (0, 32)}
ROUNDS = 16


def colours12(ram):
    q4 = m72_assets.q4_table()
    w = np.frombuffer(bytes(ram), "<u2")
    return (q4[w[0:256] & 31].astype(np.int32) << 8) | (q4[w[512:768] & 31].astype(np.int32) << 4) | \
        q4[w[1024:1280] & 31]


def lab12(c):
    """12-bit colours -> Oklab bytes (L a b) as the renderer's table"""
    tab = m72_assets.lab_table()[:, :3].astype(np.int32)
    return tab[np.asarray(c)]


def choose(keys, weights, k=16):
    """the renderer's choice: black + 15 centres (Oklab bytes), farthest-point seeds by sqrt weight, k-means L1"""
    if not len(keys):
        return np.zeros((1, 3), np.int32)
    lab = lab12(keys)
    w = np.clip(np.floor(np.sqrt(np.asarray(weights, float))), 1, 127).astype(np.int64)
    cent = [lab12([0])[0]]
    dist = np.abs(lab - cent[0]).sum(1)
    while len(cent) < k:
        v = dist * w
        i = int(v.argmax())
        if v[i] == 0:
            break
        cent.append(lab[i].copy())
        dist = np.minimum(dist, np.abs(lab - lab[i]).sum(1))
    cent = np.array(cent)
    for _ in range(ROUNDS):
        d = np.abs(lab[:, None, :] - cent[None]).sum(2)
        a = d.argmin(1)
        for j in range(1, len(cent)):
            m = a == j
            if m.any():
                cent[j] = (lab[m] * w[m, None]).sum(0) // w[m].sum()
    return cent


def nearest(cent, colours):
    d = np.abs(lab12(colours)[:, None, :] - cent[None]).sum(2)
    return d.argmin(1)


def scenes(game):
    import render_test as T                                     # (the recorded states)
    refs, members = [], []
    for which in ("attract", "play"):
        for f, item in T.load_states(game, which):
            st = pickle.loads(zlib.decompress(item))
            c = colours12(st["pal1"])
            if (c == c[0]).all():
                continue
            for i, r in enumerate(refs):
                if (c != r).sum() < SCENE_DIFF:
                    members[i].append((which, f, st))
                    break
            else:
                refs.append(c)
                members.append([(which, f, st)])
    return [(refs[i], members[i]) for i in range(len(refs)) if len(members[i]) >= MIN_FRAMES]


def scene_data(game, ref, frames, video):
    hy0, hy1 = HUD[game]
    hist, hhist, bgcols = {}, {}, {}
    pick = frames[::max(1, len(frames) // SAMPLES)][:SAMPLES]
    stable = None
    for which, f, st in frames:
        c = colours12(st["pal1"])
        stable = (c == ref) if stable is None else (stable & (c == ref))
    for which, f, st in pick:
        pens = m72.pens(st["pal0"], st["pal1"])
        bands = [(y0, y1, m72.VideoState(st["fg"], st["bg"], st["spr"], sx, sy, off))
                 for y0, y1, sx, sy, off in st["bands"]]
        raw = video.render_raw(bands)[:, 96:416]
        q = np.round(pens.astype(float) / 17).astype(np.int32)
        col = (q[:, 0] << 8) | (q[:, 1] << 4) | q[:, 2]
        cpx = col[np.minimum(raw, 512)]
        cpx[raw == 512] = 0
        hud = np.zeros(256, bool)
        if hy0:                         # (a band starting at the bar / ending at it)
            cut = any(b[0] == hy0 for b in st["bands"])
        else:
            cut = any(b[1] == hy1 - 1 for b in st["bands"])
        if cut:
            hud[hy0:hy1] = True
        for target, rows in ((hist, ~hud), (hhist, hud)):
            v, n = np.unique(cpx[rows], return_counts=True)
            for a, b in zip(v.tolist(), n.tolist()):
                target[a] = target.get(a, 0) + b
        # the BG layer's pixels in the window (visible or not): m72r_p0
        y0, y1, sx, sy, off = max(st["bands"], key=lambda b: b[1] - b[0])
        rawb, colb, _ = video._layer(1, st["bg"])
        ys = np.arange(0, 256)
        xs = np.arange(96, 416)
        bp = (256 + colb * 16 + rawb)[((ys + sy[1] + 128) & 511)[:, None], ((xs + sx[1]) & 511)[None, :]]
        v, n = np.unique(col[bp], return_counts=True)
        for a, b in zip(v.tolist(), n.tolist()):
            bgcols[a] = bgcols.get(a, 0) + b
    keys = np.array(sorted(hist), np.int32)
    cent = choose(keys, [hist[k] * 16 // 64 for k in keys.tolist()])     # (the runtime's scale: 16 a sample, 1/64 px)
    hcent = np.zeros((0, 3), np.int32)
    if hhist:
        hk = np.array(sorted(hhist), np.int32)
        hcent = choose(hk, [hhist[k] * 16 // 64 for k in hk.tolist()])
    bgk = np.array(sorted(bgcols), np.int32)
    idx = nearest(cent, bgk)
    w = np.zeros(len(cent))
    for i, k in zip(idx, bgk.tolist()):
        w[i] += bgcols[k]
    p0 = int(w.argmax())
    # key pens: stable, not black, distinct colours first
    cand = [p for p in range(256) if stable[p] and ref[p] != 0]
    seen, keysel = set(), []
    for p in cand:
        if ref[p] not in seen:
            keysel.append(p)
            seen.add(ref[p])
    for p in cand:
        if len(keysel) >= NKEYS:
            break
        if p not in keysel:
            keysel.append(p)
    keysel = keysel[:NKEYS]
    return cent, hcent, p0, [(p, int(ref[p])) for p in keysel]


def pack(entries):
    out = bytearray(len(entries).to_bytes(2, "big"))
    for ref, cent, hcent, p0 in entries:
        b = bytearray(SCENE_BYTES)
        b[0:512] = np.asarray(ref, ">u2").tobytes()
        for base, cc in ((512, cent), (578, hcent)):
            for i, (L, a, bb) in enumerate(cc.tolist()):
                b[base + 4 * i:base + 4 * i + 3] = bytes([L, a, bb])
        b[576:578] = len(cent).to_bytes(2, "big")
        b[642:644] = len(hcent).to_bytes(2, "big")
        b[644:646] = p0.to_bytes(2, "big")
        out += b
    return bytes(out)


def build(game, out=None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "games" / "rtype" / "tools"))
    out = Path(out or build_dir(game))
    video = m72.Video(game)
    entries = [(ref,) + scene_data(game, ref, frames, video)[:3] for ref, frames in scenes(game)]
    m72_assets.write(out / "m72_pal.bin", pack(entries))
    return out, entries


if __name__ == "__main__":
    for g in sys.argv[1:] or ["rtype"]:
        out, e = build(g)
        print("%s: %d scenes in %s" % (g, len(e), out / "m72_pal.bin"))
        for ref, cent, hcent, p0 in e:
            print("  %d colours, HUD %d, p0 %d" % (len(cent), len(hcent), p0))
