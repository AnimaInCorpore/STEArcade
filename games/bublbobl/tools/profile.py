"""Where the 68000's cycles go: the translated game (BUBBLE.PRG built with --sim) on Musashi, with the real VBL
schedule (50 Hz, 160256 cycles), scripted coin / start / play inputs, and the PC sampled every `chunk` cycles.

    python profile.py [frames] [--chunk 64] [--top 25] [--window A:B ...]

Per window of frames it prints, as cycles per VBL (a VBL is 160256) and percent of the CPU:
  * the game  : translated code of the main CPU (Z / Lx / BK labels), the sub CPU (Y / Ly) and the MCU (M),
  * the renderer: render_frame and what it calls (render.s),
  * the runtime: the VBL glue, the hardware stand-ins (bublbobl.s, rtlib.s),
  * idle      : the foreground wait loop (nothing to do),
and the hottest routines.  The sim build stops at `sim_frame_done` once per frame for the test harness; here that
stop is stepped over like logic_test.py does, so the schedule is the real one (the render nests into the next VBL).
Attribution is by the nearest global symbol of the linker map at or below the sampled PC, so a routine without a
label of its own is charged to the one before it.
"""
import argparse, collections, os, re, sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from sim import Sim, FRAME_CYCLES, TRAP1
from paths import ROOT, build_dir
import bisect

RUN = ROOT / "run" / "bublbobl_sim"
MAP = build_dir("bublbobl") / "bublbobl_sim.map"
SRC = ROOT / "games" / "bublbobl" / "src"


