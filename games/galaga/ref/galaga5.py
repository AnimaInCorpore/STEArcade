"""Galaga: the STE runtime's schedule (run_frame_port) against the interleaved reference
over a scripted game.  python ref/galaga5.py [frames] [outdir]   (outdir: build/galaga)"""
import os, sys
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import numpy as np
from machine import Galaga, save_png
from paths import build_dir

frames = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
out = sys.argv[2] if len(sys.argv) > 2 else str(build_dir("galaga"))


def script(m, f):
    m.in0 = m.in1 = 0xff
    if 1500 <= f < 1506: m.in1 &= ~0x10
    if 1540 <= f < 1546: m.in1 &= ~0x04
    if f >= 1560:
        g = f - 1560
        if (g // 40) % 2: m.in0 &= ~0x02
        else: m.in0 &= ~0x08
        if g % 20 < 3: m.in1 &= ~0x01


fine, port = Galaga(), Galaga()
same = diff = 0
first = None
for f in range(frames):
    script(fine, f)
    script(port, f)
    fine.run_frame()
    port.run_frame_port()
    if f % 100 == 0 or f in (1480, 1600, 2000):
        a, b = fine.render_raw(), port.render_raw()
        if np.array_equal(a, b):
            same += 1
        else:
            diff += 1
            if first is None:
                first = f
            print("frame %d: %d pixels differ (pcs %04X %04X / %04X %04X, credits %d/%d, mode %d/%d)" % (
                f, int((a != b).sum()), fine.cpus[0].pc, fine.cpus[1].pc, port.cpus[0].pc, port.cpus[1].pc,
                fine.n51.credits, port.n51.credits, fine.n51.mode, port.n51.mode))
            if diff <= 2:
                save_png(a, os.path.join(out, "g5_fine_%d.png" % f)) if False else None
                save_png(fine.render_rgb(), os.path.join(out, "g5_fine_%d.png" % f))
                save_png(port.render_rgb(), os.path.join(out, "g5_port_%d.png" % f))
print("compared frames: %d same, %d different (first %s)" % (same, diff, first))
print("port mode handler runs (CPU1 IRQ, CPU2 IRQ):", port.handler_runs[:2], "booted", port.booted)
print("port: 51xx log length", len(port.n51.log), "fine:", len(fine.n51.log))
