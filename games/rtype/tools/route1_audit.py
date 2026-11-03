"""Audit transfers that redraws could avoid; does not change rendered output.

Ceilings count actual Blitter transactions, without charging prediction, dirty
tracking or extra pass starts. Off-window copies cannot simply be discarded:
their clean-buffer updates must be deferred until that area becomes visible.
"""
import argparse
import bisect
import collections
import json
import pickle
import zlib
from pathlib import Path

import numpy as np

import stage_test
from stage_test import Harness, Expected, R


def instrument_source(window=False):
    source = (Path(__file__).resolve().parent.parent / "src/stage.s").read_text()
    for old, name in ((".l:\tcmp.w\td6,d7", "st_r1_log"),
                      (".lx:\t; the last sprites' rectangles", "st_r1_damage")):
        assert source.count(old) == 1
        source = source.replace(old, name + " = *\n" + old)
    if window:
        old = "\tcmp.l\t#ST_LOG-2,d2\n\tbhi\t.full\n"
        assert source.count(old) == 1
        source = source.replace(old, old + "\tbsr st_wi_incoming\n")
        begin = source.index("\tmoveq\t#ST_LB/64-1,d7")
        source = source[:begin] + """
	; Keep the first full refresh: untouched buffers need no incoming-strip work.
	move.l d0,-(sp)
	move.w st_draw,d0
	bset d0,st_wi_seen
	bne.s .windowfull
	move.l (sp)+,d0
	bra.s .baselinefull
.windowfull:
	move.l (sp)+,d0
	bsr st_wi_full
	rts
.baselinefull:
""" + source[begin:]
        source += "\n" + Path(__file__).with_name("route1_window.s").read_text()
    out = Path(__file__).resolve().parents[3] / ("build/rtype/route1_window_source/stage.s" if window else "build/rtype/route1_source/stage.s")
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.exists() or out.read_text() != source:
        out.write_text(source)
    return out


