"""The picture R-Type's stage renderers draw: engine/m72.py's picture with the port's simplifications (the user's rule,
2026-10-29: keep the gameplay intact, leave out what only costs work).  The STE renderer must equal this model pixel for
pixel (in STE indices); the model itself is compared with the reference only by eye (tools/stage_model.py --png).

The simplifications, per stage (STAGES):
  * stars: a BG tile with at least STAR_MIN0 of its 64 pixels at pen 0 is drawn empty (black, index 0), and the star
    sprites (codes STAR_SPRITES, 1-7 pixels, emitted by the one-entry definitions $846C-$848A) are left out;
  * the BG locked to the FG: BG is drawn at FG x + L, L the locked relative offset (Lock); L follows the arcade's
    offset (BG x - FG x) only when it is off by LOCK_SLACK pixels or more, or for free while the window's BG holds
    nothing but empty tiles;
  * no sprite / tile priority: the sprites are over both layers (the list's first entry on top, as the arcade);
  * no BG-over-FG pixels (BG groups 1-3): FG's opaque pixels are over BG;
  * the colours: a fixed STE palette per stage and a fixed index per pen (tools/stage_assets.py), the status bar's
    lines with their own.

    venv/bin/python games/rtype/tools/stage_model.py --png F,F,...      (model | reference pictures, build/rtype/)
"""
import argparse
import pickle
import sys
import zlib
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
import m72
from paths import build_dir

STAR_MIN0 = 56
STAR_SPRITES = range(0xAF2, 0xAF8)
LOCK_SLACK = 2
BLACK = 512
X0 = 96                 # the window: MAME's bitmap x 96-415 (picture x 32-351)
W = 320
HUD_Y = 240             # the status bar's first line


class Model:
    def __init__(self):
        self.video = m72.Video("rtype")
        t = self.video.tiles[1]
        self.star = (t == 0).reshape(len(t), 64).sum(1) >= STAR_MIN0      # BG codes drawn empty

    def layer(self, n, ram):
        """map pens [512, 512] (-1: transparent / empty)"""
        raw, col, _ = self.video._layer(n, ram)
        pen = 256 + col * 16 + raw
        if n == 0:
            return np.where(raw != 0, pen, -1)
        w = np.frombuffer(ram, "<u2").reshape(64, 64, 2)
        empty = np.repeat(np.repeat(self.star[w[:, :, 0] & 0x3FFF], 8, 0), 8, 1)
        return np.where(empty, -1, pen)

    def bg_empty(self, ram, y0, y1, sy, bx):
        """True when the BG map's part under the window (lines y0..y1, BG map x bx..bx+319) is empty tiles only"""
        w = np.frombuffer(ram, "<u2").reshape(64, 64, 2)
        rows = (((np.arange(y0, y1 + 1) + sy + 128) & 511) >> 3)
        cols = ((np.arange(bx, bx + W) & 511) >> 3)
        return bool(self.star[w[np.unique(rows)][:, np.unique(cols), 0] & 0x3FFF].all())

    def picture(self, st, lock):
        """the window's pens [256, 320] (BLACK = 512: empty / display off) for a recorded state (render_test's), lock
        a Lock (updated)"""
        fgm, bgm = self.layer(0, st["fg"]), self.layer(1, st["bg"])
        out = np.full((256, W), BLACK, np.int32)
        xs = np.arange(X0, X0 + W)
        main = max(st["bands"], key=lambda b: b[1] - b[0])
        lock.update(self, st, main)
        for y0, y1, sx, sy, off in st["bands"]:
            if off:
                continue
            ys = np.arange(y0, y1 + 1)
            f = fgm[((ys + sy[0] + 128) & 511)[:, None], ((xs + sx[0]) & 511)[None, :]]
            bx = (sx[0] + lock.L) if y0 < HUD_Y else sx[1]
            b = bgm[((ys + sy[1] + 128) & 511)[:, None], ((xs + bx) & 511)[None, :]]
            out[y0:y1 + 1] = np.where(f >= 0, f, np.where(b >= 0, b, BLACK))
        self.sprites(out, st["spr"])
        return out

    def sprites(self, out, spr):
        w16 = np.frombuffer(spr, "<u2").astype(np.int32)
        sp = self.video.sprites
        done = np.zeros(out.shape, bool)
        i = 0
        while i < len(w16):                     # (the first entry on top: drawn first, pixels not drawn twice)
            y, code, a, x = (int(v) for v in w16[i:i + 4])
            w, h = 1 << ((a & 0xC000) >> 14), 1 << ((a & 0x3000) >> 12)
            i += 4 * w
            if not (y or code or a or x) or (code & 0xFFF) in STAR_SPRITES:
                continue
            sx = -256 + (x & 0x3FF) - X0
            sy = 384 - (y & 0x1FF) - 16 * h
            fx, fy = a & 0x800, a & 0x400
            for cx in range(w):
                for cy in range(h):
                    c = code + (8 * (w - 1 - cx) if fx else 8 * cx) + (h - 1 - cy if fy else cy)
                    px, py = sx + 16 * cx, sy + 16 * cy
                    ax0, ax1 = max(px, 0), min(px + 15, W - 1)
                    ay0, ay1 = max(py, 0), min(py + 15, HUD_Y - 1)    # (never into the status bar)
                    if ax0 > ax1 or ay0 > ay1:
                        continue
                    src = sp[c % len(sp)]
                    if fx:
                        src = src[:, ::-1]
                    if fy:
                        src = src[::-1, :]
                    s = src[ay0 - py:ay1 - py + 1, ax0 - px:ax1 - px + 1]
                    d = out[ay0:ay1 + 1, ax0:ax1 + 1]
                    dn = done[ay0:ay1 + 1, ax0:ax1 + 1]
                    show = (s != 0) & ~dn
                    d[show] = (a & 15) * 16 + s[show]
                    dn |= s != 0


