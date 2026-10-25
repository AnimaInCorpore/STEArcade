"""The STE port's graphics and palettes (build/kungfum/, ROM-derived: never committed).

    python tools/assets.py [--hist]      (--hist: collect the colour histograms again, ~3 min)

* kf_tiles.bin: the 1024 tiles as the arcade's 3 bit planes, a byte a plane a row (plane 0 = pixel bit 0): 24 bytes
  a tile (row 0: p0 p1 p2, row 1 ...).  The leftmost pixel is the byte's MSB, as on the STE.
* kf_spr.bin: the 1024 sprite cells (16x16), 3 words a row (p0 p1 p2), 96 bytes a cell.
* kf_assets.s: the palettes and pen maps of the scenes, the height PROM.

Scenes (render.s kf_scene): 0-4 the floors (E080 & 7) while a game or the demo plays (E000 in SCENE_STATES), 5 the
attract screens.  Each scene has 16 colours: 0 black (the side bands, the blank lines), 15 fitted by a weighted
k-means in Oklab to the colours the reference's playfield (lines 48-255) shows in that scene (ref/cover.py's
scripts and cheats: every floor), snapped to the STE's 4 bits a gun; every arcade pen (0-255 tiles, 256-511 sprites)
maps to the nearest of them in Oklab (black only for black).  The score panel (lines 0-47) has its own 16 (black and
15 fitted to its pixels) and map of the tile pens.
"""
from pathlib import Path
import collections
import pickle
import random
import sys
import numpy as np
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'ref'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import KungFuPort, Video, load
import sprite_programs as sp
from paths import build_dir

BUILD = build_dir('kungfum')
SCENE_STATES = (2, 3, 4, 6, 7, 8, 12)
NSCENES = 6


def scene_of(mem):
    return mem[0xE080] & 7 if mem[0xE000] in SCENE_STATES else 5


def oklab(c):
    """sRGB 0-255 -> Oklab"""
    c = np.asarray(c, float) / 255
    lin = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929], [0.2119034982, 0.6806995451, 0.1073969566],
                   [0.0883024619, 0.2817188376, 0.6299787005]])
    m2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468], [1.9779984951, -2.4285922050, 0.4505937099],
                   [0.0259707400, 0.7827717716, -0.8086757660]])
    return np.cbrt(lin @ m1.T) @ m2.T


def histograms(again=False):
    """{scene: Counter(pen: pixels)} of the playfield, Counter(pen) of the panel: reference frames every 8th"""
    path = BUILD / 'pal_hist.pkl'
    if path.exists() and not again:
        return pickle.loads(path.read_bytes())
    import cover
    v = Video()
    scenes = collections.defaultdict(collections.Counter)
    panel = collections.Counter()
    for seed, frames in ((1, 9000), (4, 12000), (6, 12000), (9, 16000), (12, 9000)):
        rnd = random.Random(seed)
        m = KungFuPort(*cover.dsw(seed))
        st = {'select': seed in (12, 13)}
        for f in range(frames):
            m.system, m.p1 = cover.inputs(f, rnd, st, m)
            cover.cheats(seed, f, m, st)
            m.run_frame_port()
            if f % 8 == 0:
                raw = v.render_raw(m.mem, m.sprite_ram, m.scroll)[:, 128:384]
                u, c = np.unique(raw[48:], return_counts=True)
                scenes[scene_of(m.mem)].update(dict(zip(u.tolist(), c.tolist())))
                u, c = np.unique(raw[:48], return_counts=True)
                panel.update(dict(zip(u.tolist(), c.tolist())))
        print('histograms: seed %d' % seed, flush=True)
    out = (dict(scenes), panel)
    path.write_bytes(pickle.dumps(out))
    return out


GRID = np.array([[r * 17, g * 17, b * 17] for r in range(16) for g in range(16) for b in range(16)])
GRID_LAB = oklab(GRID)


