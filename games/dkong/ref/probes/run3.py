import sys, os
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "engine")]
from machine import *
m = DKong()
shots = {500, 700, 900, 1100, 1300, 1500}
for f in range(1600):
    m.in2 = 0
    if 200 <= f < 210: m.in2 |= 0x80
    if 300 <= f < 310: m.in2 |= 0x04
    m.run_frame()
    if f in shots:
        print(f, hex(m.cpu.pc), 'pb', m.palette_bank)
        save_png(m.render_rgb(), f'game_{f:04d}.png', 1)
