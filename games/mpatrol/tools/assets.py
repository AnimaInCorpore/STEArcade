"""Moon Patrol's graphics and colours for the STE: build/mpatrol/mp_assets.s (included by src/render.s).

    python tools/assets.py        (tools/build.py runs it when the file is missing or with --assets)

* the score panel (tile rows 0-6, opaque): its palette (the colours of docs/hud_pens.json, ref/hud_pens.py) and its
  pen map (the 512 text pens -> a panel index; a pen not seen there: the nearest colour);
* the text tiles (512 codes x 8 rows: the two plane bytes, the first plane the pixel value's high bit, bit 7 the
  leftmost pixel);
* the backgrounds (mp_bg0 mountains, mp_bg1 hills, mp_bg2 city): their 64 rows twice side by side (512 pixels: any
  window of 15 groups and the Blitter's pre-read is one stretch), ST groups of four plane words, a pixel value v as
  their pinned slot (pinned(): the mountains' in planes 0-1, the hills' and the city's in planes 0-2); pixel 0 is
  slot 0 (the mountains are drawn over the clear playfield: their 0 is the background);
* the hills' and the city's opaque masks (mp_bgm1, mp_bgm2): for each row with a transparent pixel, 16 shifts x 32
  words: the word j of shift s holds the doubled row's pixels 16 j + s .. 16 j + s + 15 (bit 15 the first); a table
  of 64 words (mp_bgr1, mp_bgr2) gives a row's block number + 1, 0 for a row without transparent pixels;
* the hills' and the city's version over the mountains' fill (mp_bg1f, mp_bg2f: transparent pixels in its slot)
  and their rows' passes (mp_bgp1 / mp_bgp2, indexed by mp_bgpi1 / mp_bgpi2: bg_pieces());
* the scenes' pinned slots (pinned(): MP_NPIN of them, mp_pincid / mp_pincol: the hills' scene, then the city's) and
  the backgrounds' fill slots (mp_bgfill: their pixel value 3's slot).
"""
from pathlib import Path
import json
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
import numpy as np
from paths import build_dir
from machine import Video

DOCS = Path(__file__).resolve().parents[1] / "docs"


def ste(rgb):
    """an 8-bit RGB colour -> the STE's palette word (4 bits a channel: the STE's extra bit is the nibble's bit 3)"""
    w = 0
    for c in rgb:
        v = (int(c) * 15 + 127) // 255
        w = w << 4 | (v >> 1) | (v & 1) << 3
    return w


def ste_rgb(w):
    """the STE's palette word -> 8-bit RGB (v * 17)"""
    out = []
    for sh in (8, 4, 0):
        n = w >> sh & 15
        out.append(((n & 7) << 1 | n >> 3) * 17)
    return tuple(out)


def hud(v):
    """(palette: 16 STE words, map: 512 text pens -> index)"""
    pens = json.loads((DOCS / "hud_pens.json").read_text())["pens"]
    cols = []
    for p in pens:
        c = tuple(int(x) for x in v.pens[p])
        if c not in cols:
            cols.append(c)
    if len(cols) > 16:
        raise RuntimeError("the score panel has %d colours" % len(cols))
    pal = [ste(c) for c in cols] + [0] * (16 - len(cols))
    arr = np.array(cols, np.int32)
    pmap = []
    for p in range(512):
        c = np.array(v.pens[p], np.int32)
        pmap.append(int(((arr - c) ** 2).sum(axis=1).argmin()))
    return pal, pmap


def tile_rows(v):
    """512 codes x 8 rows x (high plane byte, low plane byte)"""
    out = bytearray()
    for t in v.tiles:
        for row in t:
            hi = lo = 0
            for x in range(8):
                hi = hi << 1 | (int(row[x]) >> 1)
                lo = lo << 1 | (int(row[x]) & 1)
            out += bytes((hi, lo))
    return bytes(out)


def colour_ids(v):
    """(cid of each of the 780 pens, the cids' STE words): pens that look the same on the STE share a colour id, the
    unit the playfield's slots are given to"""
    words, cids = [], []
    for p in range(len(v.pens)):
        w = ste(v.pens[p])
        if w not in words:
            words.append(w)
        cids.append(words.index(w))
    if len(words) > 255:
        raise RuntimeError("%d colours" % len(words))
    return cids, words


