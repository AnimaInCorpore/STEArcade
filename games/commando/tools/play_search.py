"""Commando's recorded play for the benchmark (engine/playbot.py: a search bot on the reference machine, the port
replays its inputs by game tick).

    python play_search.py [ticks] [seed]       -> build/commando/play_inputs.bin (2 bytes a tick: SYSTEM, P1)

Infinite lives: $EDA0 is set to 3 before every tick from PLAY on (the port's PLAYBACK build does the same), so the play
never ends; a death costs the way back to the checkpoint.  A hit shows ~250 ticks before $EDA0 drops (HIT_BACK).  The
progress is the scroll register $C808/9 (the game scrolls up as the player walks up).  Coin and start come at the
ticks cover.py uses.  The port replays the file with build.py -D PLAYBACK=1 (bench.sh PLAY=1); logic_test.py N play
checks the replay against the reference.
"""
from pathlib import Path
import sys
sys.path[:0] = [str(Path(__file__).resolve().parents[3] / 'engine'), str(Path(__file__).resolve().parent)]
from machine import Commando, BUILD
import playbot

LIVES = 0xeda0
COIN, START = 700, 740
UP, DOWN, LEFT, RIGHT, FIRE, GRENADE = 8, 4, 2, 1, 16, 32
DIRS = [UP, UP, UP, UP | LEFT, UP | RIGHT, UP | LEFT, UP | RIGHT, LEFT, RIGHT, 0, DOWN, DOWN | LEFT, DOWN | RIGHT]


class Game:
    PLAY = 780
    POS_WRAP = 512
    HIT_BACK = 26               # segments back after a death (and 4 more after each failed retry)
    STUCK = 200                 # segments without new progress before a rewind (gates and bunkers hold the scroll)
    RETRIES = 6                 # rewinds for one death or one stuck stretch before it is accepted

    def machine(self):
        m = Commando(); m.cpu.afmask = 0xc1
        return m

    def start_system(self, t):
        return 255 & ~(128 if COIN <= t < COIN + 6 else 0) & ~(1 if START <= t < START + 6 else 0)

    def tick(self, m, t, system, p1):
        if t >= self.PLAY:
            m.mem[LIVES] = 3
        m.inputs[:3] = [system, p1, 255]
        m.run_frame_port()

    def died(self, m):
        return m.mem[LIVES] < 3

    def pos(self, m):
        return m.scroll[0] | (m.scroll[1] & 1) << 8

    def snapshot(self, m):
        return (bytes(m.mem), bytes(m.sprites), bytes(m.scroll), m.control, m.latch, m.pending, m.frame, m.booted,
                dict(m.cpu.__dict__))

    def restore(self, m, s):
        m.mem[:], m.sprites[:], m.scroll[:] = s[0], s[1], s[2]
        m.control, m.latch, m.pending, m.frame, m.booted = s[3:8]
        m.cpu.__dict__.update(s[8])

    def segment(self, rnd):
        """One direction, fire pressed every other 4 ticks, sometimes a grenade."""
        d = rnd.choice(DIRS)
        grenade = rnd.random() < 0.15
        return [255 & ~(d | (FIRE if (t // 4) % 2 == 0 else 0) | (GRENADE if grenade and t < 3 else 0))
                for t in range(playbot.SEG)]


def main():
    ticks = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    playbot.record(Game(), ticks, seed, BUILD / 'play_inputs.bin', log=lambda s: print(s, flush=True))


if __name__ == '__main__':
    main()