def inputs(f):
    """same script as logic_test.py: coin at 400, start at 440, then some movement and shooting"""
    in0 = 0x03 | (0x04 if 400 <= f < 406 else 0)
    in1 = 0xFF
    if 440 <= f < 446:
        in1 &= ~0x40
    if f > 560:
        in1 &= ~(0x02 if (f // 50) % 2 else 0x01)
        if f % 30 < 3:
            in1 &= ~0x20
        if f % 90 < 3:
            in1 &= ~0x10
    return in0, in1, 0xFF


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames", nargs="?", type=int, default=900)
    ap.add_argument("--chunk", type=int, default=64)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--window", nargs="*", default=["100:400", "600:900"], help="frame windows A:B to report")
    ap.add_argument("--hist", default="", help="comma list of routines: distribution of their cycles per VBL in each window")
    ap.add_argument("--prg", default=str(RUN / "BUBBLE.PRG"))
    ap.add_argument("--zpages", action="store_true", help="the translated code by 256-byte page of its Z80 / 6801 address")
    a = ap.parse_args()

    s = Sim(a.prg, run_dir=RUN)
    s.mem.set_trace_mode(False)
    sym = {k: v + s.base for k, v in s.symbols(MAP).items()}
    addrs = sorted((v, k) for k, v in sym.items())
    keys = [v for v, _ in addrs]
    render_names = set(re.findall(r"^([A-Za-z_]\w*):", open(SRC / "render.s", encoding="utf-8").read() + open(SRC / "srender.s", encoding="utf-8").read(), re.M))

    def src(pc):
        i = bisect.bisect_right(keys, pc) - 1
        return addrs[i][1] if i >= 0 else "?"

    def bucket(pc):
        n = src(pc)
        if n in render_names:
            return "renderer"
        if re.fullmatch(r"(Z|Lx|BK|BKT)[0-9A-Fa-f]+", n):
            return "game: main Z80 (translated)"
        if re.fullmatch(r"(Y|Ly)[0-9A-Fa-f]+", n):
            return "game: sub Z80 (translated)"
        if re.fullmatch(r"M[0-9A-Fa-f]+", n):
            return "game: MCU 6801 (translated)"
        if n.startswith("sim_frame_done"):
            return "idle / harness"
        return "runtime"

    frame_done = sym["sim_frame_done"]
    in0_a, in1_a, in2_a = sym["in0_val"], sym["in1_val"], sym["in2_val"]
    rn_addr = sym["sim_renders"]
    gf_addr = sym["sim_game_frames"]             # +1 per round of the game's interrupts (the sim build counts them)
    wins = []
    for w in a.window:
        lo, hi = (int(x) for x in w.split(":"))
        wins.append((lo, hi))

    cpu, mem = s.cpu, s.mem
    per_frame = []                                  # (bucket counter, routine counter, game frames) per VBL
    rf_stats = []                                   # (dirty cells, whole redraws, palette changes) so far, per VBL
    hb_last = 0
    gframes = 0
    rn_last = 0
    renders = 0
    cur_b, cur_r = collections.Counter(), collections.Counter()
    next_vbl = FRAME_CYCLES
    total = 0
    f = 0
    s.frames = 0
    while f < a.frames and not s.terminated:
        mem.w8(in0_a, inputs(f)[0]); mem.w8(in1_a, inputs(f)[1]); mem.w8(in2_a, inputs(f)[2])
        r = cpu.execute(a.chunk)
        c = r.cycles
        total += c
        pc = cpu.r_pc()
        if pc == frame_done:                        # step over the harness stop
            sp = cpu.r_reg(15)
            cpu.w_pc(mem.r32(sp)); cpu.w_reg(15, sp + 4)
        elif pc == TRAP1:
            s.gemdos()
        elif pc == 0x600:
            print("exception/halt at 0x600"); break
        cur_b[bucket(pc)] += c
        n = src(pc)
        if a.zpages:
            m = re.fullmatch(r"(Z|Lx|BK|BKT|Y|Ly|M)([0-9A-Fa-f]+)", n)
            if m:
                n = "%s %s00" % ({"Lx": "Z", "BK": "Z", "BKT": "Z", "Ly": "Y"}.get(m.group(1), m.group(1)), m.group(2)[:-2].upper().rjust(2, "0"))
        cur_r[n] += c
        gf_now = mem.r32(gf_addr)
        gframes += gf_now - hb_last
        hb_last = gf_now
        rn_now = mem.r32(rn_addr)
        renders += rn_now - rn_last
        rn_last = rn_now
        if total >= next_vbl:
            if s.irq(4, 28):
                next_vbl += FRAME_CYCLES
                per_frame.append((cur_b, cur_r, gframes, renders))
                if "sim_rf_cells" in sym:
                    rf_stats.append((mem.r32(sym["sim_rf_cells"]), mem.r32(sym["sim_rf_whole"]), mem.r32(sym["sim_rf_all"])))
                gframes = 0
                renders = 0
                cur_b, cur_r = collections.Counter(), collections.Counter()
                f += 1
                s.frames = f
                if f % 100 == 0:
                    print("frame %d" % f, flush=True)
    print()
    if "sim_sr_frames" in sym:
        print("sprite renderer (srender.s): %d of %d renders, column maps built %d times, refused %d"
              % (mem.r32(sym["sim_sr_frames"]), mem.r32(rn_addr), mem.r32(sym["sim_sr_maps"]), mem.r32(sym["sim_sr_cannot"])))
    for lo, hi in wins:
        sel = per_frame[lo:hi]
        if not sel:
            continue
        B, R = collections.Counter(), collections.Counter()
        for b, r, g, rn in sel:
            B.update(b); R.update(r)
        n = len(sel)
        gf = sum(x[2] for x in sel)
        rnd = sum(x[3] for x in sel)
        busy = sum(v for k, v in B.items() if k != "idle / harness")
        if rf_stats and hi <= len(rf_stats):
            c0 = rf_stats[lo - 1] if lo else (0, 0, 0)
            c1 = rf_stats[hi - 1]
            rn = max(1, sum(x[3] for x in sel))
            print("   renders: %d dirty cells each (mean), %d drawn whole, %d with a new palette" % ((c1[0] - c0[0]) // rn, c1[1] - c0[1], c1[2] - c0[2]))
        print("frames %d-%d (%d VBLs): busy %.0f%% of the CPU (%d cycles per VBL of %d)" % (lo, hi, n, 100.0 * busy / (n * FRAME_CYCLES), busy // n, FRAME_CYCLES))
        print("   game frames run per VBL: %.2f  (1.00 = the port's full speed, i.e. 50 of the arcade's 59.19 frames/s); pictures drawn: %.1f per second (%d renders in %d VBLs)" % (gf / n, 50.0 * rnd / n, rnd, n))
        for k, v in B.most_common():
            print("   %-18s %8d cycles/VBL  %5.1f%%" % (k, v // n, 100.0 * v / (n * FRAME_CYCLES)))
        if a.hist:
            names = a.hist.split(",")
            vals = sorted(sum(r[nm] for nm in names) for _, r, _, _ in sel)
            edges = [0, 1, 5000, 20000, 60000, 150000, 10**9]
            labels = ["none", "<5k", "<20k", "<60k", "<150k", ">=150k"]
            cnt = [sum(1 for v in vals if lo <= v < hi) for lo, hi in zip(edges, edges[1:])]
            print("   %s per VBL: %s   (median %d, max %d)" % ("+".join(names), "  ".join("%s:%d" % (l, c) for l, c in zip(labels, cnt)), vals[len(vals) // 2], vals[-1]))
        print("   hottest routines (cycles per VBL):")
        for k, v in R.most_common(a.top):
            print("      %-28s %8d  %5.1f%%" % (k, v // n, 100.0 * v / (n * FRAME_CYCLES)))
        print()


if __name__ == "__main__":
    main()
