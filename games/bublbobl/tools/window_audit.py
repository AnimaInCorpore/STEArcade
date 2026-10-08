"""Finds the instructions that read the banked window ($8000-$BFFF) as data through the plain block (the translation
reads the window of the current bank at the instrumented sites only): runs the translated game on Musashi with random
play and records every read of the unused window area of the shared RAM block.  The sites (virtual pcs) are added to
bb_wsites_extra.pkl, which gen reads.     python window_audit.py <seed> <frames>"""
import os, pickle, random, re, sys, bisect
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from sim import Sim, FRAME_CYCLES, TRAP1
from machine68k import Register as R
import logic_test as lt

from paths import build_dir


def main():
    seed = int(sys.argv[1]); frames = int(sys.argv[2])
    rnd = random.Random(seed)
    s = Sim(str(lt.RUN / "BUBBLE.PRG"), run_dir=lt.RUN)
    s.mem.set_trace_mode(False)
    sym = {k: v + s.base for k, v in s.symbols(lt.MAP).items()}
    cpu, mem = s.cpu, s.mem
    stop = sym["sim_frame_done"]
    g_ram = sym["g_block"] + 0x8000
    mem.w16(sym["render_frame"], 0x4E75)                # no rendering: only the game
    labels = sorted((v, k) for k, v in sym.items() if re.fullmatch(r"Z[0-9A-F]{4,5}", k))
    lv = [v for v, _ in labels]
    hits = {}
    cur = [0]

    def watch(mode, width, addr, value):
        if mode == "R" and g_ram <= addr < g_ram + 0x3FE0:
            pc = cpu.r_pc()
            i = bisect.bisect_right(lv, pc - 1) - 1
            name = labels[i][1] if i >= 0 else "?"
            hits.setdefault(name, 0)
            hits[name] += 1
    # fill the window area with a marker
    mem.w_block(g_ram, bytes([0xEE]) * 0x3FE0)
    total = 0; nv = FRAME_CYCLES; fr = 0
    booted = False
    state = "attract"; coin_at = 300 + rnd.randrange(300); joy = 0; t0 = 0
    traced = False
    while fr < frames:
        r = cpu.execute(2000); total += r.cycles
        pc = cpu.r_pc()
        if pc == TRAP1:
            s.gemdos()
        elif pc == stop:
            sp = cpu.r_reg(R.A7); cpu.w_pc(mem.r32(sp)); cpu.w_reg(R.A7, sp + 4)
        if total >= nv:
            if s.irq(4, 28):
                nv += FRAME_CYCLES; fr += 1
                in0, in1 = 0x03, 0xFF
                if state == "attract" and fr >= coin_at: state, t0 = "coin", fr
                if state == "coin":
                    if fr < t0 + 4: in0 |= 0x04
                    elif 40 <= fr - t0 < 44: in1 &= ~0x40
                    elif fr - t0 >= 44: state, t0 = "play", fr
                if state == "play":
                    g = fr - t0
                    if g % 20 == 0: joy = rnd.choice([0, 0, 1, 2, 3])
                    if joy == 1: in1 &= ~0x01
                    if joy == 2: in1 &= ~0x02
                    if rnd.random() < 0.15: in1 &= ~0x10
                    if rnd.random() < 0.15: in1 &= ~0x20
                    if g > 4000 and g % 3000 < 3: in1 &= ~0x40
                mem.w8(sym["in0_val"], in0); mem.w8(sym["in1_val"], in1)
                if not traced and mem.r8(sym["booted1"]):
                    traced = True
                    mem.set_trace_func(watch); mem.set_trace_mode(True)
    out = str(build_dir("bublbobl") / ("bb_wsites_audit_%d.pkl" % seed))
    pickle.dump(hits, open(out, "wb"))
    print("seed", seed, "frames", fr, "sites:", sorted(hits), "->", out)


if __name__ == "__main__":
    main()
