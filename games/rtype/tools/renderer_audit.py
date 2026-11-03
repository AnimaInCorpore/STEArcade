"""Measure restoration overlap and secondary-layer CPU costs on recorded pictures.

    venv/bin/python games/rtype/tools/renderer_audit.py build/rtype/stage_states_3.pkl \
        --start 1200 --frames 600 --profile-every 50 --out build/rtype/renderer_audit.json

Indices are offsets in the recording, as in stage_test.py. Warm-up pictures are
executed and compared but excluded from the statistics. The union is an ideal
transfer-only upper bound: its construction and extra pass setup are not free.
"""
import argparse
import bisect
import collections
import json
import pickle
import struct
import zlib
from pathlib import Path

import numpy as np

import stage_test
from stage_test import Expected, Harness
from machine68k import Register as R


class LayerCacheAudit:
    def __init__(self):
        self.keys = {}
        self.last = {}

    def picture(self, h):
        prefix = "fg" if h.mem.r8(h.sym["st_bgon"]) else "bg"
        # Use the actual number of rows emitted rather than decoding the scene.
        emitted = (h.r32("st_drlp") - h.sym["st_drl"]) // 6
        result = dict(layer_rows=0, partial_pieces=0, shift_cache_hits=0,
                      shift_cache_misses=0, partial_cache_hits=0, partial_cache_misses=0,
                      partial_last_shift_hits=0)
        flags = h.mem.r16(h.r32("st_scn") + 80 + 12288)  # stage.s SC_FLAGS
        if (prefix == "bg" and not flags & 8) or not 0 < emitted <= 40:
            return result
        shift = (h.r16("st_W") - h.r16("st_" + prefix + "x")) & 15
        first = h.r16("st_" + prefix + "y") >> 3
        k0 = h.r16("st_" + prefix + "k0")
        for row in [(first + j) & 63 for j in range(33)]:
            a = h.sym["st_" + prefix + "pcs"] + 2048 * row
            if h.mem.r16(a) == 65535:
                continue
            chunks = []
            partial = 0
            for off, size in ((4, 6), (534, 4), (1240, 4)):
                count = h.mem.r16(a + off)
                if off != 1240:
                    partial += count
                chunks.append(bytes(h.mem.r_block(a + off, 2 + size * count)))
            key = (k0, zlib.crc32(b"".join(chunks)))
            slot = (prefix, row)
            old, shifts = self.keys.get(slot, (None, set()))
            if key != old:
                shifts = set()
            hit = shift in shifts
            shifts.add(shift)
            self.keys[slot] = (key, shifts)
            if self.last.get(slot) == (key, shift):
                result["partial_last_shift_hits"] += partial
            self.last[slot] = (key, shift)
            result["layer_rows"] += 1
            result["partial_pieces"] += partial
            result["shift_cache_hits" if hit else "shift_cache_misses"] += 1
            result["partial_cache_hits" if hit else "partial_cache_misses"] += partial
        return result


