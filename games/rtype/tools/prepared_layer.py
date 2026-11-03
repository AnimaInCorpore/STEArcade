"""Build an isolated native prepared-layer prototype; production stage.s is unchanged.

The source-packing/code cache follows the existing window-relative row lists. This
small experiment does not yet implement fixed map chunks or a content-addressed
cache. Preparation runs as 68000 instructions, inside m72r_frame's cycle budget.

    venv/bin/python games/rtype/tools/prepared_layer.py
    venv/bin/python games/rtype/tools/renderer_audit.py build/rtype/stage_states_3.pkl \
      --source build/rtype/renderer_prepared_source/stage.s --fixed-buffers \
      --start 1200 --frames 1800 --out build/rtype/renderer_prepared_s3.json
"""
import argparse
import collections
import hashlib
import json
import pickle
import zlib
from pathlib import Path


def build_source():
    here = Path(__file__).resolve().parent
    source = (here.parent / "src/stage.s").read_text()
    begin = source.index("\tlea\tBLT_END1.w,a4", source.index("ST_LAYER\tmacro"))
    end = source.index(".pd:\t", begin)
    source = source[:begin] + r"""
	move.l a0,-(sp)
	moveq #0,d0
	ifc \1,fg
	moveq #64,d0
	endc
	move.w st_frow,d1
	and.w #63,d1
	or.w d1,d0
	move.w st_\1k0,d1
	bsr st_pr_draw
""" + source[end:]
    old = "\tbsr\tst_\\1build\n.built:"
    assert source.count(old) == 1
    source = source.replace(old, r"""
	bsr st_\1build
	; Any rebuilt row invalidates its direct-mapped prepared entry.
	movem.l d0-d2/a1,-(sp)
	moveq #0,d1
	move.w d0,d1
	and.w #31,d1
	moveq #14,d2
	lsl.l d2,d1
	lea st_pr_cache,a1
	add.l d1,a1
	clr.w (a1)
	movem.l (sp)+,d0-d2/a1
.built:""")
    source += "\n" + (here / "prepared_layer.s").read_text()
    out = here.parents[2] / "build/rtype/renderer_prepared_source/stage.s"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(source)
    print(out)
    return out


