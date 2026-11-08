"""Where a Mario picture's CPU time goes: render_frame sampled per routine (nearest map symbol) over a lock-step run.

    python profile.py [frames] [--seed N]
"""
from pathlib import Path
import argparse, bisect, collections, sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
import render_test as rt
from sim import TRAP1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=600)
    ap.add_argument('--seed', type=int, default=1)
    a = ap.parse_args()
    h = rt.Harness(a.seed)
    names = sorted((v, k) for k, v in h.sym.items() if not k.startswith('SOUND_'))
    addrs = [v for v, _ in names]
    prof = collections.Counter()
    blit = collections.Counter()

    def run_to(targets, count=None):
        cpu, s = h.cpu, h.s
        while True:
            r = cpu.execute(60)
            pc = cpu.r_pc()
            if count == 'render':
                k = names[bisect.bisect_right(addrs, pc) - 1][1]
                prof[k] += r.cycles
            if pc in targets:
                return pc
            if pc in h.bad or s.terminated:
                raise RuntimeError('stopped')
            if pc == TRAP1:
                s.gemdos()
    h.run_to = lambda t, count=None: run_to(t, count)
    for f in range(a.frames):
        h.frame()
    tot = sum(prof.values())
    print('render_frame CPU samples over %d frames: %d cycles a picture' % (a.frames, tot // a.frames))
    for k, n in prof.most_common(25):
        print('%-24s %6.1f%%  %7d' % (k, 100 * n / tot, n // a.frames))


main()
