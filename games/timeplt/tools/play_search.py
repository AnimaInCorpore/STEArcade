"""Time Pilot's recorded play for the benchmark (engine/playbot.py: a search bot on the reference machine, the port
replays its inputs by game tick).

    python play_search.py [ticks] [seed]       -> build/timeplt/play_inputs.bin

Infinite lives: $AD10 (MAME's cheat address) is set to 7 before every tick from PLAY on (the port's PLAYBACK build does
the same).  The progress: the stage ($AD11) and the kills towards the guardian ($AD02 counts down).  Coin and start
at the AUTOPLAY build's ticks.  The port replays the file with build.py -D PLAYBACK=1 (bench.sh PLAY=1).
"""
from pathlib import Path
import sys
sys.path[:0] = [str(Path(__file__).resolve().parents[3] / 'engine'), str(Path(__file__).resolve().parent)]
from machine import TimepltPort
from paths import build_dir
import playbot

LIVES, STAGE, LEFT_TO_GUARDIAN = 0xAD10, 0xAD11, 0xAD02
COIN, START = 700, 760
L, R, U, D, FIRE = 1, 2, 4, 8, 16
DIRS = [0, L, R, U, D, L | U, L | D, R | U, R | D, L, R, U, D]


class Game:
    PLAY = 840
    POS_WRAP = 0x10000
    HIT_BACK = 20
    STUCK = 400
    RETRIES = 6

    def machine(self):
        m = TimepltPort()
        m.cpu.afmask = 0xc1
        return m

    def start_system(self, t):
        return 255 & ~(1 if COIN <= t < COIN + 4 else 0) & ~(8 if START <= t < START + 4 else 0)

    def tick(self, m, t, system, p1):
        if t >= self.PLAY:
            m.mem[LIVES] = 7
        m.system, m.p1, m.p2 = system, p1, 255
        m.run_frame_port()
        if len(m.sound_log) > 1000:
            del m.sound_log[:]

    def died(self, m):
        return m.mem[LIVES] < 7

    def pos(self, m):
        return (m.mem[STAGE] << 8 | (255 - m.mem[LEFT_TO_GUARDIAN])) & 0xFFFF

    def snapshot(self, m):
        return (bytes(m.mem), list(m.latch), m.nmi_line, m.frame, m.booted, m.rnd_state, list(m.extra),
                dict(m._capt), m.nmi_count, dict(m.cpu.__dict__))

    def restore(self, m, s):
        m.mem[:] = s[0]
        m.latch[:] = s[1]
        m.nmi_line, m.frame, m.booted, m.rnd_state = s[2:6]
        m.extra, m._capt, m.nmi_count = list(s[6]), dict(s[7]), s[8]
        m.cpu.__dict__.update(s[9])

    def segment(self, rnd):
        """One direction, fire pressed every other 3 ticks (or not at all)."""
        d, fire = rnd.choice(DIRS), rnd.choice((FIRE, FIRE, 0))
        return [255 & ~(d | (fire if t % 6 < 3 else 0)) for t in range(playbot.SEG)]


def main():
    ticks = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    playbot.record(Game(), ticks, seed, build_dir('timeplt') / 'play_inputs.bin', log=lambda s: print(s, flush=True))


if __name__ == '__main__':
    main()
