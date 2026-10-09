"""The STE graphics of 1943: palette, baked tiles of both layers, sprite pixels and Blitter routines, characters.

Screen orientation (ROT270): screen x = raw y - 16 (0..223), screen y = 255 - raw x.  Everything is baked in that
orientation.  Files in build/1943 (big-endian words):

    palette.bin     16 STE colours (docs/palette.json: the Oklab k-means over docs/palette_stats.json)
    palmap.bin      arcade colour (256) -> STE index
    back_tiles.bin  the back layer's (code, attribute) pairs: 32 lines of 2 chunks (4 plane words each), 512 bytes
    back_map.bin    [column 0..2047][row 0..7] word: the baked tile's number
    front_tiles.bin the front layer's non-blank pairs: 4 planes of 32 lines x 2 words (plane-major, 512 bytes), then the
                    runs of lines with equal opaque masks: (lines, first line, mask of the left word, of the right word)
                    words, the transparent lines left out, a 0 word ends the list
    front_map.bin   [column][row] long: the offset of the baked tile in front_tiles.bin + 1, 0 = blank
    spr_pix.bin     2048 sprites, 16 lines of 16 pens (4 bit packed, 8 bytes a line), the lines in blit order (spr_order.bin)
    spr_cmap.bin    16 colours x 16 pens -> STE index
    spr_code.s ...  the generated Blitter routines and endmask streams (games/1942/tools/spritegen.py)
    chr_pix.bin     2048 characters, 8 lines of 8 pens (2 bit packed, a word a line, pixel 0 in bits 15-14)
    chr_cmap.bin    32 colours x 4 pens -> STE index
    chr_blank.bin   per character: 1 = all pens 0 (transparent)
"""
import importlib.util
import json
import struct
import sys
import types
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[2] / 'engine')]
from video import Video
from paths import build_dir

DOCS = HERE.parent / 'docs'
TOOLS_1942 = HERE.parents[1] / '1942' / 'tools'


def helper(name, path):
    """a module of the 1942 tools, loaded without its `from machine import Gfx` reaching this game's machine.py"""
    saved = sys.modules.get('machine')
    sys.modules['machine'] = types.SimpleNamespace(Gfx=None)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if saved is None:
            del sys.modules['machine']
        else:
            sys.modules['machine'] = saved
    return mod


pal = helper('pal1942', TOOLS_1942 / 'palettes.py')
sg = helper('spritegen1942', TOOLS_1942 / 'spritegen.py')


def palette(v):
    """16 STE colours by weighted k-means in Oklab (index 0 = black: the margins and bars), and the map of the 256"""
    stats = json.loads((DOCS / 'palette_stats.json').read_text())
    counts = np.array(stats['total'], np.float64)
    weight = {}
    for e in range(256):
        if counts[e] > 0:
            c = tuple(int(x) for x in v.palette[e])
            weight[c] = weight.get(c, 0) + counts[e]
    weight.setdefault((0, 0, 0), 1)
    cols = sorted(weight)
    w = np.array([weight[c] ** 0.6 + 40.0 for c in cols])
    cent = pal.kmeans(np.array(cols, np.float64), w, 16)
    words = [pal.ste_word(tuple(pal.oklab_to_rgb(c))) for c in cent]
    words[0] = 0
    def level(nib):
        return ((nib & 7) << 1) | (nib >> 3)
    rgb = np.array([[level((x >> s) & 15) * 17 for s in (8, 4, 0)] for x in words], np.uint8)
    lab = pal.rgb_to_oklab(rgb.astype(np.float64))
    mapping = np.array([int(((lab - pal.rgb_to_oklab(v.palette[e].astype(np.float64))) ** 2).sum(1).argmin())
                        for e in range(256)], np.uint8)
    return words, rgb, mapping


