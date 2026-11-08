"""The screen of a RAM.BIN (a -D RATE build's dump at the quit: $8000-$9FFF and the video latch) drawn by the reference
renderer: python ramshot.py RAM.BIN out.png"""
import os, sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from machine import DigDug, Gfx, save_png
import numpy as np
d = open(sys.argv[1], "rb").read()
m = DigDug(skip_tests=True)
m.gfx = Gfx()
m.ram[:] = d[:0x2000]
m.vlatch[:] = [b & 1 for b in d[0x2000:0x2008]]
save_png(m.render_rgb(), sys.argv[2], 1)
