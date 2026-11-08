"""Jail Break's recorded play (engine/playbot.py: a search bot on the reference machine, the port replays its inputs
by game tick).

    python play_search.py [ticks] [seed]       -> build/jailbrek/play_inputs.bin

Infinite lives: P1's lives ($15CE, MAME's cheat address) are set to 8 before every tick from PLAY on (the port's
PLAYBACK build does the same, pb_inputs).  The progress: the scroll of a visible row (9 bits, it grows as the player
walks right).  Coin and start as in ref/cover.py.  The port replays the file with build.py -D PLAYBACK=1.
"""
from pathlib import Path
import copy
import sys
sys.path[:0] = [str(Path(__file__).resolve().parents[3] / 'engine'), str(Path(__file__).resolve().parent)]
from machine import JailBreakPort, DSW1, DSW2, DSW3
from paths import build_dir
import playbot

LIVES = 0x15CE
COIN, START = 300, 360
L, R, U, D, FIRE, SEL = 1, 2, 4, 8, 16, 32
DIRS = [0, L, R, R, R, U, D, R | U, R | D, L | U, L | D, R, R]


class Game:
    PLAY = 420
    POS_WRAP = 512
    HIT_BACK = 20
    STUCK = 600
    RETRIES = 6

    def machine(self):
        m = JailBreakPort(DSW1, DSW2, DSW3)
        m.sound_log = []
        return m

    def start_system(self, t):
        return 255 & ~(1 if COIN <= t < COIN + 4 else 0) & ~(8 if START <= t < START + 4 else 0)

    def tick(self, m, t, system, p1):
        if t >= self.PLAY:
            m.mem[LIVES] = 8
        m.frame = t
        m.system, m.p1, m.p2 = system, p1, 255
        m.run_frame_port()
        if len(m.sound_log) > 1000:
            del m.sound_log[:]

    def died(self, m):
        return m.mem[LIVES] < 8

    def pos(self, m):
        return m.mem[0x2000 + 10] + 256 * (m.mem[0x2020 + 10] & 1)

    def snapshot(self, m):
        d = {k: v for k, v in m.__dict__.items() if k not in ('cpu', 'mem', 'sound_log', 'video', 'vlm_rom', 'trace')}
        return (bytes(m.mem), copy.deepcopy(d), dict(m.cpu.__dict__))

    def restore(self, m, s):
        m.mem[:] = s[0]
        m.__dict__.update(copy.deepcopy(s[1]))
        m.cpu.__dict__.update(s[2])

    def segment(self, rnd):
        """One direction (mostly right), fire held on and off, the weapon selected now and then."""
        d, fire = rnd.choice(DIRS), rnd.choice((FIRE, FIRE, 0))
        sel = SEL if rnd.random() < 0.15 else 0
        return [255 & ~(d | (fire if t % 6 < 3 else 0) | (sel if t < 2 else 0)) for t in range(playbot.SEG)]


def main():
    ticks = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    lines = []
    playbot.record(Game(), ticks, seed, build_dir('jailbrek') / 'play_inputs.bin', log=lines.append)
    print('\n'.join(lines[-40:]))


if __name__ == '__main__':
    main()
