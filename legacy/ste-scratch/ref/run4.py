import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
from dkong import *
m = DKong()
for f in range(1500):
    m.in2 = 0
    if 200 <= f < 210: m.in2 |= 0x80
    if 300 <= f < 310: m.in2 |= 0x04
    m.run_frame()
    if f == 1499: save_png(m.render_rgb(), 'ref_frame.png', 2)
