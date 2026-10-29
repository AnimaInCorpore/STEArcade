"""Coverage of the sound Z80 in the STE's schedule (tools/sound.py TickBoard), for tools/sndgen.py.  Shared by Track &
Field and Hyper Sports.

    python games/trackfld/ref/cover_sound.py <game> <seed> [frames]  ->  build/<game>/cover_sound<seed>.pkl

Seeds 1-12: the game's commands of ref/cover.py's seed (the game's own port, its inputs and cheats); seeds 101-:
random commands (a command in a frame with probability 1/8: an effect, a phrase, a tune one time in 64, any byte one
time in sixteen).  pcs: the pcs executed; jumps: where computed jumps went; odd: accesses the translation does not
expect (the RAM's mirrors, the timer outside the waits: the run stops); dac: the DAC's non-zero writes outside the tunes; io: (pc, address,
'r' / 'w') of the accesses to $5000-$FFFF; commands: Counter of the commands; events: the DMA's (phrases, tunes).
"""
import collections
import pickle
import random
import sys
from pathlib import Path
GAMES_DIR = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'tools'), str(Path(__file__).resolve().parents[3] / 'engine')]
from sound import TickBoard
from paths import build_dir

RANGES = {'trackfld': (0x35, (0x40, 0x41), (0x80, 0xC4)), 'hyperspt': (0x69, tuple(range(0x40, 0x48)), (0x80, 0xD9))}


def game_commands(game, seed, frames):
    """-> a list of each frame's commands of ref/cover.py's seed in the game's port"""
    sys.path[:0] = [str(GAMES_DIR / game / 'tools'), str(GAMES_DIR / game / 'ref')]
    for m in ('machine', 'cover'):
        sys.modules.pop(m, None)
    import machine
    import cover
    if game == 'trackfld':
        m = machine.TrackFieldPort(*cover.dsw(seed))
        st = {'two': seed in (10, 11)}
    else:
        m = machine.HyperSportsPort(*cover.dsw(seed))
        st = {'two': seed == 11}
    rnd = random.Random(seed)
    out = []
    n = 0
    for f in range(frames):
        m.frame = f
        ins = cover.inputs(f, rnd, st)
        if game == 'trackfld':
            m.system, m.in0, m.in1 = ins
        else:
            m.system, m.p1_p2, m.p3_p4 = ins
        cover.cheats(seed, f, m, st)
        m.run_frame_port()
        out.append([v for fr, v in m.sound_log[n:]])
        n = len(m.sound_log)
    return out


def random_commands(game, seed, frames):
    effects, tunes, speech = RANGES[game]
    rnd = random.Random(seed)
    out = []
    for _ in range(frames):
        if rnd.randrange(8):
            out.append([])
        elif rnd.randrange(16) == 0:
            out.append([rnd.randrange(256)])
        elif rnd.randrange(64) == 0:
            out.append([rnd.choice(tunes)])
        elif rnd.randrange(3) == 0:
            out.append([rnd.choice((rnd.randrange(speech[0], speech[1] + 1), 0xFF))])
        else:
            out.append([rnd.randrange(effects) if rnd.randrange(16) else 0])
    return out


def main():
    game = sys.argv[1]
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    frames = int(sys.argv[3]) if len(sys.argv) > 3 else 20000
    cmds_by_frame = game_commands(game, seed, frames) if seed < 100 else random_commands(game, seed, frames)
    b = TickBoard(game, boot=False)
    c = b.cpu
    pcs, jumps = set(), set()
    computed = [False]
    step0, rd = c.step, b.rd
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
        if a >= 0x5000:
            io.add((site[0], a, 'r'))
        return rd0(a)

    def wr_io(a, v):
        if a >= 0x5000:
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
    out = build_dir(game) / ('cover_sound%d.pkl' % seed)
    ev = collections.Counter((k, n) for _, k, n in b.events)
    out.write_bytes(pickle.dumps({'pcs': pcs, 'jumps': jumps, 'io': io, 'commands': cmds, 'events': ev,
                                  'dac': b.dac_on, 'seed': seed, 'frames': frames}))
    print(out, len(pcs), 'pcs,', len(jumps), 'jump targets,', len(cmds), 'distinct commands,',
          sorted('%s %02X:%d' % (k, n, v) for (k, n), v in ev.items() if k != 'phrase'), sum(
              v for (k, n), v in ev.items() if k == 'phrase'), 'phrases,', b.dac_on, 'DAC pulses')


if __name__ == '__main__':
    main()
