"""Blitter sprite drawing code for 1942, following stefastbobs2/FAST_BLITTER_SPRITES.md.

A part is 16 x 16 pixels.  Its opaque rows are blitted in the order of the baked source (rows with equal opaque masks follow each other,
so the endmasks are written once per group; fully transparent rows are left out): one Blitter call per row with Y count 4 (the four
planes), the opaque mask cut into the two destination words as the endmasks (holes included), the source walking through the baked
words by itself (X and Y increment 2, one word per plane and row; the second destination word of a shifted row has NFSR and reuses
it).  Pixel shift 0 draws one destination word per row, shifts 1-15 two.

There is one routine per row structure and per "shifted or not" (about 770 for the 500 shapes).  What differs between the 16 shifts of
a part is data: the endmasks and the control word (skew + NFSR) are read from a stream (`move (a0)+,(a2)`) that the table entry
`spr_code_tab[code * 16 + shift]` (routine, stream) points to.  This keeps the generated code at a third of the size of constants in the
routines and costs the same cycles.

Register contract (set once per frame by the caller, preserved by the routines):
    a2 = END1 ($ff8a28)   a3 = END3 ($ff8a2c)   a4 = destination address low word ($ff8a34)   a5 = Y count ($ff8a38)
    a6 = control ($ff8a3c)   d4 = +248   d5 = -264   d6 = 4   d7 = $c0
and per sprite: a0 = the stream, $ff8a24 = the baked part (source), $ff8a32 = the destination address of the first chunk of the
part's first line.  Source X and Y increment 2, destination X increment 8, END2 $ffff, HOP/OP $0203 are frame constants.
The routines add to the low word of the destination address only: the part must not reach a 64 KB boundary (`LOW_LIMIT`), the
caller draws such parts with the generic path.  After a row the Blitter has advanced the destination address to the row's start + 8
(Y increment -8 * (n - 1) + 2, Y count 4), which is what `pos` tracks.

`check` runs every routine/stream pair against a model of the Blitter (32 bit source buffer with stale bits, skew, NFSR, endmasks) over
memory full of noise: exactly the opaque pixels of the part must change, to the source through the shift, and the source must be
consumed completely.  Nothing is written unless all 8000 pass.

    python spritegen.py        # report the sizes and run the check
"""
import os
import random
import sys

sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]

STRIDE = 256
LOW_LIMIT = 0xEFE0                     # a part whose first chunk has a destination low word above this goes the generic way
NFSR = 0x40


def lines_of(opaque, order):
    """[(row, mask)] of the part's opaque rows in blit order"""
    rows = []
    for r in order:
        if int(opaque[r]) == 0:
            break
        rows.append((r, int(opaque[r])))
    return rows


def split(mask, shift):
    """the endmasks of a row: the opaque pixels in the first and in the second destination word"""
    return mask >> shift, ((mask << (16 - shift)) & 0xFFFF) if shift else 0


def program(rows, wide):
    """The routine of a row structure: wide = the shifted one (two destination words per row)."""
    ops = []
    pos = 0                             # where the Blitter's destination address stands, relative to the first chunk of row 0
    prev = None
    for i, (row, mask) in enumerate(rows):
        delta = row * STRIDE - pos
        if delta == 248:
            ops.append(("add_d4",))
        elif delta == -264:
            ops.append(("add_d5",))
        elif delta:
            ops.append(("add", delta))
        if mask != prev:
            ops.append(("end1",))
            if wide:
                ops.append(("end3",))
        if i == 0:
            ops.append(("width", 2 if wide else 1))
            ops.append(("start_w",))
        else:
            ops.append(("ycount",))
            ops.append(("start",))
        prev = mask
        pos = row * STRIDE + 8
    ops.append(("rts",))
    return tuple(ops)


def stream(rows, shift):
    """the words the routine reads: per group END1 (and END3 when shifted), the control word with the first row"""
    out = []
    prev = None
    for i, (row, mask) in enumerate(rows):
        e1, e3 = split(mask, shift)
        if mask != prev:
            out.append(e1)
            if shift:
                out.append(e3)
        if i == 0:
            out.append(0xC000 | (NFSR if shift else 0) | shift)       # BUSY + HOG, NFSR, skew
        prev = mask
    return tuple(out)


