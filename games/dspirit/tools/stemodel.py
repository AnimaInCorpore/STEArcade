"""The STE renderer's picture in Python (src/render.s, the simple full-redraw renderer): its geometry and its order,
checked against the reference (engine/namcos1.py render_raw) by tools/render_test.py and by this file's main.

    venv/bin/python games/dspirit/tools/stemodel.py [frames]     (the port's schedule, seed 5's play: mismatches)

The picture is the arcade's 288 x 224 turned upright (ROT90, the game never flips): picture row r = arcade x, column
c = 223 - arcade y (MAME's visible area).  Every picture is drawn whole, bottom to top:
  * black inside the C116 window (and outside it);
  * per priority 0-7: the enabled layers of that priority (the lower number first), then the sprites of that priority
    (the lower entry first: the arcade's first-drawn entry, the highest, ends on top);
  * a scrolling layer i (0-3) as its turned image (row X = tile RAM's logical x, column k = h - 1 - logical y):
    picture row r shows image row (r + 44 + adj_i + sx_i) & 511 (adj 4 2 1 0), column c image column
    (c - 248 - sy_i) mod h (h 512, layer 3 256); the fixed layers 4, 5: row r = 8 C + .., column c = 223 - 8 R - ..;
  * a sprite: x = (b13 + (b12 & 1) * 256 + xoffs) & $1FF, y = ((17 - b15 - sizey - yoffs) & $FF) - 16, its top row
    r0 = x - 73, its first column c0 = 240 - y - sizey; pixel (dr, dc) = the part's I[iy][ix] with
    ix = tx + (flip x ? sizex - 1 - dr : dr), iy = ty + (flip y ? dc : sizey - 1 - dc) (galaga88's ren_convert does
    exactly this with its turned images); colour $7F (shadow) is not drawn.
The arcade lets a sprite pixel hidden under a layer still take the pixel from the entries drawn after it; the painter's
order here shows those (pixels_differ counts them).
"""
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
from namcos1 import VIS_X0, VIS_Y0

ADJ = (4, 2, 1, 0)
SIZE = (16, 8, 32, 4)
PIC_H, PIC_W = 288, 224


def clip_rect(regs):
    """the C116 window as picture rows r0..r1, columns c0..c1 (inclusive), or None (nothing shown)"""
    x0 = max(73, regs[0] - 1)
    x1 = min(360, regs[1] - 2)
    y0 = max(16, regs[2] - 0x11)
    y1 = min(239, regs[3] - 0x12)
    if x0 > x1 or y0 > y1:
        return None
    return x0 - 73, x1 - 73, 239 - y1, 239 - y0


def layer_pixels(gfx, vram, control, i):
    """layer i on the picture: (pens 288 x 224, opaque) in the picture's orientation"""
    chr_, mask, _ = gfx
    words = np.frombuffer(bytes(vram), ">u2")
    r = np.arange(PIC_H)[:, None]
    c = np.arange(PIC_W)[None, :]
    if i < 4:
        h = 256 if i == 3 else 512
        rows = h // 8
        codes = words[i * 0x1000:i * 0x1000 + rows * 64].reshape(rows, 64) & 0x3FFF
        sx = (control[i * 4] << 8) | control[i * 4 + 1]
        sy = (control[i * 4 + 2] << 8) | control[i * 4 + 3]
        X = (r + 44 + ADJ[i] + sx) & 511                    # the image row
        k = (c - 248 - sy) % h                              # the image column
        Y = h - 1 - k                                       # tile RAM's logical y
        X, Y = np.broadcast_arrays(X, Y)
        code = codes[Y >> 3, X >> 3]
    else:
        base = 0x3808 if i == 4 else 0x3C08
        codes = words[base:base + 36 * 28].reshape(28, 36) & 0x3FFF
        X = np.broadcast_to(r, (PIC_H, PIC_W))
        Y = np.broadcast_to(223 - c, (PIC_H, PIC_W))
        code = codes[Y >> 3, X >> 3]
    pen = chr_[code, Y & 7, X & 7]
    opq = mask[code, Y & 7, X & 7]
    bank = control[0x18 + i] & 7
    return 0x800 + (bank << 8) + pen.astype(np.int32), opq


