"""The STE's sound player (Track & Field's src/sound.s on Musashi with Hyper Sports' driver) against its model
(games/trackfld/tools/sound.py STEBoard), every arcade frame of a game run: games/trackfld/tools/sound_test.py's run()
with this port's harness.

    python sound_test.py [frames] [--seed N] [--tag hyperspt_sim]

The build: python tools/build.py --sim.  Equal every frame: the sound RAM $4000-$4FFF (but the dead stack below SP),
the SN's registers, the YM's registers and channel choice, the schedule's time, the VLM's busy time and the DMA's
last request.
"""
from pathlib import Path
import argparse
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'ref'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
from render_test import Harness
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'trackfld' / 'tools'))
for _m in ('sound', 'sound_test'):
    sys.modules.pop(_m, None)
import sound_test as shared


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=3000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--tag', default='hyperspt_sim')
    args = ap.parse_args()
    shared.run('hyperspt', Harness(args.seed, tag=args.tag), args.frames, args.seed, 0x5000)


if __name__ == '__main__':
    main()
