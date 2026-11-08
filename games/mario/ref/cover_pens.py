"""The pens the picture shows, tiles and sprites apart (the colour fit's training data, tools/assets.py).

    python ref/cover_pens.py <seed> <frames>      ->  build/mario/pens_<seed>.pkl  {'tiles': Counter, 'sprites': Counter,
                                                      'shapes': Counter((code, colour, flipx, flipy))}

Random play as ref/cover.py (free play, infinite lives and bonus time by MAME's cheats), a picture counted every 10th
frame.  The pens include the palette bank ($7E83: pens 0-127 and 128-255).
"""
import sys, os, random, pickle, collections
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from machine import *
from paths import build_dir

seed = int(sys.argv[1]); nframes = int(sys.argv[2])
rnd = random.Random(seed)
m = Mario(); m.gfx = Gfx()
tiles, sprites, shapes = collections.Counter(), collections.Counter(), collections.Counter()
joy = 0; jleft = 0
for f in range(nframes):
    if jleft == 0:
        joy = rnd.choice([0, 0, 1, 2, 16, 17, 18, 1, 2, 0]); jleft = rnd.randint(3, 40)
    jleft -= 1
    m.ram[0x6BF0 - 0x6000] = 1; m.ram[0x6116 - 0x6000] = 7; m.ram[0x66D4 - 0x6000] = 0x99
    m.set_inputs(p1=joy, p2=joy if seed % 5 == 0 else 0, coin=f % 400 == 30, start1=f % 500 in (60, 61, 62), start2=seed % 5 == 0 and f % 500 in (200, 201))
    m.run_frame()
    if f % 10 == 0 and f > 60:
        bmp, issp = m.render_raw(layers=True)
        v, s = bmp[16:240], issp[16:240]
        for p, n in zip(*np.unique(v[~s], return_counts=True)): tiles[int(p)] += int(n)
        for p, n in zip(*np.unique(v[s], return_counts=True)): sprites[int(p)] += int(n)
        for o in range(0, 0x400, 4):
            if m.ram[0x1000 + o]:
                a = m.ram[0x1000 + o + 1]
                shapes[(m.ram[0x1000 + o + 2], (a & 15) + 16 * m.palette_bank, bool(a & 0x80), bool(a & 0x40))] += 1
pickle.dump({'tiles': tiles, 'sprites': sprites, 'shapes': shapes}, open(build_dir('mario') / f'pens_{seed}.pkl', 'wb'))
print('pens', len(tiles), len(sprites), 'shapes', len(shapes))
