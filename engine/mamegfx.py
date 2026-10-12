"""MAME's video building blocks for the reference renderers (numpy): graphics decoding by a gfx_layout, the resistor
networks of the colour PROMs (emu/video/resnet.cpp), tilemaps with row scroll and drawgfx's sprites.

    gfx = decode_gfx(rom, 16, 16, 256, planes, xoffs, yoffs, 64 * 8)     # [code, y, x] pixel values
    w = resistor_weights(0, 255, -1.0, [1000, 470, 220], 1000, 0, ...)     # compute_resistor_weights
    v = combine(w[0], bit0, bit1, bit2)                                    # combine_weights (rounded)
    draw_gfx(bitmap, clip, gfx, code, pen_base, flipx, flipy, sx, sy, trans)   # drawgfx transpen / transmask
Bitmaps hold pen numbers (MAME's bitmap_ind16); pens -> RGB is the palette's job.
"""
import numpy as np


def rgn_frac(region_len, num, den):
    """RGN_FRAC(num, den) of a region, in bits."""
    return region_len * 8 * num // den


def decode_gfx(data, width, height, total, planes, xoffs, yoffs, inc, start=0):
    """gfx_layout -> uint8 [total, height, width]; offsets in bits, the first plane is the most significant
    (MAME's readbit: byte bit // 8, mask 0x80 >> bit % 8).  start: the GFXDECODE_ENTRY offset in bytes."""
    bits = np.unpackbits(np.frombuffer(bytes(data), np.uint8))
    off = (start * 8 + np.arange(total)[:, None, None] * inc + np.array(yoffs)[None, :, None] +
           np.array(xoffs)[None, None, :])
    out = np.zeros((total, height, width), np.uint8)
    n = len(planes)
    for i, p in enumerate(planes):
        o = off + p
        ok = o < len(bits)                    # (MAME: bits beyond the region read as 0)
        out |= (np.where(ok, bits[np.minimum(o, len(bits) - 1)], 0) << (n - 1 - i)).astype(np.uint8)
    return out


def resistor_weights(minval, maxval, scaler, *nets):
    """compute_resistor_weights: nets are (resistances, pulldown, pullup) tuples; returns one weight list per net."""
    ws = []
    for res, pd, pu in nets:
        w = []
        for n in range(len(res)):
            r0 = 1.0 / 1e12 if pd == 0 else 1.0 / pd
            r1 = 1.0 / 1e12 if pu == 0 else 1.0 / pu
            for j, r in enumerate(res):
                if j == n:
                    if r != 0:
                        r1 += 1.0 / r
                elif r != 0:
                    r0 += 1.0 / r
            r0 = 1.0 / r0
            r1 = 1.0 / r1
            vout = (maxval - minval) * r0 / (r1 + r0) + minval
            w.append(min(max(vout, float(minval)), float(maxval)))
        ws.append(w)
    if scaler < 0:
        scale = float(maxval) / max(sum(w) for w in ws)
    else:
        scale = scaler
    return [[x * scale for x in w] for w in ws]


def combine(weights, *bits):
    """combine_weights: the weighted sum of the bits, + 0.5, truncated."""
    s = 0.0
    for w, b in zip(weights, bits):
        s = s + w * b
    return int(s + 0.5)


def tile_pixmap(gfx, codes, colors, flipx, flipy, rows, cols, pen_base, granularity):
    """A tilemap's pixmap of pens [rows*h, cols*w] (TILEMAP_SCAN_ROWS arrays [rows, cols]); also the raw pixel
    values (for transparency masks)."""
    n, h, w = gfx.shape
    t = gfx[codes % n]                                         # [rows, cols, h, w]
    fx = flipx.astype(bool)[:, :, None, None]
    fy = flipy.astype(bool)[:, :, None, None]
    t = np.where(fx, t[:, :, :, ::-1], t)
    t = np.where(fy, t[:, :, ::-1, :], t)
    raw = t.transpose(0, 2, 1, 3).reshape(rows * h, cols * w)
    col = np.repeat(np.repeat(colors, h, 0), w, 1)
    return pen_base + col.astype(np.int32) * granularity + raw, raw


def scroll_rows(pixmap, scrollx, height):
    """The screen [height, W] of a pixmap with per-row-group x scroll (set_scroll_rows(len(scrollx))):
    screen x shows pixmap x + scroll."""
    ph, pw = pixmap.shape
    per = ph // len(scrollx)
    xs = np.arange(pw)
    out = np.empty((height, pw), pixmap.dtype)
    for y in range(height):
        out[y] = pixmap[y % ph, (xs + scrollx[(y % ph) // per]) % pw]
    return out


def draw_gfx(bitmap, clip, gfx, code, pen_base, flipx, flipy, sx, sy, trans):
    """drawgfx: element `code` (modulo the count) at (sx, sy), clipped to clip = (min_x, max_x, min_y, max_y);
    trans(pixels) -> bool mask of the transparent pixels (transpen: pixels == pen; transmask: by the pens)."""
    n, h, w = gfx.shape
    src = gfx[code % n]
    if flipx:
        src = src[:, ::-1]
    if flipy:
        src = src[::-1, :]
    x0, x1, y0, y1 = clip
    ax0, ay0 = max(sx, x0), max(sy, y0)
    ax1, ay1 = min(sx + w - 1, x1), min(sy + h - 1, y1)
    if ax0 > ax1 or ay0 > ay1:
        return
    s = src[ay0 - sy:ay1 - sy + 1, ax0 - sx:ax1 - sx + 1]
    d = bitmap[ay0:ay1 + 1, ax0:ax1 + 1]
    keep = ~trans(s)
    d[keep] = pen_base + s[keep]
