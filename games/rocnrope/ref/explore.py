"""Go-Explore (docs/go-explore.md) on the reference machine: real play to the later stages, no state pokes.

    python ref/explore.py [seconds] [seed] [out]  ->  build/rocnrope/explore<seed>.pkl  (a list of (SYSTEM, IN0, IN1) per frame)

The player is sprite slot 0 (screen column = $4001, screen row = $4400: the row shrinks as it climbs), the stage is $50C1, lives $50C0.  A cell
is (stage, x // 8, y // 8); the archive keeps the snapshot of each cell and its input
timeline (a cell is replaced when a shorter way to it, or a higher stage, is found).  A segment is
SEG frames of one input; a lost life is not archived (the state is dropped).  The product replays in ref/cover.py as
seed 24 (replay=...).  Writes its file once at the end.
"""
import pickle
import random
import sys
import time
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'tools'), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import RocnRopePort
from paths import build_dir

LEFT, RIGHT, UP, DOWN, B1, B2 = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20
LIVES, STAGE, MODE = 0x50C0, 0x50C1, 0x5005
SEG = 6
DIRS = [0, LEFT, RIGHT, UP, DOWN, LEFT, RIGHT, UP, RIGHT | UP, LEFT | UP]
BTNS = [0, 0, 0, B1, B1, B2]


def snapshot(m):
    return (bytes(m.mem), list(m.latch), m.sound_latch, m.frame, m.watchdog, m.booted, m.irqs, m.next_vblank,
            dict(m.cpu.__dict__))


def restore(m, s):
    m.mem[:] = s[0]
    m.latch[:] = s[1]
    m.sound_latch, m.frame, m.watchdog, m.booted, m.irqs, m.next_vblank = s[2:8]
    m.cpu.__dict__.update(s[8])
    del m.sound_log[:]


def cell(m):
    mem = m.mem
    return (mem[STAGE], mem[0x4001] // 8, mem[0x4400] // 8)


def score(m):
    return m.mem[STAGE] * 1000 + (255 - m.mem[0x4400])


def run(m, n, system, in0):
    for _ in range(n):
        m.system, m.in0, m.in1 = system, in0, 0xFF
        m.run_frame_port()


def boot(seed):
    m = RocnRope = RocnRopePort()
    tl = []
    for system, n in ((0xFF, 600), (0xFE, 4), (0xFF, 56), (0xF7, 4), (0xFF, 20)):
        run(m, n, system, 0xFF)
        tl += [(system, 0xFF, 0xFF)] * n
    while m.mem[MODE] != 1:
        run(m, 1, 0xFF, 0xFF)
        tl.append((0xFF, 0xFF, 0xFF))
    run(m, 30, 0xFF, 0xFF)
    tl += [(0xFF, 0xFF, 0xFF)] * 30
    return m, tl


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 600
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    rnd = random.Random(seed)
    m, base = boot(seed)
    lives0 = m.mem[LIVES]
    # archive: cell -> [snapshot, the segments to it, segment (in0 byte, buttons), depth, visits, score]
    root = ('root',)
    arch = {root: [snapshot(m), (), None, 0, 0, score(m)]}
    t_end = time.time() + secs
    best = (0, root)
    explored = 0
    while time.time() < t_end:
        keys = list(arch)
        w = [1.0 / (1 + arch[k][4]) ** 0.5 * (1 + arch[k][5] / 300.0) for k in keys]
        k = rnd.choices(keys, w)[0]
        arch[k][4] += 1
        restore(m, arch[k][0])
        cur, depth = k, arch[k][3]
        for _ in range(rnd.choice((2, 4, 8, 16))):
            d, b = rnd.choice(DIRS), rnd.choice(BTNS)
            if rnd.random() < 0.5 and cur != root:                       # repeat the cell's last decision
                d, b = arch[cur][2] if arch[cur][2] else (d, b)
            in0 = 0xFF & ~(d | b)
            lives = m.mem[LIVES]
            run(m, SEG, 0xFF, in0)
            explored += SEG
            if m.mem[LIVES] < lives:
                break
            c = cell(m)
            depth += 1
            sc = score(m)
            old = arch.get(c)
            if old is None or depth < old[3] and sc >= old[5]:
                arch[c] = [snapshot(m), arch[cur][1] + ((d, b),), (d, b), depth, old[4] if old else 0, sc]
                if sc > best[0]:
                    best = (sc, c)
                    print(f'{explored} frames, {len(arch)} cells, best score {sc} stage {m.mem[STAGE]}', flush=True)
            cur = c
    # the timeline to the best cell
    path = arch[best[1]][1]
    frames = list(base)
    for d, b in path:
        frames += [(0xFF, 0xFF & ~(d | b), 0xFF)] * SEG
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else build_dir('rocnrope') / f'explore{seed}.pkl'
    out.write_bytes(pickle.dumps({'frames': frames, 'best': best, 'cells': len(arch), 'explored': explored}))
    print(out, len(frames), 'frames, best', best[0], len(arch), 'cells,', explored, 'frames simulated')


if __name__ == '__main__':
    main()