def text(ops):
    out = []
    for op in ops:
        k = op[0]
        if k == "add_d4":
            out.append("\tadd\td4,(a4)")
        elif k == "add_d5":
            out.append("\tadd\td5,(a4)")
        elif k == "add":
            out.append("\tadd\t#%d,(a4)" % op[1])
        elif k == "end1":
            out.append("\tmove\t(a0)+,(a2)")
        elif k == "end3":
            out.append("\tmove\t(a0)+,(a3)")
        elif k == "width":
            n = op[1]
            out.append("\tmove\t#%d,-4(a4)" % (2 if n == 1 else -6))      # destination Y increment
            out.append("\tmove.l\t#$%08x,2(a4)" % ((n << 16) | 4))        # X count, Y count
        elif k == "ycount":
            out.append("\tmove\td6,(a5)")
        elif k == "start":
            out.append("\tmove.b\td7,(a6)")
        elif k == "start_w":
            out.append("\tmove\t(a0)+,(a6)")
        elif k == "rts":
            out.append("\trts")
    return out


SIZE = {"add_d4": 2, "add_d5": 2, "add": 4, "end1": 2, "end3": 2, "width": 6 + 8, "ycount": 2, "start": 2, "start_w": 2, "rts": 2}


def size(ops):
    return sum(SIZE[op[0]] for op in ops)


# ---------------------------------------------------------------------------------------------------------------------------
# The check: a model of the Blitter and of the registers the routine writes.

class Model:
    def __init__(self, mem, src, dst, rng):
        self.mem = mem
        self.src = src
        self.dst = dst
        self.upper = rng.getrandbits(16)               # (the source buffer is never cleared: stale bits)
        self.lower = rng.getrandbits(16)
        self.end1 = self.end3 = rng.getrandbits(16)
        self.yinc = rng.choice((2, -6, 100))
        self.xcount = rng.choice((1, 2))
        self.ycount = 0
        self.ctrl = rng.getrandbits(8) & 0x4F

    def r16(self, a):
        return (self.mem[a] << 8) | self.mem[a + 1]

    def w16(self, a, v):
        self.mem[a] = v >> 8
        self.mem[a + 1] = v & 255

    def start(self, ctrl):
        nfsr, skew = bool(ctrl & NFSR), ctrl & 15
        assert self.xcount in (1, 2) and self.ycount == 4, (self.xcount, self.ycount)
        for _ in range(self.ycount):
            for x in range(self.xcount):
                mask = self.end1 if x == 0 else self.end3
                if not (x == self.xcount - 1 and nfsr):
                    self.lower = self.r16(self.src)
                    self.src += 2
                s = (((self.upper << 16) | self.lower) >> skew) & 0xFFFF
                d = self.r16(self.dst)
                self.w16(self.dst, (d & ~mask & 0xFFFF) | (s & mask))
                self.upper = self.lower
                self.dst += self.yinc if x == self.xcount - 1 else 8
        self.ycount = 0


def run(ops, words, model):
    """Execute the abstract instructions on the model; `words` is the stream (a0)."""
    it = iter(words)
    ctrl = model.ctrl
    for op in ops:
        k = op[0]
        if k == "add_d4":
            model.dst += 248
        elif k == "add_d5":
            model.dst -= 264
        elif k == "add":
            model.dst += op[1]
        elif k == "end1":
            model.end1 = next(it)
        elif k == "end3":
            model.end3 = next(it)
        elif k == "width":
            model.yinc = 2 if op[1] == 1 else -6
            model.xcount = op[1]
            model.ycount = 4
        elif k == "ycount":
            model.ycount = 4
        elif k == "start_w":
            ctrl = next(it) & 0xFF
            model.start(ctrl)
        elif k == "start":
            model.start(ctrl)
    assert next(it, None) is None, "stream not consumed"


def check(entries, opaque, orders, rng):
    """Every (code, shift): routine + stream against the pixels it must draw (random source words and background)."""
    done = 0
    for code, shift, ops, words in entries:
        rows = lines_of(opaque[code], orders[code])
        base = 0x40                                                   # (the part's first chunk; a gap before it)
        mem = bytearray(rng.getrandbits(8) for _ in range(16 * STRIDE + 0x80))
        before = bytes(mem)
        src = [[rng.getrandbits(16) for _ in range(4)] for _ in rows]
        smem = len(mem)
        mem += b"".join(w.to_bytes(2, "big") for r in src for w in r) + bytes(16)
        m = Model(mem, smem, base, rng)
        run(ops, words, m)
        assert m.src == smem + 8 * len(rows), ("source consumption", code, shift)
        want = bytearray(before)
        for (r, mask), planes in zip(rows, src):
            e1, e3 = split(mask, shift)
            for p in range(4):
                word = planes[p]
                for chunk, mk, val in ((0, e1, word >> shift), (1, e3, (word << (16 - shift)) & 0xFFFF if shift else 0)):
                    off = base + r * STRIDE + chunk * 8 + p * 2
                    old = (want[off] << 8) | want[off + 1]
                    new = (old & ~mk & 0xFFFF) | (val & mk)
                    want[off], want[off + 1] = new >> 8, new & 255
        assert bytes(mem[:len(before)]) == bytes(want), ("pixels", code, shift)
        done += 1
    return done


