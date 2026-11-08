"""Go-Explore on the reference machine (docs/go-explore.md): a cell archive over snap.py's snapshot / restore, to reach the
rooms by play (no room cheat; lives kept as in cover.py seeds 4-6).

    python ref/explore.py [seconds] [seed]  ->  prints the archive's reach; F:/claude/tmp/mikie/explore<seed>.pkl once at the end

A cell: (room, mode $2902, play state $2908, the player's position $295A / $295C in 16-pixel buckets).  Each round picks a cell
weighted to few visits, restores it, plays N segments of 12 frames of random input, archives every new cell with the
input timeline (list of (system, p1) per frame) that reached it.  The timeline is the count/SYSTEM/P1 format's source.
"""
import pickle
import random
import sys
import time
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'tools'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
import cover
from machine import MikiePort
from snap import snapshot, restore

SEG = 12
ROOM, STATE, LIVES = 0x2971, 0x2908, 0x2970


def cell(m):
    mem = m.mem
    return (mem[ROOM], mem[0x2902], mem[STATE], mem[0x295A] >> 4, mem[0x295C] >> 4, mem[0x2974], mem[0x297E], mem[0x2958])


def segment(rnd):
    d = rnd.choice((0, 1, 2, 4, 8, 5, 6, 9, 10))
    b = rnd.choice((0, 0, 0x10, 0x20, 0x30))
    return 0xFF ^ d ^ b


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 120
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    rnd = random.Random(seed)
    m = MikiePort(*cover.dsw(4))
    frame = [0]

    def step(system, p1):
        m.frame = frame[0]
        m.system, m.in0, m.in1 = system, p1, 0xFF
        if m.mem[LIVES] < 2:
            m.mem[LIVES] = 2
        m.run_frame_port()
        frame[0] += 1
    inputs = []
    for f in range(800):                     # attract, coin, start, the intro
        sy = 0xFE if 300 <= f < 304 else 0xF7 if 360 <= f < 364 else 0xFF
        step(sy, 0xFF)
        inputs.append((sy, 0xFF))
    archive = {}
    c = cell(m)
    archive[c] = [snapshot(m), tuple(inputs), 0, frame[0]]
    t0 = time.time()
    rounds = 0
    best_room = 0
    while time.time() - t0 < secs:
        rounds += 1
        keys = list(archive)
        w = [1.0 / (1 + archive[k][2]) ** 0.5 for k in keys]
        k = rnd.choices(keys, w)[0]
        snap, tl, _, fr = archive[k]
        archive[k][2] += 1
        restore(m, snap)
        frame[0] = fr
        tl = list(tl)
        for _ in range(rnd.randrange(1, 6)):
            p1 = segment(rnd)
            for _ in range(SEG):
                step(0xFF, p1)
                tl.append((0xFF, p1))
            c = cell(m)
            if c not in archive:
                archive[c] = [snapshot(m), tuple(tl), 0, frame[0]]
                if c[0] > best_room:
                    best_room = c[0]
                    print('room %d reached after %d frames (round %d, %.0f s)' % (c[0], len(tl), rounds, time.time() - t0), flush=True)
    rooms = sorted({k[0] for k in archive})
    print('cells %d, rounds %d, rooms %s, states %s' % (len(archive), rounds, rooms, sorted({k[2] for k in archive})))
    out = Path('F:/claude/tmp/mikie/explore%d.pkl' % seed)
    out.write_bytes(pickle.dumps({k: v[1] for k, v in archive.items() if k[0] == max(rooms)} | {'cells': list(archive)}))
    print(out)


if __name__ == '__main__':
    main()
