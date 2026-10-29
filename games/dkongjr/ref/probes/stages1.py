"""Bring-up probe: are $6227 (stage), $6228 (lives), $6229 (level) Donkey Kong's?  Starts a game, logs the three
bytes, and for each stage s = 1-4 sets $6227 = s during the intro and saves the stage's picture.
    python stages1.py OUTDIR"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
from machine import DKongJr, save_png

out = sys.argv[1]
os.makedirs(out, exist_ok=True)
for stage in (1, 2, 3, 4):
    m = DKongJr()
    last = None
    for f in range(2500):
        m.in2 = 0x80 if 300 <= f < 304 else 0x04 if 400 <= f < 404 else 0
        if f == 450:
            m.mem[0x6227] = stage
        m.run_frame()
        cur = (m.mem[0x6227], m.mem[0x6228], m.mem[0x6229])
        if cur != last and stage == 1:
            print("frame", f, "6227/8/9 =", cur)
            last = cur
        if f in (1000, 1300):
            save_png(m.render_rgb(), os.path.join(out, "s%d_%d.png" % (stage, f)))
    print("stage", stage, "done, 6227 =", m.mem[0x6227])