def build(opaque, orders):
    """-> (routines {ops: name}, streams {words: name}, entries [(code, shift, ops, words)] for the codes that draw something)"""
    routines, streams, entries = {}, {}, []
    for code in range(len(opaque)):
        rows = lines_of(opaque[code], orders[code])
        if not rows:
            continue
        for shift in range(16):
            ops = program(rows, shift > 0)
            words = stream(rows, shift)
            routines.setdefault(ops, "sfc%d" % len(routines))
            streams.setdefault(words, "sfs%d" % len(streams))
            entries.append((code, shift, ops, words))
    return routines, streams, entries


def emit(routines, streams, entries, ncodes):
    """the assembler source: the table (routine, stream) per code and shift, the routines, the streams"""
    have = {(c, s): (routines[o], streams[w]) for c, s, o, w in entries}
    lines = ["; generated by spritegen.py: Blitter routines (shared by row structure) and streams of endmasks per sprite code and shift",
             "\tsection data,data", "\tcnop 0,2", "spr_code_tab:"]
    for c in range(ncodes):
        for s in range(16):
            r, w = have.get((c, s), ("0", "0"))
            lines.append("\tdc.l\t%s,%s" % (r, w))
    for ops, name in routines.items():
        lines.append(name + ":")
        lines += text(ops)
    lines.append("\tcnop 0,2")
    for words, name in streams.items():
        lines.append(name + ":")
        for i in range(0, len(words), 8):
            lines.append("\tdc.w\t" + ",".join("$%04x" % w for w in words[i:i + 8]))
    lines.append("\tsection text,code")
    return "\n".join(lines) + "\n"


def plan_bytes(opaque, orders):
    """shift independent plans for the generic path (parts at a 64 KB boundary; the masks come from the stream): per code an offset, per group
    count.w and `count` row deltas (words: (row - previous row) * STRIDE, the first against row 0), a 0 word ends it"""
    import struct
    offsets, data = [], bytearray()
    for code in range(len(opaque)):
        offsets.append(len(data))
        rows = lines_of(opaque[code], orders[code])
        i, prev = 0, 0
        while i < len(rows):
            j = i
            while j < len(rows) and rows[j][1] == rows[i][1]:
                j += 1
            data += struct.pack(">H", j - i)
            for r, _m in rows[i:j]:
                data += struct.pack(">h", (r - prev) * STRIDE)
                prev = r
            i = j
        data += struct.pack(">H", 0)
    return struct.pack(">%dI" % len(offsets), *offsets), bytes(data)


def tables():
    import numpy as np
    from machine import Gfx
    from assets import sprite_screen, one_hot, sprite_orders
    g = Gfx()
    spr = np.zeros((512, 16, 16), np.uint8)
    for code in range(512):
        spr[code] = sprite_screen(g, code)
    opaque = one_hot((spr != 15).astype(np.uint8), 2)[..., 1]
    return opaque, sprite_orders(opaque)


def write(build_dir, opaque=None, orders=None, verify=True):
    if opaque is None:
        opaque, orders = tables()
    routines, streams, entries = build(opaque, orders)
    if verify:
        n = check(entries, opaque, orders, random.Random(1942))
    else:
        n = 0
    with open(os.path.join(build_dir, "spr_code.s"), "w") as f:
        f.write(emit(routines, streams, entries, len(opaque)))
    offs, data = plan_bytes(opaque, orders)
    open(os.path.join(build_dir, "spr_plan_offsets.bin"), "wb").write(offs)
    open(os.path.join(build_dir, "spr_plan.bin"), "wb").write(data)
    return len(routines), sum(size(o) for o in routines), len(streams), sum(2 * len(w) for w in streams), n, len(data)


def main():
    from paths import build_dir
    r, rb, s, sb, n, pb = write(str(build_dir("1942")))
    print("%d routines (%d bytes), %d streams (%d bytes), table %d bytes, plans %d bytes; %d routine/stream pairs passed the model check"
          % (r, rb, s, sb, 512 * 16 * 8, pb, n))


if __name__ == "__main__":
    main()
