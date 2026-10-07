import sys, os, random, collections, pickle
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
from dkong import *
seed=int(sys.argv[1]); n=int(sys.argv[2])
rnd = random.Random(seed)
m = DKong()
used = collections.Counter()
for f in range(n):
    m.in2 = 0
    if f % 3000 == 100: m.in2 |= 0x80
    if f % 3000 == 200: m.in2 |= 0x04
    m.in0 = rnd.choice([0,0,1,2,4,8,16,17,18])
    if f % 1500 == 900:
        m.mem[0x6227] = rnd.choice([1,2,3,4]); m.mem[0x6229] = rnd.choice([1,2,3,4,5])
    if f % 2500 == 1200: m.mem[0x6228] = 3
    m.run_frame()
    if f % 10 == 0:
        bmp = m.render_raw()
        vals, cnts = np.unique(bmp, return_counts=True)
        for v, c in zip(vals.tolist(), cnts.tolist()): used[v] += c
pickle.dump(used, open(f'pens_{seed}.pkl','wb'))
print(len(used))
