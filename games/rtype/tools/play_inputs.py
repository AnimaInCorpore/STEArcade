"""The inputs of a lock-step test's play (ref/cover.py press: seeds 4-7 random play, 8+ with the Invulnerability DIP
switch) as the STE program's PLAYBACK table (src/rtype.s): runs of (arcade frames, IN0, IN1), big-endian words, a
zero count at the end.  The program runs the same game the tests compare (its arcade frame k = the test's frame k).

    venv/bin/python games/rtype/tools/play_inputs.py [--seed 8] [--frames 20000] [--start F]
"""
import argparse
import random
import struct
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / "ref"),
                str(Path(__file__).resolve().parents[3] / "engine")]
import cover
from paths import build_dir


class Ports:
    in0 = in1 = 0xFFFF


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=8)
    ap.add_argument("--frames", type=int, default=20000, help="the last frame (exclusive)")
    ap.add_argument("--start", type=int, default=0, help="the first frame (a replay point: snapshot.py REPLAY)")
    args = ap.parse_args()
    m, rng, state = Ports(), random.Random(args.seed), dict(hold=0, bits=0)
    runs = []
    for f in range(args.frames):
        cover.press(m, f, args.seed, rng, state)
        if f < args.start:
            continue
        v = (m.in0 & 0xFFFF, m.in1 & 0xFFFF)
        if runs and tuple(runs[-1][1:]) == v and runs[-1][0] < 0xFFFF:
            runs[-1][0] += 1
        else:
            runs.append([1, *v])
    out = build_dir("rtype") / "play_inputs.bin"
    out.write_bytes(b"".join(struct.pack(">HHH", *r) for r in runs) + bytes(6))
    print("%s: seed %d, frames %d-%d, %d runs" % (out, args.seed, args.start, args.frames, len(runs)))


if __name__ == "__main__":
    main()
