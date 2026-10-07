import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
from dkong import *
m = DKong()
for f in range(199): m.run_frame()
v = m.mem[0x7400:0x7800]
# print top two display rows (col 31, col 30) for rows
for col in (31,30,29):
    print(col, [hex(v[r*32+col]) for r in range(2,10)])
print([hex(x) for x in m.mem[0x7000:0x7040]])
print([hex(x) for x in m.mem[0x6900:0x6940]])
img = m.render_rgb()
print(img.shape)
for y in range(0,12):
    print(''.join('#' if img[y][x].any() else '.' for x in range(0,60)))
