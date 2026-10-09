"""The translated game (BUBBLE.PRG built with --sim) on Musashi against the Z80 / 6801 reference in
the port's schedule: after every frame's game interrupts (the runtime's `sim_frame_done`) the
shared video / work RAM, the palette and the MCU's RAM are compared.

    python logic_test.py [frames] [--input scripted|random] [--stop-on-error]
"""
import argparse, os, sys
from pathlib import Path
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from sim import Sim
from machine68k import Register as R
from machine import Bublbobl

from paths import ROOT, build_dir
RUN = ROOT / "run" / "bublbobl_sim"
MAP = build_dir("bublbobl") / "bublbobl_sim.map"
RANGES = [(0xC000, 0xF7C0), (0xF800, 0xFA00), (0xFC00, 0x10000)]     # (the stacks at F7C0-F7FF hold the interrupt tokens)


def inputs(f):
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


def run_to(s, stop_pc, limit=400_000_000):
    """Run the 68000 with the VBL interrupt to stop_pc; False if the program ended or looped."""
    from sim import FRAME_CYCLES, TRAP1
    cpu = s.cpu
    next_vbl = getattr(s, "_next_vbl", FRAME_CYCLES)
    total = getattr(s, "_total", 0)
    start = total
    ok = True
    while True:
        r = cpu.execute(2000)
        total += r.cycles
        pc = cpu.r_pc()
        if pc == stop_pc:
            break
        if pc == s.bad or pc == s.bad + 4:
            ok = False
            break
        if pc == TRAP1:
            s.gemdos()
        elif pc == 0x600 or s.terminated:
            ok = False
            break
        if total >= next_vbl:
            if s.irq(4, 28):
                next_vbl += FRAME_CYCLES
                s.frames += 1
        if total - start > limit:
            ok = False
            break
    s._next_vbl = next_vbl
    s._total = total
    return ok


def name_of(sym, pc):
    best = None
    for k, v in sym.items():
        if v <= pc and (best is None or v > best[1]):
            best = (k, v)
    return "%s+%d" % (best[0], pc - best[1]) if best else "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames", nargs="?", type=int, default=300)
    ap.add_argument("--prg", default=str(RUN / "BUBBLE.PRG"))
    ap.add_argument("--stop", action="store_true")
    a = ap.parse_args()
    s = Sim(a.prg, run_dir=RUN)
    s.mem.set_trace_mode(False)         # (no I/O capture: much faster)
    sym = s.symbols(MAP)
    sym = {k: v + s.base for k, v in sym.items()}      # (the map's addresses are relative to the load address)
    frame_done = sym["sim_frame_done"]
    s.bad = sym["z80_badpc"]
    g_ram = sym["g_block"] + 0x8000
    ref = Bublbobl()
    mem, cpu = s.mem, s.cpu
    print("sim_frame_done %06X g_block %06X (load base %06X)" % (frame_done, sym["g_block"], s.base))
    in0_a, in1_a, in2_a = sym["in0_val"], sym["in1_val"], sym["in2_val"]
    booted1 = sym["booted1"]
    bad = 0
    f = 0
    total_cycles = 0
    while f < a.frames and not s.terminated:
        in0, in1, in2 = inputs(f)
        ref.in0, ref.in1, ref.in2 = in0, in1, in2
        mem.w8(in0_a, in0)
        mem.w8(in1_a, in1)
        mem.w8(in2_a, in2)
        ref.run_frame_port()
        # run the 68000 until its next frame_done with the main CPU booted
        while True:
            if not run_to(s, frame_done):
                print("68000 stopped: pc %06X (%s) log %s" % (cpu.r_pc(), name_of(sym, cpu.r_pc()), s.log[-3:]))
                print("  d0-d7", " ".join("%08X" % cpu.r_reg(r) for r in (R.D0, R.D1, R.D2, R.D3, R.D4, R.D5, R.D6, R.D7)))
                print("  a0-a7", " ".join("%08X" % cpu.r_reg(r) for r in (R.A0, R.A1, R.A2, R.A3, R.A4, R.A5, R.A6, R.A7)))
                sp = cpu.r_reg(R.A7)
                print("  stack", " ".join("%08X" % mem.r32(sp + 4 * i) for i in range(8)))
                return
            booted = mem.r8(booted1)
            sp = cpu.r_reg(R.A7)
            cpu.w_pc(mem.r32(sp))
            cpu.w_reg(R.A7, sp + 4)
            if booted:
                break
        # every page of the video RAM that differs from the renderer's copy is marked (gen.VRAM_WRITERS)
        if not mem.r8(sym["vmark_all"]) and not mem.r8(sym["vdiff_busy"]):
            live = bytes(mem.r_block(g_ram + 0xC000 - 0x8000, 0x1D00))
            snap = bytes(mem.r_block(sym["snap_vram"], 0x1D00))
            for pg in range(58):
                if live[pg * 128:pg * 128 + 128] != snap[pg * 128:pg * 128 + 128] and not mem.r8(sym["vmarks"] + 0x180 + pg):
                    i = next(i for i in range(pg * 128, pg * 128 + 128) if live[i] != snap[i])
                    print("frame %d: video RAM %04X changed without its page mark (a writer missing in gen.VRAM_WRITERS)" % (f, 0xC000 + i))
                    return
        # compare
        errs = []
        if mem.r16(sym["rnd_state"]) != ref.rnd_state and not getattr(ref, "_rnd_reported", False):
            ref._rnd_reported = True
            print("frame %d: the random generator differs: 68000 %04X reference %04X" % (f, mem.r16(sym["rnd_state"]), ref.rnd_state))
        for lo, hi in RANGES:
            got = bytes(mem.r_block(g_ram + lo - 0x8000, hi - lo))
            if lo < 0xDD00 and hi > 0xDD00:
                pass
            want = bytearray(hi - lo)
            for ad in range(lo, hi):
                want[ad - lo] = ref.rd_main(ad) if not (0xFA00 <= ad < 0xFC00) else 0
            # (rd_main of the window range is not used here; the ranges start at C000)
            d = [lo + i for i in range(hi - lo) if got[i] != want[i]]
            if d:
                errs.append((d[0], len(d), d[:8]))
                if bad == 0:
                    runs = []
                    for ad in d:
                        if runs and ad == runs[-1][1] + 1:
                            runs[-1][1] = ad
                        else:
                            runs.append([ad, ad])
                    print("  differing runs:", ["%04X-%04X" % tuple(r) for r in runs[:20]])
                    print("  got/want of the first run:", [(hex(got[a - lo]), hex(want[a - lo])) for a in range(runs[0][0], min(runs[0][0] + 12, runs[0][1] + 1))])
        if errs:
            bad += 1
            print("frame %d: %s" % (f, ["first %04X, %d bytes, %s" % (e[0], e[1], ["%04X" % x for x in e[2]]) for e in errs]))
            if a.stop or bad > 5:
                return
        if f % 50 == 0:
            print("frame %d ok (%s) pc %06X" % (f, "mismatch" if errs else "same", cpu.r_pc()), flush=True)
        f += 1
    print("compared %d frames, %d with differences" % (f, bad))


if __name__ == "__main__":
    main()
