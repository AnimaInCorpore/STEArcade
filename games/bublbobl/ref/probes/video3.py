import os, sys
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "engine")]
from machine import Bublbobl, load
m = Bublbobl()
prom = load("a71-25.41")
N = int(sys.argv[1])
for f in range(N):
    m.in0 = 0x03 | (0x04 if 700 <= f < 706 else 0)
    m.in1 = 0xFF & ~(0x40 if 760 <= f < 766 else 0)
    if f > 900:
        m.in1 &= ~(0x02 if (f // 50) % 2 else 0x01)
        if f % 30 < 3: m.in1 &= ~0x20
    m.run_frame_port()
o = m.oram
print("frame", N)
for i in range(0, 0x300, 4):
    if o[i:i+4] == b"\0\0\0\0": continue
    gfx_num, attr = o[i+1], o[i+3]
    sx = o[i+2]; y = (-o[i]) & 0xFF
    pl = 0x80 + ((gfx_num & 0xE0) >> 1)
    shape = "".join("%X" % prom[pl + k] for k in range(16))
    rows = [yc for yc in range(32) if not prom[pl + yc // 2] & 8]
    print("%3d x=%3d%s y=%3d num=%02X attr=%02X prom=%s rows=%d cols=%s" % (i // 4, sx, "-256" if attr & 0x40 else "    ", y, gfx_num, attr, shape, len(rows),
          "".join("N" if not prom[pl + yc // 2] & 4 else "c" for yc in rows[::2])))
