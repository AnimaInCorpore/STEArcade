"""Who writes a shared RAM address in the first frames (reference).  python ref/find_write.py <addr> <frames>"""
import os, sys
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from machine import Bublbobl
addr = int(sys.argv[1], 16); n = int(sys.argv[2])
m = Bublbobl()
cur = {}
for name, cpu in (("main", m.main), ("sub", m.sub)):
    def mk(name, cpu):
        step = cpu.step
        def st():
            cur[name] = cpu.pc
            return step()
        cpu.step = st
        orig = cpu.wr8
        def wr(a, v):
            if a == addr or a == addr + 1:
                print("frame", m.frame, name, "pc %04X" % cur[name], "wrote %04X <- %02X" % (a, v))
            orig(a, v)
        cpu.wr8 = wr
    mk(name, cpu)
import logic_test as lt
for f in range(n):
    i0, i1, i2 = lt.inputs(f)
    m.in0, m.in1, m.in2 = i0, i1, i2
    m.run_frame_port()
