import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
import sim
from sim import Sim, RUN, STE
log = []
orig = sim.Blitter.run
def run(self):
    io = self.sim.io
    log.append((self.reg32(0xA24), self.reg32(0xA32), self.reg16(0xA36), self.reg16(0xA38), io[0xA3A], io[0xA3B], io[0xA3D], self.reg16(0xA28), self.reg16(0xA2C)))
    orig(self)
sim.Blitter.run = run
s = Sim(RUN / "DKSIM.PRG")
syms = s.symbols(STE / "build" / "dkong.map")
base = s.base
def on_frame(sim_):
    f = sim_.frames
    sim_.mem.w8(base + syms["in2_kbd"], 0x80 if 40 <= f < 50 else (0x04 if 80 <= f < 90 else 0))
s.run_frames(250, on_frame)
n0 = len(log)
log.clear()
s.run_frames(1, on_frame)
print(len(log), 'blits in a frame')
for e in log[:40]:
    print(['%X' % v for v in e])
