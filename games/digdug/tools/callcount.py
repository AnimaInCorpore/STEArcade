"""Hits of chosen symbols per frame (single-stepped, so slow: use a few dozen frames): python callcount.py first count sym..."""
import os, sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import sim as simmod
from sim import Sim
from paths import ROOT, build_dir
import render_test as rt

first, count = int(sys.argv[1]), int(sys.argv[2])
RUN = ROOT / "run" / "digdug_sim"
s = Sim(str(RUN / "DIGDUG.PRG"), ram_kib=16384, run_dir=RUN)
syms = s.symbols(build_dir("digdug") / "digdug.map")
watch = {syms[k] + s.base: k for k in sys.argv[3:]}
hits = dict.fromkeys(sys.argv[3:], 0)
s.run_frames(first, on_frame=lambda sim: (setattr(sim, "_x", 0), sim.mem.w8(syms["in0_kbd"] + s.base, (~rt.script(sim.frames)[0]) & 0xff), sim.mem.w8(syms["in1_kbd"] + s.base, (~rt.script(sim.frames)[1]) & 0xff)))
next_vbl = s._next_vbl
total = s._total
end = s.frames + count
while s.frames < end:
    r = s.cpu.execute(1)
    total += r.cycles + s.blitter.cycles
    s.blitter.cycles = 0
    pc = s.cpu.r_pc()
    if pc in watch:
        hits[watch[pc]] += 1
    if pc == simmod.TRAP1:
        s.gemdos()
    if total >= next_vbl and s.irq(4, 28):
        next_vbl += simmod.FRAME_CYCLES
        s.frames += 1
        i0, i1 = rt.script(s.frames)
        s.mem.w8(syms["in0_kbd"] + s.base, (~i0) & 0xff)
        s.mem.w8(syms["in1_kbd"] + s.base, (~i1) & 0xff)
for k, v in hits.items():
    print("%-16s %.2f a frame" % (k, v / count))
