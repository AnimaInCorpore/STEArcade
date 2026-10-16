"""Double Dragon's recorded play (engine/playbot.py: a search bot on the reference machine's port schedule; the coverage
replays it as ref/cover.py seed -1 to reach the later missions, a PLAYBACK build could replay it for the benchmark).

    python games/ddragon/tools/play_search.py [frames] [seed]       -> build/ddragon/play_inputs.bin

Infinite lives by the DIP switch (DSW1 bits 6-7 = 0, MAME's "Infinite (Cheat)"); coin at frame 700, start at 800.
The bot's P1 byte is the game's P1 with bit 6 (start 1, of no use once playing) standing for button 3 (jump, EXTRA
bit 1) from PLAY on.  The progress: the camera ($0A65 x, $0A62 y) moving right or up.
"""
from pathlib import Path
import copy
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[3] / "engine"), str(Path(__file__).resolve().parent)]
import machine as M
from paths import build_dir
import playbot

COIN, START = 700, 800
RIGHT, LEFT, UP, DOWN, PUNCH, KICK, JUMP = 1, 2, 4, 8, 0x10, 0x20, 0x40
DSW1 = M.DSW1 & 0x3F


def cam(m):
    return (m.mem[0xA65] << 8 | m.mem[0xA66]), (m.mem[0xA62] << 8 | m.mem[0xA63])


class Game:
    PLAY = 1000
    POS_WRAP = 0x10000
    HIT_BACK = 20
    STUCK = 120
    RETRIES = 6

    def machine(self):
        return M.DDragonPort(M.DSW0, DSW1)

    def start_system(self, t):
        return 255 & ~(0x40 if t == COIN else 0)

    def start_p1(self, t):
        return 255 & ~(0x40 if START <= t < START + 6 else 0)

    def tick(self, m, t, system, p1):
        if not system & 0x40:
            m.coin(0x40)
        extra = 0x07
        if t >= self.PLAY:
            if not p1 & 0x40:
                extra &= ~0x02
            p1 |= 0x40
        m.inputs[0], m.inputs[2] = p1, extra
        m.run_frame_port()
        if len(m.sound_log) > 1000:
            del m.sound_log[:]

    def died(self, m):
        return False

    def pos(self, m):
        x, y = cam(m)
        return (x - y) & 0xFFFF

    def snapshot(self, m):
        """the data of the machine and of its two CPUs (their opcode tables are closures over them: restored in place)"""
        def data(o, skip=()):
            return {k: copy.deepcopy(v) for k, v in o.__dict__.items()
                    if k not in skip and not callable(v) and k != "insn"}
        skip = ("main", "mcu", "sub", "snd", "cpus", "ym", "video", "timers", "queues", "deferred")
        return data(m, skip), data(m.main), data(m.mcu)

    def restore(self, m, s):
        for o, d in zip((m, m.main, m.mcu), s):
            for k, v in d.items():
                setattr(o, k, copy.deepcopy(v))

    def segment(self, rnd):
        """a direction (mostly ahead), attacks, now and then a jump"""
        d = rnd.choice([RIGHT, RIGHT, RIGHT, RIGHT | UP, RIGHT | DOWN, UP, DOWN, LEFT, 0])
        b = rnd.choice([0, PUNCH, KICK, PUNCH, KICK, JUMP | KICK, JUMP])
        return [255 & ~(d | (b if t % 4 < 2 else 0)) for t in range(playbot.SEG)]


def main():
    ticks = int(sys.argv[1]) if len(sys.argv) > 1 else 30000
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    out = build_dir("ddragon") / ("play_inputs.bin" if seed == 1 else "play_inputs_%d.bin" % seed)
    playbot.record(Game(), ticks, seed, out, log=lambda s: print(s, flush=True))


if __name__ == "__main__":
    main()
