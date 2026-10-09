"""Instruction-level lock-step of the NMIs from a frame on: python nmitrace.py <first frame>"""
import random, sys
import os
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from fullrun import Lock, fine_trace, R

first = int(sys.argv[1])
L = Lock()
rnd = random.Random(1)
L.set_inputs(0, 0, 0, 0x80)
visits = frame = joy = 0
while True:
    L.ref_to_idle()
    why = L.run68()
    assert why == "z80_hook", why
    visits += 1
    assert L.compare("visit %d" % visits)
    L.cpu.w_reg(R.A7, L.cpu.r_reg(R.A7) + 4)   # the hook pushed its resume label
    L.cpu.w_pc(L.sym["Z02BD_r"])
    if visits % 3 == 0 and L.ref.nmi_mask:
        frame += 1
        if frame % 7 == 0:
            joy = rnd.choice([0, 0, 1, 2, 4, 8, 16, 17, 18])
        in2 = 0
        if 20 <= frame < 24: in2 |= 0x80
        if 40 <= frame < 44: in2 |= 0x04
        L.set_inputs(joy, 0, in2, 0x80)
        cpu = L.ref.cpu
        cpu.nmi()
        a5 = L.cpu.r_reg(R.A5) - 2
        L.mem.w8(a5, 0x01)
        L.mem.w8(a5 + 1, 0x40)
        L.cpu.w_reg(R.A5, a5)
        L.cpu.w_pc(L.sym["Z0066"])
        if frame >= first:
            print("tracing NMI of frame", frame)
            if not fine_trace(L, 2000000, stop_pc=0x2BD):
                sys.exit(1)
            # the 68k is at Z02BD (ret token consumed); continue like the main loop
            L.cpu.w_pc(L.sym["Z02BD_r"])
            if not L.compare("after NMI %d" % frame):
                sys.exit(1)
        else:
            sp0, pc0 = cpu.sp, cpu.pc
            n = 0
            while not (cpu.sp == sp0 + 2 and cpu.pc == 0x2BD):
                cpu.step()
                n += 1
                if n > 5_000_000:
                    raise RuntimeError("reference NMI did not return")
            why = L.run68()
            assert why == "z80_nmi_ret", why
            L.cpu.w_pc(L.sym["Z02BD_r"])
            assert L.compare("after NMI %d" % frame)
