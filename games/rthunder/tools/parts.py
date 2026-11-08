"""The sprite parts the STE renderer finds ready (src/sprites.s part_get): made at build time for every part the reference
shows in its coverage runs, the rest is converted on first use (part_make).

    python games/rthunder/tools/parts.py collect [frames] [--seeds 1,2,3]    -> build/rthunder/parts_seen_<seed>.pkl
    python games/rthunder/tools/parts.py build                                 -> build/rthunder/ren_parts.bin, ren_pidx.bin

desc (src/sprites.s): bits 0-9 sprite code, 10-16 colour row, 17 flip x, 18 flip y, 19-20 width index (16 8 32 4), 21-22
height index, 23-24 x offset / 8, 25-26 y offset / 8, 31 set.  A part (the same layout in memory, the static ones packed):
+0 key.l, +4 rows.w, +6 groups.w, +8 c.w (source words a row and plane: 1 up to 16 pixels, else 2), +10 the rows' offset
from the part's start.w, +12 the row groups (6 bytes: rows.w, the opaque mask.l left justified), then the rows: the planes
0-3 one after the other, c words each.  ren_pidx.bin: the hash table of the static parts (8192 entries of key.l, offset.l).
"""
import argparse
import pickle
import struct
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / "ref"),
                str(Path(__file__).resolve().parents[3] / "engine")]
from paths import build_dir

SIZES = (16, 8, 32, 4)
IDX_SLOTS = 8192


def entries(sr):
    """the descs of the visible entries of a sprite RAM (what src/sprites.s spr_build keeps), in list order"""
    xoffs = sr[0x7F5] + ((sr[0x7F4] & 1) << 8)
    yoffs = sr[0x7F7]
    out = []
    for off in range(0, 0x7F0, 16):
        attr1, attr2, colb = sr[off + 10], sr[off + 14], sr[off + 12]
        xi, yi = attr1 >> 6, (attr2 & 6) >> 1
        w, h = SIZES[xi], SIZES[yi]
        cy = (((-sr[off + 15] - h - yoffs + 1 + 16) & 0xFF) - 16)
        if cy + h <= 16 or cy >= 240:
            continue
        x = (sr[off + 13] + ((colb & 1) << 8) + xoffs) & 0x1FF
        if x + w <= 51 or x >= 371:
            continue
        code = (sr[off + 11] & 127) | ((attr1 & 7) << 7)
        tx = ((attr1 & 0x18) & ~(w - 1)) >> 3
        ty = ((attr2 & 0x18) & ~(h - 1)) >> 3
        desc = (code | ((colb >> 1) << 10) | ((1 if attr1 & 0x20 else 0) << 17) | ((attr2 & 1) << 18) | (xi << 19)
                | (yi << 21) | (tx << 23) | (ty << 25) | 0x80000000)
        out.append(desc)
    return out


def make_part(desc, spr, spm):
    """the part's bytes (static form)"""
    code = desc & 1023
    color = (desc >> 10) & 127
    flipx, flipy = (desc >> 17) & 1, (desc >> 18) & 1
    w, h = SIZES[(desc >> 19) & 3], SIZES[(desc >> 21) & 3]
    tx, ty = ((desc >> 23) & 3) * 8, ((desc >> 25) & 3) * 8
    c = 1 if w <= 16 else 2
    groups = []
    rows = bytearray()
    prev = None
    for r in range(h):
        ry = h - 1 - r if flipy else r
        pens = spr[code, ty + ry, tx:tx + w]
        if flipx:
            pens = pens[::-1]
        idx = spm[color][pens]
        opq = pens != 15
        mask = 0
        planes = [0, 0, 0, 0]
        for p in range(w):
            mask = (mask << 1) | int(opq[p])
            for k in range(4):
                planes[k] = (planes[k] << 1) | ((int(idx[p]) >> k) & 1)
        sh = 32 - w
        mask <<= sh
        planes = [v << sh for v in planes]
        for v in planes:
            rows += struct.pack(">I", v) if c == 2 else struct.pack(">H", v >> 16)
        if groups and prev == mask:
            groups[-1][0] += 1
        else:
            groups.append([1, mask])
        prev = mask
    head = struct.pack(">IHHHH", desc, h, len(groups), c, 12 + 6 * len(groups))
    return head + b"".join(struct.pack(">HI", n, m) for n, m in groups) + bytes(rows)


def hash_desc(d):
    return ((d >> 18) ^ (d >> 9) ^ d) & (IDX_SLOTS - 1)


def build(out=None):
    out = out or build_dir("rthunder")
    from machine import Rthunder
    descs = set()
    for f in sorted(out.glob("parts_seen_*.pkl")):
        descs |= pickle.load(open(f, "rb"))
    m = Rthunder(cpus=False)
    _, _, spr = m.gfx()
    spm = np.frombuffer((out / "ren_spm.bin").read_bytes(), np.uint8).reshape(128, 16)
    blob = bytearray()
    table = [None] * IDX_SLOTS
    for d in sorted(descs):
        h = hash_desc(d)
        while table[h] is not None:
            h = (h + 1) & (IDX_SLOTS - 1)
        table[h] = (d, len(blob))
        blob += make_part(d, spr, spm)
        if len(blob) & 1:
            blob += b"\0"
    (out / "ren_parts.bin").write_bytes(bytes(blob))
    (out / "ren_pidx.bin").write_bytes(b"".join(struct.pack(">II", *(e or (0, 0))) for e in table))
    print("%d parts, %d bytes" % (len(descs), len(blob)))


def collect(frames, seeds):
    import cover
    from machine import RthunderRule
    for seed in seeds:
        dswa, dswb, inputs = cover.schedule(seed)
        m = RthunderRule()
        m.dsw = [dswa, dswb]
        m.boot()
        seen = set()
        for f in range(frames):
            m.in0, m.in1, m.in2 = inputs(f)
            m.run_frame_port()
            seen.update(entries(m.spriteram))
        pickle.dump(seen, open(build_dir("rthunder") / ("parts_seen_%d.pkl" % seed), "wb"))
        print("seed %d: %d parts" % (seed, len(seen)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("collect", "build"))
    ap.add_argument("frames", nargs="?", type=int, default=3000)
    ap.add_argument("--seeds", default="1,2,3,4,5")
    a = ap.parse_args()
    if a.cmd == "collect":
        collect(a.frames, [int(x) for x in a.seeds.split(",")])
    else:
        build()
