"""What a Blitter renderer could save, projected on real frames: the mix of tile draws and of clear / copy runs of
the current renderer (BUBBLE.PRG built with --sim) over windows of consecutive reference frames, costed with the
per-case numbers that ref/blit_bench.py measures (Blitter vs CPU on Musashi, pixel-identical).

    python blit_project.py A N [A N ...]

Per window it prints the measured render_frame cycles per frame, the counts per frame of
  aligned tiles with / without transparent pixels, shifted tiles (left cell even = 1 destination word, odd = 2),
  cells cleared and cells copied, and in how many runs of whole groups (2 cells, one blit each) those cells fall,
and the cycles a Blitter version would save for: shifted tiles / clears / copies / all three.
Only draws that really use the Blitter are replaced; aligned tiles stay on the CPU (the Blitter is not faster there).
"""
import os, sys
import numpy as np
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine"),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ref")]
from sim import Sim
from machine68k import Register as R
from machine import Bublbobl
import logic_test as lt
import render_test as rt


def runs(bits_rows):
    """bits_rows: 28 ints (bit c = cell column c).  -> (cells, whole-group runs, cells in whole groups, single cells)"""
    cells = whole = single = nruns = 0
    for row in bits_rows:
        c = bin(row).count("1")
        cells += c
        g = 0
        groups = []
        for gi in range(16):
            two = (row >> (2 * gi)) & 3
            if two == 3:
                groups.append(gi)
                whole += 2
            elif two:
                single += 1
        prev = -2
        for gi in groups:
            if gi != prev + 1:
                nruns += 1
            prev = gi
    return cells, nruns, whole, single


def main():
    args = [int(x) for x in sys.argv[1:]]
    windows = sorted((args[i], args[i + 1]) for i in range(0, len(args) - 1, 2)) or [(110, 60), (400, 60), (640, 60)]
    # costs from ref/blit_bench.py (cycles per tile / per run, measured; CPU loop vs Blitter incl. setup).  Its simulator
    # must be gone before the render simulator exists: the CPU emulator keeps global state.
    import blit_bench, gc
    bn = blit_bench.Bench()
    c_sh_even = bn.tile_case(2, 3, False)
    c_sh_odd = bn.tile_case(3, 3, False)
    runs_cost = {k: (bn.run_case("clear", k), bn.run_case("copy", k)) for k in (1, 2, 4, 8)}
    del bn
    gc.collect()
    s = Sim(str(lt.RUN / "BUBBLE.PRG"), run_dir=lt.RUN)
    s.mem.set_trace_mode(False)
    sym = {k: v + s.base for k, v in s.symbols(lt.MAP).items()}
    s.bad = sym["z80_badpc"]
    cpu, mem = s.cpu, s.mem
    stop = sym["sim_frame_done"]
    while True:
        lt.run_to(s, stop)
        b = mem.r8(sym["booted1"])
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp)); cpu.w_reg(R.A7, sp + 4)
        if b:
            break
    ctr = {k: sym["sim_cnt_" + k] for k in ("arows", "orows", "leven", "lodd")}      # counted by the --sim build
    ref = Bublbobl()
    g_ram = sym["g_block"] + 0x8000
    f = 0
    for (a0, n) in windows:
        tot = dict(cycles=0, opaque=0, arow=0, lrow_even=0, lrow_odd=0, clear=0, clr_runs=0, clr_single=0, copy=0, cpy_runs=0, cpy_single=0)
        for target in range(a0, a0 + n):
            while f <= target:
                rt.inputs_upto(ref, f)
                ref.run_frame_port()
                f += 1
            mem.w_block(g_ram + 0x4000, bytes(ref.vram))
            mem.w_block(g_ram + 0x5D00, bytes(ref.oram))
            mem.w_block(g_ram + 0x7800, bytes(ref.pal))
            prev = [mem.r32(sym["dirty_prev"] + 4 * i) for i in range(28)]
            sp = 0x3FF000
            cpu.w_reg(R.A7, sp - 4)
            mem.w32(sp - 4, stop)
            cpu.w_sr(0x2700)
            cpu.w_pc(sym["render_frame"])
            cyc = 0
            c0 = {k: mem.r32(a) for k, a in ctr.items()}
            while cpu.r_pc() != stop:
                cyc += cpu.execute(20000).cycles
            cnt = {k: mem.r32(a) - c0[k] for k, a in ctr.items()}
            R_set = [mem.r32(sym["dirty"] + 4 * i) for i in range(28)]
            copy_set = [p & ~r & 0xFFFFFFFF for p, r in zip(prev, R_set)]
            swap = (mem.r32(sym["display_screen_address"]), mem.r32(sym["draw_screen_address"]))
            mem.w32(sym["draw_screen_address"], swap[0]); mem.w32(sym["display_screen_address"], swap[1])
            tot["cycles"] += cyc
            tot["opaque"] += cnt["orows"] // 8
            tot["arow"] += cnt["arows"] // 8
            tot["lrow_even"] += cnt["leven"]
            tot["lrow_odd"] += cnt["lodd"]
            c, nr, whole, single = runs(R_set)
            tot["clear"] += c; tot["clr_runs"] += nr; tot["clr_single"] += single
            c, nr, whole, single = runs(copy_set)
            tot["copy"] += c; tot["cpy_runs"] += nr; tot["cpy_single"] += single
        pf = lambda k: tot[k] / n
        print("\nframes %d-%d: render_frame %d cycles a frame" % (a0, a0 + n - 1, tot["cycles"] // n))
        print("   per frame: aligned %.0f (without transparent px %.0f), shifted %.0f (left cell even %.0f, odd %.0f), "
              "cells cleared %.0f in %.0f runs of whole groups (+ %.0f lone cells), cells copied %.0f in %.0f runs (+ %.0f lone)"
              % (pf("arow") + pf("opaque"), pf("opaque"), pf("lrow_even") + pf("lrow_odd"), pf("lrow_even"), pf("lrow_odd"),
                 pf("clear"), pf("clr_runs"), pf("clr_single"), pf("copy"), pf("cpy_runs"), pf("cpy_single")))
        # savings (cycles a frame): shifted tiles; whole-group runs of clears / copies (taken as the average run: cells / runs)
        sav_sh = pf("lrow_even") * (c_sh_even[0] - c_sh_even[1]) + pf("lrow_odd") * (c_sh_odd[0] - c_sh_odd[1])

        def run_saving(kind_idx, cells_key, runs_key, single_key):
            nr = pf(runs_key)
            if nr == 0:
                return 0.0
            k = max(1, int(round((pf(cells_key) - pf(single_key)) / 2 / nr)))
            kk = min(runs_cost, key=lambda q: abs(q - k))          # the nearest measured run length
            cpu_c, blt_c, _ = runs_cost[kk][kind_idx]
            return nr * (cpu_c - blt_c)
        sav_clr = run_saving(0, "clear", "clr_runs", "clr_single")
        sav_cpy = run_saving(1, "copy", "cpy_runs", "cpy_single")
        total = tot["cycles"] / n
        print("   Blitter would save per frame: shifted tiles %.0f (%.1f%%), clears %.0f (%.1f%%), copies %.0f (%.1f%%); all %.0f = %.1f%% of the frame"
              % (sav_sh, 100 * sav_sh / total, sav_clr, 100 * sav_clr / total, sav_cpy, 100 * sav_cpy / total,
                 sav_sh + sav_clr + sav_cpy, 100 * (sav_sh + sav_clr + sav_cpy) / total))


if __name__ == "__main__":
    main()
