"""Where the translated program's 68000 cycles go (Musashi): per 6809 routine (the label at or before each 68000
instruction, grouped by the 6809 pc's nearest JSR / BSR target the coverage saw) and per 6809 instruction, over frames
F0 .. F1 of a seed's port schedule.

    python games/ddragon/tools/profile.py F0 F1 [--seed N] [--top 30]
"""
from pathlib import Path
import argparse
import bisect
import collections
import sys

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine"),
                str(Path(__file__).resolve().parents[1] / "ref")]
from sim import Sim, TRAP1
from machine68k import Register as R
from paths import ROOT, build_dir
import cover


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("f0", type=int)
    ap.add_argument("f1", type=int)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--top", type=int, default=30)
    args = ap.parse_args()
    run = ROOT / "run" / "ddragon_sim"
    sim = Sim(str(run / "DDRAGON.PRG"), run_dir=run)
    sim.mem.set_trace_mode(False)
    sym = {k: v + sim.base for k, v in sim.symbols(build_dir("ddragon") / "ddragon_sim.map").items()}
    stops = {sym[n]: n for n in ["sim_wait", "sim_frame_done", "sim_badpc"]}
    mem, cpu = sim.mem, sim.cpu
    # the 68000 address of every translated label and of the runtime's routines
    labs = sorted((v, k) for k, v in sym.items() if k[:1] == "M" and len(k) == 7 or k in (
        "main_dispatch", "main_dispatch_nf", "main_io_r", "main_io_w", "mcu_job", "m6809_daa", "m6809_mul",
        "port_frame", "bank_set", "native_clear_sprites", "native_copy_sprites", "main_bank_w", "p2_byte",
        "extra_byte", "enter_nmi", "enter_firq", "enter_idle", "port_save") or k.startswith("hook_"))
    addrs = [a for a, k in labs]
    dsw1, inputs = cover.schedule(args.seed)
    mem.w8(sym["dd_dsw"] + 1, dsw1)

    def run_to_stop(prof=None):
        while True:
            if prof is None:
                cpu.execute(4000)
            else:
                pc = cpu.r_pc()
                c = cpu.execute(1).cycles
                i = bisect.bisect_right(addrs, pc) - 1
                prof[labs[i][1] if i >= 0 else "?"] += c
            pc = cpu.r_pc()
            if pc in stops:
                return stops[pc]
            if pc == TRAP1:
                sim.gemdos()

    def resume():
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp))
        cpu.w_reg(R.A7, sp + 4)

    run_to_stop()
    prof = collections.Counter()
    for f in range(args.f1):
        p1, p2, extra, coins = inputs(f)
        if coins:
            mem.w8(sym["port_coins"], mem.r8(sym["port_coins"]) | coins)
        for k, v in enumerate((p1, p2, extra)):
            mem.w8(sym["in_bytes"] + k, v)
        resume()
        run_to_stop(prof if f >= args.f0 else None)
        resume()
        run_to_stop()
    total = sum(prof.values())
    n = args.f1 - args.f0
    print("%d frames, %.0f 68000 cycles a frame" % (n, total / n))
    # per 6809 instruction
    for k, c in prof.most_common(args.top):
        print("  %-24s %8.0f a frame %5.1f%%" % (k, c / n, 100 * c / total))
    # per 64-byte block of 6809 code (routines)
    blocks = collections.Counter()
    for k, c in prof.items():
        if k[:1] == "M":
            blocks["M%05X" % (int(k[1:], 16) & ~0x3F)] += c
        else:
            blocks[k] += c
    print("by 64-byte block:")
    for k, c in blocks.most_common(args.top):
        print("  %-24s %8.0f a frame %5.1f%%" % (k, c / n, 100 * c / total))


if __name__ == "__main__":
    main()