class Lock:
    """the BG's locked offset from FG (see the module's docstring); redraw: set when L moved while the BG showed"""
    def __init__(self):
        self.L = None
        self.redraw = False

    def update(self, model, st, band):
        y0, y1, sx, sy, off = band
        rel = (sx[1] - sx[0]) & 511
        self.redraw = False
        if self.L is None:
            self.L = rel
            return
        d = (rel - self.L + 256) % 512 - 256
        if d == 0:
            return
        if model.bg_empty(st["bg"], y0, min(y1, HUD_Y - 1), sy[1], (sx[0] + self.L + X0) & 511) and \
                model.bg_empty(st["bg"], y0, min(y1, HUD_Y - 1), sy[1], (sx[0] + rel + X0) & 511):
            self.L = rel
        elif abs(d) >= LOCK_SLACK:
            self.L = rel
            self.redraw = True


def main():
    import render_test as T
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="play")
    ap.add_argument("--png", default="1000,2600,3000,4000")
    args = ap.parse_args()
    want = sorted(int(x) for x in args.png.split(","))
    from PIL import Image
    md, lock = Model(), Lock()
    for f, item in T.load_states("rtype", args.set):
        if f > want[-1]:
            break
        st = pickle.loads(zlib.decompress(item))
        pens = md.picture(st, lock)
        if f in want:
            pal = m72.pens(st["pal0"], st["pal1"])
            ref = T.reference("rtype", st)
            img = np.hstack([pal[np.minimum(pens, 512)], pal[np.minimum(ref, 512)]]).astype(np.uint8)
            out = build_dir("rtype") / ("model_%s_%d.png" % (args.set, f))
            Image.fromarray(img).resize((img.shape[1] * 2, img.shape[0] * 2), Image.NEAREST).save(out)
            print("%d: L %s, %s" % (f, lock.L, out))


if __name__ == "__main__":
    main()