def fit(counter, pens, k=15, starts=20):
    """15 colours (4 bits a gun) for the pens' pixel counts, besides black: weighted k-means in Oklab"""
    cols = {}
    for p, n in counter.items():
        c = tuple(int(x) for x in pens[p])
        if c != (0, 0, 0):
            cols[c] = cols.get(c, 0) + n
    if not cols:
        return [(0, 0, 0)] * k
    rgb = np.array(list(cols), float)
    w = np.array(list(cols.values()), float)
    lab = oklab(rgb)
    if len(rgb) <= k:
        cen = lab.copy()
    else:
        rng = np.random.default_rng(3)
        best = None
        for _ in range(starts):
            c = lab[rng.choice(len(lab), k, replace=False, p=w / w.sum())]
            for _ in range(60):
                a = ((lab[:, None] - c[None]) ** 2).sum(2).argmin(1)
                for j in range(k):
                    if (a == j).any():
                        c[j] = (lab[a == j] * w[a == j, None]).sum(0) / w[a == j].sum()
            cost = (np.sqrt(((lab[:, None] - c[None]) ** 2).sum(2).min(1)) * w).sum()
            if best is None or cost < best[0]:
                best = (cost, c.copy())
        cen = best[1]
    out = []
    for c in cen:                            # snapped to the STE's grid (not black: that is colour 0)
        d = ((GRID_LAB - c) ** 2).sum(1)
        d[0] = 1e9
        g = tuple(int(x) for x in GRID[d.argmin()])
        if g not in out:
            out.append(g)
    while len(out) < k:
        out.append(out[-1])
    return sorted(out, key=lambda c: oklab([c])[0][0])


def pen_map(colours, pens):
    """each pen -> the nearest colour index (Oklab); black pens -> 0"""
    lab = oklab(np.array(colours, float))
    pl = oklab(np.asarray(pens, float))
    idx = ((pl[:, None] - lab[None]) ** 2).sum(2).argmin(1)
    idx[np.all(np.asarray(pens) == 0, axis=1)] = 0
    return idx.astype(np.uint8)