class Transfers:
    def __init__(self, h):
        self.h, self.enabled, self.passes = h, False, []
        self.max_window_copy = self.window_copies = 0
        labels = sorted((v, k) for k, v in h.sym.items() if k.startswith(("st_", "stc_", "m72r_")))
        self.addresses, self.labels = zip(*labels)
        self.original = h.s.blitter.run
        h.s.blitter.run = self.run

    def run(self):
        h, b = self.h, self.h.s.blitter
        pc = h.cpu.r_pc()
        label = self.labels[bisect.bisect_right(self.addresses, pc) - 1]
        category = None
        if h.sym["st_sync"] <= pc < h.sym["st_copy"]:
            category = "clear" if pc < h.sym["st_r1_log"] else "log" if pc < h.sym["st_r1_damage"] else "erase"
        elif label == "st_copy":
            category = "full_sync"
        elif label in ("st_fgdraw", "st_bgdraw"):
            category = "layer"
        elif label == "st_wallfix":
            category = "wallfix"
        elif label.startswith("stc_"):
            category = "sprites"
        if self.enabled and category:
            xc, yc = b.reg16(0xA36), b.reg16(0xA38)
            dx, dy = b.s16(b.reg16(0xA2E)), b.s16(b.reg16(0xA30))
            start = b.reg32(0xA32) - h.r32("st_dbuf")
            positions = (start + np.arange(yc)[:, None] * ((xc - 1) * dx + dy)
                         + np.arange(xc)[None, :] * dx).ravel() // 2
            masks = np.array([b.reg16(0xA28)] if xc == 1 else
                             [b.reg16(0xA28)] + [b.reg16(0xA2A)] * (xc - 2) + [b.reg16(0xA2C)], np.uint16)
            op, hop = b.sim.io[0xA3B], b.sim.io[0xA3A]
            costs = np.full(xc, 4, np.int32)  # destination writes
            if hop >= 2:
                costs += 4
                if b.sim.io[0xA3D] & 64:
                    costs[-1] -= 4
                if b.sim.io[0xA3D] & 128:
                    costs[0] += 4
            costs += 4 * ((masks != 65535) | (op not in (0, 3, 12, 15)))
            if "st_wi_full" in h.sym and category == "full_sync":
                bus = int(costs.sum()) * yc
                assert bus <= 256 and b.sim.io[0xA3C] & 0x40
                self.max_window_copy = max(self.max_window_copy, bus)
                self.window_copies += 1
            assert positions.min() >= 0 and positions.max() < 1280 * 256
            self.passes.append((category, positions, np.tile(masks, yc), np.tile(costs, yc)))
        self.original()

    def summarize(self):
        h = self.h
        future = np.zeros(1280 * 256, np.uint16)
        walls = np.zeros_like(future)
        visible = np.zeros_like(future)
        offset = h.r32("st_dorg") - h.r32("st_dbuf") + 64 * 512 + (h.r16("st_W") >> 4) * 8
        fine = h.r16("st_W") & 15
        shown = h.r16("m72r_shown")
        bottom = min(256, h.r16("m72r_disp_hud", 4 * shown + 2))
        for chunk in range(21):
            mask = sum(1 << (15 - bit) for bit in range(16) if 0 <= chunk * 16 + bit - fine < 320)
            positions = offset // 2 + np.arange(bottom)[:, None] * 256 + chunk * 4 + np.arange(4)[None, :]
            visible[positions.ravel()] = mask
        out = collections.Counter()
        for category, positions, masks, costs in reversed(self.passes):
            out[category + "_bus"] += int(costs.sum())
            out[category + "_passes"] += 1
            if category in ("clear", "log", "erase", "full_sync"):
                covered = masks & ~future[positions] == 0
                outside = masks & visible[positions] == 0
                out[category + "_overwritten_bus"] += int(costs[covered].sum())
                out[category + "_offwindow_bus"] += int(costs[outside].sum())
                out[category + "_union_bus"] += int(costs[covered | outside].sum())
                if covered.all():
                    out[category + "_overwritten_pass_bus"] += int(costs.sum())
            else:
                covered = masks & ~future[positions] == 0
                hidden_by_walls = masks & ~walls[positions] == 0
                out[category + "_overwritten_bus"] += int(costs[covered].sum())
                if covered.all():
                    out[category + "_overwritten_pass_bus"] += int(costs.sum())
                if category == "layer":
                    out["layer_hidden_by_walls_bus"] += int(costs[hidden_by_walls].sum())
                    if hidden_by_walls.all():
                        out["layer_hidden_by_walls_pass_bus"] += int(costs.sum())
                np.bitwise_or.at(future, positions, masks)
                if category == "wallfix":
                    np.bitwise_or.at(walls, positions, masks)
        return out


def profile(h):
    cpu, mem = h.cpu, h.mem
    entries = {h.sym["st_" + name]: name for name in ("palette", "vram", "bands", "compose", "sync", "sprites", "bardraw")}
    sp = cpu.r_reg(R.A7) - 4
    mem.w32(sp, h.sym["h_wait"])
    cpu.w_reg(R.A7, sp)
    cpu.w_pc(h.sym["m72r_frame"])
    phase, costs = "frame", collections.Counter()
    ctotal = btotal = 0
    while cpu.r_pc() != h.sym["h_wait"]:
        pc = cpu.r_pc()
        if pc in entries:
            phase = entries[pc]
        elif h.sym["m72r_frame"] <= pc < h.sym["m72r_vbl"]:
            phase = "frame"
        h.s.blitter.cycles = 0
        c = cpu.execute(1).cycles
        b = h.s.blitter.cycles
        costs[phase] += c + b
        ctotal += c
        btotal += b
    h.call("m72r_vbl")
    h.call("m72r_vbl")
    return (ctotal, btotal), costs


