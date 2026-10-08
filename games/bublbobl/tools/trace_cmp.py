"""Instruction level comparison of the translated game (Musashi) with the reference: the Z80 pcs the
main and sub CPU execute in frame N (the port's schedule) against the translated labels the 68000
passes.  python trace_cmp.py <frame>"""
import os, sys, re
from pathlib import Path
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from sim import Sim
from machine68k import Register as R
from machine import Bublbobl
import gen, logic_test as lt

RUN = lt.RUN


def main():
    N = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    s = Sim(str(RUN / "BUBBLE.PRG"), run_dir=RUN)
    s.mem.set_trace_mode(False)
    sym = {k: v + s.base for k, v in s.symbols(lt.MAP).items()}
    s.bad = sym["z80_badpc"]
    cpu, mem = s.cpu, s.mem
    labels = {}
    for k, v in sym.items():
        m = re.fullmatch(r"([ZY])([0-9A-F]{4,5})", k)
        if m:
            labels[v] = (m.group(1), int(m.group(2), 16))
    ref = Bublbobl()
    frame_done = sym["sim_frame_done"]
    booted1 = sym["booted1"]

    def vpc(pc, bank):
        return pc + ((bank ^ 4) & 7) * 0x4000 if 0x8000 <= pc < 0xC000 else pc

    # frames before N
    for f in range(N):
        i0, i1, i2 = lt.inputs(f)
        ref.in0, ref.in1, ref.in2 = i0, i1, i2
        mem.w8(sym["in0_val"], i0); mem.w8(sym["in1_val"], i1); mem.w8(sym["in2_val"], i2)
        ref.run_frame_port()
        while True:
            lt.run_to(s, frame_done)
            b = mem.r8(booted1)
            sp = cpu.r_reg(R.A7)
            cpu.w_pc(mem.r32(sp)); cpu.w_reg(R.A7, sp + 4)
            if b:
                break
    print("sim state before frame %d: main_irq %d g1_iff %d g2_iff %d booted1 %d booted2 %d sub_run %d mcu_run %d mcu_booted %d" % (
        N, mem.r8(sym["main_irq"]), mem.r8(sym["g1_iff"]), mem.r8(sym["g2_iff"]), mem.r8(booted1), mem.r8(sym["booted2"]),
        mem.r8(sym["sub_run"]), mem.r8(sym["mcu_run"]), mem.r8(sym["mcu_booted"])))
    g_ram = sym["g_block"] + 0x8000
    print("E194 sim %02X ref %02X; FC20 sim %02X ref %02X" % (mem.r8(g_ram + 0x6194), ref.shared[0x194], mem.r8(g_ram + 0x7C20), ref.mcram[0x20]))
    print("ref state: irq_main %s iff1 %s sub iff1 %s" % (ref.irq_main, ref.main.iff1, ref.sub.iff1))
    # frame N: trace both
    i0, i1, i2 = lt.inputs(N)
    ref.in0, ref.in1, ref.in2 = i0, i1, i2
    mem.w8(sym["in0_val"], i0); mem.w8(sym["in1_val"], i1); mem.w8(sym["in2_val"], i2)
    log = {"main": [], "sub": []}
    for name, c in (("main", ref.main), ("sub", ref.sub)):
        step = c.step
        def st(name=name, c=c, step=step):
            pc = c.pc
            log[name].append(vpc(pc, ref.bank) if name == "main" else pc)
            return step()
        c.step = st
    ref.run_frame_port()
    print("reference: main %d sub %d instructions" % (len(log["main"]), len(log["sub"])))
    # the sim: step until the next frame_done
    got = {"main": [], "sub": []}
    nv = getattr(s, "_next_vbl", None)
    from sim import FRAME_CYCLES, TRAP1
    total = getattr(s, "_total", 0)
    nv = getattr(s, "_next_vbl", FRAME_CYCLES)
    done = False
    steps = 0
    bank_of = lambda: mem.r8(sym["g_bank"])
    while not done and steps < 3_000_000:
        r = cpu.execute(1)
        total += r.cycles
        steps += 1
        pc = cpu.r_pc()
        if pc in labels:
            kind, v = labels[pc]
            if kind == "Z":
                if v != 0x1ED:                 # (the idle loop the VBL interrupts)
                    got["main"].append(v)
            else:
                got["sub"].append(v)
        if pc == TRAP1:
            s.gemdos()
            if s.terminated:
                print("program terminated"); break
        if pc == s.bad or pc == s.bad + 4:
            print("bad pc reached after %d steps" % steps)
            break
        if pc == frame_done:
            done = True
        if total >= nv:
            if s.irq(4, 28):
                nv += FRAME_CYCLES
    print("sim: main %d sub %d labels; steps %d pc %06X done %s total-nv %d sr %04X" % (len(got["main"]), len(got["sub"]), steps, cpu.r_pc(), done, total - nv, cpu.r_sr()))
    # window code in the reference is virtualised as pc + 0x4000*entry (8000..BFFF + e*4000); the labels are 0x10000+...
    def norm(v):
        if v >= 0x10000:
            return v
        return v
    for name in ("main", "sub"):
        a = [(0x10000 + (p - 0x8000) if name == "main" and p >= 0x8000 else p) for p in log[name]]
        b = got[name]
        dedup = lambda l: [x for i, x in enumerate(l) if i == 0 or x != l[i - 1]]
        a, b = dedup(a), dedup(b)          # (block instructions repeat in the reference)
        n = min(len(a), len(b))
        d = next((i for i in range(n) if a[i] != b[i]), None)
        if d is None:
            print(name, "sequences agree over", n, "(lengths %d / %d)" % (len(a), len(b)))
        else:
            print(name, "diverge at", d, "ref", ["%X" % x for x in a[max(0, d - 6):d + 4]], "sim", ["%X" % x for x in b[max(0, d - 6):d + 4]])


if __name__ == "__main__":
    main()
