"""Who writes a shared RAM address in the first frames (reference).  python ref/bb_find_write.py <addr> <frames>"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from bublbobl import Bublbobl
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
for f in range(n):
    m.run_frame_port()
