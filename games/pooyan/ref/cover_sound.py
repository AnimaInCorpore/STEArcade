"""Coverage of the sound Z80 in the STE's schedule (tools/sound.py TickBoard), for tools/sndgen.py.

    python ref/cover_sound.py <seed> [frames]  ->  build/pooyan/cover_sound<seed>.pkl

Seed 0: the game's commands (machine.PooyanPort with ref/cover.py's inputs and cheats of its seeds 1, 5, 9 and 12:
attract, play through the rounds, the high score, no demo sounds; `frames` each); seeds 1-: random commands (a command
in a frame with probability 1/8: one of the driver's $00-$2A, with bit 7 (stop) one time in four; any byte one time in
sixteen).  pcs: the pcs executed; jumps: where computed jumps went; odd: accesses the translation does not expect
(the RAM's mirrors, deselected AYs, the timer outside the waits: the run stops); io: (pc, address, 'r' / 'w') of the
accesses to $4000-$FFFF (the AYs, the filters); commands: Counter of the commands.
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

GAME_SEEDS = (1, 5, 9, 12)


def commands(seed, frames):
    """-> a list of each frame's commands"""
    if seed == 0:
        from machine import PooyanPort
        import cover
        out = []
        for s in GAME_SEEDS:
            m = PooyanPort(*cover.dsw(s))
            rnd, st = random.Random(s), {'two': s in (10, 11)}
            if s == 13:
                st['coin_at'] = frames
            for f in range(frames):
                m.system, m.p1, m.p2 = cover.inputs(f, rnd, st)
                cover.cheats(s, f, m, st)
                m.run_frame_port()
                out.append([v for fr, v in m.sound_log if fr == f])
        return out
    rnd = random.Random(seed)
    out = []
    for _ in range(frames):
        if rnd.randrange(8):
            out.append([])
        elif rnd.randrange(16) == 0:
            out.append([rnd.randrange(256)])
        else:
            out.append([rnd.randrange(0x2B) | (0x80 if rnd.randrange(4) == 0 else 0)])
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
    io = set()
    site = [0]
    rd0, wr0 = c.rd8, c.wr8

    def rd_io(a):
        if a >= 0x4000:
            io.add((site[0], a, 'r'))
        return rd0(a)

    def wr_io(a, v):
        if a >= 0x4000:
            io.add((site[0], a, 'w'))
        return wr0(a, v)

    def step_site():
        site[0] = c.pc
        return step()
    c.step, c.rd8, c.wr8 = step_site, rd_io, wr_io
    cmds = collections.Counter()
    for fc in commands(seed, frames):
        cmds.update(fc)
        b.run_frame(fc)
    if b.odd:
        raise RuntimeError('unexpected accesses (pc, address, kind): %s' % sorted(set(b.odd))[:20])
    out = build_dir('pooyan') / ('cover_sound%d.pkl' % seed)
    out.write_bytes(pickle.dumps({'pcs': pcs, 'jumps': jumps, 'io': io, 'commands': cmds, 'seed': seed, 'frames': frames}))
    print(out, len(pcs), 'pcs,', len(jumps), 'jump targets,', len(cmds), 'distinct commands')


if __name__ == '__main__':
    main()
