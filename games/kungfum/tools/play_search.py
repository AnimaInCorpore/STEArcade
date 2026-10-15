"""Kung-Fu Master's recorded play for the benchmark (engine/playbot.py: a search bot on the reference machine's port
schedule; the port replays its inputs by arcade frame).

    python play_search.py [frames] [seed]       -> build/kungfum/play_inputs.bin

Coin at frame 700, start at 760 (as the AUTOPLAY build); from PLAY on infinite lives ($E084 = 6, MAME's cheat
address, before every frame: the port's PLAYBACK build does the same).  The progress is the distance walked: the
scroll register, falling on floors 1, 3, 5 and rising on 2 and 4, plus $4000 a floor.  The port replays the file with
build.py -D PLAYBACK=1 (bench.sh PLAY=1); logic_test.py N --play checks the replay against the reference.
"""
from pathlib import Path
import sys
sys.path[:0] = [str(Path(__file__).resolve().parents[3] / 'engine'), str(Path(__file__).resolve().parent)]
from machine import KungFuPort
from paths import build_dir
import playbot

LIVES = 0xE084
COIN, START = 700, 760
RIGHT, LEFT, DOWN, UP, KICK, PUNCH = 1, 2, 4, 8, 0x20, 0x80


class Game:
    PLAY = 900
    POS_WRAP = 0x10000
    HIT_BACK = 20
    STUCK = 150
    RETRIES = 6

    def machine(self):
        m = KungFuPort()
        m.cpu.afmask = 0xc1
        return m

    def start_system(self, t):
        return 255 & ~(0x08 if COIN <= t < COIN + 4 else 0) & ~(1 if START <= t < START + 4 else 0)

    def tick(self, m, t, system, p1):
        if t >= self.PLAY:
            m.mem[LIVES] = 6
        m.system, m.p1 = system, p1
        m.frame = t
        m.run_frame_port()
        if len(m.sound_log) > 1000:
            del m.sound_log[:]

    def died(self, m):
        return m.mem[LIVES] < 6

    def pos(self, m):
        floor = m.mem[0xE080] & 7
        s = m.scroll & 0x3FFF
        return (floor * 0x4000 + (0x3FFF - s if floor % 2 == 0 else s)) & 0xFFFF

    def snapshot(self, m):
        return (bytes(m.mem), bytes(m.sprite_ram), m.scroll, m.flip, m.frame, m.irq_count, m.booted, m.idle_pc,
                m.rnd_state, dict(m.cpu.__dict__))

    def restore(self, m, s):
        m.mem[:], m.sprite_ram[:] = s[0], s[1]
        m.scroll, m.flip, m.frame, m.irq_count, m.booted, m.idle_pc, m.rnd_state = s[2:9]
        m.cpu.__dict__.update(s[9])

    def segment(self, rnd):
        """a direction (mostly ahead: the bot finds which way by its progress), a punch or kick pattern"""
        d = rnd.choice([LEFT, LEFT, RIGHT, RIGHT, LEFT | DOWN, RIGHT | DOWN, 0, UP, DOWN])
        b = rnd.choice([0, PUNCH, KICK, PUNCH, KICK])
        return [255 & ~(d | (b if t % 4 < 2 else 0)) for t in range(playbot.SEG)]


def main():
    ticks = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    playbot.record(Game(), ticks, seed, build_dir('kungfum') / 'play_inputs.bin', log=lambda s: print(s, flush=True))


if __name__ == '__main__':
    main()
