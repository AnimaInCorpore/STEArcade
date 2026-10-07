import sys, os, random, collections
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
from dkong import *
m = DKong(); cpu = m.cpu
rnd = random.Random(3)
per_bank = collections.defaultdict(lambda: collections.Counter())
union = collections.defaultdict(set)
maxn = 0
frames_seen = 0
for f in range(30000):
    m.in2 = 0
    r = rnd.random()
    if f % 3000 == 100: m.in2 |= 0x80
    if f % 3000 == 200: m.in2 |= 0x04
    m.in0 = rnd.choice([0,0,1,2,4,8,16,17,18])
    if f % 1500 == 900:
        m.mem[0x6227] = rnd.choice([1,2,3,4]); m.mem[0x6229] = rnd.choice([1,2,3,4,5])
    m.run_frame()
    if f % 40 == 0:
        bmp = m.render_raw()
        pens = set(int(x) for x in set(bmp.flatten().tolist()))
        gfx = m.gfx
        rgb = set()
        for p in pens:
            rgb.add(tuple(v >> 4 for v in gfx.pens[p]))   # STE 4 bit per channel
        rgb.discard((0,0,0))
        union[m.palette_bank] |= rgb
        maxn = max(maxn, len(rgb))
        per_bank[m.palette_bank][len(rgb)] += 1
        frames_seen += 1
print('max distinct non-black colors in a frame:', maxn)
for b in sorted(per_bank): print('bank', b, sorted(per_bank[b].items()))

for b in sorted(union): print('bank',b,'union',len(union[b]), sorted(union[b]))
