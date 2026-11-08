"""Coverage of the sound Z80 in the STE's schedule (tools/sound.py TickBoard).

    python ref/cover_sound.py <seed> [frames]  ->  build/junofrst/cover_sound<seed>.pkl

Seed 0: the game's commands (ref/sound_log.py's build/junofrst/sndlog*.pkl: attract, play, game over of seeds 1-12 that
exist), seeds 1-: random commands (a command in a frame with probability 1/6, any of 0-255, half of them 0-31; not $59-$5B, which run into garbage: the game never sends them).
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
        out = []
        for f in sorted(build_dir('junofrst').glob('sndlog*.pkl')):
            out += pickle.loads(f.read_bytes())
        return out[:frames] if frames else out
    rnd = random.Random(seed)
    out = []
    for _ in range(frames):
        if rnd.randrange(6):
            out.append([])
        else:
            v = rnd.randrange(32) if rnd.randrange(2) else rnd.randrange(256)
            out.append([] if v in (0x59, 0x5A, 0x5B) else [v])      # (these run into garbage: the game never sends them)
    return out


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
    out = build_dir('junofrst') / ('cover_sound%d.pkl' % seed)
    out.write_bytes(pickle.dumps({'pcs': pcs, 'jumps': jumps, 'dac': dac, 'seed': seed, 'frames': frames}))
    print(out, len(pcs), 'pcs,', len(jumps), 'jump targets, i8039 commands', dict(dac), 'fast loop heads', b.fast)


if __name__ == '__main__':
    main()
