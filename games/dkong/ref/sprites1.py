import sys, os, random, collections, pickle
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from machine import *
from paths import build_dir
seed = int(sys.argv[1]); n = int(sys.argv[2])
rnd = random.Random(seed)
m = DKong()
shapes = collections.Counter(); full = collections.Counter(); maxspr = 0
for f in range(n):
    m.in2 = 0
    if f % 3000 == 100: m.in2 |= 0x80
    if f % 3000 == 200: m.in2 |= 0x04
    m.in0 = rnd.choice([0,0,1,2,4,8,16,17,18])
    if f % 1500 == 900:
        m.mem[0x6227] = rnd.choice([1,2,3,4]); m.mem[0x6229] = rnd.choice([1,2,3,4,5])
    if f % 2500 == 1200: m.mem[0x6228] = 3
    m.run_frame()
    cnt = 0
    for i in range(0, 0x180, 4):
        y, cb, at, x = m.mem[0x6900+i:0x6900+i+4]
        if y == 0 and cb == 0 and at == 0 and x == 0: continue
        if y == 0: continue
        code = (cb & 0x7F) + ((at & 0x40) << 1)
        shapes[(code, bool(at & 0x80), bool(cb & 0x80))] += 1
        full[(code, bool(at & 0x80), bool(cb & 0x80), at & 0x0F, m.palette_bank)] += 1
        cnt += 1
    maxspr = max(maxspr, cnt)
print('shapes', len(shapes), 'full variants', len(full), 'max sprites on screen', maxspr)
pickle.dump((shapes, full), open(build_dir('dkong') / f'sprites_{seed}.pkl', 'wb'))
