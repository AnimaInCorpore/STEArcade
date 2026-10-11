"""A game's STE sound player (engine/rt/capsnd.s in its --sim build) against engine/capsnd.py's Ste, tick by tick:
random commands (effects, tunes, stops) through both, the YM's registers 0-10 compared after each cs_tick.

    python capsnd_test.py <game> [ticks]       (the game's tools/sound.py has driver(); the --sim build must exist)
"""
import importlib
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from machine68k import Register as R
from sim import Sim
from paths import ROOT, build_dir
import capsnd

PRG = {"gunsmoke": "GUNSMOKE.PRG", "1943": "1943.PRG"}


def run(game, ticks):
    sys.path.insert(0, str(ROOT / "games" / game / "tools"))
    d = importlib.import_module("sound").driver()
    seq = capsnd.random_latches(d, ticks, seed=7) if os.environ.get("CS_LATCHES") != "game" else importlib.import_module("sound").game_latches(ticks)
    model = capsnd.Ste(d)
    rundir = ROOT / "run" / (game + "_sim")
    s = Sim(str(rundir / PRG[game]), ram_kib=16384, run_dir=rundir)
    mem, cpu = s.mem, s.cpu
    sym = {k: v + s.base for k, v in s.symbols(build_dir(game) / (game + "_sim.map")).items()}
    stop = sym["cs_off"]                         # (a return address: the calls stop before running it)

    def call(addr):
        sp = 0xF00000
        cpu.w_reg(R.A7, sp - 4)
        mem.w32(sp - 4, stop)
        cpu.w_pc(addr)
        n = 0
        for _ in range(400000):
            if cpu.r_pc() == stop:
                return n
            n += cpu.execute(1).cycles
        raise RuntimeError("no return from %06X: pc %06X" % (addr, cpu.r_pc()))

    cpu.w_sr(0x2700)
    call(sym["cs_init"])
    latch = sym["cs_latch_addr"] if "cs_latch_addr" in sym else None
    if latch is None:
        raise SystemExit("the build has no cs_latch_addr (the address of CS_LATCH)")
    latch = mem.r32(latch)
    bad = sounding = 0
    cycles = []
    for i, v in enumerate(seq):
        want = model.tick(v)
        mem.w8(latch, v)
        cycles.append(call(sym["cs_tick"]))
        got = list(mem.r_block(sym["cs_regs"], 11))
        sounding += any(want[8 + c] for c in range(3))
        if got != want:
            bad += 1
            if bad <= 5:
                print("tick %d (latch %02X): 68000 %s model %s" % (i, v, got, want))
    cycles.sort()
    print("%s: %d ticks (%d with sound), %d differ; cs_tick %d cycles on average, %d at most (median %d)" % (
        game, len(seq), sounding, bad, sum(cycles) // len(cycles), cycles[-1], cycles[len(cycles) // 2]))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 20000))
