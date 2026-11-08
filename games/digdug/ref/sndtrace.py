import sys
sys.path[:0] = ["games/digdug/tools", "engine"]
import machine
from machine import DigDug
rd, wr = set(), set()
other = {0: (set(), set()), 1: (set(), set())}
orig_r, orig_w = DigDug.reader, DigDug.writer
def reader(self, n):
    f = orig_r(self, n)
    if n != 2:
        def g0(a):
            if 0x9A80 <= a < 0xa000 or 0x8A00 <= a < 0x8A50: other[n][0].add(a)
            return f(a)
        return g0
    def g(a):
        if 0x8000 <= a < 0xa000: rd.add(a)
        return f(a)
    return g
def writer(self, n):
    f = orig_w(self, n)
    if n != 2:
        def g0(a, v):
            if 0x9A80 <= a < 0xa000 or 0x8A00 <= a < 0x8A50: other[n][1].add(a)
            return f(a, v)
        return g0
    def g(a, v):
        if 0x8000 <= a < 0xa000: wr.add(a)
        return f(a, v)
    return g
DigDug.reader, DigDug.writer = reader, writer
import render_test as rt
m = DigDug(skip_tests=True, mcu_events=True)
for f in range(int(sys.argv[1])):
    m.in0, m.in1 = rt.script(f)
    m.run_frame_port()
def rng(s):
    s = sorted(s); out = []; 
    for a in s:
        if out and a == out[-1][1] + 1: out[-1][1] = a
        else: out.append([a, a])
    return " ".join("%04X-%04X" % (x, y) if x != y else "%04X" % x for x, y in out)
print("reads:", rng(rd)); print("writes:", rng(wr))
for n in (0,1): print("cpu",n,"reads", rng(other[n][0]), "writes", rng(other[n][1]))