def ste_word(c):
    conv = lambda n: ((n >> 1) & 7) | ((n & 1) << 3)
    r, g, b = (int(v) // 17 for v in c)
    return (conv(r) << 8) | (conv(g) << 4) | conv(b)


def palettes(again=False):
    """-> (scene colours [6][16], scene maps [6][512], panel colours [16], panel map [256])"""
    v = Video()
    scenes, panel = histograms(again)
    cols, maps = [], []
    for s in range(NSCENES):
        c = [(0, 0, 0)] + fit(scenes.get(s, collections.Counter()), v.pens)
        cols.append(c)
        maps.append(pen_map(c, v.pens))
    pc = [(0, 0, 0)] + fit(panel, v.pens)
    return cols, maps, pc, pen_map(pc, v.pens[:256])


def gfx():
    chars = load('g-4c-a.bin') + load('g-4d-a.bin') + load('g-4e-a.bin')
    n = len(chars) // 3
    tiles = bytearray()
    for t in range(n // 8):
        for r in range(8):
            for p in range(3):
                tiles.append(chars[p * n + t * 8 + r])
    spr = b''.join(load(x) for x in ('b-4k-.bin', 'b-4f-.bin', 'b-4l-.bin', 'b-4h-.bin', 'b-3n-.bin', 'b-4n-.bin',
                                     'b-4m-.bin', 'b-3m-.bin', 'b-4c-.bin', 'b-4e-.bin', 'b-4d-.bin', 'b-4a-.bin'))
    n = len(spr) // 3
    cells = bytearray()
    for c in range(n // 32):
        for r in range(16):
            for p in range(3):
                base = p * n + c * 32
                cells += bytes((spr[base + r], spr[base + 16 + r]))
    return bytes(tiles), bytes(cells)


def check_gfx(tiles, cells):
    """the planes give the reference's decoded pixels"""
    v = Video()
    for t in (0, 1, 77, 500, 1023):
        for r in range(8):
            px = [sum(((tiles[t * 24 + r * 3 + p] >> (7 - x)) & 1) << p for p in range(3)) for x in range(8)]
            assert px == v.tiles[t, r].tolist(), (t, r)
    for c in (0, 5, 300, 1023):
        for r in range(16):
            ws = [cells[c * 96 + r * 6 + 2 * p] << 8 | cells[c * 96 + r * 6 + 2 * p + 1] for p in range(3)]
            px = [sum(((ws[p] >> (15 - x)) & 1) << p for p in range(3)) for x in range(16)]
            assert px == v.sprites[c, r].tolist(), (c, r)


def cell_masks(cells, code, fx):
    """a sprite cell's 16 opaque row masks (pen 0 transparent; flip x: the bits reversed)"""
    out = []
    for r in range(16):
        o = code * 96 + r * 6
        m = int.from_bytes(cells[o:o + 2], 'big') | int.from_bytes(cells[o + 2:o + 4], 'big') | \
            int.from_bytes(cells[o + 4:o + 6], 'big')
        if fx:
            m = int('{:016b}'.format(m)[::-1], 2)
        out.append(m)
    return out


SHAPE_SHARE = 0.99                      # the cells with generated code: the most drawn ones, this share of the draws


def coverage_cells(share=SHAPE_SHARE):
    """the cells (code, flip x, flip y) of the sprites the coverage drew (ref/cover.py: the first code, the cells),
    the most drawn first up to `share` of the cell draws (the rest: the row path)"""
    seen = collections.Counter()
    for f in sorted(BUILD.glob('cover[0-9]*.pkl')):
        for (code, n, fx, fy), k in pickle.loads(f.read_bytes())['sprites'].items():
            for i in range(n):
                seen[((code + i) % 1024, bool(fx), bool(fy))] += k
    total, acc, out = sum(seen.values()), 0, []
    for cell, k in sorted(seen.items(), key=lambda e: (-e[1], e[0])):
        if acc >= share * total:
            break
        out.append(cell)
        acc += k
    return sorted(out)


def sprite_programs(cells):
    """engine/sprite_programs.py for the coverage's cells: shape = code << 2 | flip x << 1 | flip y (render.s's slot
    is baked per (code, colour, flip x) in kf_order's order; flip y maps row r to 15 - r when drawing)"""
    shapes = {}
    for code, fx, fy in coverage_cells():
        m = cell_masks(cells, code, fx)
        shapes[code << 2 | fx << 1 | fy] = (m, [15 - r for r in range(16)]) if fy else m
    lines, stream, stats = sp.programs(shapes, 4096, line=424, prefix='kshp', table='kf_shapes', record='kshr',
                                       stream_sym='kf_sstream', stream_mode=True, long_dst=True)
    print('generated code: %(routines)d routines (%(code_lines)d lines) for %(shapes)d shapes x 16 shifts x 3 clips; '
          'stream blocks %(stream_blocks)d, %(stream_bytes)d bytes' % stats)
    order = sp.order_table([cell_masks(cells, code, fx) for code in range(1024) for fx in (0, 1)], 16)
    return lines, stream, order


def build(again=False):
    tiles, cells = gfx()
    check_gfx(tiles, cells)
    (BUILD / 'kf_tiles.bin').write_bytes(tiles)
    (BUILD / 'kf_spr.bin').write_bytes(cells)
    cols, maps, pc, pmap = palettes(again)
    out = ['; generated by games/kungfum/tools/assets.py (ROM-derived: not in git)', '\tsection data,data', '\teven',
           'kf_pals:']
    for c in cols:
        out.append('\tdc.w ' + ','.join('$%03X' % ste_word(x) for x in c))
    out.append('kf_hudpal:')
    out.append('\tdc.w ' + ','.join('$%03X' % ste_word(x) for x in pc))
    out.append('kf_maps:\t\t\t; a scene: 512 bytes, pens 0-255 tiles (colour * 8 + pixel), 256-511 sprites')
    for mp in maps:
        for i in range(0, 512, 32):
            out.append('\tdc.b ' + ','.join(str(int(x)) for x in mp[i:i + 32]))
    out.append('kf_hudmap:')
    for i in range(0, 256, 32):
        out.append('\tdc.b ' + ','.join(str(int(x)) for x in pmap[i:i + 32]))
    out.append('kf_height:')
    out.append('\tdc.b ' + ','.join(str(b) for b in load('b-5f-.bin')))
    out += ['\teven', 'kf_tiles:\tincbin\t"kf_tiles.bin"', 'kf_spr:\tincbin\t"kf_spr.bin"', '\teven']
    progs, stream, order = sprite_programs(cells)
    (BUILD / 'kf_sstream.bin').write_bytes(stream)
    (BUILD / 'kf_order.bin').write_bytes(order)
    out += progs + ['\tsection data,data', 'kf_order:\tincbin\t"kf_order.bin"', 'kf_sstream:\tincbin\t"kf_sstream.bin"',
                    '\teven', '\tsection text,code']
    (BUILD / 'kf_assets.s').write_text('\n'.join(out) + '\n')
    (BUILD / 'kf_palettes.pkl').write_bytes(pickle.dumps({'cols': cols, 'maps': maps, 'panel': pc, 'panel_map': pmap}))
    return cols, maps, pc, pmap


if __name__ == '__main__':
    cols, maps, pc, pmap = build('--hist' in sys.argv)
    v = Video()
    scenes, panel = histograms()
    for s in range(NSCENES):
        h = scenes.get(s, {})
        tot = sum(h.values()) or 1
        err = sum(n * np.abs(v.pens[p].astype(int) - np.array(cols[s][maps[s][p]])).mean() for p, n in h.items())
        print('scene %d: %d pens seen, mean error %.1f / 255 a channel' % (s, len(h), err / tot))
    tot = sum(panel.values())
    err = sum(n * np.abs(v.pens[p].astype(int) - np.array(pc[pmap[p]])).mean() for p, n in panel.items())
    print('panel: %d pens, mean error %.1f' % (len(panel), err / tot))
