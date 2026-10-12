"""Renderer cost and picture quality on consecutive reference frames (the A/B tool for renderer changes).

The reference machine is advanced frame by frame; for each frame in the windows its video / object / palette RAM are
copied into the 68000 (BUBBLE.PRG built with --sim, Musashi) and render_frame is called, exactly like
render_test.py seq.  Per frame it records
  * cycles          what render_frame cost,
  * wrong pixels    the screen against the reference bitmap through the renderer's own colour table (must be 0),
  * colour error    the shown picture (STE palette) against the arcade's RGB picture: mean absolute error per
                    channel in 0..255 and the share of pixels that are not shown in their exact (12 bit) colour,
  * rf_all          the colour mapping changed, every cell was redrawn,
  * dirty           how many of the 28 x 32 cells of the frame were redrawn (this frame's plus what the other screen lacked).

    python render_bench.py A N [A N ...] [--json file] [--prof]   windows of N consecutive frames from frame A;
                                                                    --step K: render every K-th frame only (the frames between
                                                                              are run, their changes come with the next render)
                                                                    --prof: where render_frame's cycles go (PC sampled every 64 cycles)
                                                                    --count: how often draw_tile (aligned / shifted / off-screen or blank),
                                                                             get_tile misses (tc_bake), mark_tile, obj_slots run (single-stepped: slow)

Run it before and after a change and compare the summaries; the frames are the same, the game's pacing does not
come into it (that is what tools/profile.py is for).
"""
import json, os, sys
import numpy as np
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from sim import Sim
from machine68k import Register as R
from machine import Bublbobl
import logic_test as lt
import render_test as rt