def planar(pixels):
    """[lines][16 * n] STE indices -> bytes: per line n chunks of 4 plane words"""
    out = bytearray()
    for line in pixels:
        for c in range(0, len(line), 16):
            for p in range(4):
                word = 0
                for i in range(16):
                    word |= ((int(line[c + i]) >> p) & 1) << (15 - i)
                out += struct.pack('>H', word)
    return bytes(out)


def tile_screen(v, gfx, code, attr):
    """[32 lines][32 pixels] pens of a layer tile as the screen shows it (lines top down, pixels left to right)"""
    t = np.arange(32)
    wx = 31 - t                               # (raw x within the tile, line t)
    wy = np.arange(32)                        # (raw y within the tile, pixel k)
    px = 31 - wx if attr & 64 else wx
    py = 31 - wy if attr & 128 else wy
    return gfx[code % len(gfx)][py[None, :], px[:, None]]


def sprite_code(out, masks, orders):
    """spritegen's routines and streams (checked against its Blitter model), with a packed table: per (code, shift) a long
    = routine number << 20 | the stream's offset in spr_streams (0 = nothing to draw); spr_routines: the addresses."""
    import random
    routines, streams, entries = sg.build(masks, orders)
    checked = sg.check(entries, masks, orders, random.Random(1943))
    have = {(c, sh): (routines[o], streams[w]) for c, sh, o, w in entries}
    names = {name: i for i, name in enumerate(routines.values())}
    assert len(names) < 4096
    lines = ['; generated by tools/assets.py from games/1942/tools/spritegen.py: Blitter routines (shared by row structure), '
             'endmask streams per sprite code and shift', '	section data,data', '	cnop 0,2', 'spr_code_tab:']
    for c in range(len(masks)):
        row = []
        for sh in range(16):
            r, w = have.get((c, sh), (None, None))
            row.append('0' if r is None else f'({names[r]}<<20)|({w}-spr_streams)')
        lines.append('	dc.l	' + ','.join(row))
    lines.append('spr_routines:')
    for name in routines.values():
        lines.append(f'	dc.l	{name}')
    for ops, name in routines.items():
        lines.append(name + ':')
        lines += sg.text(ops)
    lines += ['	cnop 0,2', 'spr_streams:']
    for words, name in streams.items():
        lines.append(name + ':')
        for i in range(0, len(words), 8):
            lines.append('	dc.w	' + ','.join('$%04x' % x for x in words[i:i + 8]))
    lines.append('	section text,code')
    (out / 'spr_code.s').write_text('\n'.join(lines) + '\n')
    offs, data = sg.plan_bytes(masks, orders)
    (out / 'spr_plan_offsets.bin').write_bytes(offs)
    (out / 'spr_plan.bin').write_bytes(data)
    return (len(routines), sum(sg.size(o) for o in routines), len(streams), sum(2 * len(w) for w in streams), checked,
            len(data))


