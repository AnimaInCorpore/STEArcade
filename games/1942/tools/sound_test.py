"""The STE's sound player (src/sound.s, the --sim build) against tools/sound.py's Player, tick by tick: the latch values of
the game run and of random commands fed to both, the YM's registers 0-10 compared after every tick.

    python sound_test.py [ticks]
"""
import os
import sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from machine68k import Register as R
from sim import Sim
from paths import ROOT, build_dir
import sound

RUN = ROOT / "run" / "1942_sim"
MAP = build_dir("1942") / "1942_sim.map"


def main():
    ticks = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    images, streams = sound.encode(sound.programs())
    s = Sim(str(RUN / "1942.PRG"), run_dir=RUN)
    mem, cpu = s.mem, s.cpu
    sym = {k: v + s.base for k, v in s.symbols(MAP).items()}
    stop = sym["snd_off"]                       # (a return address: the test stops before running it)

    def call(addr):
        sp = s.base - 0x100
        cpu.w_reg(R.A7, sp - 4)
        mem.w32(sp - 4, stop)
        cpu.w_pc(addr)
        for _ in range(100000):
            if cpu.r_pc() == stop:
                return
            cpu.execute(1)
        raise RuntimeError("no return from %06X: pc %06X" % (addr, cpu.r_pc()))

    cpu.w_sr(0x2700)
    latch = sym["g_block"] + 0x8000 - 0x3800
    bad = 0
    for label, seq in (("game run", sound.game_latches(ticks)), ("random commands", sound.random_latches(ticks, 1)),
                       ("random commands", sound.random_latches(ticks, 2))):
        call(sym["snd_init"])
        p = sound.Player(images, streams)
        n = 0
        for t, v in enumerate(seq):
            mem.w8(latch, v)
            call(sym["snd_tick"])
            got = tuple(mem.r_block(sym["snd_ym"], 11))
            want = p.tick(v)
            if got != want:
                n += 1
                if n <= 5:
                    print("  tick %d (latch %02X): player %s Player %s" % (t, v, got, want))
        print("%s: %d ticks, %d differ" % (label, len(seq), n))
        bad += n
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
