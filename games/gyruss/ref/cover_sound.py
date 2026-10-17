"""Coverage of the sound Z80 in the STE's schedule (tools/sound.py TickBoard).

    python ref/cover_sound.py <seed> [frames]  ->  build/gyruss/cover_sound<seed>.pkl

Seed 0: the game's commands (machine.GyrussPort with ref/cover.py's inputs of seed 1: attract, play, game over);
seeds 1-: random commands (a command in a frame with probability 1/8, any of 0-255; one of the tunes now and then).
pcs: the pcs executed; jumps: where computed jumps went; dac: Counter of the i8039's commands.
"""
import collections
import pickle
import random
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'tools'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
from sound import TickBoard
from paths import build_dir


def commands(seed, frames):
    """-> a list of each frame's commands"""
    if seed == 0:
        from machine import GyrussPort
        import cover
        m = GyrussPort()
        rnd = random.Random(1)
        st = {}
        out = []
        for f in range(frames):
            m.system, m.p1 = cover.inputs(f, rnd, st, m)
            m.run_frame_port()
            out.append([v for fr, v in m.sound_log if fr == f])
        return out
    rnd = random.Random(seed)
    return [[rnd.randrange(256)] if rnd.randrange(8) == 0 else [] for _ in range(frames)]


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    b = TickBoard()
    c = b.cpu
    pcs, jumps = set(), set()
    computed = [False]
    step0, rd = c.step, b.rd

    def step():
        pc = c.pc
        pcs.add(pc)
        if computed[0]:
            jumps.add(pc)
        op = rd(pc)
        computed[0] = op == 0xe9 or op in (0xdd, 0xfd) and rd((pc + 1) & 0xffff) == 0xe9
        return step0()
    c.step = step
    for cmds in commands(seed, frames):
        b.run_frame(cmds)
    dac = collections.Counter(v for f, v in b.dac_log)
    out = build_dir('gyruss') / ('cover_sound%d.pkl' % seed)
    out.write_bytes(pickle.dumps({'pcs': pcs, 'jumps': jumps, 'dac': dac, 'seed': seed, 'frames': frames}))
    print(out, len(pcs), 'pcs,', len(jumps), 'jump targets, i8039 commands', dict(dac))


if __name__ == '__main__':
    main()
