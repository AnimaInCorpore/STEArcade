"""Odd word / long accesses of the translated game (a 68000 faults on them, Musashi does not): runs the game
on Musashi with an access trace after the boot and lists the sites.   python bb_align_test.py [frames]"""
import os, sys, bisect
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sim import Sim
from machine68k import Register as R
import bb_logic_test as lt


def main():
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    s = Sim(str(lt.RUN / "BUBBLE.PRG"), run_dir=lt.RUN)
    s.mem.set_trace_mode(False)
    sym = {k: v + s.base for k, v in s.symbols(lt.MAP).items()}
    s.bad = sym["z80_badpc"]
    cpu, mem = s.cpu, s.mem
    stop = sym["sim_frame_done"]
    names = sorted((v, k) for k, v in sym.items() if not k.startswith(("Z", "Y", "M", "L")) or True)
    vs = [v for v, _ in names]
    nm = lambda pc: names[bisect.bisect_right(vs, pc) - 1][1] + "+%d" % (pc - names[bisect.bisect_right(vs, pc) - 1][0])
    hits = Counter()
    last = {}

    def watch(mode, width, addr, value):
        if width and (addr & 1) and addr < 0xFF8000:
            hits[(mode, ("b", "w", "l")[width], nm(cpu.r_pc()))] += 1
    while True:
        lt.run_to(s, stop)
        b = mem.r8(sym["booted1"])
        sp = cpu.r_reg(R.A7); cpu.w_pc(mem.r32(sp)); cpu.w_reg(R.A7, sp + 4)
        if b:
            break
    mem.set_trace_func(watch)
    mem.set_trace_mode(True)
    for f in range(frames):
        i0, i1, i2 = lt.inputs(f)
        mem.w8(sym["in0_val"], i0); mem.w8(sym["in1_val"], i1); mem.w8(sym["in2_val"], i2)
        lt.run_to(s, stop)
        sp = cpu.r_reg(R.A7); cpu.w_pc(mem.r32(sp)); cpu.w_reg(R.A7, sp + 4)
    for k, n in hits.most_common(40):
        print(n, k)
    print("sites:", len(hits))


if __name__ == "__main__":
    main()
