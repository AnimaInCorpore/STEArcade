"""The STE picture (run/mpatrol_sim: the translated logic and render.s on Musashi with its Blitter) against the
reference renderer, frame by frame, in the shown colours.

    python games/mpatrol/tools/render_test.py [frames] [--seed N] [--start F] [--every K] [--layers bg,tx,sp]
                                              [--shots DIR] [--stop]

The logic runs as in logic_test.py (the reference's port schedule, ref/cover.py's inputs and cheats); every frame
render_frame draws, and the test reads the picture the STE would show: lines 0-49 from the panel image with the
panel's colours, 50-251 from the published playfield buffer with its colours (pf_pal), screen x 32-271.  Expected:
machine.Video.render_raw with the given layers (the panel's rows always), each pen's colour as the STE shows it
(assets.ste).  Reports the differing pixels, the frames with any, and the 68000 cycles a picture (Musashi's count of
render_frame: CPU and Blitter).
"""
from pathlib import Path
import argparse
import random
import sys
import numpy as np
from PIL import Image
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / "ref"),
                str(Path(__file__).resolve().parents[3] / "engine")]
from machine68k import Register as R
from sim import Sim, TRAP1
from machine import MoonPatrolPort, Video, VISIBLE
from paths import ROOT, build_dir
import assets
import cover

BUILD = build_dir("mpatrol")
PF_TOP, X0 = 50, 32
BUF_LINES = 268                        # (render.s: the picture's 252 and 16 guard lines)


def planes_to_idx(words):
    """[..., 4] plane words -> [..., 16] indices"""
    bits = np.arange(15, -1, -1)
    out = np.zeros(words.shape[:-1] + (16,), np.uint8)
    for p in range(4):
        out |= (((words[..., p, None] >> bits) & 1) << p).astype(np.uint8)
    return out


def image(mem, addr, lines):
    raw = np.frombuffer(bytes(mem.r_block(addr, lines * 160)), ">u2").reshape(lines, 20, 4).astype(np.int64)
    return planes_to_idx(raw).reshape(lines, 320)


