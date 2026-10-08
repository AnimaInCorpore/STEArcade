"""Run DKSIM.PRG on the simulator with a coin/start script and save screenshots.

    python simplay.py [frames] [shot_every]
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sim import Sim, RUN, STE
from PIL import Image

frames = int(sys.argv[1]) if len(sys.argv) > 1 else 600
every = int(sys.argv[2]) if len(sys.argv) > 2 else 100
s = Sim(RUN / "DKSIM.PRG")
syms = s.symbols(STE / "build" / "dkong.map")
base = s.base
in2 = base + syms["in2_kbd"]
in0 = base + syms["in0_kbd"]
def on_frame(sim):
    f = sim.frames
    sim.mem.w8(in2, 0x80 if 40 <= f < 50 else (0x04 if 80 <= f < 90 else 0))
    if f % every == 0:
        Image.fromarray(sim.screen_rgb()).save(RUN / ("sim_%04d.png" % f))
        print("frame", f, "lag", getattr(sim, "lag", 0))
s.run_frames(frames, on_frame)
print("done", s.frames, s.log[-3:])