def bg_image(img, slots, trans=0):
    """the doubled image as ST groups: 64 rows x 32 groups x 4 plane words, pixel v -> slots[v], a transparent pixel
    -> trans (0, or the mountains' fill slot: the version for the rows that lie over the mountains' fill)"""
    out = bytearray()
    for row in img[:64]:
        px = [int(p) for p in row] * 2
        for g in range(32):
            words = [0, 0, 0, 0]
            for i in range(16):
                v = px[16 * g + i]
                slot = slots[v] if v else trans
                for pl in range(4):
                    words[pl] |= (slot >> pl & 1) << (15 - i)
            for w in words:
                out += w.to_bytes(2, "big")
    return bytes(out)


def pinned(v, cids):
    """the scenes' pinned slots (0 the hills', 1 the city's): (ids of slots 0.., the slots of the backgrounds' pixel
    values 0-3: the mountains, the hills, the city).  Slot 0 is id 0 (the sprite palette's pen 0, the clear picture);
    the mountains' ids, then the scene's, each new id the next slot (an id met before, black ones too, keeps its
    slot): the slots the backgrounds bake in stay few, the rest are the text's and the sprites'."""
    from machine import SP_PENS, BG_PENS
    pins, vslots = [], {}
    for scene, img in ((0, 1), (1, 2)):
        ids = [cids[SP_PENS]]
        for i in (0, img):
            sl = [0]
            for val in (1, 2, 3):
                c = cids[BG_PENS + 4 * i + val]
                if c not in ids:
                    ids.append(c)
                sl.append(ids.index(c))
            if i in vslots and vslots[i] != sl:
                raise RuntimeError("the mountains' slots differ by scene")
            vslots[i] = sl
        pins.append(ids)
    if max(max(vslots[0]), 3) > 3 or max(max(vslots[1]), max(vslots[2])) > 7:
        raise RuntimeError("the backgrounds' planes: %s" % vslots)
    return pins, vslots


def bg_pieces(img):
    """for each row with a transparent pixel and each shift: the passes over the doubled row's 32 words (bytes: first
    word, end word; $FF ends a list): a run of opaque words, a partial word before it and one after it taken in (the
    pass's END1 and END3 are the end words' masks); -> (the lists, an index: block * 16 + shift -> the list's offset)"""
    data, index = bytearray(), []
    for row in img[:64]:
        op = [1 if int(p) else 0 for p in row]
        if all(op):
            continue
        bits = op * 3
        for sh in range(16):
            kinds = []
            for j in range(32):
                w = bits[16 * j + sh:16 * j + sh + 16]
                kinds.append("F" if all(w) else ("E" if not any(w) else "P"))
            index.append(len(data))
            i = 0
            while i < 32:
                if kinds[i] == "E":
                    i += 1
                    continue
                j = i + 1
                while j < 32 and kinds[j] == "F":
                    j += 1
                if j < 32 and kinds[j] == "P":
                    j += 1
                data += bytes((i, j))
                i = j
            data.append(0xFF)
            if len(data) & 1:
                data.append(0xFF)
    return bytes(data), index


