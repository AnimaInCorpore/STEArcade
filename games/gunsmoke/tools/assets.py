"""The STE renderer's assets: palette, graphics as pixel-value bit planes in screen orientation, the generated sprite code.

    python assets.py      (build.py runs it when --assets is given or the files are missing)

The arcade raster is rotated: screen row r = 255 - raw x, screen column c = raw y - 16.  A graphic's oriented form is
`pixels.transpose(1, 0)[::-1]` (rows from the top of the screen).

* palette.bin / palmap.bin: one 16 colour palette for the whole game (weighted k-means in Oklab over the pens of
  docs/palette_stats.json, colour 0 black) and the STE colour of each of the 640 pens and of 640 = no layer (black).
  docs/palette.json keeps both.
* tile_planes.bin: 512 tiles x 32 rows x 4 longs (pixel value bits 0-3, bit 31 = the left pixel); spr_planes.bin:
  2048 sprites x 16 rows x 4 words; chr_planes.bin: 1024 characters x 8 rows x 2 bytes; chr_pens.bin: the pens each
  character uses (bits), chr_trans.bin: the transparent pens of each of the 32 character colours (lookup PROM $4F).
* The sprite code: Blitter routines and streams (games/1942/tools/spritegen.py) for the shapes (code, y flip) drawn most
  often in coverage (cover.py 'sprites'), as many as fit SPRITE_BUDGET bytes; spr_shape.bin maps code * 2 + flip to
  the shape's index there or $FFFF (those are drawn by the generic path: the same Blitter calls, the end masks made
  from the shape's rows).
"""
from pathlib import Path
import importlib.util
import json
import pickle
import sys
import numpy as np
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from paths import build_dir, require_coverage
from video import Video

BUILD = build_dir('gunsmoke')
DOCS = Path(__file__).resolve().parents[1] / 'docs'
SPRITE_BUDGET = 900 * 1024


