"""1943's recorded play for the benchmark (engine/playbot.py; the port replays its inputs by game tick).

    python play_search.py [ticks] [seed]       -> build/1943/play_inputs.bin (2 bytes a tick: SYSTEM, P1)

1943 scrolls by itself, and MAME's cheats (1943.xml, as logic_test.py --cheat and the AUTOPLAY STAGE build: infinite
energy $F206 = $40, invincibility $F214 = 2, set before every tick from PLAY on; the port's PLAYBACK build does the
same) keep the plane alive: no search is needed, the bot only moves and shoots at random (nothing dies, nothing gets
stuck, so it never rewinds).  The port replays the file with build.py -D PLAYBACK=1 (bench.sh PLAY=1);
logic_test.py N --play checks the replay against the reference.
"""
from pathlib import Path
import sys
sys.path[:0] = [str(Path(__file__).resolve().parents[3] / 'engine'), str(Path(__file__).resolve().parent)]
from machine import Game1943
from paths import build_dir
import playbot

COIN, START = 900, 940
UP, DOWN, LEFT, RIGHT, FIRE, LOOP = 8, 4, 2, 1, 16, 32
DIRS = [0, UP, DOWN, LEFT, RIGHT, LEFT, RIGHT, UP | LEFT, UP | RIGHT, DOWN | LEFT, DOWN | RIGHT]


class Game:
    PLAY = 1000
    POS_WRAP = 2
    HIT_BACK = 0
    STUCK = 10 ** 9
    RETRIES = 0

    def machine(self):
        return Game1943()

    def start_system(self, t):
        return 255 & ~(0x40 if COIN <= t < COIN + 5 else 0) & ~(1 if START <= t < START + 5 else 0)

    def tick(self, m, t, system, p1):
        if t >= self.PLAY:
            m.mem[0xf206], m.mem[0xf214] = 0x40, 2
        m.inputs[:3] = [system, p1, 255]
        m.run_frame_port()

    def died(self, m):
        return False

    def pos(self, m):
        return 0

    def snapshot(self, m):
        return None

    def segment(self, rnd):
        """One direction, fire pressed every other 3 ticks, now and then a loop."""
        d = rnd.choice(DIRS)
        loop = rnd.random() < 0.05
        return [255 & ~(d | (FIRE if t % 6 < 3 else 0) | (LOOP if loop and t < 3 else 0)) for t in range(playbot.SEG)]


def main():
    ticks = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    playbot.record(Game(), ticks, seed, build_dir('1943') / 'play_inputs.bin', log=lambda s: print(s, flush=True))


if __name__ == '__main__':
    main()
