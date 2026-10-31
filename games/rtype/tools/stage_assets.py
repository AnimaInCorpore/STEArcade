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


_rom = []


def pen_colours(st):
    """the 512 pens' 12-bit colours (4 bits a channel): from the rows' targets (st["recs"]: each row's colours are its
    record's target's table in ROM - the STE build keeps no arcade palette RAM), else from the palette RAMs"""
    if "recs" in st:
        if not _rom:
            from m72board import load_regions
            _rom.append(load_regions("rtype")["main"])
        out = np.zeros(512, np.int32)
        for r in range(32):
            out[16 * r:16 * r + 16] = target_colours(_rom[0], r >> 4, st["recs"][r])
        return out
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


# ---- scenes: the screens told apart by their tile rows' targets (the renderer picks one when a tile row's target
# changes)
SCENE_RECORDINGS = ["build/rtype/stage_states_1.pkl", "build/rtype/stage_states_8.pkl", "build/rtype/stage_states_s2.pkl"]
SCENE_DIFF_ROWS = 3         # a frame belongs to the first scene whose tile-row targets differ in fewer rows
SCENE_STEP = 5
SCENE_MATCH = 12            # the renderer switches to the best scene only when it matches this many tile rows
# scenes whose sprites are squeezed toward the centre (the user, 2026-10-30: the title's R-TYPE logo, 384 pixels wide
# on the arcade, fits the STE's 320): an object's x moves by -(its picture x - 192) / 10 (stage_model.squeeze_x)
SQUEEZE_SCENES = {0}        # (scene 0: the title - the recordings start with it)
# scenes whose tiles are shown shifted (the window over the tile layers moves, the sprites keep their places): the
# title's text lines reach the arcade's right edge (x 168-367; the ranking 88-287): 16 shows them whole
TILE_DX = {0: 16}
BG_STRIPS = ["s2"]
BG_STRIP_SCENES = {3}       # (flag bit 1: the BG from the stage's strip, locked to FG - stage 2's tunnel: stage_bg_s2)
# scenes whose BG is the scrolling layer once it holds a tile that is not empty (the user, 2026-10-31: stage 3's warship;
# flag bit 2): the buffer holds the BG at its own scroll (x and y), the FG is drawn over it each picture like sprites
# (stage_model.Model.picture bgscroll; src/stage.s st_bgon)
BG_SCROLL_SCENES = {4}       # (scene 4: stage 3)
# BG piece scenes (the user, 2026-10-31: flag bit 3, with bit 2): the FG stays the buffer's layer, the BG is drawn over
# it each picture like sprites (src/stage.s st_bgdraw) and the FG's opaque pixels again over those (st_wallfix)
BG_PIECE_SCENES = {4}
# hybrid scenes (the user, 2026-10-31: flag bit 4, with bits 2 and 3): the BG pieces while the BG has fewer chunks with
# pixels in the window than the FG, then the BG scroll mode with the FG pieces for the rest of the scene
BG_HYBRID_SCENES = {4}
SC_SIZE = 16 + 64 + 3 * 4096 + 2


def q4_12(r, g, b):
    """5-bit channels -> the 12-bit colour (4 bits a channel: round(pal5bit(v) / 17), as pen_colours)"""
    q = lambda v: int(round(((v << 3) | (v >> 2)) / 17))
    return (q(r) << 8) | (q(g) << 4) | q(b)


def target_colours(rom, kind, t):
    """the ROM's colour table t (sprite rows: kind 0, tile rows: 1): its 16 pens' 12-bit colours"""
    a = 0x3B000 + t * 48 + (0x2400 if kind else 0)
    return [q4_12(rom[a + 3 * p] & 31, rom[a + 3 * p + 1] & 31, rom[a + 3 * p + 2] & 31) for p in range(16)]


def choose_scene(tile_targets, refs, current):
    """the renderer's choice (src/stage.s st_scene): the scene whose reference has the most tile-row targets equal to
    the current ones (the first of equals); kept unless that one matches SCENE_MATCH rows"""
    counts = [int((np.asarray(tile_targets) == r).sum()) for r in refs]
    best = max(range(len(refs)), key=lambda k: (counts[k], -k))
    if current is None or (best != current and counts[best] >= SCENE_MATCH):
        return best
    return current


