"""The STE's music player (src/music.s, the --sim build) against tools/sound_music.py's Player and combine, tick by
tick: a latch sequence with every tune, the stops and effects (tunes that pause and resume, tails, loops), and the
effect registers of tools/sound_sfx.py's decoder; the YM registers 0-10 compared.

    python music_test.py [ticks]
"""
import os
import random
import sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from machine68k import Register as R
from sim import Sim
from paths import ROOT, build_dir
import sound_music as sm
import sound_sfx as sx


def latches(ticks, seed=1):
    """a command every 30-900 ticks: mostly tunes (the main theme often, so the jingles pause it), some stops and
    effects; $FF between them (the main CPU's idle value)"""
    rnd = random.Random(seed)
    effects = [c for c in range(0x02, 0x1C)]
    out, cmd = [], 0xFF
    while len(out) < ticks:
        r = rnd.random()
        cmd = (0x21 if r < 0.25 else rnd.choice(list(sm.TUNES)) if r < 0.7 else rnd.choice(sm.STOPS) if r < 0.78
               else rnd.choice(effects))
        out += [cmd] * rnd.choice((1, 1, 2, 5)) + [0xFF] * rnd.randrange(30, 900)
    return out[:ticks]


def main():
    ticks = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    seq = latches(ticks)
    player, mixer = sm.Player(sm.encode(sm.all_tunes())), sm.Mixer()
    sfx = sx.Decoded(sx.encode(sx.all_effects()), sx.idle_regs())
    run = ROOT / "run" / "commando_sim"
    s = Sim(str(run / "COMMANDO.PRG"), ram_kib=16384, run_dir=run)
    mem, cpu = s.mem, s.cpu
    sym = {k: v + s.base for k, v in s.symbols(build_dir("commando") / "commando_sim.map").items()}
    stop = sym["sim_render_ret"]                 # (a loop of the sim build: the return address of the calls)

    def call(addr, a1=None):
        sp = 0xF00000
        cpu.w_reg(R.A7, sp - 4)
        mem.w32(sp - 4, stop)
        if a1 is not None:
            cpu.w_reg(R.A1, a1)
        cpu.w_pc(addr)
        for _ in range(400000):
            if cpu.r_pc() == stop:
                return
            cpu.execute(1)
        raise RuntimeError("no return from %06X: pc %06X" % (addr, cpu.r_pc()))

    cpu.w_sr(0x2700)
    call(sym["mus_init"])
    latch = sym["g_block"] + 0x8000 - 0x3800
    buf = 0xE00000
    bad = playing = 0
    eff = list(sfx.idle[0])
    for i, v in enumerate(seq):
        for _ in range(4):                       # (the effect of the chip whose effect started last, as sfx_tick)
            outs = sfx.irq(v)
        serial = [max((sl["serial"] for sl in sfx.slots[chip] if sl), default=0) for chip in (0, 1)]
        chip = 1 if serial[1] > serial[0] else 0
        if outs[chip] is not None:
            eff = list(outs[chip])
        want = sm.combine(eff, mixer, player.tick(v))
        mem.w8(latch, v)
        call(sym["mus_tick"])
        mem.w_block(buf, bytes(eff))
        call(sym["mus_mix"], buf)
        got = list(mem.r_block(sym["mus_regs"], 11))
        playing += any(want[8 + c] for c in range(3))
        if got != want:
            bad += 1
            if bad <= 5:
                print("tick %d (latch %02X): player %s model %s" % (i, v, got, want))
    print("%d ticks (%d with sound), %d differ" % (len(seq), playing, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
