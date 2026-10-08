"""Which palette entries change between frames (the logo screen).  python ref/pal1.py <from> <frames>"""
import os, sys
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from machine import Bublbobl
m = Bublbobl()
a = int(sys.argv[1]); n = int(sys.argv[2])
for f in range(a):
    m.run_frame_port()
prev = bytes(m.pal)
for f in range(a, a + n):
    m.run_frame_port()
    cur = bytes(m.pal)
    ch = [i // 2 for i in range(0, 512, 2) if cur[i:i + 2] != prev[i:i + 2]]
    print(f, "changed entries (bank:pen):", ["%d:%d" % (e // 16, e % 16) for e in ch][:20], len(ch))
    prev = cur
