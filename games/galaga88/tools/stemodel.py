"""The STE picture as src/render.s builds it, in Python: from the turned graphics (tools/assets.py) and the formulas
there, without MAME's drawing; the specification of the renderer's geometry, checked against the reference
(engine/namcos1.py render_raw turned).

    venv/bin/python games/galaga88/tools/stemodel.py      (checks the recorded states, build/galaga88/render_states.pkl)

ste_pens(state) -> 288 x 224 pens (13 bit; -1 black) and the layer / sprite each pixel came from.
"""
import pickle
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
from assets import turned
from namcos1 import NamcoS1
from paths import build_dir

H, W = 288, 224                         # the STE picture (rows, columns)
ADJ = (4, 2, 1, 0)
SIZE = (16, 8, 32, 4)
_T = None


def data():
    global _T
    if _T is None:
        _T = turned()
    return _T


def layer_cells(vram, i):
    """the tile codes of layer i as [rows][cols] (logical: row = Y / 8, col = X / 8)"""
    words = np.frombuffer(vram, ">u2")
    if i < 4:
        rows = 32 if i == 3 else 64
        return (words[i * 0x1000:i * 0x1000 + rows * 64] & 0x3FFF).reshape(rows, 64)
    base = 0x3808 if i == 4 else 0x3C08
    return (words[base:base + 36 * 28] & 0x3FFF).reshape(28, 36)


def layer_xy(control, i):
    """per STE pixel the layer's logical (X, Y)"""
    r = np.arange(H)[:, None]
    c = np.arange(W)[None, :]
    if i >= 4:
        return np.broadcast_to(r, (H, W)), np.broadcast_to(223 - c, (H, W))
    w, h = 512, (256 if i == 3 else 512)
    sx = (control[i * 4] << 8) | control[i * 4 + 1]
    sy = (control[i * 4 + 2] << 8) | control[i * 4 + 3]
    return np.broadcast_to((r - 332 - ADJ[i] - sx) % w, (H, W)), np.broadcast_to((-25 - sy - c) % h, (H, W))


def ste_pens(st):
    rc, rm, rs = data()
    control, vram, sr = st["control"], st["vram"], st["spriteram"]
    assert st["flip"], "the model knows the flipped screen only (Galaga '88 always flips)"
    out = np.full((H, W), -1, np.int32)
    pri = np.zeros((H, W), np.int32)
    src = np.full((H, W), -1, np.int32)          # 0-5 the layer, 100 + entry a sprite
    for p in range(8):
        for i in range(6):
            if (control[0x10 + i] & 7) != p or control[0x10 + i] & 8:
                continue
            cells = layer_cells(vram, i)
            X, Y = layer_xy(control, i)
            code = cells[Y >> 3, X >> 3]
            # the turned cell R[dr][dc] = T[7 - dc][dr]: dr = X & 7, dc = 7 - (Y & 7)
            dr, dc = X & 7, 7 - (Y & 7)
            o = rm[code, dr, dc]
            pen = rc[code, dr, dc]
            colour = 0x800 + ((control[0x18 + i] & 7) << 8)
            out[o] = colour + pen[o].astype(np.int32)
            pri[o] = p
            src[o] = i
    regs = st["regs"]
    # the C116 window (MAME's visible area 73-360 x 16-239) in picture coordinates
    x0, x1 = max(73, regs[0] - 1) - 73, min(360, regs[1] - 2) - 73
    y0, y1 = max(16, regs[2] - 0x11) - 16, min(239, regs[3] - 0x12) - 16
    clip = np.zeros((H, W), bool)
    if x0 <= x1 and y0 <= y1:
        clip[287 - x1:287 - x0 + 1, y0:y1 + 1] = True
    out[~clip] = -1
    xoffs = sr[0x7F5] + ((sr[0x7F4] & 1) << 8)
    yoffs = sr[0x7F7]
    taken = np.zeros((H, W), bool)
    for e in range(126, -1, -1):
        off = e * 16
        attr1, attr2, color = sr[off + 10], sr[off + 14], sr[off + 12]
        sizex, sizey = SIZE[attr1 >> 6], SIZE[(attr2 & 6) >> 1]
        tx = (attr1 & 0x18) & ~(sizex - 1)
        ty = (attr2 & 0x18) & ~(sizey - 1)
        code = sr[off + 11] + ((attr1 & 7) << 8)
        sx = sr[off + 13] + ((color & 1) << 8) + xoffs
        sy = -sr[off + 15] - sizey - yoffs
        # the flipped screen: x = (-sx - sizex) & $1FF, y = ((-sy - sizey + 1 + 16) & $FF) - 16; the flips invert
        x = (-sx - sizex) & 0x1FF
        y = ((-sy - sizey + 1 + 16) & 0xFF) - 16
        flipx, flipy = not (attr1 & 0x20), not (attr2 & 1)
        sp = (attr2 & 0xE0) >> 5
        # picture rows: r = 360 - (x + dx), columns c = y - 16 + dy; the image's dx runs up, dy right
        r0 = 360 - x - (sizex - 1)
        c0 = y - 16
        # the turned 32 x 32 image: S[dr][dc] = I[dc][31 - dr]; the sub-rectangle I[ty..][tx..] and the flips
        img = rs[code]
        # rows dr = 0..sizex-1 (top to bottom) show dx = sizex-1-dr; I x = tx + (sizex-1-dx if flipx else dx)
        dxs = sizex - 1 - np.arange(sizex)
        ix = tx + np.where(flipx, sizex - 1 - dxs, dxs)
        dys = np.arange(sizey)
        iy = ty + np.where(flipy, sizey - 1 - dys, dys)
        sub = img[31 - ix][:, iy]                    # S[31 - X][Y] = I[Y][X]
        ra, rb = max(r0, 0), min(r0 + sizex, H)
        ca, cb = max(c0, 0), min(c0 + sizey, W)
        if ra >= rb or ca >= cb:
            continue
        s = sub[ra - r0:rb - r0, ca - c0:cb - c0]
        reg = (slice(ra, rb), slice(ca, cb))
        opq = (s != 15) & clip[reg] & ~taken[reg]
        vis = opq & (pri[reg] <= sp)
        o = out[reg]
        if color >> 1 == 0x7F:
            sh = vis & (o >= 0x800) & (o < 0x1000)
            o[sh] += 0x800
        else:
            o[vis] = ((color >> 1) << 4) + s[vis].astype(np.int32)
        src[reg][vis] = 100 + e
        taken[reg] |= opq
    return out, src


def reference(st):
    m = NamcoS1("galaga88", cpus=False)
    for k in range(3):
        m.pal[k][:] = st["pal"][k]
    m.c116_regs = list(st["regs"])
    m.vram[:] = st["vram"]
    m.control[:] = st["control"]
    m.spriteram[:] = st["spriteram"]
    m.flip = st["flip"]
    return np.ascontiguousarray(np.rot90(m.render_raw(), k=1))


if __name__ == "__main__":
    states = pickle.load(open(build_dir("galaga88") / "render_states.pkl", "rb"))
    bad = 0
    n = 0
    for name, seq in states.items():
        for k, st in enumerate(seq[::10]):
            got, _ = ste_pens(st)
            want = reference(st)
            n += 1
            d = int((got != want).sum())
            if d:
                bad += 1
                if bad <= 5:
                    ys, xs = np.nonzero(got != want)
                    print("%s %d: %d pixels differ, first (r %d c %d) %d/%d" % (name, k * 10, d, ys[0], xs[0],
                                                                                got[ys[0], xs[0]], want[ys[0], xs[0]]))
    print("%d of %d pictures differ" % (bad, n))
