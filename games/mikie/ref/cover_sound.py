"""Coverage of the sound Z80 in the STE's schedule (tools/sound.py TickBoard), for tools/sndgen.py.

    python games/mikie/ref/cover_sound.py <seed> [frames]  ->  build/mikie/cover_sound<seed>.pkl

Seeds 1-9: the game's commands of ref/cover.py's seed (the game's own port, its inputs and cheats); seeds 101-: random
commands (a command in a frame with probability 1/8: mostly the driver's effect range, any byte one time in sixteen).
pcs: the pcs executed; jumps: where computed jumps went; io: (pc, address, 'r' / 'w') of the accesses to $4400-$FFFF;
commands: Counter of the commands.  An unexpected access (the timer outside the waits, an unmapped address) stops the run.
"""
import collections
import pickle
import random
import sys
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'tools'), str(Path(__file__).resolve().parents[1] / 'ref'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
from sound import TickBoard
from paths import build_dir


def game_commands(seed, frames):
    """-> a list of each frame's commands of ref/cover.py's seed in the game's port"""
    import cover
    from machine import MikiePort
    m = MikiePort(*cover.dsw(seed))
    rnd = random.Random(seed)
    state = {'two': seed in (7, 8)}
    out, n = [], 0
    for f in range(frames):
        m.frame = f
        m.system, m.in0, m.in1 = cover.inputs(f, rnd, state)
        cover.cheats(seed, f, m, state)
        m.run_frame_port()
        out.append([v for fr, v in m.sound_log[n:]])
        n = len(m.sound_log)
    return out


def random_commands(seed, frames):
    rnd = random.Random(seed)
    out = []
    for _ in range(frames):
        if rnd.randrange(8):
            out.append([])
        elif rnd.randrange(16) == 0:
            out.append([rnd.randrange(256)])
        else:
            out.append([rnd.randrange(0x40) if rnd.randrange(8) else rnd.randrange(0x40, 0x80)])
    return out


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    cmds_by_frame = game_commands(seed, frames) if seed < 100 else random_commands(seed, frames)
    b = TickBoard(boot=False)
    c = b.cpu
    pcs, jumps = set(), set()
    computed = [False]
    step0 = c.step
    io = set()
    site = [0]

    def step():
        pc = c.pc
        site[0] = pc
        pcs.add(pc)
        if computed[0]:
            jumps.add(pc)
        op = b.mem[pc]
        computed[0] = op == 0xe9 or op in (0xdd, 0xfd) and b.mem[(pc + 1) & 0xffff] == 0xe9
        return step0()
    rd0, wr0 = c.rd8, c.wr8

    def rd_io(a):
        if a >= 0x4400:
            io.add((site[0], a, 'r'))
        return rd0(a)

    def wr_io(a, v):
        if a >= 0x4400:
            io.add((site[0], a, 'w'))
        return wr0(a, v)
    c.step, c.rd8, c.wr8 = step, rd_io, wr_io
    b.boot()
    cmds = collections.Counter()
    for fc in cmds_by_frame:
        cmds.update(fc)
        b.run_frame(fc)
    if b.odd:
        raise RuntimeError('unexpected accesses (pc, address, kind): %s' % sorted(set(b.odd))[:20])
    out = build_dir('mikie') / ('cover_sound%d.pkl' % seed)
    out.write_bytes(pickle.dumps({'pcs': pcs, 'jumps': jumps, 'io': io, 'commands': cmds, 'seed': seed, 'frames': frames}))
    print(out, len(pcs), 'pcs,', len(jumps), 'jump targets,', len(cmds), 'distinct commands:',
          ' '.join('%02X' % k for k in sorted(cmds)))


if __name__ == '__main__':
    main()