def sprite_list(spriteram):
    """the entries the arcade draws (0-126), as (entry, priority, r0, c0, rows sizex, columns sizey, image) with the
    image's pens (rows x columns, 15 transparent) and the colour"""
    sr = spriteram
    xoffs = sr[0x7F5] + ((sr[0x7F4] & 1) << 8)
    yoffs = sr[0x7F7]
    out = []
    for e in range(127):
        off = 16 * e
        attr1, attr2, color = sr[off + 10], sr[off + 14], sr[off + 12]
        sizex, sizey = SIZE[attr1 >> 6], SIZE[(attr2 & 6) >> 1]
        x = (sr[off + 13] + ((color & 1) << 8) + xoffs) & 0x1FF
        y = ((17 - sr[off + 15] - sizey - yoffs) & 0xFF) - 16
        r0, c0 = x - 73, 240 - y - sizey
        if r0 >= PIC_H or r0 + sizex <= 0 or c0 >= PIC_W or c0 + sizey <= 0:
            continue
        out.append(dict(entry=e, pri=attr2 >> 5, r0=r0, c0=c0, sizex=sizex, sizey=sizey, colour=color >> 1,
                        code=sr[off + 11] + ((attr1 & 7) << 8), tx=(attr1 & 0x18) & ~(sizex - 1),
                        ty=(attr2 & 0x18) & ~(sizey - 1), flipx=bool(attr1 & 0x20), flipy=bool(attr2 & 1)))
    return out


def sprite_image(spr, s):
    """the part's pens in the picture's orientation: [dr][dc]"""
    dr = np.arange(s["sizex"])[:, None]
    dc = np.arange(s["sizey"])[None, :]
    ix = s["tx"] + (s["sizex"] - 1 - dr if s["flipx"] else dr)
    iy = s["ty"] + (dc if s["flipy"] else s["sizey"] - 1 - dc)
    ix, iy = np.broadcast_arrays(ix, iy)
    if s["code"] >= len(spr):
        return np.zeros((s["sizex"], s["sizey"]), np.int32)
    return spr[s["code"]][iy, ix].astype(np.int32)


def picture(gfx, st):
    """the picture of a state (states.py): pens 288 x 224, -1 black"""
    out = np.full((PIC_H, PIC_W), -1, np.int32)
    rect = clip_rect(st["regs"])
    if rect is None:
        return out
    r0, r1, c0, c1 = rect
    clip = np.zeros((PIC_H, PIC_W), bool)
    clip[r0:r1 + 1, c0:c1 + 1] = True
    control = st["control"]
    sprites = sprite_list(st["spriteram"])
    for p in range(8):
        for i in range(6):
            if control[0x10 + i] & 8 or (control[0x10 + i] & 7) != p:
                continue
            pens, opq = layer_pixels(gfx, st["vram"], control, i)
            o = opq & clip
            out[o] = pens[o]
        for s in sprites:
            if s["pri"] != p or s["colour"] == 0x7F:
                continue
            img = sprite_image(gfx[2], s)
            rr = slice(max(s["r0"], 0), min(s["r0"] + s["sizex"], PIC_H))
            cc = slice(max(s["c0"], 0), min(s["c0"] + s["sizey"], PIC_W))
            sub = img[rr.start - s["r0"]:rr.stop - s["r0"], cc.start - s["c0"]:cc.stop - s["c0"]]
            o = (sub != 15) & clip[rr, cc]
            reg = out[rr, cc]
            reg[o] = (s["colour"] << 4) + sub[o]
    return out


def reference(m):
    """the reference's picture in the same orientation: pens 288 x 224, -1 black"""
    raw = m.render_raw()
    return np.ascontiguousarray(np.rot90(raw, -1))


