"""How often every palette entry shows on screen: the input of the 16 colour palettes (tools/palettes.py).

    python palette_stats.py [frames] [step]  ->  games/1942/docs/palette_stats.json

Runs the reference in the port's schedule with scripted play (tools/logic_test.py inputs, several seeds in turn),
renders every `step`-th frame and counts, per source of the pixel, how often each palette entry occurs in the visible
area: background tiles (entry & 15; the palette bank only adds 16 * bank, so the counts are valid for every bank),
sprites (entries 64-79) and characters (128-143).  Frames with a different palette bank are counted with the bank
removed.
"""
import json
import os
import random
import sys

sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import numpy as np
from machine import Machine1942
import logic_test as lt

DOCS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs")


def main():
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 30000
    step = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    bg = np.zeros(16, np.int64)
    spr = np.zeros(16, np.int64)
    chr_ = np.zeros(16, np.int64)
    banks = {}
    for seed in (1, 2, 3):
        rnd = random.Random(seed)
        m = Machine1942()
        m.run_to_idle()
        m.booted = True
        for f in range(frames):
            m.sys_in, m.p1, m.p2 = lt.inputs(f, rnd)
            m.run_frame_port()
            if f % step == 0 and f > 0:
                bmp = m.render_raw()[16:240]
                h = np.bincount(bmp.ravel(), minlength=256)
                bg += h[0:64].reshape(4, 16).sum(axis=0)
                spr += h[64:80]
                chr_ += h[128:144]
                banks[m.palette_bank] = banks.get(m.palette_bank, 0) + 1
        print("seed", seed, "done", banks, flush=True)
    os.makedirs(DOCS, exist_ok=True)
    out = {"frames": frames, "step": step, "banks_seen": banks, "bg": bg.tolist(), "sprites": spr.tolist(),
           "chars": chr_.tolist()}
    json.dump(out, open(os.path.join(DOCS, "palette_stats.json"), "w"), indent=1)
    print(out)


if __name__ == "__main__":
    main()