class PassAudit:
    """Check the generated program's actual transfers, without charging host inspection."""
    def __init__(self, h):
        self.h = h
        self.passes = self.longest = self.destination_crossings = self.source_crossings = 0
        self.relocated_source = None
        self.original = h.s.blitter.run
        h.s.blitter.run = self.run

    def run(self):
        h, b = self.h, self.h.s.blitter
        pc, cache = h.cpu.r_pc(), h.sym.get("st_pr_cache", -1)
        prepared = cache <= pc < cache + 32 * 16384 if cache != -1 else False
        if prepared:
            slot = cache + ((pc - cache) // 16384) * 16384
            xc, yc = b.reg16(0xA36), b.reg16(0xA38)
            assert b.sim.io[0xA3A] == 2 and b.sim.io[0xA3B] == 3
            assert b.sim.io[0xA3C] & 0xC0 == 0xC0 and yc == 4
            assert b.s16(b.reg16(0xA20)) == b.s16(b.reg16(0xA22)) == 2
            assert not b.sim.io[0xA3D] & 0x80
            reads = xc - bool(b.sim.io[0xA3D] & 0x40)
            src, dst = b.reg32(0xA24), b.reg32(0xA32)
            lower, upper = self.relocated_source or (slot + 4192, slot + 4192 + h.mem.r16(slot + 8))
            assert lower <= src < src + 2 * reads * yc <= upper
            masks = [b.reg16(0xA28)] if xc == 1 else [b.reg16(0xA28)] + [b.reg16(0xA2A)] * (xc - 2) + [b.reg16(0xA2C)]
            cycles = 4 * yc * (xc + reads + sum(m != 65535 for m in masks))
            assert cycles <= 256, (pc, xc, masks, cycles)
            self.longest = max(self.longest, cycles)
            self.passes += 1
            self.source_crossings += (src >> 16) != ((src + 2 * reads * yc - 1) >> 16)
            self.destination_crossings += (dst >> 16) != ((dst + 8 * (xc - 1) + 6) >> 16)
        self.original()

    def bounds(self):
        h = self.h
        if "st_pr_cache" not in h.sym:
            return
        for n in range(32):
            a = h.sym["st_pr_cache"] + n * 16384
            if not h.mem.r16(a):
                continue
            count, code, pixels = (h.mem.r16(a + off) for off in (4, 6, 8))
            assert count <= 176 and code <= 3072 and pixels <= 1408, (count, code, pixels)
            mask_bytes = sum(4 if h.mem.r16(a + 32 + 6 * j) == 1 else 6 for j in range(count))
            assert mask_bytes <= 704, mask_bytes
            assert h.mem.r16(a + 10) == mask_bytes
            assert 5632 + mask_bytes * (16 if mask_bytes <= 672 else 8) <= 16384


def measure(args, source):
    import numpy as np
    import stage_test
    from renderer_audit import profile_frame

    states = pickle.loads(args.states.read_bytes())
    selected = range(args.start, min(len(states), args.start + args.frames), args.every)
    if len(selected) <= args.warmup:
        raise ValueError("window must contain more pictures than the warm-up")
    reports = {}
    from paths import src_dir as production
    for variant in ("baseline", "prepared"):
        stage_test.src_dir = production if variant == "baseline" else lambda game: source.parent
        h = stage_test.Harness(["PREP_BENCH=" + str(int(variant == "prepared"))])
        assert ("st_pr_cache" in h.sym) == (variant == "prepared"), "wrong renderer selected"
        init = h.call("m72r_init")
        assert max(h.sym.values()) < 0xD00000, "harness overlaps fixed screen buffers"
        for n in range(4):
            h.mem.w32(h.sym["st_bufs"] + 4 * n, 0xD00000 + n * 655360)
        h.mem.w32(h.sym["st_bar"], 0xF80000)
        expected, observer = stage_test.Expected(), PassAudit(h)
        rows, profile = [], collections.Counter()
        for j, i in enumerate(selected):
            frame, packed = states[i]
            state = pickle.loads(zlib.decompress(packed))
            h.put_state(state)
            sampled = bool(args.profile_every and j >= args.warmup and (j - args.warmup) % args.profile_every == 0)
            if sampled:
                result, costs = profile_frame(h)
                profile.update(costs)
            else:
                result = h.frame()
            assert result is not None, (variant, frame)
            got, _ = h.screen()
            want = expected(state)
            if all(b[4] for b in state["bands"]):
                shown = h.r16("m72r_shown")
                assert not any(h.r16(name, 32 * shown + 2 * k)
                               for name in ("m72r_disp_pal", "m72r_disp_hpal") for k in range(16))
            elif np.any(got != want):
                raise RuntimeError("%s: %d differing pixels at %d" % (variant, int((got != want).sum()), frame))
            observer.bounds()
            counters = {name: h.r32("st_pr_" + name) for name in ("rows", "packs", "masks", "maskhits")} if variant == "prepared" else {}
            rows.append(dict(frame=frame, cpu=result[0], blitter=result[1],
                             bgscroll=bool(h.mem.r8(h.sym["st_bgon"])), profile=sampled, **counters))
            if j % 100 == 0:
                print("%s: %d/%d pictures exact" % (variant, j + 1, len(selected)), flush=True)
        samples = sum(r["profile"] for r in rows)
        def stats(items):
            totals = [r["cpu"] + r["blitter"] for r in items]
            return dict(pictures=len(items), mean=float(np.mean(totals)), median=float(np.median(totals)),
                        p90=float(np.percentile(totals, 90)), cpu=float(np.mean([r["cpu"] for r in items])),
                        blitter=float(np.mean([r["blitter"] for r in items])))
        reports[variant] = dict(cold_inclusive=stats(rows), warmed=stats(rows[args.warmup:]),
                                modes={str(mode): stats([r for r in rows[args.warmup:] if r["bgscroll"] == mode])
                                       for mode in (False, True) if any(r["bgscroll"] == mode for r in rows[args.warmup:])},
                                init_cycles=sum(init), counters=counters,
                                prepared_passes=observer.passes, longest_prepared_pass=observer.longest,
                                destination_crossings=observer.destination_crossings, source_crossings=observer.source_crossings,
                                profile_samples=samples, profile={k: v / samples for k, v in profile.items()} if samples else {},
                                pictures=rows)
        # Save each completed side so a later failure cannot erase its evidence.
        args.out.write_text(json.dumps(dict(recording=str(args.states), start=args.start, frames=args.frames,
                                            every=args.every, warmup=args.warmup,
                                            baseline_sha256=hashlib.sha256((production("rtype") / "stage.s").read_bytes()).hexdigest(),
                                            source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                                            reports=reports), indent=2) + "\n")
        print(variant, json.dumps({k: v for k, v in reports[variant].items() if k not in ("pictures", "profile")}, indent=2), flush=True)
    stage_test.src_dir = production
    assert [(r["frame"], r["bgscroll"]) for r in reports["baseline"]["pictures"]] == [
        (r["frame"], r["bgscroll"]) for r in reports["prepared"]["pictures"]], "different rendered workload"
    before, after = (reports[v]["warmed"]["mean"] for v in ("baseline", "prepared"))
    print("Prepared mean change: %+.2f%%" % (100 * (after / before - 1)), flush=True)


def focused(source):
    """Independent pixel-word oracle, including partial masks and the seven-word split."""
    import random
    import struct
    import stage_test
    from stage_test import R

    stage_test.src_dir = lambda game: source.parent
    h = stage_test.Harness(["PREP_FOCUSED=1"])
    h.call("m72r_init")
    audit, rng = PassAudit(h), random.Random(7291)
    image, pieces = h.sym["st_bgimg"], h.sym["st_bgpcs"]
    # (screen row, chunk, width in words, opaque source bits, piece-list class)
    shapes = [(0, 0, 2, 0xA55A3CC3, 2), (0, 5, 1, 0x00F0, 1), (0, 8, 7, (1 << 112) - 1, 0),
              (1, 0, 6, (1 << 96) - 1, 0), (1, 9, 1, 0x8001, 1), (1, 14, 2, 0x0123FEDC, 2),
              (2, 0, 1, 0xFFFF, 1), (3, 10, 2, 0xFFFFFFFF, 0), (4, 1, 1, 1, 1),
              (5, 2, 2, 0x0FFE0FF0, 2), (6, 0, 3, (1 << 48) - 1, 0), (7, 20, 1, 0xFFFF, 0)]
    raw = bytes(rng.randrange(256) for _ in range(4096))
    h.mem.w_block(image, raw)
    h.mem.w_block(pieces, bytes(2048))
    for kind, base in ((2, 4), (1, 534), (0, 1240)):
        group = [p for p in shapes if p[4] == kind]
        data = bytearray(struct.pack(">H", len(group)))
        for y, x, width, mask, _ in group:
            offset = y * 512 + x * 8
            data += struct.pack(">HI", offset, mask) if kind == 2 else struct.pack(">HH", offset, mask) if kind == 1 else struct.pack(">HH", 2 * width, offset)
        h.mem.w_block(pieces + base, bytes(data))
    cases = 0
    # Physical row wraps, visible/guard positions and a destination word pair across 64 KB.
    for dest in (0xD08000, 0xD0FFF8, 0xD001F8, 0xD00000 + 57 * 512 - 8,
                 0xD00000 + 319 * 512 + 504):
        for shift in list(range(16)) + [0, 15, 0]:
            initial = bytes(rng.randrange(256) for _ in range(4096 + 256))
            h.mem.w_block(dest, initial)
            want = bytearray(initial)
            # Expand source bits and opacity into destination words independently.
            for y, x, width, mask, _ in shapes:
                count = width + bool(shift)
                opaque = mask << (16 * (count - width)) >> shift
                for plane in range(4):
                    pixels = 0
                    for word in range(width):
                        pos = y * 512 + (x + word) * 8 + 2 * plane
                        pixels = (pixels << 16) | int.from_bytes(raw[pos:pos + 2], "big")
                    pixels = pixels << (16 * (count - width)) >> shift
                    for word in range(count):
                        k = 16 * (count - 1 - word)
                        m, v = (opaque >> k) & 65535, (pixels >> k) & 65535
                        pos = y * 512 + (x + word) * 8 + 2 * plane
                        old = int.from_bytes(want[pos:pos + 2], "big")
                        want[pos:pos + 2] = ((old & ~m) | (v & m)).to_bytes(2, "big")
            for n in range(1, 8):
                xc = n + bool(shift)
                h.mem.w16(h.sym["st_ptab"] + 2 * n, xc)
                h.mem.w16(h.sym["st_ptab"] + 32 + 2 * n, (2 - 8 * (xc - 1)) & 65535)
            for reg, value in ((R.A0, pieces), (R.A2, image), (R.A3, dest),
                               (R.D0, 0), (R.D1, 0), (R.D6, shift)):
                h.cpu.w_reg(reg, value)
            h.call("st_pr_draw")
            audit.bounds()
            got = bytes(h.mem.r_block(dest, len(want)))
            assert got == want, (hex(dest), shift, sum(a != b for a, b in zip(got, want)))
            cases += 1
    # Invalidate/rebuild the same key after a colour/content change, checking pixels too.
    changed = bytes(v ^ 255 for v in raw)
    h.mem.w_block(image, changed)
    h.mem.w16(h.sym["st_pr_cache"], 0)
    dest = 0xD08000
    want = bytearray(4352)
    for y, x, width, mask, _ in shapes:
        for word in range(width):
            m = (mask >> (16 * (width - 1 - word))) & 65535
            for plane in range(4):
                pos = y * 512 + (x + word) * 8 + 2 * plane
                want[pos:pos + 2] = (int.from_bytes(changed[pos:pos + 2], "big") & m).to_bytes(2, "big")
    h.mem.w_block(dest, bytes(len(want)))
    h.cpu.w_reg(R.A0, pieces)
    h.cpu.w_reg(R.A2, image)
    h.cpu.w_reg(R.A3, 0xD08000)
    h.cpu.w_reg(R.D0, 0)
    h.cpu.w_reg(R.D1, 0)
    h.cpu.w_reg(R.D6, 0)
    before = h.r32("st_pr_packs")
    h.call("st_pr_draw")
    assert h.r32("st_pr_packs") == before + 1
    assert bytes(h.mem.r_block(dest, len(want))) == want
    cases += 1
    # Execute the very same program with its packed source crossing a 64 KB boundary.
    cache = h.sym["st_pr_cache"]
    length = h.mem.r16(cache + 8)
    relocated = 0xD3FFF8
    h.mem.w_block(relocated, bytes(h.mem.r_block(cache + 4192, length)))
    audit.relocated_source = (relocated, relocated + length)
    h.mem.w_block(dest, bytes(len(want)))
    h.s.io[0xA24:0xA28] = relocated.to_bytes(4, "big")
    h.sym["focused_program"] = cache + 1120
    for reg, value in ((R.A0, cache + 5632), (R.A1, 0xFF8A28), (R.A2, h.sym["st_ptab"]),
                       (R.A3, dest), (R.A4, 0xFF8A32), (R.A5, 0xFF8A38), (R.A6, 0xFF8A3C),
                       (R.D4, 4), (R.D2, 0xC0)):
        h.cpu.w_reg(reg, value)
    h.call("focused_program")
    assert bytes(h.mem.r_block(dest, len(want))) == want
    cases += 1
    assert audit.source_crossings
    # Maximum list size: 176 different single-word masks, exercising the eight-entry
    # overflow policy and the code/source/descriptor capacity bounds.
    audit.relocated_source = None
    h.mem.w16(pieces + 4, 0)
    h.mem.w16(pieces + 1240, 0)
    masks = [(y * 512 + x * 8, rng.randrange(1, 65535)) for y in range(8) for x in range(22)]
    h.mem.w_block(pieces + 534, struct.pack(">H", len(masks)) + b"".join(struct.pack(">HH", *p) for p in masks))
    h.mem.w16(cache, 0)
    for shift in range(16):
        want = bytearray(4352)
        for offset, mask in masks:
            for plane in range(4):
                pos = offset + 2 * plane
                pixels = int.from_bytes(changed[pos:pos + 2], "big") << 16 >> shift
                opaque = mask << 16 >> shift
                for word in range(2 if shift else 1):
                    m, v = (opaque >> (16 * (1 - word))) & 65535, (pixels >> (16 * (1 - word))) & 65535
                    p = pos + 8 * word
                    old = int.from_bytes(want[p:p + 2], "big")
                    want[p:p + 2] = ((old & ~m) | (v & m)).to_bytes(2, "big")
        h.mem.w_block(dest, bytes(len(want)))
        for n in range(1, 8):
            xc = n + bool(shift)
            h.mem.w16(h.sym["st_ptab"] + 2 * n, xc)
            h.mem.w16(h.sym["st_ptab"] + 32 + 2 * n, (2 - 8 * (xc - 1)) & 65535)
        for reg, value in ((R.A0, pieces), (R.A2, image), (R.A3, dest), (R.D0, 0), (R.D1, 0), (R.D6, shift)):
            h.cpu.w_reg(reg, value)
        h.call("st_pr_draw")
        audit.bounds()
        assert h.mem.r16(cache + 10) == 704
        assert bytes(h.mem.r_block(dest, len(want))) == want, shift
        cases += 1
    print(json.dumps(dict(focused_cases=cases, longest_pass=audit.longest,
                          destination_crossings=audit.destination_crossings,
                          source_crossings=audit.source_crossings), indent=2), flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--check", action="store_true", help="focused masks/shifts/address tests")
    ap.add_argument("--states", type=Path, default=Path("build/rtype/stage_states_3.pkl"))
    ap.add_argument("--start", type=int, default=1200)
    ap.add_argument("--frames", type=int, default=1800)
    ap.add_argument("--every", type=int, default=2)
    ap.add_argument("--warmup", type=int, default=30)
    ap.add_argument("--profile-every", type=int, default=20)
    ap.add_argument("--out", type=Path, default=Path("build/rtype/renderer_prepared_comparison.json"))
    args = ap.parse_args()
    if min(args.frames, args.every) < 1 or min(args.start, args.warmup, args.profile_every) < 0:
        ap.error("invalid frame counts")
    source = build_source()
    if args.check:
        focused(source)
    if args.measure:
        measure(args, source)
