"""Trojan's recorded play for the benchmark (engine/playbot.py: a search bot on the reference machine's port schedule,
the STE program replays its inputs by arcade frame).

    python games/trojan/tools/play_search.py [frames] [seed]     -> build/trojan/play_inputs.bin

Infinite lives: $CDA0 is set to 3 before every frame from PLAY on (the PLAYBACK build does the same, src/trojan.s
pb_inputs), so the play never ends; a death costs the way back.  The progress is bg1's x scroll ($F800/1, 512 pixels
around).  Coin and start at the frames of the AUTOPLAY schedule (900, 940).  logic_test.py --play checks the replay
against the reference; bench.sh PLAY=1 measures it in Hatari.
"""
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[3] / 'engine'), str(Path(__file__).resolve().parent)]
from machine import TrojanPort
from paths import build_dir
import playbot

LIVES = 0xCDA0
COIN, START = 900, 940
RIGHT, LEFT, DOWN, UP, B1, B2 = 1, 2, 4, 8, 16, 32
DIRS = [RIGHT, RIGHT, RIGHT, RIGHT | UP, RIGHT | DOWN, 0, LEFT, UP, DOWN, RIGHT]


class Game:
    PLAY = 1000
    POS_WRAP = 512
    HIT_BACK = 20
    STUCK = 150
    RETRIES = 6

    def machine(self):
        m = TrojanPort()
        m.run_to_idle()
        m.booted = True
        return m

    def start_system(self, t):
        return 255 & ~(0x40 if COIN <= t < COIN + 5 else 0) & ~(1 if START <= t < START + 5 else 0)

    def tick(self, m, t, system, p1):
        if t >= self.PLAY:
            m.mem[LIVES] = 3
        m.inputs[0], m.inputs[1] = system, p1
        m.run_frame_port()

    def died(self, m):
        return m.mem[LIVES] < 3

    def pos(self, m):
        return m.regs['scroll1x']

    def snapshot(self, m):
        return (bytes(m.mem), bytes(m.sprites), dict(m.regs), bytes(m.scroll), bytes(m.pal_hi), bytes(m.pal_lo),
                m.bank, m.bankreg, m.nmi_mask, m.frame, list(m.inputs), dict(m.cpu.__dict__))

    def restore(self, m, s):
        m.mem[:], m.sprites[:] = s[0], s[1]
        m.regs = dict(s[2])
        m.scroll[:], m.pal_hi[:], m.pal_lo[:] = s[3], s[4], s[5]
        m.bank, m.bankreg, m.nmi_mask, m.frame = s[6:10]
        m.inputs[:] = s[10]
        m.cpu.__dict__.update(s[11])

    def segment(self, rnd):
        """one direction, attack every other 4 frames, sometimes a jump (button 2)"""
        d = rnd.choice(DIRS)
        jump = rnd.random() < 0.2
        return [255 & ~(d | (B1 if (t // 4) % 2 == 0 else 0) | (B2 if jump and t < 4 else 0))
                for t in range(playbot.SEG)]


def main():
    frames = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    playbot.record(Game(), frames, seed, build_dir('trojan') / 'play_inputs.bin', log=lambda s: print(s, flush=True))


if __name__ == '__main__':
    main()