class DrawingAudit:
    """Observe nonzero end masks; do not change emulated drawing or its cycles."""
    def __init__(self, h):
        self.h = h
        self.touched = set()
        labels = sorted((v, k) for k, v in h.sym.items() if k.startswith(("st_", "stc_", "m72r_")))
        self.addresses = [v for v, _ in labels]
        self.labels = [k for _, k in labels]
        self.original = h.s.blitter.run
        h.s.blitter.run = self.run

    def run(self):
        h, b = self.h, self.h.s.blitter
        i = bisect.bisect_right(self.addresses, h.cpu.r_pc()) - 1
        label = self.labels[i] if i >= 0 else ""
        if label.startswith("stc_") or label in ("st_fgdraw", "st_bgdraw", "st_wallfix"):
            xc, yc = b.reg16(0xA36), b.reg16(0xA38)
            dx, dy = b.s16(b.reg16(0xA2E)), b.s16(b.reg16(0xA30))
            dst = b.reg32(0xA32) & 0xFFFFFE
            base = h.r32("st_dbuf")
            masks = [b.reg16(0xA28)] if xc == 1 else [b.reg16(0xA28)] + [b.reg16(0xA2A)] * (xc - 2) + [b.reg16(0xA2C)]
            for _ in range(yc):
                for j, mask in enumerate(masks):
                    if mask:
                        self.touched.add((dst - base) // 8)
                    dst += dy if j == xc - 1 else dx
        self.original()


def profile_frame(h):
    labels = sorted((v, k) for k, v in h.sym.items()
                    if k.startswith(("st_", "m72r_", "stc_")))
    addresses = [v for v, _ in labels]
    cpu, mem = h.cpu, h.mem
    sp = cpu.r_reg(R.A7) - 4
    mem.w32(sp, h.sym["h_wait"])
    cpu.w_reg(R.A7, sp)
    cpu.w_pc(h.sym["m72r_frame"])
    costs = collections.Counter()
    total_cpu = total_blit = 0
    while cpu.r_pc() != h.sym["h_wait"]:
        pc = cpu.r_pc()
        i = bisect.bisect_right(addresses, pc) - 1
        h.s.blitter.cycles = 0
        c = cpu.execute(1).cycles
        b = h.s.blitter.cycles
        costs[labels[i][1] if i >= 0 else "other"] += c + b
        total_cpu += c
        total_blit += b
    h.call("m72r_vbl")
    h.call("m72r_vbl")
    return (total_cpu, total_blit), costs


def damage(h, drawing):
    buffer = h.r16("st_draw")
    n = h.r16("st_dmgn", 2 * buffer)
    a = h.sym["st_dmg"] + buffer * 600 * 8
    rects = [struct.unpack(">IBBH", bytes(h.mem.r_block(a + 8 * i, 8))) for i in range(n)]
    coverage = np.zeros(1280 * 64 + 128, bool)
    copied = cleared = 0
    for offset, words, lines, clear in rects:
        y, x = divmod(offset, 512)
        assert x % 8 == 0 and words % 4 == 0, (offset, words)
        x //= 8
        groups = words // 4
        assert y + lines <= 1280, (y, x, groups, lines)
        if clear:
            cleared += groups * lines
        else:
            copied += groups * lines
            # A sprite over the physical left edge may start in the preceding
            # line's margin. Follow actual addresses, including such row wraps.
            for line in range(lines):
                a = (y + line) * 64 + x
                coverage[a:a + groups] = True
    union = int(coverage.sum())
    touched = np.array([i for i in drawing.touched if 0 <= i < len(coverage)], dtype=np.int32)
    sparse = int(coverage[touched].sum())
    return dict(rectangles=n, copy_groups=copied, clear_groups=cleared,
                union_copy_groups=union, duplicate_copy_groups=copied - union,
                touched_copy_groups=sparse, untouched_copy_groups=union - sparse)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("states", type=Path)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--frames", type=int, default=600)
    ap.add_argument("--warmup", type=int, default=30, help="pictures excluded from statistics")
    ap.add_argument("--every", type=int, default=2)
    ap.add_argument("--profile-every", type=int, default=0)
    ap.add_argument("--source", type=Path, help="isolated experimental stage.s (default: production source)")
    ap.add_argument("--fixed-buffers", action="store_true",
                    help="place simulator buffers at $D00000 to control 64 KB crossings across builds")
    ap.add_argument("-D", dest="defines", action="append", default=[])
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    if args.every < 1 or args.frames < 1 or args.start < 0 or args.warmup < 0 or args.profile_every < 0:
        ap.error("frame counts/stride must be positive; start, warmup and profile interval nonnegative")
    if args.source:
        if args.source.name != "stage.s" or not args.source.is_file():
            ap.error("--source must name an existing stage.s")
        stage_test.src_dir = lambda game: args.source.resolve().parent
    states = pickle.loads(args.states.read_bytes())
    count = len(range(args.start, min(len(states), args.start + args.frames), args.every))
    if count <= args.warmup:
        ap.error("the selected recording window must contain more pictures than --warmup")
    h, expected, cache = Harness(args.defines), Expected(), LayerCacheAudit()
    h.call("m72r_init")
    if args.fixed_buffers:
        # Private simulator RAM only. Keep every variant at the same addresses;
        # this is not a hardware memory layout or a claim about the load budget.
        base, size = 0xD00000, 1280 * 512
        assert h.sym["v30_image"] + 0xE0000 < base
        for n in range(4):
            h.mem.w32(h.sym["st_bufs"] + 4 * n, base + n * size)
        h.mem.w32(h.sym["st_bar"], base + 4 * size)
    drawing = DrawingAudit(h)
    rows, prof, samples = [], collections.Counter(), 0
    for j, i in enumerate(range(args.start, min(len(states), args.start + args.frames), args.every)):
        frame, packed = states[i]
        state = pickle.loads(zlib.decompress(packed))
        h.put_state(state)
        drawing.touched.clear()
        if args.profile_every and j >= args.warmup and (j - args.warmup) % args.profile_every == 0:
            result, costs = profile_frame(h)
            prof.update(costs)
            samples += 1
        else:
            result = h.frame()
        want = expected(state)
        if result is None:
            raise RuntimeError("no free buffer at %d" % frame)
        got, _ = h.screen()
        if all(b[4] for b in state["bands"]):
            shown = h.r16("m72r_shown")
            assert not any(h.r16(name, 32 * shown + 2 * k)
                           for name in ("m72r_disp_pal", "m72r_disp_hpal") for k in range(16))
        elif np.any(got != want):
            raise RuntimeError("%d differing pixels at %d" % (int((got != want).sum()), frame))
        layer = cache.picture(h)
        if j >= args.warmup:
            rows.append(dict(frame=frame, cpu=result[0], blitter=result[1],
                             bgscroll=bool(h.mem.r8(h.sym["st_bgon"])), **damage(h, drawing), **layer))
        if j and j % 100 == 0:
            print("%s: %d pictures checked" % (args.states.name, j), flush=True)
    totals = np.array([r["cpu"] + r["blitter"] for r in rows])
    means = {k: float(np.mean([r[k] for r in rows])) for k in rows[0] if k != "frame"}
    summary = dict(recording=str(args.states), start=args.start, frames=args.frames,
                   defines=args.defines, source=str(args.source) if args.source else None,
                   fixed_buffers=args.fixed_buffers,
                   measured_pictures=len(rows), checked_pictures=j + 1,
                   mean_total=float(totals.mean()), median_total=float(np.median(totals)),
                   p90_total=float(np.percentile(totals, 90)), means=means,
                   profile_samples=samples,
                   profile={k: v / max(1, samples) for k, v in prof.most_common()})
    print(json.dumps(summary, indent=2), flush=True)
    if args.out:
        args.out.write_text(json.dumps(dict(summary=summary, pictures=rows), indent=2) + "\n")


if __name__ == "__main__":
    main()