if __name__ == "__main__":
    import random
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ref"))
    from machine import DSpirit
    from cover import random_bits
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
    m = DSpirit()
    m.boot()
    gfx = m.gfx()
    rng = random.Random(5)
    hold = 0
    bad_frames, worst = 0, 0
    for f in range(frames):
        if f == 30:
            m.coin_in &= ~0x10
        elif f == 36:
            m.coin_in |= 0x10
        elif f == 130:
            m.control_in[0] &= ~0x80
        elif f == 136:
            m.control_in[0] |= 0x80
        elif f > 180:
            if hold <= 0:
                m.control_in[0] = (0xFF & ~random_bits(rng)) | 0x80
                hold = rng.randint(2, 30)
            hold -= 1
        m.run_frame_port()
        if f % 10:
            continue
        st = dict(regs=list(m.c116_regs), vram=bytes(m.vram), control=bytes(m.control),
                  spriteram=bytes(m.spriteram))
        a, b = picture(gfx, st), reference(m)
        n = int((a != b).sum())
        if n:
            bad_frames += 1
            worst = max(worst, n)
            if bad_frames <= 8:
                ys, xs = np.nonzero(a != b)
                print("frame %d: %d pixels differ, first at r %d c %d: model %X reference %X" % (
                    f, n, ys[0], xs[0], a[ys[0], xs[0]], b[ys[0], xs[0]]))
    print("%d of %d pictures differ (worst %d pixels)" % (bad_frames, (frames + 9) // 10, worst))


# ---- the widened picture (the user, 2026-11-07: the scrolling layers and the sprites over the STE's whole 320 pixels;
# the score and lives text at its old place) ----
SCR_W = 320
X0 = 48                         # (the arcade's picture column 0 at screen x 48)
CROP_TOP = 5                    # (the 277 lines shown: picture rows 5-281)
SHOWN = 277
HUD_TOP = 16                    # the text layers' rows 0-15 shown 5 lines lower, rows 264-287 6 lines higher
HUD_BOT = 264


def clip_wide(regs):
    """the C116 window on the widened picture: None (nothing), or rows r0..r1 and screen columns x0..x1; the full
    arcade window opens to the whole width"""
    rect = clip_rect(regs)
    if rect is None:
        return None
    r0, r1, c0, c1 = rect
    if c0 == 0 and c1 == PIC_W - 1:
        return r0, r1, 0, SCR_W - 1
    return r0, r1, c0 + X0, c1 + X0


def fixed_source_row(r):
    """the text layers' row shown at picture row r (the HUD rows moved into the lines shown), or None"""
    if CROP_TOP <= r < CROP_TOP + HUD_TOP:
        return r - CROP_TOP
    if CROP_TOP + SHOWN - (PIC_H - HUD_BOT) <= r < CROP_TOP + SHOWN:
        return r + (PIC_H - CROP_TOP - SHOWN)
    if CROP_TOP + HUD_TOP <= r < CROP_TOP + SHOWN - (PIC_H - HUD_BOT):
        return r
    return None


def layer_wide(gfx, vram, control, i, lock=None):
    """layer i on the widened picture (288 x 320): (pens, opaque).  lock: {layer: (dr, dc)} the layers drawn into
    layer 0's holes at layer 0's image row + dr, column + dc (the water locked to the terrain)"""
    chr_, mask, _ = gfx
    words = np.frombuffer(bytes(vram), ">u2")
    r = np.arange(PIC_H)[:, None]
    x = np.arange(SCR_W)[None, :]
    bank = control[0x18 + i] & 7
    if i < 4:
        h = 256 if i == 3 else 512
        codes = words[i * 0x1000:i * 0x1000 + (h // 8) * 64].reshape(h // 8, 64) & 0x3FFF
        sx = (control[i * 4] << 8) | control[i * 4 + 1]
        sy = (control[i * 4 + 2] << 8) | control[i * 4 + 3]
        X = (r + 44 + ADJ[i] + sx) & 511
        k = (x - X0 - 248 - sy) % h
        X, k = np.broadcast_arrays(X, k)
        Y = h - 1 - k
        code = codes[Y >> 3, X >> 3]
        pen = 0x800 + (bank << 8) + chr_[code, Y & 7, X & 7].astype(np.int32)
        opq = mask[code, Y & 7, X & 7].copy()
        if i == 0 and lock:
            for j, (dr, dc) in lock.items():
                hj = 256 if j == 3 else 512
                cj = words[j * 0x1000:j * 0x1000 + (hj // 8) * 64].reshape(hj // 8, 64) & 0x3FFF
                Xj = (X + dr) & 511
                Yj = hj - 1 - ((k + dc) % hj)
                codej = cj[Yj >> 3, Xj >> 3]
                oj = mask[codej, Yj & 7, Xj & 7] & ~opq
                pj = 0x800 + ((control[0x18 + j] & 7) << 8) + chr_[codej, Yj & 7, Xj & 7].astype(np.int32)
                pen[oj] = pj[oj]
                opq |= oj
        return pen, opq
    pen = np.full((PIC_H, SCR_W), 0, np.int32)
    opq = np.zeros((PIC_H, SCR_W), bool)
    base = 0x3808 if i == 4 else 0x3C08
    codes = words[base:base + 36 * 28].reshape(28, 36) & 0x3FFF
    for rr in range(PIC_H):
        sr = fixed_source_row(rr)
        if sr is None:
            continue
        c = np.arange(PIC_W)
        Y = 223 - c
        code = codes[Y >> 3, sr >> 3]
        pen[rr, X0:X0 + PIC_W] = 0x800 + (bank << 8) + chr_[code, Y & 7, sr & 7].astype(np.int32)
        opq[rr, X0:X0 + PIC_W] = mask[code, Y & 7, sr & 7]
    return pen, opq


def locked_layers(control):
    """the enabled layers drawn before layer 0 (lower priority, or equal and a lower number... the drawing order):
    locked into layer 0 while it is enabled"""
    if control[0x10] & 8:
        return []
    order = [(control[0x10 + i] & 7, i) for i in range(6) if not control[0x10 + i] & 8]
    order.sort()
    return [i for p, i in order[:order.index((control[0x10] & 7, 0))] if i < 4]


def picture_wide(gfx, st, lock=None):
    """the STE's picture of a state: pens 288 x 320 (screen x), -1 black; lock {layer: (dr, dc)} for the layers
    locked_layers names (the renderer's offsets); only rows CROP_TOP .. CROP_TOP + SHOWN - 1 are shown"""
    out = np.full((PIC_H, SCR_W), -1, np.int32)
    rect = clip_wide(st["regs"])
    if rect is None:
        return out
    r0, r1, x0, x1 = rect
    clip = np.zeros((PIC_H, SCR_W), bool)
    clip[r0:r1 + 1, x0:x1 + 1] = True
    control = st["control"]
    locked = locked_layers(control)
    lk = {j: lock[j] for j in locked} if locked else None
    sprites = sprite_list_wide(st["spriteram"])
    for p in range(8):
        for i in range(6):
            if control[0x10 + i] & 8 or (control[0x10 + i] & 7) != p or i in locked:
                continue
            pens, opq = layer_wide(gfx, st["vram"], control, i, lk if i == 0 else None)
            o = opq & clip
            out[o] = pens[o]
        for s in sprites:
            if s["pri"] != p or s["colour"] == 0x7F:
                continue
            img = sprite_image(gfx[2], s)
            x = s["c0"] + X0
            rr = slice(max(s["r0"], 0), min(s["r0"] + s["sizex"], PIC_H))
            cc = slice(max(x, 0), min(x + s["sizey"], SCR_W))
            if rr.start >= rr.stop or cc.start >= cc.stop:
                continue
            sub = img[rr.start - s["r0"]:rr.stop - s["r0"], cc.start - x:cc.stop - x]
            o = (sub != 15) & clip[rr, cc]
            reg = out[rr, cc]
            reg[o] = (s["colour"] << 4) + sub[o]
    return out


def sprite_list_wide(spriteram):
    """sprite_list over the widened picture: an entry is on it when it reaches screen x 0-319"""
    sr = spriteram
    xoffs = sr[0x7F5] + ((sr[0x7F4] & 1) << 8)
    yoffs = sr[0x7F7]
    out = []
    for e in range(127):
        off = 16 * e
        attr1, attr2, color = sr[off + 10], sr[off + 14], sr[off + 12]
        sizex, sizey = SIZE[attr1 >> 6], SIZE[(attr2 & 6) >> 1]
        x = (sr[off + 13] + ((color & 1) << 8) + xoffs) & 0x1FF
        y = ((17 - sr[off + 15] - sizey - yoffs) & 0xFF) - 16
        r0, c0 = x - 73, 240 - y - sizey
        if r0 >= PIC_H or r0 + sizex <= 0 or c0 + X0 >= SCR_W or c0 + X0 + sizey <= 0:
            continue
        out.append(dict(entry=e, pri=attr2 >> 5, r0=r0, c0=c0, sizex=sizex, sizey=sizey, colour=color >> 1,
                        code=sr[off + 11] + ((attr1 & 7) << 8), tx=(attr1 & 0x18) & ~(sizex - 1),
                        ty=(attr2 & 0x18) & ~(sizey - 1), flipx=bool(attr1 & 0x20), flipy=bool(attr2 & 1)))
    return out
