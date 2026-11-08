"""The STE renderer's picture in Python (the order and geometry src/render.s follows), checked against the reference
(machine.py render_raw) with the fitted palette map (tools/palfit.py).

    python games/rthunder/tools/stemodel.py [frames] [--seed N]       -> pixels that differ, per frame

The picture is 288 x 224 STE colour indices.  Painter's order: the picture's colour 0 (back colour), then for priority
0..7 the scrolling layers of that priority (layer 3 down to 0 on equal priority, as render_raw), then the sprites with
sprite priority k = that priority (attr2 bits 7-5), the lowest entry first.  A sprite is hidden under the layers with
a priority above its k: the painter's order gets that; what it does not get is the arcade's per-pixel rule (a sprite
pixel hidden under a layer still takes pixels of the sprites drawn after it, and a sprite drawn earlier hides later
ones where they overlap): `pixels_differ` counts those, with the layers' own pixels equal.
"""
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / "ref"),
                str(Path(__file__).resolve().parents[3] / "engine")]
from machine import RthunderRule, VIS_X0, VIS_X1, VIS_Y0, VIS_Y1
import cover
from paths import build_dir


def load_map():
    d = np.load(build_dir("rthunder") / "palfit.npz")
    return d["flat"], d["palette"]


def sprite_entries(m):
    """the sprites by priority k, each list in painter's order (the lowest entry first: the arcade draws the highest
    entry first and lets it win where they overlap): (x, y, image [sy, sx] of 4 bit colours, colour row)"""
    _, _, spr = m.gfx()
    sr = m.spriteram
    size = (16, 8, 32, 4)
    xoffs = sr[0x7F5] + ((sr[0x7F4] & 1) << 8)
    yoffs = sr[0x7F7]
    bank_sprites = len(spr) // 8
    out = [[] for _ in range(8)]
    for off in range(0, 0x7F0, 0x10):
        attr1, attr2, color = sr[off + 10], sr[off + 14], sr[off + 12]
        flipx, flipy = bool(attr1 & 0x20), bool(attr2 & 1)
        sizex, sizey = size[attr1 >> 6], size[(attr2 & 6) >> 1]
        tx = (attr1 & 0x18) & ~(sizex - 1)
        ty = (attr2 & 0x18) & ~(sizey - 1)
        sx = sr[off + 13] + ((color & 1) << 8)
        sy = -sr[off + 15] - sizey
        code = (sr[off + 11] & (bank_sprites - 1)) + (attr1 & 7) * bank_sprites
        k = (attr2 & 0xE0) >> 5
        color >>= 1
        sx += xoffs
        sy -= yoffs
        if m.flip:
            sx, sy = -sx - sizex, -sy - sizey
            flipx, flipy = not flipx, not flipy
        sy += 1
        x, y = sx & 0x1FF, ((sy + 16) & 0xFF) - 16
        img = spr[code, ty:ty + sizey, tx:tx + sizex]
        if flipx:
            img = img[:, ::-1]
        if flipy:
            img = img[::-1, :]
        out[k].append((x, y, img, color))
    return out


def blit(out, x, y, img, color, lut):
    sizey, sizex = img.shape
    bh, bw = out.shape
    yy0, xx0 = max(y, 0), max(x, 0)
    yy1, xx1 = min(y + sizey, bh), min(x + sizex, bw)
    if yy0 >= yy1 or xx0 >= xx1:
        return
    sub = img[yy0 - y:yy1 - y, xx0 - x:xx1 - x]
    o = out[yy0:yy1, xx0:xx1]
    opq = sub != 15
    o[opq] = lut[2048 + color * 16 + sub[opq].astype(np.int32)]


def picture(m, flat, bgfirst=False):
    """the painter's-order picture as indirect colours (288 x 224), then mapped with `flat`"""
    bw, bh = 384, 264
    lut = m.pen_table()
    out = np.full((bh, bw), lut[8 * m.backcolor + 7], np.int32)
    ys, xs = np.mgrid[0:bh, 0:bw]
    xextent, yextent = VIS_X1 + VIS_X0 + 1, VIS_Y1 + VIS_Y0 + 1
    spr_by_pri = sprite_entries(m)
    if bgfirst:
        # the renderer's order: the three scrolling layers, every sprite below priority 7 (by k, lowest entry first), the
        # fixed layer 3, the sprites of priority 7
        order = [i for i in sorted(range(3), key=lambda i: (((m.xscroll[i >> 1][i & 1] & 0x0E00) >> 9), 3 - i))] + [3]
        for i in order:
            if i == 3:
                for k in range(7):
                    for (x, y, img, color) in spr_by_pri[k]:
                        blit(out, x, y, img, color, lut)
            dev, lay = i >> 1, i & 1
            pens, opaque = m.tilemap(dev, lay)
            dx = (47 if dev == 0 else 46) + (0, 2)[lay]
            sx, sy = m.xscroll[dev][lay], m.yscroll[dev][lay]
            h, w = pens.shape
            vx, vy = dx - sx, -9 - sy
            px, py = (xs - vx) % w, (ys - vy) % h
            o = opaque[py, px]
            out[o] = pens[py, px][o]
        for (x, y, img, color) in spr_by_pri[7]:
            blit(out, x, y, img, color, lut)
        return flat[out[VIS_Y0:VIS_Y1 + 1, VIS_X0:VIS_X1 + 1]]
    for pri in range(8):
        for i in (3, 2, 1, 0):
            dev, lay = i >> 1, i & 1
            if ((m.xscroll[dev][lay] & 0x0E00) >> 9) != pri:
                continue
            pens, opaque = m.tilemap(dev, lay)
            dx = (47 if dev == 0 else 46) + (0, 2)[lay]
            dxf = 422 - dx
            sx, sy = m.xscroll[dev][lay], m.yscroll[dev][lay]
            if m.flip:
                pens, opaque = pens[::-1, ::-1], opaque[::-1, ::-1]
                sx, sy = -sx, -sy
            h, w = pens.shape
            vx = (dx - sx) if not m.flip else (xextent - w - (dxf - sx))
            vy = (-9 - sy) if not m.flip else (yextent - h - (9 - sy))
            px, py = (xs - vx) % w, (ys - vy) % h
            o = opaque[py, px]
            out[o] = pens[py, px][o]
        for (x, y, img, color) in spr_by_pri[pri]:
            blit(out, x, y, img, color, lut)
    return flat[out[VIS_Y0:VIS_Y1 + 1, VIS_X0:VIS_X1 + 1]]


def main():
    frames = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 300
    seed = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 1
    flat, palette = load_map()
    dswa, dswb, inputs = cover.schedule(seed)
    m = RthunderRule()
    m.dsw = [dswa, dswb]
    m.boot()
    worst = 0
    for f in range(frames):
        m.in0, m.in1, m.in2 = inputs(f)
        m.run_frame_port()
        if f % 10 == 9:
            ref = flat[m.render_raw()]
            got = picture(m, flat, "--bgfirst" in sys.argv)
            n = int((ref != got).sum())
            worst = max(worst, n)
            if n:
                print("frame %d: %d pixels differ" % (f, n))
    print("%d frames checked, worst %d pixels differ" % (frames // 10, worst))


if __name__ == "__main__":
    main()
