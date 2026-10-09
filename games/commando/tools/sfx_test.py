"""The STE's effect player (src/sfx.s, the --sim build) against tools/sound_sfx.py's Decoded, IRQ by IRQ: the latch
values the sound CPU reads in the game run of ref/cover.py, fed to both; both chips' output registers compared.

    python sfx_test.py [frames]
"""
import os
import random
import sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine"),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ref")]
from machine68k import Register as R
from sim import Sim
from paths import ROOT, build_dir
import sound
import sound_sfx as sx
from cover import inputs
from machine import Commando, CYCLES_PER_LINE, LINES


def latches(frames):
    """the latch value at each IRQ the sound CPU takes in the game run"""
    m, s = Commando(), sound.SoundBoard()
    rnd = random.Random(1)
    out = []
    s.on_irq_done = lambda b: out.append(b.irq_latch)
    for f in range(frames):
        m.inputs[0], m.inputs[1], m.inputs[2] = inputs(f, rnd)
        target = m.frame * CYCLES_PER_LINE * LINES
        for line in range(LINES):
            irq = m.irqprom[line & 255]
            if irq & 8:
                m.pending = 0xc7 | ((irq << 3) & 0x18)
            target += CYCLES_PER_LINE
            while m.cpu.cycles < target:
                m.step()
            s.latch = m.latch
            s.run_line(target, bool(irq & 4))
            del s.writes[:]
        m.frame += 1
    return out


def main():
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    seq = latches(frames)
    effects = sx.all_effects()
    ref = sx.Decoded(sx.encode(effects), sx.idle_regs())
    run = ROOT / "run" / "commando_sim"
    s = Sim(str(run / "COMMANDO.PRG"), ram_kib=16384, run_dir=run)
    mem, cpu = s.mem, s.cpu
    sym = {k: v + s.base for k, v in s.symbols(build_dir("commando") / "commando_sim.map").items()}
    stop = sym["sim_render_ret"]                 # (a loop of the sim build: the return address of the calls)

    def call(addr):
        sp = 0xF00000
        cpu.w_reg(R.A7, sp - 4)
        mem.w32(sp - 4, stop)
        cpu.w_pc(addr)
        for _ in range(200000):
            if cpu.r_pc() == stop:
                return
            cpu.execute(1)
        raise RuntimeError("no return from %06X: pc %06X" % (addr, cpu.r_pc()))

    cpu.w_sr(0x2700)
    call(sym["sfx_init"])
    latch = sym["g_block"] + 0x8000 - 0x3800
    bad = total = 0
    for i, v in enumerate(seq):
        mem.w8(latch, v)
        call(sym["sfx_irq"])
        want = ref.irq(v)
        for chip in (0, 1):
            got = bytes(mem.r_block(mem.r32(sym["sfx_chip_out"] + 4 * chip), 11))
            if want[chip] is None:
                continue
            total += 1
            if got != bytes(want[chip]):
                bad += 1
                if bad <= 5:
                    print("IRQ %d (latch %02X) chip %d: player %s decoder %s" % (i, v, chip, list(got), list(want[chip])))
    print("%d IRQs, %d chip outputs compared, %d differ" % (len(seq), total, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
