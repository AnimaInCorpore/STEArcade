"""Splatterhouse's recorded play for the benchmark and the coverage (engine/playbot.py: a search bot on the reference
machine's port schedule, machine.run_frame_port; the port replays its inputs by arcade frame from the snapshot's start,
-D PLAYBACK=1).

    venv/bin/python games/splatter/tools/play_search.py [ticks] [seed]   -> build/splatter/play_inputs.bin

A tick is the port's arcade frame t (the reference's frame machine.START + t), its inputs COIN (the system byte) and
CONTROL0 (P1, start in bit 7).  Coin at 30, start at 130 (logic_test.py's schedule), the bot from PLAY on.  Cheats
before every tick from PLAY on, the same in the port's replay and logic_test.py --play: lives ($014F) 3, health
($0139, the hearts) 4.  A hit (health below 4 after a tick) counts as a death for the search: it rewinds and plays
the stretch again.  The progress: the group's horizontal scroll (layer 0's x register falls as Rick walks right).
"""
from pathlib import Path
import sys
sys.path[:0] = [str(Path(__file__).resolve().parents[3] / 'engine'), str(Path(__file__).resolve().parent)]
from machine import Splatter
from paths import build_dir
import playbot

LIVES, HEALTH = 0x14F, 0x139
COIN_IDLE = 0xF8                            # (the board's COIN byte: coin 1 in bit 4)
COIN, START = 30, 130
RIGHT, LEFT, DOWN, UP, ATTACK, JUMP = 1, 2, 4, 8, 16, 32
MOVES = [RIGHT, RIGHT, RIGHT, RIGHT | ATTACK, RIGHT | ATTACK, ATTACK, RIGHT | JUMP, RIGHT | JUMP | ATTACK, JUMP,
         DOWN | ATTACK, LEFT, LEFT | ATTACK, 0, DOWN, UP]


def cheat(m):
    m.ram[LIVES] = 3
    m.ram[HEALTH] = 4


class State:
    """The machine's state by value: every list, bytearray, dict and CPU reachable from it, restored in place (the
    timers are shared lists and the board's closures keep their objects)."""
    CLASSES = ('Splatter', 'M6809', 'YM2151', 'HD63701')

    def __init__(self, m):
        self.items = []
        seen = set()
        todo = [m]
        while todo:
            o = todo.pop()
            if id(o) in seen:
                continue
            seen.add(id(o))
            if isinstance(o, bytearray):
                self.items.append((o, bytes(o)))
                continue
            if isinstance(o, list):
                self.items.append((o, list(o)))
                kids = o
            elif isinstance(o, dict):
                self.items.append((o, dict(o)))
                kids = o.values()
            elif type(o).__name__ in self.CLASSES:
                d = {k: v for k, v in vars(o).items() if not callable(v)}
                self.items.append((o, d))
                kids = d.values()
            else:
                continue
            todo += [k for k in kids if isinstance(k, (list, dict, bytearray)) or type(k).__name__ in self.CLASSES]

    def restore(self):
        for o, v in self.items:
            if isinstance(o, (list, bytearray)):
                o[:] = v
            elif isinstance(o, dict):
                o.clear()
                o.update(v)
            else:
                vars(o).update(v)


class Game:
    PLAY = 200
    SYSTEM = COIN_IDLE
    POS_WRAP = 0x10000
    HIT_BACK = 3
    STUCK = 120
    RETRIES = 6

    def machine(self):
        m = Splatter()
        m.boot()
        return m

    def start_system(self, t):
        return COIN_IDLE & ~(0x10 if COIN <= t < COIN + 6 else 0)

    def start_p1(self, t):
        return 0x7F if START <= t < START + 6 else 0xFF

    def tick(self, m, t, system, p1):
        if t >= self.PLAY:
            cheat(m)
        m.coin_in = system
        m.control_in[0] = p1
        m.run_frame_port()

    def died(self, m):
        return m.ram[HEALTH] < 4 or m.ram[LIVES] < 3

    def pos(self, m):
        return -(m.control[0] << 8 | m.control[1]) & 0xFFFF

    def snapshot(self, m):
        return State(m)

    def restore(self, m, s):
        s.restore()

    def segment(self, rnd):
        """One move held for the segment, the attack pressed in every other 4 ticks, a jump only at its start."""
        d = rnd.choice(MOVES)
        out = []
        for t in range(playbot.SEG):
            b = d & ~(JUMP | ATTACK)
            if d & JUMP and t < 6:
                b |= JUMP
            if d & ATTACK and (t // 4) % 2 == 0:
                b |= ATTACK
            out.append(0xFF & ~b)
        return out


def main():
    ticks = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    playbot.record(Game(), ticks, seed, build_dir('splatter') / 'play_inputs.bin', log=lambda s: print(s, flush=True))


if __name__ == '__main__':
    main()
