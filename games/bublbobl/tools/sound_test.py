"""Bubble Bobble's STE sound player (src/sound.s, the --sim build) against tools/sound.py's play(), VBL by VBL: random
commands put through the latch hook (bb_snd_put), then bb_snd_vbl; the YM's registers 0-10 compared.  The model
against the sound driver itself: tools/sound.py check.

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
    cmds = {v: [c] for v, c in sound.random_commands(vbls, seed=3).items()}
    for v in list(cmds)[::7]:                    # (some VBLs with two commands)
        cmds[v].append(sound.random_commands(vbls, seed=v)[min(sound.random_commands(vbls, seed=v))])
    want = sound.play(cmds, vbls)
    run = ROOT / "run" / "bublbobl_sim"
    s = Sim(str(run / "BUBBLE.PRG"), ram_kib=16384, run_dir=run)
    mem, cpu = s.mem, s.cpu
    sym = {k: v + s.base for k, v in s.symbols(build_dir("bublbobl") / "bublbobl_sim.map").items()}
    stop = sym["cs_off"]                         # (a return address: the calls stop before running it)

    def call(addr, d0=None):
        cpu.w_reg(R.A7, 0xF00000 - 4)
        mem.w32(0xF00000 - 4, stop)
        if d0 is not None:
            cpu.w_reg(R.D0, d0)
        cpu.w_pc(addr)
        n = 0
        for _ in range(4000000):
            if cpu.r_pc() == stop:
                return n
            n += cpu.execute(1).cycles
        raise RuntimeError("no return from %06X: pc %06X" % (addr, cpu.r_pc()))

    cpu.w_sr(0x2700)
    call(sym["bb_snd_init"])
    bad = sounding = 0
    cycles = []
    for v in range(vbls):
        for c in cmds.get(v, ()):
            call(sym["bb_snd_put"], c)
        cycles.append(call(sym["bb_snd_vbl"]))
        got = list(mem.r_block(sym["cs_regs"], 11))
        sounding += any(want[v][8 + k] for k in range(3))
        if got != want[v]:
            bad += 1
            if bad <= 5:
                print("VBL %d (%s): 68000 %s model %s" % (v, cmds.get(v), got, want[v]))
    cycles.sort()
    print("%d VBLs (%d with sound), %d differ; the VBL's player %d cycles on average, %d at most" % (
        vbls, sounding, bad, sum(cycles) // len(cycles), cycles[-1]))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
