"""The colours (master palette entries) the picture shows, for the STE palette fit (tools/assets.py): the play of
ref/cover.py's seeds, a picture sampled every EVERY frames, counted per layer (sprites / tiles).
    python ref/pens.py <seed> <frames> [every]  ->  build/xevious/xevious_pens_<seed>.pkl
"""
import os, pickle, random, sys
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import numpy as np
from paths import build_dir
from machine import Xevious

seed = int(sys.argv[1])
frames = int(sys.argv[2])
every = int(sys.argv[3]) if len(sys.argv) > 3 else 20
rnd = random.Random(seed)
m = Xevious(skip_tests=True, invincible=seed >= 31)
sprites = np.zeros(129, np.int64)
tiles = np.zeros(129, np.int64)
scroll_seen = [set(), set(), set(), set()]
coin_at = 300 + rnd.randrange(300)
state, t0, joy = "attract", 0, 0
for f in range(frames):
    m.in0 = m.in1 = 0xff
    m.dswb |= 1
    if state == "attract" and f >= coin_at:
        state, t0 = "coin", f
    if state == "coin":
        if f < t0 + 5: m.in1 &= ~0x10
        elif f < t0 + 85 and f >= t0 + 80: m.in1 &= ~0x04
        elif f >= t0 + 85: state, t0 = "play", f
    if state == "play":
        g = f - t0
        if g % 12 == 0:
            joy = rnd.choice([0, 1, 2, 3, 4, 5, 6, 7, 8])
        m.in0 &= ~{1: 0x01, 2: 0x03, 3: 0x02, 4: 0x06, 5: 0x04, 6: 0x0c, 7: 0x08, 8: 0x09}.get(joy, 0)
        if rnd.random() < 0.15: m.in1 &= ~0x01
        if rnd.random() < 0.05: m.dswb &= ~1
        if m.n51.mcu.ram[3] == 0 and g > 600:
            state, coin_at = "attract", f + 400
    m.run_frame_port()
    for i in range(4):
        scroll_seen[i].add(m.scroll[i] if i != 0 else 0)
    if f % every == 0 and f > 150:
        bg, spr, fg = m.render_layers()
        top = np.where(fg != 0x80, fg, np.where(spr != 0x80, spr, bg))
        s_mask = (spr != 0x80) & (fg == 0x80)
        sprites += np.bincount(top[s_mask].ravel(), minlength=129)
        tiles += np.bincount(top[~s_mask].ravel(), minlength=129)
    if f % 5000 == 0:
        print(seed, f, state, flush=True)
pickle.dump({"sprites": sprites, "tiles": tiles, "scroll_seen": [sorted(s) for s in scroll_seen]}, open(build_dir("xevious") / ("xevious_pens_%d.pkl" % seed), "wb"))
print("done", seed, "colours", int((sprites + tiles > 0).sum()), "scroll regs seen", [len(s) for s in scroll_seen])