def build():
    v = Video('1943')
    out = build_dir('1943')
    words, rgb, mapping = palette(v)
    (out / 'palette.bin').write_bytes(struct.pack('>16H', *words))
    (out / 'palmap.bin').write_bytes(mapping.tobytes())
    (DOCS / 'palette.json').write_text(json.dumps(dict(ste=[f'{w:03x}' for w in words], rgb=rgb.tolist(),
                                                       map=mapping.tolist())) + '\n')
    tm = v.tilemap
    # back layer: every (code, attribute) of the map baked, the map as tile numbers
    back = tm[0x8000:0x10000].reshape(2048, 8, 2)
    pairs, index = {}, np.zeros((2048, 8), np.uint16)
    data = bytearray()
    for c in range(2048):
        for r in range(8):
            code, attr = int(back[c, r, 0]), int(back[c, r, 1])
            if (code, attr) not in pairs:
                pens = tile_screen(v, v.back, code, attr).astype(np.int32)
                colours = v.lookup[384 + ((attr & 60) >> 2) * 16 + pens]
                pairs[code, attr] = len(pairs)
                data += planar(mapping[colours])
            index[c, r] = pairs[code, attr]
    (out / 'back_tiles.bin').write_bytes(bytes(data))
    (out / 'back_map.bin').write_bytes(index.astype('>u2').tobytes())
    nback = len(pairs)
    # front layer: the non-blank pairs, plane-major, with their runs of equal opaque masks
    front = tm[0:0x8000].reshape(2048, 8, 2)
    pairs, offsets = {}, np.zeros((2048, 8), np.uint32)
    data = bytearray()
    for c in range(2048):
        for r in range(8):
            code, attr = int(front[c, r, 0]), int(front[c, r, 1])
            key = (code + ((attr & 1) << 8), attr)
            if key not in pairs:
                pens = tile_screen(v, v.front, key[0], attr).astype(np.int32)
                colours = v.lookup[128 + ((attr & 60) >> 2) * 16 + pens]
                opaque = colours != 15
                if not opaque.any():
                    pairs[key] = 0
                else:
                    pairs[key] = len(data) + 1
                    ste = np.where(opaque, mapping[colours], 0)
                    for p in range(4):
                        for line in ste:
                            for half in (0, 16):
                                word = sum(((int(line[half + i]) >> p) & 1) << (15 - i) for i in range(16))
                                data += struct.pack('>H', word)
                    masks = [(sum(int(opaque[t, i]) << (15 - i) for i in range(16)),
                              sum(int(opaque[t, 16 + i]) << (15 - i) for i in range(16))) for t in range(32)]
                    t = 0
                    while t < 32:
                        u = t
                        while u < 32 and masks[u] == masks[t]:
                            u += 1
                        if masks[t] != (0, 0):
                            data += struct.pack('>4H', u - t, t, *masks[t])
                        t = u
                    data += struct.pack('>H', 0)
            offsets[c, r] = pairs[key]
    (out / 'front_tiles.bin').write_bytes(bytes(data))
    (out / 'front_map.bin').write_bytes(offsets.astype('>u4').tobytes())
    nfront = sum(1 for o in pairs.values() if o)
    # sprites: screen oriented pens (pen 0 transparent), the rows in blit order, spritegen's routines and streams
    spr = np.array([v.sprites[code][:, ::-1].T for code in range(len(v.sprites))])   # [code][line t][pixel k]
    masks = np.zeros((len(spr), 16), np.uint32)
    for i in range(16):
        masks |= (spr[:, :, i] != 0).astype(np.uint32) << (15 - i)
    orders = [sorted(range(16), key=lambda row: (int(masks[c, row]) == 0, int(masks[c, row]), row)) for c in range(len(spr))]
    (out / 'spr_order.bin').write_bytes(bytes(r for order in orders for r in order))
    packed = bytearray()
    for c in range(len(spr)):
        for row in orders[c]:
            line = spr[c, row]
            packed += bytes((int(line[i]) << 4) | int(line[i + 1]) for i in range(0, 16, 2))
    (out / 'spr_pix.bin').write_bytes(bytes(packed))
    (out / 'spr_cmap.bin').write_bytes(mapping[v.lookup[640:896]].tobytes())
    result = sprite_code(out, masks, orders)
    # characters: screen oriented, 2 bit
    chars = np.array([v.chars[code][:, ::-1].T for code in range(len(v.chars))])     # [code][line][pixel]
    cp = bytearray()
    for c in range(len(chars)):
        for line in chars[c]:
            cp += struct.pack('>H', sum(int(line[i]) << (14 - 2 * i) for i in range(8)))
    (out / 'chr_pix.bin').write_bytes(bytes(cp))
    (out / 'chr_blank.bin').write_bytes(bytes(int(not chars[c].any()) for c in range(len(chars))))
    (out / 'chr_cmap.bin').write_bytes(mapping[v.lookup[:128]].tobytes())
    print(f'palette {" ".join(f"{w:03x}" for w in words)}; back tiles {nback}, front tiles {nfront} '
          f'({len(data)} bytes); sprite routines/bytes, streams/bytes, checked, plan bytes {result}')


if __name__ == '__main__':
    build()