def palette(mem, addr):
    return np.array([assets.ste_rgb(mem.r16(addr + 2 * i)) for i in range(16)], np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames", nargs="?", type=int, default=600)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--start", type=int, default=0, help="compare from this frame on")
    ap.add_argument("--every", type=int, default=1)
    ap.add_argument("--layers", default="bg,tx,sp")
    ap.add_argument("--shots", type=Path, default=None, help="save STE | reference | differences of bad frames here")
    ap.add_argument("--stop", action="store_true", help="stop at the first difference")
    ap.add_argument("--debug", type=int, default=None, help="print the colour slots at this frame")
    ap.add_argument("--prof", action="store_true", help="sample render_frame's pc every 64 cycles: cycles by routine")
    ap.add_argument("--phases", action="store_true", help="with --prof: the cycles by render_frame's calls instead")
    ap.add_argument("--autoplay", action="store_true",
                    help="the inputs of the bench builds' AUTOPLAY script (mpatrol.s: coin, start, driving) instead of the "
                         "seed's (its DIP switches stay)")
    ap.add_argument("--buckets", type=int, default=0, help="the mean cycles a picture per this many frames")
    ap.add_argument("--within", help="with --prof: this routine's cycles by pc offset (16-byte buckets)")
    ap.add_argument("--vbl", type=float, default=1.0,
                    help="the share of pictures a VBL shows before the next one is drawn (vbl_video's buffer rotation; "
                         "less than 1: some pictures dropped, their buffer drawn again at once)")
    args = ap.parse_args()
    layers = tuple(args.layers.split(","))
    program = ROOT / "run" / "mpatrol_sim" / "MPATROL.PRG"
    s = Sim(str(program), run_dir=program.parent, ram_kib=16384)
    sym = {k: v + s.base for k, v in s.symbols(BUILD / "mpatrol_sim.map").items()}
    mem, cpu = s.mem, s.cpu
    wait, done, bad = sym["sim_wait"], sym["sim_frame_done"], sym["z80_badpc"]
    m = MoonPatrolPort(*cover.dsw(args.seed))
    m.cpu.afmask = 0xC1
    v = Video()
    ste_pens = np.array([assets.ste_rgb(assets.ste(c)) for c in v.pens], np.uint8)
    x0, x1, y0, y1 = VISIBLE

    def put_inputs():
        for i, val in enumerate((m.in0, m.in1, m.in2, m.dsw1, m.dsw2)):
            mem.w8(sym["io_in"] + i, val)

    put_inputs()
    rnd = random.Random(args.seed)
    vrnd = random.Random(args.seed + 1000)
    cyc = {"render": 0, "n": 0, "blit": 0}
    per_pic = []
    import bisect
    import collections
    import re as _re
    _map = (BUILD / "mpatrol_sim.map").read_text()
    absolute = {mm[1] for mm in _re.finditer(r"\s0x[0-9a-f]{8} (\S+?): \S+ abs", _map)}
    labels = sorted((val, k) for k, val in sym.items() if not k.startswith("Z") and k not in absolute)
    lv = [x for x, _ in labels]
    prof = collections.Counter()
    rf_lo = sym["render_frame"]

    def where():
        if args.phases:             # the routine render_frame called: its return address on the stack
            sp = cpu.r_reg(R.A7)
            key = None
            for a in range(sp, sp + 160, 2):
                ret = mem.r32(a)
                t = None
                if rf_lo < ret < rf_hi and mem.r16(ret - 4) == 0x6100:
                    t = ret - 2 + ((mem.r16(ret - 2) ^ 0x8000) - 0x8000)
                elif rf_lo < ret < rf_hi and mem.r8(ret - 2) == 0x61 and mem.r8(ret - 1):
                    t = ret + ((mem.r8(ret - 1) ^ 0x80) - 0x80)
                if t is not None:
                    i = bisect.bisect_right(lv, t) - 1
                    key = labels[i][1] if i >= 0 else "?"
            return key or "render_frame"
        i = bisect.bisect_right(lv, cpu.r_pc()) - 1
        if i >= 0 and labels[i][1] == args.within:
            return "%s+%03X" % (args.within, (cpu.r_pc() - labels[i][0]) & ~15)
        return labels[i][1] if i >= 0 else "?"

    if args.prof:                   # (a Blitter pass's cycles go to the routine that started it)
        brun = s.blitter.run

        def run_blit():
            c0 = s.blitter.cycles
            brun()
            if prof_on[0]:
                prof[where()] += s.blitter.cycles - c0
                cyc["blit"] += s.blitter.cycles - c0
        s.blitter.run = run_blit
    prof_on = [False]
    rf_hi = min(x for x in lv if x > rf_lo)

    def run_to(targets, count=None):
        total = 0
        chunk = 64 if (args.prof and count == "render") else 2000
        while total < 2_000_000_000:
            prof_on[0] = chunk == 64
            n = cpu.execute(chunk).cycles + s.blitter.cycles     # (CPU and Blitter: a HOG pass holds the CPU)
            blit_n = s.blitter.cycles
            s.blitter.cycles = 0
            total += n
            if chunk == 64:
                prof[where()] += n - blit_n
            pc = cpu.r_pc()
            if pc in targets:
                if count:
                    cyc[count] += total
                return pc
            if pc in (bad, bad + 4) or s.terminated:
                raise RuntimeError("CPU stopped at %06x, d7=%08x" % (pc - s.base, cpu.r_reg(R.D7)))
            if pc == TRAP1:
                s.gemdos()
        raise RuntimeError("CPU timeout at %06x" % (cpu.r_pc() - s.base))

    def resume():
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp))
        cpu.w_reg(R.A7, sp + 4)

    def ste_picture():
        pub = mem.r16(sym["pub_idx"]) - 1
        hud = image(mem, sym["hud_img"], PF_TOP)
        pf = image(mem, sym["pf_bufs"] + pub * BUF_LINES * 160 + PF_TOP * 160, 252 - PF_TOP)
        rgb = np.zeros((252, 240, 3), np.uint8)
        rgb[:PF_TOP] = palette(mem, sym["hud_pal"])[hud[:, X0:X0 + 240]]
        rgb[PF_TOP:] = palette(mem, sym["pf_pal"] + 32 * pub)[pf[:, X0:X0 + 240]]
        return rgb

    run_to({wait})
    m.frame = -1
    m.run_to_idle()
    m.booted = True
    m.frame = 0
    state = {}
    bad_frames, worst, checked = [], 0, 0
    over16 = []
    for f in range(args.frames):
        if args.autoplay:                   # (mpatrol.s AUTOPLAY, by the arcade frame)
            t = f % 4000
            m.in0, m.in1 = 0xFF, 0xFF
            if 700 <= t < 710:
                m.in0 &= ~0x08
            if 790 <= t < 800:
                m.in0 &= ~0x01
            if t >= 900:
                m.in1 = 0xFF if t & 0x80 else 0xFE
                if (t & 15) < 3:
                    m.in1 &= 0x7F
                if (f & 63) < 4:
                    m.in1 &= 0xDF
        else:
            m.in0, m.in1 = cover.inputs(f, rnd, state, args.seed)
        put_inputs()
        before = bytes(m.mem[0xE000:0xE800])
        cover.cheats(args.seed, f, m, state)
        after = bytes(m.mem[0xE000:0xE800])
        for i in range(0x800):
            if before[i] != after[i]:
                mem.w8(sym["g_block"] + 0x8000 + 0xE000 - 0x10000 + i, after[i])
        mem.w8(sym["vbl_pending"], 1)
        if f == args.start:                 # (the SIM counters from --start on)
            for k in [k for k in sym if k.startswith("cnt_")]:
                for i in range(32 if k == "cnt_rows" else 1):
                    mem.w32(sym[k] + 4 * i, 0)
        m.frame = f
        m.run_frame_port()
        resume()
        if run_to({done, sym["sim_render_start"]}) != done:
            resume()
            if f >= args.start:             # (the cycles and the profile from --start on)
                r0 = cyc["render"]
                run_to({done}, "render")
                cyc["n"] += 1
                per_pic.append((cyc["render"] - r0, f))
            else:
                run_to({done})
            if vrnd.random() < args.vbl:    # the VBL shows it (render.s vbl_video): the buffers rotate as on the STE
                mem.w16(sym["prev_idx"], mem.r16(sym["shown_idx"]))
                ready = mem.r8(sym["frame_ready"])
                if ready:
                    mem.w16(sym["shown_idx"], ready - 1)
                    mem.w8(sym["frame_ready"], 0)
        if args.debug == f and "lkind" in sym:
            print("lkind", "".join("." if mem.r8(sym["lkind"] + i) == 255 else str(mem.r8(sym["lkind"] + i))
                                   for i in range(202)))
            print("lovl ", "".join("%x" % (mem.r8(sym["lovl"] + i) >> 4) for i in range(202)))
        if args.debug == f:
            nc = len(assets.colour_ids(v)[1])
            cslot = [mem.r8(sym["cid_slot"] + i) for i in range(nc)]
            cref = [mem.r16(sym["cid_ref"] + 2 * i) for i in range(nc)]
            print("slot_cid", [mem.r8(sym["slot_cid"] + i) for i in range(16)])
            print("cid_slot/ref", [(i, cslot[i], cref[i]) for i in range(nc) if cslot[i] or cref[i]])
            pens = set()
            for i in range(7 * 32, 1024):
                code = m.mem[0x8000 + i] | (m.mem[0x8400 + i] & 0x80) << 1
                col = m.mem[0x8400 + i] & 0x7F
                for px in {int(p) for p in v.tiles[code].ravel()} - {0}:
                    pens.add(col * 4 + px)
            cids = assets.colour_ids(v)[0]
            print("text ids needed", sorted({cids[p] for p in pens}))
            print("pf_pal", [hex(mem.r16(sym["pf_pal"] + 32 * (mem.r16(sym["pub_idx"]) - 1) + 2 * i)) for i in range(16)])
            st = image(mem, sym["st_img"] - 0, 0) if False else None
            raw = np.frombuffer(bytes(mem.r_block(sym["st_img"], 136 * 120)), ">u2").reshape(136, 15, 4).astype(np.int64)
            got_idx = planes_to_idx(raw).reshape(136, 240)
            cnt = [mem.r16(sym["st_cnt"] + 2 * i) for i in range(136)]
            shown = 0
            for r in range(7, 24):
                for c in range(1, 31):
                    i = r * 32 + c
                    code = m.mem[0x8000 + i] | (m.mem[0x8400 + i] & 0x80) << 1
                    col = m.mem[0x8400 + i] & 0x7F
                    t = v.tiles[code]
                    exp = np.array([[0 if px == 0 else cslot[cids[col * 4 + px]] & 15 for px in row] for row in t])
                    g = got_idx[(r - 7) * 8:(r - 7) * 8 + 8, 8 * (c - 1):8 * c]
                    if (g != exp).any() and shown < 4:
                        shown += 1
                        print("cell r%d c%d code %03x col %02x: got %s want %s" % (r, c, code, col, g.tolist()[:3], exp.tolist()[:3]))
            print("st_cnt", cnt[24:112])
        if f >= args.start and (f - args.start) % args.every == 0:
            got = ste_picture()
            raw = v.render_raw(m.mem[0x8000:0x8400], m.mem[0x8400:0x8800], m.sprite_ram[:0x100], m.regs,
                               layers=layers)[y0:y1 + 1, x0:x1 + 1]
            want = ste_pens[raw]
            diff = np.any(got != want, axis=2)
            n = int(diff.sum())
            checked += 1
            if n:
                ncol = len(np.unique(want[PF_TOP:].reshape(-1, 3), axis=0))
                if ncol > 16:                   # (more than 16 colours on the playfield: a borrowed slot, known)
                    over16.append(f)
                    n = 0
            if n:
                bad_frames.append(f)
                worst = max(worst, n)
                ys = np.nonzero(diff.any(axis=1))[0]
                if len(bad_frames) <= 10:
                    print("frame %d: %d pixels differ, lines %d-%d (regs %s)" % (f, n, ys[0], ys[-1], m.regs),
                          flush=True)
                if args.shots and len(bad_frames) <= 20:
                    args.shots.mkdir(parents=True, exist_ok=True)
                    mark = want.copy()
                    mark[diff] = (255, 0, 255)
                    Image.fromarray(np.hstack((got, want, mark))).resize((720 * 2, 252 * 2), Image.NEAREST).save(
                        args.shots / ("f%d.png" % f))
                if args.stop:
                    break
        resume()
        run_to({wait})
    print("%s: %d frames checked (layers %s, seed %d), %d with differences (worst %d pixels)%s" % (
        "PASS" if not bad_frames else "FAIL", checked, ",".join(layers), args.seed, len(bad_frames), worst,
        "" if not bad_frames else ", first " + " ".join(map(str, bad_frames[:10]))) +
          ("; %d frames with more than 16 colours on the playfield differ (borrowed slots: known), first %s" % (
              len(over16), " ".join(map(str, over16[:5]))) if over16 else ""))
    if cyc["n"]:
        print("68000 cycles a picture (Musashi: render_frame with its Blitter passes): %d" % (cyc["render"] // cyc["n"]))
        if args.buckets:
            bk = {}
            for c, fr in per_pic:
                bk.setdefault(fr // args.buckets, []).append(c)
            print("  by %d frames:" % args.buckets, " ".join("%d:%dk" % (k * args.buckets, sum(v) / len(v) / 1000)
                                                          for k, v in sorted(bk.items())))
        srt = sorted(per_pic)
        print("  median %d, 90th percentile %d, max %d (frame %d)" % (
            srt[len(srt) // 2][0], srt[len(srt) * 9 // 10][0], srt[-1][0], srt[-1][1]))
    if "cnt_bake" in sym and cyc["n"]:
        print("sprites drawn %.1f, baked %.2f a picture" % (mem.r32(sym["cnt_drawn"]) / cyc["n"], mem.r32(sym["cnt_bake"]) / cyc["n"]))
    if "cnt_rows" in sym:
        rows = [mem.r32(sym["cnt_rows"] + 4 * r) for r in range(32)]
        print("text cells baked: %.1f a picture (by row: %s)" % (sum(rows) / max(1, cyc["n"]), rows[7:]))
    if "cnt_full" in sym and cyc["n"]:
        print("playfield: %d whole redraws; lines a picture: %.1f whole segments, %.1f changed (%.1f runs), %.1f ground"
              % (mem.r32(sym["cnt_full"]), *(mem.r32(sym[k]) / cyc["n"] for k in ("cnt_lw", "cnt_ld", "cnt_rd", "cnt_lg"))))
    if args.prof and cyc["n"]:
        tot = sum(prof.values())
        print("  (the Blitter: %d a picture)" % (cyc["blit"] // cyc["n"]))
        for k, n in prof.most_common(60 if args.within else 25):
            print("  %-22s %7d a picture  %5.1f%%" % (k, n // cyc["n"], 100.0 * n / tot))


if __name__ == "__main__":
    main()
