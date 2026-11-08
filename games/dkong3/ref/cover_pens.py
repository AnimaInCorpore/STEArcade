"""The pens the picture shows, tiles and sprites apart (the colour fit's training data, tools/assets.py).

    python ref/cover_pens.py <seed> <frames>      ->  build/dkong3/pens_<seed>.pkl  {'tiles': Counter, 'sprites': Counter,
                                                      'shapes': Counter((code, colour, display flip x, display flip y))}

Random play as ref/cover.py (coins, starts, a random joystick and fire), a picture counted every 10th frame.  The pens
include the palette bank ($7E86-$7E87: pens 0-63, 64-127, ...).  A shape's flips are the picture's (the display is the
arcade bitmap turned: the arcade's flip y is the display's flip x and the other way round; the screen flip inverts both).
"""
import sys, os, random, pickle, collections
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from machine import *
from paths import build_dir

seed = int(sys.argv[1]); nframes = int(sys.argv[2])
rnd = random.Random(seed)
m = DK3(); m.gfx = Gfx()
tiles, sprites, shapes = collections.Counter(), collections.Counter(), collections.Counter()
joy = 0; jleft = 0
for f in range(nframes):
    if jleft == 0:
        joy = rnd.choice([0, 0, 1, 2, 4, 8, 16, 17, 18, 5, 9, 1, 2, 0]); jleft = rnd.randint(3, 40)
    jleft -= 1
    if seed >= 7:                                       # later stages: the stage byte $601B poked at each start, lives and credits
        m.ram[0x6BF1 - 0x6000] = 0x63
        m.ram[0x601A - 0x6000] = 6
        if f % 500 in range(63, 200):
            m.ram[0x601B - 0x6000] = (seed + f // 500) % 6
    m.set_inputs(p1=joy, p2=joy if seed % 5 == 0 else 0, coin=f % 400 == 30, start1=f % 500 in (60, 61, 62), start2=seed % 5 == 0 and f % 500 in (200, 201))
    m.run_frame()
    if f % 10 == 0 and f > 60:
        bmp, issp = m.render_raw(layers=True)
        v, s = bmp[16:240], issp[16:240]
        for p, n in zip(*np.unique(v[~s], return_counts=True)): tiles[int(p)] += int(n)
        for p, n in zip(*np.unique(v[s], return_counts=True)): sprites[int(p)] += int(n)
        base = 0x1000 + (m.sprite_bank << 9)
        for o in range(0, 0x200, 4):
            if m.ram[base + o]:
                b1, b2 = m.ram[base + o + 1], m.ram[base + o + 2]
                fx, fy = bool(b1 & 0x80), bool(b2 & 0x80)          # (display: raw flip y, raw flip x)
                if m.flip:
                    fx, fy = not fx, not fy
                shapes[((b1 & 0x7F) | ((b2 & 0x40) << 1), (b2 & 15) + 16 * m.palette_bank, fx, fy)] += 1
pickle.dump({'tiles': tiles, 'sprites': sprites, 'shapes': shapes}, open(build_dir('dkong3') / f'pens_{seed}.pkl', 'wb'))
print('pens', len(tiles), len(sprites), 'shapes', len(shapes))
