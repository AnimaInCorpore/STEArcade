"""The return points' weights for the translator (m6809x Program.ret_weights, fast_forms): how often the translated
program returns to each instruction after a JSR / BSR, counted on Musashi over a seed's port schedule (the --sim
build).  Written to games/ddragon/docs/ret_weights.json, which gen.py reads: an RTS compares the most frequent of its
return points first.  Only the order of the compares depends on it (a return point not compared goes through the
dispatcher), never the result.

    python games/ddragon/tools/ret_profile.py [--seed N ...] [--frames F0 F1]   (default: seeds -1 and 4, frames 5000-12000)
"""
from pathlib import Path
import argparse
import collections
import json
import re
import sys

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine"),
                str(Path(__file__).resolve().parents[1] / "ref")]
from sim import Sim, TRAP1
from machine68k import Register as R
from paths import ROOT, build_dir
import cover

OUT = Path(__file__).resolve().parents[1] / "docs" / "ret_weights.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, action="append")
    ap.add_argument("--frames", type=int, nargs=2, default=(5000, 12000))
    args = ap.parse_args()
    seeds = args.seed or [-1, 4]
    # the return points: the instructions after a JSR / BSR / LBSR (code_main.s: "; pc MNEMONIC")
    lines = (build_dir("ddragon") / "code_main.s").read_text().splitlines()
    points, prev = set(), None
    for line in lines:
        m = re.match(r"(M[0-9A-F]{6}):\t\t; [0-9A-F]{4} (\S+)", line)
        if m:
            if prev in ("JSR", "BSR", "LBSR"):
                points.add(m.group(1))
            prev = m.group(2)
    counts = collections.Counter()
    for seed in seeds:
        run = ROOT / "run" / "ddragon_sim"
        sim = Sim(str(run / "DDRAGON.PRG"), run_dir=run)
        sim.mem.set_trace_mode(False)
        sym = {k: v + sim.base for k, v in sim.symbols(build_dir("ddragon") / "ddragon_sim.map").items()}
        stops = {sym[n] for n in ("sim_wait", "sim_frame_done", "sim_badpc")}
        at = {sym[k]: k for k in points if k in sym}
        mem, cpu = sim.mem, sim.cpu
        dsw1, inputs = cover.schedule(seed)
        mem.w8(sym["dd_dsw"] + 1, dsw1)

        def run_to(count):
            while True:
                pc = cpu.r_pc()
                if count and pc in at:
                    counts[at[pc]] += 1
                cpu.execute(1 if count else 4000)
                pc = cpu.r_pc()
                if pc in stops:
                    return
                if pc == TRAP1:
                    sim.gemdos()

        def resume():
            sp = cpu.r_reg(R.A7)
            cpu.w_pc(mem.r32(sp))
            cpu.w_reg(R.A7, sp + 4)

        run_to(False)
        f0, f1 = args.frames
        for f in range(f1):
            p1, p2, extra, coins = inputs(f)
            if coins:
                mem.w8(sym["port_coins"], mem.r8(sym["port_coins"]) | coins)
            for k, v in enumerate((p1, p2, extra)):
                mem.w8(sym["in_bytes"] + k, v)
            resume()
            run_to(f >= f0)
            resume()
            run_to(False)
        sim.m.cleanup()
    OUT.write_text(json.dumps({k[1:]: n for k, n in sorted(counts.items())}, indent=0) + "\n")
    print("%d return points, %d returns: %s" % (len(counts), sum(counts.values()), OUT))


if __name__ == "__main__":
    main()