def helper(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TOOLS_1942 = Path(__file__).resolve().parents[2] / '1942' / 'tools'


def planes(pixels, bits, dtype):
    """[n, rows, width] pixel values -> [n, rows, bits] words of each value bit (the left pixel in the top bit)"""
    width = pixels.shape[-1]
    weights = (1 << np.arange(width - 1, -1, -1)).astype(np.uint64)
    out = np.stack([(((pixels >> b) & 1).astype(np.uint64) * weights).sum(-1) for b in range(bits)], axis=-1)
    return out.astype(dtype)


def palette(video):
    pal = helper('gunsmoke_palettes', TOOLS_1942 / 'palettes.py')
    rgb = np.vstack((video.pens, [[0, 0, 0]])).astype(float)
    stats = json.loads((DOCS / 'palette_stats.json').read_text())
    weights = np.zeros(641)
    for counts in stats.values():
        weights += np.array(counts, float)
    used = weights > 0
    colours = pal.oklab_to_rgb(pal.kmeans(rgb[used], weights[used] ** 0.6 + 1, 16))
    colours = np.clip(np.round(colours / 17) * 17, 0, 255)
    colours[0] = 0
    mapping = ((pal.rgb_to_oklab(rgb)[:, None] - pal.rgb_to_oklab(colours)[None]) ** 2).sum(axis=2).argmin(axis=1)
    mapping[640] = 0
    (BUILD / 'palmap.bin').write_bytes(mapping.astype(np.uint8).tobytes())
    (BUILD / 'palette.bin').write_bytes(np.array([pal.ste_word(c) for c in colours], '>u2').tobytes())
    (DOCS / 'palette.json').write_text(json.dumps(dict(rgb=colours.astype(int).tolist(), map=mapping.tolist())) + '\n')
    return colours, mapping


def sprite_counts():
    require_coverage('gunsmoke', [f'cover{s}.pkl' for s in range(1, 15)])
    counts = {}
    for path in sorted(BUILD.glob('cover*.pkl')):
        for key, n in pickle.loads(path.read_bytes())['sprites'].items():
            counts[key] = counts.get(key, 0) + n
    return counts


def build():
    sg = helper('gunsmoke_spritegen', TOOLS_1942 / 'spritegen.py')
    v = Video()
    _, mapping = palette(v)
    tiles = v.tiles.transpose(0, 2, 1)[:, ::-1]
    (BUILD / 'tile_planes.bin').write_bytes(planes(tiles, 4, '>u4').tobytes())
    sprites = v.sprites.transpose(0, 2, 1)[:, ::-1]
    (BUILD / 'spr_planes.bin').write_bytes(planes(sprites, 4, '>u2').tobytes())
    chars = v.chars.transpose(0, 2, 1)[:, ::-1]
    (BUILD / 'chr_planes.bin').write_bytes(planes(chars, 2, np.uint8).tobytes())
    (BUILD / 'chr_pens.bin').write_bytes(bytes(int(sum(1 << p for p in np.unique(c))) for c in chars))
    (BUILD / 'chr_trans.bin').write_bytes(bytes(sum(1 << p for p in range(4) if v.lookup[c * 4 + p] == 0x4f)
                                                for c in range(32)))
    (BUILD / 'reverse.bin').write_bytes(bytes(int(f'{i:08b}'[::-1], 2) for i in range(256)))
    # The sprite shapes with generated code: the most drawn first, while they fit the budget.
    counts = sprite_counts()
    shapes = []
    total = 0
    seen_routines = set()
    for (code, flip), n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        t = sprites[code][:, ::-1] if flip else sprites[code]
        mask = ((t != 0) * (1 << np.arange(15, -1, -1))).sum(-1).astype(np.uint16)
        if not mask.any():
            continue
        order = sorted(range(16), key=lambda r: (int(mask[r]) == 0, int(mask[r]), r))
        routines, streams, _ = sg.build([mask], [order])
        new = set(routines) - seen_routines
        cost = sum(2 * len(w) for w in streams) + 16 * 8 + 32 + sum(sg.size(o) for o in new)  # (streams, table, plan, new routines)
        if total + cost > SPRITE_BUDGET:
            break
        total += cost
        seen_routines |= new
        shapes.append((code, flip, mask, order))
    opaque = np.array([s[2] for s in shapes], np.uint16)
    orders = [s[3] for s in shapes]
    index = np.full(4096, 0xffff, np.uint16)
    for i, (code, flip, _, _) in enumerate(shapes):
        index[code * 2 + flip] = i
    (BUILD / 'spr_shape.bin').write_bytes(index.astype('>u2').tobytes())
    (BUILD / 'spr_order.bin').write_bytes(bytes(r for order in orders for r in order))
    result = sg.write(str(BUILD), opaque, orders)
    drawn = sum(counts.get((c, f), 0) for c, f, _, _ in shapes)
    print(f'sprites: {len(shapes)} of {len(counts)} shapes generated ({100 * drawn / sum(counts.values()):.1f}% of the draws); '
          'routines/bytes, streams/bytes, checked pairs, plan bytes:', result, flush=True)
    # Tile end masks and control per pixel shift (32 pixel tiles: 2 destination words, 3 when shifted).
    lines = ['tile_shift:']
    for shift in range(16):
        lines.append('\tdc.w $%04x,$%04x,$%04x,%d,%d' % (
            0xffff >> shift, (0xffff << (16 - shift)) & 0xffff if shift else 0xffff,
            0xc000 | shift | (0x40 if shift else 0), 3 if shift else 2, 256 - (16 if shift else 8)))

    # Baking: the 16 (4) pen masks of a row are longs at (a4) (pen * 4); a routine per colour bank ORs them into the
    # four STE planes d0-d3 by the palette map (and the opaque pixels of a character colour into d4).
    def acc(name, pens, opaque=False):
        out = [name + ':'] + ['\tmoveq #0,d%d' % q for q in range(5 if opaque else 4)]
        for q in range(4):
            out += ['\tor.l %d(a4),d%d' % (pen * 4, q) for pen, colour in pens if colour >> q & 1]
        if opaque:
            out += ['\tor.l %d(a4),d4' % (pen * 4) for pen, _ in pens]
        return out + ['\trts']
    lines += ['acc_tile_tab:', '\tdc.l ' + ','.join(f'acc_t{b}' for b in range(16))]
    lines += ['acc_spr_tab:', '\tdc.l ' + ','.join(f'acc_s{b}' for b in range(16))]
    lines += ['acc_chr_tab:', '\tdc.l ' + ','.join(f'acc_c{c}' for c in range(32))]
    for b in range(16):
        lines += acc(f'acc_t{b}', [(p, int(mapping[128 + b * 16 + p])) for p in range(16)])
        lines += acc(f'acc_s{b}', [(p, int(mapping[384 + b * 16 + p])) for p in range(1, 16)])
    for c in range(32):
        lines += acc(f'acc_c{c}', [(p, int(mapping[c * 4 + p])) for p in range(4) if v.lookup[c * 4 + p] != 0x4f], True)
    (BUILD / 'render_tables.s').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    build()
