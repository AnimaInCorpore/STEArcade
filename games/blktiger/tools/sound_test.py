"""Black Tiger's STE sound player (src/sound.s, the --sim build) against tools/sound.py's play(), VBL by VBL: random
commands (effects, tunes, stops) through both; per VBL bt_snd_cmd, bt_snd_load (the idle hook's unpacking, here at
once), bt_snd_steps; the YM's registers 0-10 compared.  The model against the driver itself: tools/sound.py check.

    python sound_test.py [vbls]
"""
import os
import sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from machine68k import Register as R
from sim import Sim
from paths import ROOT, build_dir
import sound


def main():
    vbls = int(sys.argv[1]) if len(sys.argv) > 1 else 6000
    latch_at = sound.random_commands(3)
    want = sound.play(latch_at, vbls)
    run = ROOT / "run" / "blktiger_sim"
    s = Sim(str(run / "BLKTIGER.PRG"), ram_kib=16384, run_dir=run)
    mem, cpu = s.mem, s.cpu
    sym = {k: v + s.base for k, v in s.symbols(build_dir("blktiger") / "blktiger_sim.map").items()}
    stop = sym["cs_off"]                         # (a return address: the calls stop before running it)

    def call(addr):
        cpu.w_reg(R.A7, 0xF00000 - 4)
        mem.w32(0xF00000 - 4, stop)
        cpu.w_pc(addr)
        n = 0
        for _ in range(4000000):
            if cpu.r_pc() == stop:
                return n
            n += cpu.execute(1).cycles
        raise RuntimeError("no return from %06X: pc %06X" % (addr, cpu.r_pc()))

    cpu.w_sr(0x2700)
    call(sym["bt_snd_init"])
    latch = mem.r32(sym["bt_latch_addr"])
    bad = sounding = 0
    cycles, loads = [], []
    for v in range(vbls):
        mem.w8(latch, latch_at(v))
        c = call(sym["bt_snd_cmd"])
        if mem.r8(sym["bt_load_req"]):
            loads.append(call(sym["bt_snd_load"]))
        c += call(sym["bt_snd_steps"])
        cycles.append(c)
        got = list(mem.r_block(sym["cs_regs"], 11))
        sounding += any(want[v][8 + k] for k in range(3))
        if got != want[v]:
            bad += 1
            if bad <= 5:
                print("VBL %d (latch %02X): 68000 %s model %s" % (v, latch_at(v), got, want[v]))
    cycles.sort()
    print("%d VBLs (%d with sound), %d differ; the VBL's player %d cycles on average, %d at most; %d tunes unpacked, "
          "%d cycles at most" % (vbls, sounding, bad, sum(cycles) // len(cycles), cycles[-1], len(loads), max(loads or [0])))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
