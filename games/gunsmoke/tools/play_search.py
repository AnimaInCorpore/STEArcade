"""Gun.Smoke's recorded play for the benchmark (engine/playbot.py: a search bot on the reference machine, the port
replays its inputs by game tick).

    python play_search.py [ticks] [seed]       -> build/gunsmoke/play_inputs.bin (2 bytes a tick: SYSTEM, P1)

Infinite lives: $E040 (MAME's cheat address) is set to 3 before every tick from PLAY on (the port's PLAYBACK build does
the same).  The progress is the scroll position $D800/1 (it drops back to the checkpoint after a death).  Coin and
start at the ticks of the AUTOPLAY build.  The port replays the file with build.py -D PLAYBACK=1 (bench.sh PLAY=1);
logic_test.py N --play checks the replay against the reference.
"""
from pathlib import Path
import sys
sys.path[:0] = [str(Path(__file__).resolve().parents[3] / 'engine'), str(Path(__file__).resolve().parent)]
from machine import GunSmoke
from paths import build_dir
import playbot

LIVES = 0xe040
COIN, START = 700, 740
UP, DOWN, LEFT, RIGHT = 8, 4, 2, 1
SHOTS = [0x20, 0x20, 0x10, 0x40, 0x30, 0x60, 0x50]      # buttons 1-3: shoot left, straight, right
DIRS = [UP, UP, UP, UP | LEFT, UP | RIGHT, LEFT, RIGHT, LEFT, RIGHT, 0, DOWN, DOWN | LEFT, DOWN | RIGHT]


class Game:
    PLAY = 800
    POS_WRAP = 0x10000
    HIT_BACK = 26
    STUCK = 200
    RETRIES = 6

    def machine(self):
        m = GunSmoke(); m.cpu.afmask = 0xc1
        return m

    def start_system(self, t):
        return 255 & ~(0x40 if COIN <= t < COIN + 4 else 0) & ~(1 if START <= t < START + 4 else 0)

    def tick(self, m, t, system, p1):
        if t >= self.PLAY:
            m.mem[LIVES] = 3
        m.inputs[0], m.inputs[1] = system, p1
        m.run_frame_port()
        if len(m.io_log) > 1000:
            del m.io_log[:]

    def died(self, m):
        return m.mem[LIVES] < 3

    def pos(self, m):
        return m.mem[0xd800] | m.mem[0xd801] << 8

    def snapshot(self, m):
        return (bytes(m.mem), bytes(m.sprites), m.bank, m.control, m.layers, m.sound_latch, m.frame, m.irq_count,
                m.pending_irq, m.booted, dict(m.cpu.__dict__))

    def restore(self, m, s):
        m.mem[:], m.sprites[:] = s[0], s[1]
        m.bank, m.control, m.layers, m.sound_latch, m.frame, m.irq_count, m.pending_irq, m.booted = s[2:10]
        m.cpu.__dict__.update(s[10])

    def segment(self, rnd):
        """One direction, a shot pattern pressed every other 3 ticks."""
        d, shot = rnd.choice(DIRS), rnd.choice(SHOTS)
        return [255 & ~(d | (shot if t % 6 < 3 else 0)) for t in range(playbot.SEG)]


def main():
    ticks = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    playbot.record(Game(), ticks, seed, build_dir('gunsmoke') / 'play_inputs.bin', log=lambda s: print(s, flush=True))


if __name__ == '__main__':
    main()
