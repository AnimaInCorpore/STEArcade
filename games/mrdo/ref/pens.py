"""The pens the reference shows, for the palette fit (tools/assets.py).

    python ref/pens.py <seed> [frames]  ->  build/mrdo/pens<seed>.pkl

ref/cover.py's inputs and cheats for the seed; every 10th frame the visible picture's pens (machine.MrDo.render_raw,
0-319) counted.  Seeds 7 (two players), 10 (the rack test switch: the scenes go by), 11 / 12 (start scenes 10 / 21) at
8000 frames cover the title, the intermissions and every scene's colours.
"""
import collections
import pickle
import random
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'tools'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
import numpy as np
import cover
from machine import MrDoPort, VIS_X0, VIS_X1, VIS_Y0, VIS_Y1
from paths import build_dir

SEEDS = (7, 10, 11, 12)


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 8000
    rnd = random.Random(seed)
    m = MrDoPort(*cover.dsw(seed))
    state = {'seed': seed}
    pens = collections.Counter()
    for f in range(frames):
        cover.apply_inputs(m, f, rnd, state)
        cover.cheats(seed, f, m, state)
        m.run_frame_port()
        if f % 10 == 0:
            u, n = np.unique(m.render_raw()[VIS_Y0:VIS_Y1, VIS_X0:VIS_X1], return_counts=True)
            pens.update(dict(zip(u.tolist(), n.tolist())))
    out = build_dir('mrdo') / f'pens{seed}.pkl'
    out.write_bytes(pickle.dumps({'pens': pens, 'seed': seed, 'frames': frames}))
    print(out, len(pens), 'pens')


if __name__ == '__main__':
    main()