def main():
    args = sys.argv[1:]
    out = None
    if "--json" in args:
        i = args.index("--json")
        out = args[i + 1]
        del args[i:i + 2]
    prof = "--prof" in args
    if prof:
        args.remove("--prof")
    if "--detail" in args:
        args.remove("--detail")
    step = 1
    if "--step" in args:
        i = args.index("--step")
        step = int(args[i + 1])
        del args[i:i + 2]
    count = "--count" in args
    if count:
        args.remove("--count")
        calls = {k: 0 for k in ("draw_tile", "draw aligned", "draw shifted", "tc_bake", "mark_tile", "obj_slots", "obj_masks", "get_tile")}
    nums = [int(x) for x in args]
    windows = sorted((nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2))
    if not windows:
        windows = [(100, 60), (400, 60), (620, 120)]
    s = Sim(str(lt.RUN / "BUBBLE.PRG"), run_dir=lt.RUN)
    s.mem.set_trace_mode(True)                 # Blitter register writes drive Sim.on_access
    sym = {k: v + s.base for k, v in s.symbols(lt.MAP).items()}
    s.bad = sym["z80_badpc"]
    cpu, mem = s.cpu, s.mem
    stop = sym["sim_frame_done"]
    if count:
        watch = {sym[k]: k for k in ("draw_tile", "tc_bake", "mark_tile", "obj_slots", "obj_masks", "get_tile")}
    while True:                                      # to the idle loop
        if not lt.run_to(s, stop):
            raise SystemExit("68000 stopped before the idle loop")
        b = mem.r8(sym["booted1"])
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp)); cpu.w_reg(R.A7, sp + 4)
        if b:
            break
    ref = Bublbobl()
    g_ram = sym["g_block"] + 0x8000
    f = 0
    results = []
    import bisect, collections
    import re
    reloc = {m.group(1) for m in re.finditer(r"0x[0-9a-fA-F]+ (\w+): .*?reloc,", open(lt.MAP).read())}
    addrs = sorted((v, k) for k, v in sym.items() if k in reloc)     # (absolute symbols are not code)
    keys = [v for v, _ in addrs]
    hot = collections.Counter()
    detail = collections.Counter()
    prof_detail = "--detail" in sys.argv[1:]
    d_name = os.environ.get("DETAIL", "draw_tile")          # --detail: the routine sampled by instruction
    d_lo = sym[d_name]
    d_hi = min(v for v in sym.values() if v > d_lo)
    last_vram = None
    for (a0, n) in windows:
        for target in range(a0, a0 + n, step):
            while f <= target:
                rt.inputs_upto(ref, f)
                ref.run_frame_port()
                f += 1
            vram = bytes(ref.vram)
            mem.w_block(g_ram + 0x4000, vram)
            if last_vram is None:
                mem.w8(sym["vmark_all"], 1)
            else:                                            # the pages the game's writers would have marked
                for pg in range(0, 0x1D00, 128):
                    if vram[pg:pg + 128] != last_vram[pg:pg + 128]:
                        mem.w8(sym["vmarks"] + 0x180 + pg // 128, 0xFF)
            last_vram = vram
            mem.w_block(g_ram + 0x5D00, bytes(ref.oram))
            mem.w_block(g_ram + 0x7800, bytes(ref.pal))
            ttab_before = bytes(mem.r_block(sym["ttab"], 256))
            sp = 0x3FF000
            cpu.w_reg(R.A7, sp - 4)
            mem.w32(sp - 4, stop)
            cpu.w_sr(0x2700)
            cpu.w_pc(sym["render_frame"])
            cyc = 0
            while cpu.r_pc() != stop:
                c = cpu.execute(1 if count else (64 if prof else 20000)).cycles + s.blitter.cycles
                s.blitter.cycles = 0
                cyc += c
                if count:
                    pc = cpu.r_pc()
                    k = watch.get(pc)
                    if k:
                        calls[k] += 1
                        if k == "draw_tile":
                            x = cpu.r_reg(R.D0) & 0xFFFF
                            x = x - 65536 if x > 32767 else x
                            y = cpu.r_reg(R.D1) & 0xFFFF
                            if -7 <= x <= 255 and 9 <= y <= 239:
                                calls["draw aligned" if x & 7 == 0 else "draw shifted"] += 1
                if prof and results:            # (not the first frame: a full redraw)
                    hot[addrs[bisect.bisect_right(keys, cpu.r_pc()) - 1][1]] += c
                    if prof_detail:
                        pcn = cpu.r_pc()
                        if d_lo <= pcn < d_hi:
                            detail[pcn] += c
                if cyc > 400_000_000:
                    raise SystemExit("render_frame does not return")
            scr = mem.r32(sym["draw_screen_address"])
            swap_screens = lambda: (mem.w32(sym["draw_screen_address"], mem.r32(sym["display_screen_address"])), mem.w32(sym["display_screen_address"], scr))   # the VBL swaps after a render
            got = rt.decode_screen(mem, scr, 10 + 16, 224)
            ttab = bytes(mem.r_block(sym["ttab"], 256))
            banks_changed = sum(1 for b in range(16) if ttab[b * 16:b * 16 + 15] != ttab_before[b * 16:b * 16 + 15])
            raw = ref.render_raw()
            exp = np.array([ttab[v] if v != 255 else 0 for v in raw.ravel()], np.uint8).reshape(224, 256)
            wrong = int((got != exp).sum())
            shown = rt.ste_palette(mem, sym)[got].astype(np.int32)
            want = ref.render_rgb().astype(np.int32)
            err = float(np.abs(shown - want).mean())
            inexact = float((np.abs(shown - want).sum(axis=2) > 0).mean())
            dirty = sum(bin(mem.r32(sym["dirty"] + 4 * i)).count("1") for i in range(28))
            results.append({"frame": target, "cycles": cyc, "wrong": wrong, "err": round(err, 3), "inexact": round(inexact, 4), "dirty": dirty, "banks": banks_changed,
                            "rf_all": int(mem.r8(sym["rf_all"]) != 0)})
            swap_screens()
        w = [r for r in results if a0 <= r["frame"] < a0 + n]
        if w and w[0] is results[0] and len(w) > 1:
            w = w[1:]                                # (the first frame is a full redraw)
        print("frames %d-%d: render_frame mean %7d  median %7d  max %7d cycles | wrong pixels %d | colour error %.2f/255, %.1f%% of pixels not their exact colour | colour mapping changed in %d frames | dirty cells %d of 896"
              % (a0, a0 + n - 1, sum(r["cycles"] for r in w) // len(w), sorted(r["cycles"] for r in w)[len(w) // 2], max(r["cycles"] for r in w), sum(r["wrong"] for r in w),
                 sum(r["err"] for r in w) / len(w), 100 * sum(r["inexact"] for r in w) / len(w), sum(r["rf_all"] for r in w), sum(r["dirty"] for r in w) // len(w)), flush=True)
    if "sim_sr_frames" in sym:
        print("drawn by the sprite renderer (srender.s): %d of %d frames (column maps built %d times, refused %d)"
              % (mem.r32(sym["sim_sr_frames"]) - mem.r32(sym["sim_sr_cannot"]), len(results), mem.r32(sym["sim_sr_maps"]),
                 mem.r32(sym["sim_sr_cannot"])))
    if "sim_c_chg" in sym:
        print("sr_scan paths per frame:", {k: round(mem.r32(sym["sim_c_" + k]) / len(results), 1) for k in ("chg", "til", "same", "col", "slow")})
    if "sim_c_bake" in sym:
        print("sprites drawn %.1f, baked %.1f per frame" % (mem.r32(sym["sim_c_draw"]) / len(results), mem.r32(sym["sim_c_bake"]) / len(results)))
    if count:
        print("calls per frame (%d frames): %s" % (len(results), ", ".join("%s %.0f" % (k, v / len(results)) for k, v in calls.items())))
    if prof:
        tot = sum(hot.values())
        print("where render_frame's cycles go (all windows, %d frames after the first):" % (len(results) - 1))
        for k, v in hot.most_common(22):
            print("   %-22s %10d  %5.1f%%   (%d per frame)" % (k, v, 100.0 * v / tot, v // max(1, len(results) - 1)))
    ch = [r for r in results if r["rf_all"]]
    if ch:
        print("frames with a colour mapping change: %d; banks whose mapping changed in them: %s; cycles %s"
              % (len(ch), [r["banks"] for r in ch], [r["cycles"] // 1000000 for r in ch]))
    if prof_detail:
        print("%s by instruction (cycles per frame):" % d_name)
        tot = sum(detail.values())
        rows = sorted(detail.items())
        # group consecutive instructions into 12 hottest 'regions' by a simple threshold listing
        for pcn, v in sorted(detail.items(), key=lambda kv: -kv[1])[:28]:
            print("   %06X +%-4d %9d (%4.1f%%)  %s" % (pcn, pcn - d_lo, v // len(results), 100.0 * v / tot, cpu.disassemble(pcn)[1] if hasattr(cpu, "disassemble") else ""))
    if out:
        json.dump(results, open(out, "w"))


if __name__ == "__main__":
    main()