def bg_masks(img):
    """(masks: for each row with a transparent pixel 16 shifts x 32 words, rows: 64 words, block + 1 or 0)"""
    blocks, rows = bytearray(), []
    for row in img[:64]:
        op = [1 if int(p) else 0 for p in row]
        if all(op):
            rows.append(0)
            continue
        bits = op * 3
        for sh in range(16):
            for j in range(32):
                w = 0
                for i in range(16):
                    w = w << 1 | bits[16 * j + sh + i]
                blocks += w.to_bytes(2, "big")
        rows.append(len(blocks) // (16 * 32 * 2))
    return bytes(blocks), rows


def build():
    v = Video()
    pal, pmap = hud(v)
    out = build_dir("mpatrol")
    (out / "mp_tiles.bin").write_bytes(tile_rows(v))
    from machine import SP_PENS, BG_PENS
    cids, words = colour_ids(v)
    pins, vslots = pinned(v, cids)
    for i in (0, 1, 2):
        (out / ("mp_bg%d.bin" % i)).write_bytes(bg_image(v.bgs[i], vslots[i]))
    for i in (1, 2):
        (out / ("mp_bg%df.bin" % i)).write_bytes(bg_image(v.bgs[i], vslots[i], vslots[0][3]))
        data, index = bg_pieces(v.bgs[i])
        (out / ("mp_bgp%d.bin" % i)).write_bytes(data)
        (out / ("mp_bgpi%d.bin" % i)).write_bytes(b"".join(x.to_bytes(2, "big") for x in index))
    masks = {}
    for i in (1, 2):
        blocks, rows = bg_masks(v.bgs[i])
        (out / ("mp_bgm%d.bin" % i)).write_bytes(blocks)
        masks[i] = rows
    lines = ["; generated by games/mpatrol/tools/assets.py", "\tsection data,data", "\teven",
             "mp_hudpal:\tdc.w\t" + ",".join("$%03X" % w for w in pal),
             "mp_hudmap:"]
    for i in range(0, 512, 32):
        lines.append("\tdc.b\t" + ",".join("%d" % x for x in pmap[i:i + 32]))
    lines += ["\teven", "mp_tiles:\tincbin\t\"mp_tiles.bin\"", "\teven"]
    npin = max(len(x) for x in pins)
    lines += ["MP_NPIN = %d" % npin,
              "mp_pincid:\tdc.b\t" + ",".join(str(c) for sc in pins for c in sc + [0] * (npin - len(sc))),
              "\teven",
              "mp_pincol:\tdc.w\t" + ",".join("$%03X" % words[c] for sc in pins for c in sc + [0] * (npin - len(sc))),
              "mp_bgfill:\tdc.b\t" + ",".join(str(vslots[i][3]) for i in (0, 1, 2)), "\teven"]
    near = []
    rgb = np.array([ste_rgb(w) for w in words], np.int32)
    for c in range(len(words)):
        near += [int(x) for x in np.argsort(((rgb - rgb[c]) ** 2).sum(axis=1), kind="stable")]
    used = []
    for t in v.tiles:
        vals = {int(p) for p in t.ravel()}
        used.append(sum(1 << k for k in (1, 2, 3) if k in vals))
    lines += ["MP_NCID = %d" % len(words),
              "mp_cidcol:\tdc.w\t" + ",".join("$%03X" % w for w in words),
              "mp_pencid:"]
    for i in range(0, len(cids), 32):
        lines.append("\tdc.b\t" + ",".join(map(str, cids[i:i + 32])))
    lines.append("mp_cidnear:")
    for i in range(0, len(near), 32):
        lines.append("\tdc.b\t" + ",".join(map(str, near[i:i + 32])))
    spix = bytearray()
    for code in range(128):
        for fx in (0, 1):
            for r in range(16):
                row = v.sprites[code][r][::-1] if fx else v.sprites[code][r]
                hi = lo = 0
                for x in range(16):
                    hi = hi << 1 | (int(row[x]) >> 1)
                    lo = lo << 1 | (int(row[x]) & 1)
                spix += hi.to_bytes(2, "big") + lo.to_bytes(2, "big")
    (out / "mp_spix.bin").write_bytes(bytes(spix))
    pat = []
    for c in range(16):
        lut = v.sp_lookup[c * 8:c * 8 + 4]
        pat.append(sum(1 << k for k in range(4) if lut[k] == 0))
    sused = [sum(1 << k for k in (1, 2, 3) if (v.sprites[c] == k).any()) for c in range(128)]
    lines += ["mp_sptr:\tdc.b\t" + ",".join(map(str, pat)), "mp_sused:\tdc.b\t" + ",".join(map(str, sused)),
              "\teven", "mp_spix:\tincbin\t\"mp_spix.bin\""]
    lines.append("mp_tused:")
    for i in range(0, 512, 32):
        lines.append("\tdc.b\t" + ",".join(map(str, used[i:i + 32])))
    lines.append("\teven")
    for i in (1, 2):
        lines.append("mp_bgr%d:\tdc.w\t" % i + ",".join(str(r) for r in masks[i]))
    for i in (0, 1, 2):
        lines.append("mp_bg%d:\tincbin\t\"mp_bg%d.bin\"" % (i, i))
    for i in (1, 2):
        lines.append("mp_bgm%d:\tincbin\t\"mp_bgm%d.bin\"" % (i, i))
        lines.append("mp_bg%df:\tincbin\t\"mp_bg%df.bin\"" % (i, i))
        lines.append("mp_bgp%d:\tincbin\t\"mp_bgp%d.bin\"" % (i, i))
        lines.append("mp_bgpi%d:\tincbin\t\"mp_bgpi%d.bin\"" % (i, i))
    lines += ["\teven", "\tsection text,code"]
    (out / "mp_assets.s").write_text("\n".join(lines) + "\n")
    print("assets: panel %d colours, %d tiles; masked background rows: hills %d, city %d" % (
        sum(1 for w in pal if w) + 1, len(v.tiles), sum(1 for r in masks[1] if r), sum(1 for r in masks[2] if r)))


if __name__ == "__main__":
    build()
