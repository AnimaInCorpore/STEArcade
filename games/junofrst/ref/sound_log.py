"""The sound commands the game writes: ref/cover.py's play of a seed on the reference (machine.JunoPort), each
frame's latch values at the $8040 triggers -> build/junofrst/sndlog<seed>.pkl  ([frame] -> [values])

    python sound_log.py <seed> [frames]
"""
import pickle
import random
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'tools'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import JunoPort
from paths import build_dir
import cover


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    rnd = random.Random(seed)
    m = JunoPort(*cover.dsw(seed))
    state = {'two': seed == 7, 'coin2': True if seed in (2, 6) else None}
    out = []
    n = 0
    for frame in range(frames):
        m.frame = frame
        m.system, m.p1, m.p2 = cover.inputs(frame, rnd, state)
        m.run_frame_port()
        out.append([v for f, v in m.sound_log[n:]])
        n = len(m.sound_log)
    p = build_dir('junofrst') / ('sndlog%d.pkl' % seed)
    p.write_bytes(pickle.dumps(out))
    import collections
    print(p, collections.Counter(v for c in out for v in c))


if __name__ == '__main__':
    main()