def check_window(source):
    stage_test.src_dir = lambda game: source.parent
    h = Harness(["ROUTE1_CHECK=1"])
    h.call("m72r_init")
    observe = Transfers(h)
    observe.enabled = True
    rng = np.random.default_rng(7203)
    clean = rng.integers(0, 256, (1280, 512), dtype=np.uint8)
    clean_base = 0xEE0000
    h.mem.w_block(clean_base, clean.tobytes())
    moves = [(0, 64, f) for f in range(16)] + [
        (1, 64, 0), (1, 64, 1), (31, 64, 15), (0, 64, 0),
        (8, 65, 3), (9, 70, 8), (7, 64, 0), (0, 448, 0),
        (1, 449, 15), (0, 447, 1), (31, 959, 15), (0, 448, 0)]
    cases = 0
    for buffer in range(3):
        base = 0xD00000 + buffer * 655360
        h.mem.w_block(base, bytes([0xA5]) * 655360)
        for i, (x, y, fine) in enumerate(moves):
            h.mem.w16(h.sym["st_draw"], buffer)
            h.mem.w32(h.sym["st_dbuf"], base)
            h.mem.w32(h.sym["st_dorg"], base + (y - 64) * 512)
            h.mem.w16(h.sym["st_W"], x * 16 + fine)
            h.cpu.w_reg(R.A5, clean_base)
            h.cpu.w_reg(R.A6, base)
            h.call("st_wi_full" if i == 0 else "st_wi_incoming")
            width = (20 + bool(fine)) * 8
            got = np.frombuffer(bytes(h.mem.r_block(base + y * 512, 256 * 512)), np.uint8).reshape(256, 512)
            assert np.array_equal(got[:, x * 8:x * 8 + width], clean[y:y + 256, x * 8:x * 8 + width]), (buffer, x, y, fine)
            cases += 1
    print("window geometry:", json.dumps(dict(cases=cases, max_pass=observe.max_window_copy,
                                              passes=observe.window_copies)), flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("states", type=Path)
    ap.add_argument("--start", type=int, default=1200)
    ap.add_argument("--frames", type=int, default=1800)
    ap.add_argument("--every", type=int, default=2)
    ap.add_argument("--warmup", type=int, default=30)
    ap.add_argument("--profile-every", type=int, default=20)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--window-prototype", action="store_true")
    ap.add_argument("--check-window", action="store_true")
    args = ap.parse_args()
    if min(args.frames, args.every, args.profile_every) < 1 or min(args.start, args.warmup) < 0:
        ap.error("invalid frame counts")
    source = instrument_source(args.window_prototype)
    if args.check_window:
        if not args.window_prototype:
            ap.error("--check-window requires --window-prototype")
        check_window(source)
    stage_test.src_dir = lambda game: source.parent
    states = pickle.loads(args.states.read_bytes())
    h, want = Harness(["ROUTE1=" + str(zlib.crc32(str(args.out).encode()) & 0x7FFFFFFF)]), Expected()
    h.call("m72r_init")
    for n in range(4):
        h.mem.w32(h.sym["st_bufs"] + 4 * n, 0xD00000 + n * 655360)
    h.mem.w32(h.sym["st_bar"], 0xF80000)
    observe = Transfers(h)
    rows, phase, samples = [], collections.Counter(), 0
    for j, i in enumerate(range(args.start, min(len(states), args.start + args.frames), args.every)):
        frame, packed = states[i]
        state = pickle.loads(zlib.decompress(packed))
        h.put_state(state)
        observe.enabled = j >= args.warmup
        observe.passes.clear()
        if observe.enabled and (j - args.warmup) % args.profile_every == 0:
            result, p = profile(h)
            phase.update(p)
            samples += 1
        else:
            result = h.frame()
        assert result is not None
        got, _ = h.screen()
        expected = want(state)
        if not all(b[4] for b in state["bands"]):
            assert np.array_equal(got, expected), (frame, int((got != expected).sum()))
        if observe.enabled:
            rows.append(dict(frame=frame, cpu=result[0], blitter=result[1],
                             bgscroll=bool(h.mem.r8(h.sym["st_bgon"])), **observe.summarize()))
        if j % 100 == 0:
            print("%s: %d pictures exact" % (args.states.name, j + 1), flush=True)
    keys = set().union(*(r.keys() for r in rows)) - {"frame"}
    means = {k: float(np.mean([r.get(k, 0) for r in rows])) for k in sorted(keys)}
    summary = dict(checked=j + 1, measured=len(rows), means=means,
                   phase_samples=samples, phases={k: v / samples for k, v in phase.items()},
                   max_window_copy=observe.max_window_copy, window_copies=observe.window_copies)
    args.out.write_text(json.dumps(dict(recording=str(args.states), start=args.start, every=args.every,
                                        summary=summary, pictures=rows), indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
