"""Black Tiger's recorded play for the benchmark (engine/playbot.py: a search bot on the reference machine, the port
replays its inputs by game tick).

    python play_search.py [ticks] [seed]       -> build/blktiger/play_inputs.bin (runs of count, SYSTEM, P1)

Infinite lives: $F3A0 is set to 3 before every tick from PLAY on (the cheat of ref/cover.py's seeds 4-11; the port's
PLAYBACK build does the same).  The progress is the horizontal scroll (ports 8/9: the first stages lead right).  Coin
and start at the ticks of logic_test.py's default schedule.  The port replays the file with build.py -D PLAYBACK=1
(bench.sh PLAY=1); logic_test.py N --play checks the replay against the reference.
"""
from pathlib import Path
import sys
sys.path[:0] = [str(Path(__file__).resolve().parents[3] / 'engine'), str(Path(__file__).resolve().parent)]
from machine import BlackTiger
from paths import build_dir
import playbot

LIVES = 0xf3a0
COIN, START = 900, 940
UP, DOWN, LEFT, RIGHT, ATTACK, JUMP = 8, 4, 2, 1, 16, 32
DIRS = [RIGHT, RIGHT, RIGHT, RIGHT, RIGHT | JUMP, RIGHT | JUMP, JUMP, UP, DOWN, LEFT, LEFT | JUMP, 0, RIGHT | UP]


def copy_state(d):
    return {k: bytearray(v) if isinstance(v, bytearray) else v for k, v in d.items()}


class Game:
    PLAY = 1000
    POS_WRAP = 0x10000
    HIT_BACK = 26
    STUCK = 200
    RETRIES = 6

    def machine(self):
        return BlackTiger()

    def start_system(self, t):
        return 255 & ~(0x40 if COIN <= t < COIN + 5 else 0) & ~(1 if START <= t < START + 5 else 0)

    def tick(self, m, t, system, p1):
        if t >= self.PLAY:
            m.mem[LIVES] = 3
        m.inputs[:3] = [system, p1, 255]
        m.run_frame_port()
        if len(m.io_log) > 1000:
            del m.io_log[:]

    def died(self, m):
        return m.mem[LIVES] < 3

    def pos(self, m):
        return m.scroll[0] | m.scroll[1] << 8

    def snapshot(self, m):
        return (bytes(m.mem), bytes(m.bg), bytes(m.sprites), bytes(m.scroll),
                (m.bank, m.bg_bank, m.control, m.video_enable, m.layout, m.sound_latch, m.coin_lockout, m.booted,
                 m.frame, m.pending_irq, m.irq_count),
                dict(m.cpu.__dict__), copy_state(m.mcu.__dict__))

    def restore(self, m, s):
        m.mem[:], m.bg[:], m.sprites[:], m.scroll[:] = s[0], s[1], s[2], s[3]
        (m.bank, m.bg_bank, m.control, m.video_enable, m.layout, m.sound_latch, m.coin_lockout, m.booted,
         m.frame, m.pending_irq, m.irq_count) = s[4]
        m.cpu.__dict__.update(s[5])
        m.mcu.__dict__.update(copy_state(s[6]))

    def segment(self, rnd):
        """One move (mostly right, jumps), attack pressed every other 4 ticks."""
        d = rnd.choice(DIRS)
        return [255 & ~((d & ~JUMP) | (JUMP if d & JUMP and t < 6 else 0) | (ATTACK if (t // 4) % 2 == 0 else 0))
                for t in range(playbot.SEG)]


def main():
    ticks = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    playbot.record(Game(), ticks, seed, build_dir('blktiger') / 'play_inputs.bin', log=lambda s: print(s, flush=True))


if __name__ == '__main__':
    main()
