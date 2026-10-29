"""Bring-up probe: run the reference machine, screenshots at a few frames, a coin + start, DMA and I/O summary.
    python boot1.py OUTDIR"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
from machine import DKongJr, save_png

out = sys.argv[1]
os.makedirs(out, exist_ok=True)
m = DKongJr()
shots = {300, 700, 1200, 1700, 2100, 2400, 2800, 3400}
t = time.time()
for f in range(3500):
    m.in2 = 0x80 if 1500 <= f < 1504 else 0x04 if 1600 <= f < 1604 else 0
    m.in0 = 0x01 if 2200 <= f < 2300 else 0x10 if 2300 <= f < 2310 else 0   # right, then jump
    m.run_frame()
    if f in shots:
        save_png(m.render_rgb(), os.path.join(out, "f%04d.png" % f))
print("frames", m.frame, "%.1fs" % (time.time() - t), "pc %04X nmi_mask %d" % (m.cpu.pc, m.nmi_mask))
print("dma regs", [hex(x) for x in m.dma.addr], [hex(x) for x in m.dma.count], "mode", hex(m.dma.mode))
print("dma skips", [e for e in m.dma_log if e[1] == "skip"][:5])
print("io", {hex(k): v for k, v in sorted(m.io_writes.items())})
