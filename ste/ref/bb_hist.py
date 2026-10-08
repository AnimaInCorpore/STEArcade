import os, sys
from collections import Counter
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from bublbobl import Bublbobl
m = Bublbobl()
n = int(sys.argv[1])
for f in range(n):
    m.run_frame()
h = [Counter(), Counter(), Counter()]
orig = [c.step for c in (m.main, m.sub, m.snd)]
for i, c in enumerate((m.main, m.sub, m.snd)):
    def st(i=i, c=c, f=orig[i]):
        h[i][c.pc] += 1
        return f()
    c.step = st
for f in range(3):
    m.run_frame()
for i, nm in enumerate(("main", "sub", "snd")):
    tot = sum(h[i].values())
    print(nm, tot, ", ".join("%04X:%d" % (a, c) for a, c in h[i].most_common(14)))
print("mcram", m.mcram[:32].hex(), "irq_main", m.irq_main, "iff1", m.main.iff1, "im", m.main.im, "snd log", m.snd_log[:10])