def load_scenes():
    """[(reference tile targets [16], playfield palette, status bar palette (STE words, bytes), sprite premap
    [256, 16], tile premap [256, 16], status bar premap [256, 16], flags)] from build/rtype/stage_scenes.bin"""
    d = (build_dir("rtype") / "stage_scenes.bin").read_bytes()
    out = []
    for k in range(int.from_bytes(d[:2], "big")):
        o = 2 + k * SC_SIZE
        ref = np.frombuffer(d[o:o + 16], np.uint8).astype(np.int32)
        pal, hpal = d[o + 16:o + 48], d[o + 48:o + 80]
        pm = [np.frombuffer(d[o + 80 + 4096 * j:o + 80 + 4096 * (j + 1)], np.uint8).reshape(256, 16).astype(np.int32)
              for j in range(3)]
        flags = int.from_bytes(d[o + 80 + 3 * 4096:o + 82 + 3 * 4096], "big")
        out.append((ref, pal, hpal, pm[0], pm[1], pm[2], flags))
    return out


def scenes(png=False):
    """build/rtype/stage_scenes.bin (big-endian): a word, the scenes; per scene (SC_SIZE bytes) 16 bytes its reference
    tile-row targets, 16 + 16 words the playfield's and the status bar's STE colours, 256 x 16 bytes the playfield
    index of each pen of each sprite target (the ROM's colour tables at $3B000 + 48 t), the same for the tile targets
    ($3B000 + $2400 + 48 t) and the status bar's indices of the tile targets, a word of flags (bit 0: the sprites
    squeezed, SQUEEZE_SCENES; bits 8-15 the tiles' shift in pixels, TILE_DX).  A palette row's colours are its
    record's target's table (the game sets and fades its rows to them; FADE_SNAP at once): src/stage.s copies a row's
    16 indices when its target changes - no colours at run time (the user, 2026-10-30: as if written for the STE)."""
    from m72board import load_regions
    rom = load_regions("rtype")["main"]
    refs, members = [], []
    for path in SCENE_RECORDINGS:
        for i, (_, it) in enumerate(pickle.load(open(path, "rb"))):
            if i % SCENE_STEP:
                continue
            st = pickle.loads(zlib.decompress(it))
            if (pen_colours(st)[256:] == 0).all():
                continue
            t = np.frombuffer(st["recs"][16:], np.uint8)
            for k, r in enumerate(refs):
                if (t != r).sum() < SCENE_DIFF_ROWS:
                    members[k].append(st)
                    break
            else:
                refs.append(t.copy())
                members.append([st])
    md = SM.Model()
    lab_all = MP.lab12(np.arange(4096)).astype(float)
    data = bytearray(len(refs).to_bytes(2, "big"))
    for k, frames in enumerate(members):
        frames = frames[::max(1, len(frames) // 150)]
        tg = np.array([np.frombuffer(st["recs"][16:], np.uint8) for st in frames])
        ref = [collections.Counter(tg[:, r].tolist()).most_common(1)[0][0] for r in range(16)]
        hist, hhist = collections.Counter(), collections.Counter()
        pics = []
        for st in frames:
            pens = md.picture(st, SM.Lock())
            pics.append((st, pens))
            col = pen_colours(st)
            for hud, rows, h in ((0, slice(0, SM.HUD_Y), hist), (1, slice(SM.HUD_Y, 256), hhist)):
                v = pens[rows]
                for p, n in zip(*np.unique(v[v < 512], return_counts=True)):
                    h[int(col[p])] += int(n) * (SPRITE_WEIGHT if p < 256 else 1)
        pal_tab = []
        for hud, h in enumerate((hist, hhist)):
            if not h:
                h = collections.Counter({0: 1})
            kk = np.array(sorted(h), np.int32)
            cl, _ = medoids(kk, np.array([h[x] for x in kk.tolist()], float), min(16, max(2, len(kk) + 1)))
            pal = np.zeros(16, np.int32)
            pal[:len(cl)] = cl
            lab_c = MP.lab12(cl).astype(float)
            pal_tab.append((pal, np.abs(lab_all[:, None, :] - lab_c[None]).sum(2).argmin(1)))
        (pal, tab), (hpal, htab) = pal_tab
        data += bytes(ref)
        for v in list(pal) + list(hpal):
            data += int(ste12(int(v))).to_bytes(2, "big")
        for kind, table in ((0, tab), (1, tab), (1, htab)):
            for t in range(256):
                data += bytes(int(table[c]) for c in target_colours(rom, kind, t))
        data += ((1 if k in SQUEEZE_SCENES else 0) | (2 if k in BG_STRIP_SCENES else 0) | (4 if k in BG_SCROLL_SCENES else 0) | (8 if k in BG_PIECE_SCENES else 0) | (16 if k in BG_HYBRID_SCENES else 0) |
                 (TILE_DX.get(k, 0) << 8)).to_bytes(2, "big")
        print("scene %d: %d frames, tile targets %s; playfield %s | bar %s" % (
            k, len(members[k]), " ".join("%02X" % t for t in ref), " ".join("%03X" % v for v in pal),
            " ".join("%03X" % v for v in hpal)))
        if png:
            from PIL import Image
            rgb4 = lambda c: np.stack([(c >> 8) & 15, (c >> 4) & 15, c & 15], -1) * 17
            st, pens = pics[len(pics) // 2]
            col = pen_colours(st)
            p = np.minimum(pens, 511)
            ste = np.where(np.arange(256)[:, None] >= SM.HUD_Y, hpal[htab[col[p]]], pal[tab[col[p]]])
            ste = np.where(pens == 512, 0, ste)
            arc = rgb4(np.append(col, 0)[np.minimum(pens, 512)])
            img = np.hstack([rgb4(ste), arc]).astype(np.uint8)
            o = build_dir("rtype") / ("scene_%d.png" % k)
            Image.fromarray(img).resize((img.shape[1] * 2, img.shape[0] * 2), Image.NEAREST).save(o)
    (build_dir("rtype") / "stage_scenes.bin").write_bytes(bytes(data))


def stage_pal():
    """build/rtype/stage_pal.s (src/natives.s, STAGE): the brighter target of the crystal's glow (PAL_GLOW) and every
    tile target's brightness (pal_tile_bright: the sum of its table's 48 channel bytes, ROM $3B000 + $2400 + 48 t)"""
    from m72board import load_regions
    rom = load_regions("rtype")["main"]
    def table(kind, t):
        a = 0x3B000 + t * 48 + (0x2400 if kind else 0)
        return rom[a:a + 48]
    glow = max((0x0A, 0x0B), key=lambda t: sum(table(0, t)))
    lines = ["; generated by games/rtype/tools/stage_assets.py", "PAL_GLOW = $%02X" % glow, "\teven", "pal_tile_bright:"]
    for t in range(0, 256, 16):
        lines.append("\tdc.w " + ",".join(str(sum(table(1, k))) for k in range(t, t + 16)))
    (build_dir("rtype") / "stage_pal.s").write_text("\n".join(lines) + "\n")


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
    # the FG tiles' opaque pixels (pen not 0): per tile 8 longs, a row's byte (the left pixel bit 7) in each plane's
    # byte (movep order), then the same X-flipped: src/stage.s st_cell composes a FG cell over a BG strip's
    rows, rowsf = bytearray(), bytearray()
    for tile in v.tiles[0]:
        for row in tile:
            b = sum(1 << (7 - k) for k in range(8) if row[k])
            bf = int("{:08b}".format(b)[::-1], 2)
            rows += bytes([b] * 4)
            rowsf += bytes([bf] * 4)
    (build_dir("rtype") / "stage_tmask.bin").write_bytes(bytes(rows + rowsf))
    # the BG tiles drawn empty (stage_model's stars): a byte per code (& $FFF), 1 empty - src/stage.s st_bgstar (the
    # BG cells that are not empty: st_bgn; the BG layer's cells)
    md = SM.Model()
    (build_dir("rtype") / "stage_bgstar.bin").write_bytes(bytes(int(x) for x in md.star[:4096]))
    strips()


def strips():
    """build/rtype/stage_strip_<name>.bin (src/stage.s): a word, the columns; per column 64 rows of (code, attribute)
    big-endian words - the code's bit 12 set (a BG tile: st_tile's tables and cache), $FFFF an empty tile (the
    model's rule: drawn black)"""
    md = SM.Model()
    for name in BG_STRIPS:
        strip = SM.load_strip(name)
        out = bytearray(len(strip).to_bytes(2, "big"))
        for col in strip:
            for code, attr in col:
                code, attr = int(code), int(attr)
                if md.star[(code & 0x3FFF) % len(md.star)]:
                    out += b"\xff\xff" + attr.to_bytes(2, "big")
                else:
                    out += (((code & 0xCFFF) | 0x1000) & 0xFFFF).to_bytes(2, "big") + attr.to_bytes(2, "big")
        (build_dir("rtype") / ("stage_strip_%s.bin" % name)).write_bytes(bytes(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--png", action="store_true")
    args = ap.parse_args()
    tiles()
    stage_pal()
    scenes(args.png)


if __name__ == "__main__":
    main()
