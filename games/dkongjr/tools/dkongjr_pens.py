"""Donkey Kong Junior pen colours as MAME computes them: 256 pens (bank * 64 + colour code * 4 + pixel), 0xRRGGBB.

Junior uses Donkey Kong's palette circuit (dkong_v.cpp, dkong2b_palette), only with its own PROMs (2e: low bits,
2f: high bits).  No current MAME build is installed here to dump the pens as games/dkong/tools/dkong_pens.py was,
so this is MAME's code itself in Python: compute_res_net (emu/video/resnet.cpp, dkong_net_info, MB7052 = TTL
outputs, Sanyo EZV20 monitor), the tri-state black of pixel 0 and palette_t::normalize_range(0, 255) in integer
arithmetic as MAME does it.  `python dkongjr_pens.py` checks it against Donkey Kong's MAME dump: all 256 pens exact.
"""
import os
import sys

sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from paths import EXTRACTED

VCC, VOL, VOH, TTL_HRES = 5.0, 0.05, 4.0, 50.0
# per channel: (amplifier minout, cut, rBias, resistors LSB first)
NET = [(0.7, 0.0, 470.0, (1000.0, 470.0, 220.0)),     # red: darlington
       (0.7, 0.0, 470.0, (1000.0, 470.0, 220.0)),     # green: darlington
       (0.0, 0.7, 680.0, (470.0, 220.0))]             # blue: emitter follower


def res_net(inputs, channel, background=False):
    minout, cut, rbias, rs = NET[channel]
    if background:
        rs = ()
    rtot = v = 0.0
    for i, r in enumerate(rs):
        if not (inputs >> i) & 1:
            rtot += 1.0 / r
            v += VOL / r
    rtot += 1.0 / rbias
    v += VCC / rbias
    opencol = v / rtot > VOH
    for i, r in enumerate(rs):
        if (inputs >> i) & 1 and not opencol:
            rtot += 1.0 / (r + TTL_HRES)
            v += VOH / (r + TTL_HRES)
    v *= 1.0 / rtot
    v = max(minout, v - cut)
    v = VCC - v                                         # Sanyo EZV20
    v = max(0.0, v - 0.7)
    v = min(v, VCC - 2 * 0.7)
    v = v / (VCC - 1.4) * VCC
    return int(v * 255 / VCC + 0.4)


def _clamp(x):
    return 0 if x < 0 else 255 if x > 255 else x


def _div(a, b):
    """C integer division (truncates toward zero)"""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def pens(prom_lo, prom_hi):
    rgb = []
    for i in range(256):
        p0, p1 = prom_lo[i], prom_hi[i]
        r = (p1 >> 1) & 7
        g = ((p1 << 2) & 4) | ((p0 >> 2) & 3)
        b = p0 & 3
        if i & 3 == 0:
            rgb.append(tuple(res_net(1, c, True) for c in range(3)))
        else:
            rgb.append((res_net(r, 0), res_net(g, 1), res_net(b, 2)))
    ys = [299 * r + 587 * g + 114 * b for r, g, b in rgb]
    ymin, ymax = min(ys), max(ys)
    tmin, tmax = 0, 255
    out = []
    for (r, g, b), y in zip(rgb, ys):
        u = _div((b - _div(y, 1000)) * 492, 1000)
        v = _div((r - _div(y, 1000)) * 877, 1000)
        t = tmin + _div((y - ymin) * (tmax - tmin + 1), ymax - ymin)
        out.append((_clamp(t + _div(1140 * v, 1000)) << 16) | (_clamp(t - _div(395 * u, 1000) - _div(581 * v, 1000)) << 8)
                   | _clamp(t + _div(2032 * u, 1000)))
    return out


def load(game, name):
    with open(os.path.join(str(EXTRACTED / game), name), "rb") as f:
        return f.read()


def junior_pens():
    return pens(load("dkongjr", "djr1-c-2e.2e"), load("dkongjr", "djr1-c-2f.2f"))


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "dkong", "tools"))
    from dkong_pens import PENS
    mine = pens(load("dkong", "c-2k.bpr"), load("dkong", "c-2j.bpr"))
    bad = [i for i in range(256) if mine[i] != PENS[i]]
    print("Donkey Kong pens: %d/256 match MAME's dump" % (256 - len(bad)))
    for i in bad[:8]:
        print("  pen %d: %06x, MAME %06x" % (i, mine[i], PENS[i]))
    sys.exit(1 if bad else 0)
