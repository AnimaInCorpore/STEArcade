"""Galaga reference probes: coin/start through the 51XX, where the CPUs idle, and whether
the sound CPU matters.  python ref/galaga1.py <outdir>"""
import os, sys, pickle
from collections import Counter
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from galaga import Galaga, save_png

out = sys.argv[1] if len(sys.argv) > 1 else "."
m = Galaga()
hist = [Counter(), Counter(), Counter()]
orig_step = [c.step for c in m.cpus]


def counting(n):
    cpu = m.cpus[n]
    f = orig_step[n]

    def step():
        hist[n][cpu.pc] += 1
        return f()
    return step


for f in range(1500):
    m.run_frame()
    if f == 1200:
        for n in range(3):
            m.cpus[n].step = counting(n)
for n in range(3):
    tot = sum(hist[n].values())
    print("CPU%d attract-mode instructions %d, top pcs:" % (n + 1, tot),
          ", ".join("%04X %.0f%%" % (pc, 100.0 * c / tot) for pc, c in hist[n].most_common(8)))
save_png(m.render_rgb(), os.path.join(out, "g_attract.png"))

# coin, start, play
print("credits before", m.n51.credits)
for f in range(6):
    m.in1 = 0xff & ~0x10
    m.run_frame()
m.in1 = 0xff
for f in range(30):
    m.run_frame()
print("credits after coin", m.n51.credits)
save_png(m.render_rgb(), os.path.join(out, "g_coin.png"))
for f in range(6):
    m.in1 = 0xff & ~0x04
    m.run_frame()
m.in1 = 0xff
print("credits after start", m.n51.credits, "mode", m.n51.mode)
for f in range(300):
    m.in0 = 0xff & ~0x02 if (f // 40) % 2 else 0xff & ~0x08     # right / left
    m.in1 = 0xff & ~0x01 if f % 20 < 3 else 0xff                 # fire
    m.run_frame()
    if f in (120, 299):
        save_png(m.render_rgb(), os.path.join(out, "g_play%d.png" % f))
print("51xx log:", m.n51.log)
print("unknown writes:", m.io_log[:10])

# the same boot without the sound CPU
m2 = Galaga()
m2.run_frame()
m2.held[2] = True
orig = m2.latch_w


def latch_no_cpu3(bit, v):
    orig(bit, v)
    m2.held[2] = True
m2.latch_w = latch_no_cpu3
m3 = Galaga()
diff = None
for f in range(1500):
    m2.run_frame()
    m3.run_frame()
    if m2.ram != m3.ram and diff is None:
        diff = f
        d = [i for i in range(0x2000) if m2.ram[i] != m3.ram[i]]
        print("RAM differs without CPU3 from frame", f, "at", ["%04X" % (0x8000 + i) for i in d[:10]], len(d))
print("without CPU3: main pc %04X sub pc %04X, RAM same as with CPU3: %s" % (m2.cpus[0].pc, m2.cpus[1].pc, diff is None))
save_png(m2.render_rgb(), os.path.join(out, "g_nocpu3.png"))
