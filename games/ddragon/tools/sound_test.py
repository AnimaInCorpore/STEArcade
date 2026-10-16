"""src/sound.s's ADPCM player (run/ddragon_sim) against a model of it: MAME's MSM5205 decoding (tools/sound.py Voice:
msm5205.cpp's step table, the 12-bit signal, the high nibble first, the sample's end resets the chip) of the driver's
samples (21j-0-1's table at $8966), 7812.5 Hz read at 6258 Hz in 16.16, each chip's signal >> 4, the two summed and
clipped to 8 bits.  (The player plays streams decoded at build time from the same decoder: this checks the streams,
the command starts, the restarts and the mixing.)

    python games/ddragon/tools/sound_test.py

Every sample command $80-$9A alone, then a few overlapping, through snd_frame (126 samples a call in the SIM build):
every written byte compared.
"""
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
from sim import Sim, TRAP1
from machine68k import Register as R
from machine import load
from paths import ROOT, build_dir
import sound


class Model:
    def __init__(self):
        self.rom = load("21j-6") + load("21j-7")
        self.cmds = sound.adpcm_commands()
        d = sound.msm_diff()
        self.v = [sound.Voice(self.rom, d), sound.Voice(self.rom, d)]

    def command(self, c):
        if not 0x80 <= c < 0x9B:
            return
        chip, a, b = self.cmds[c & 0x7F]
        self.v[chip].start(a, b)

    def samples(self, n):
        out = []
        for _ in range(n):
            s = (self.v[0].sample() >> 4) + (self.v[1].sample() >> 4)
            out.append(max(-128, min(127, s)) & 0xFF)
        return out


def main():
    run = ROOT / "run" / "ddragon_sim"
    sim = Sim(str(run / "DDRAGON.PRG"), run_dir=run)
    sim.mem.set_trace_mode(False)
    sym = {k: v + sim.base for k, v in sim.symbols(build_dir("ddragon") / "ddragon_sim.map").items()}
    mem, cpu = sim.mem, sim.cpu
    stop = sym["sim_wait"]

    def call(label):
        sp = cpu.r_reg(R.A7) - 4
        mem.w32(sp, stop)
        cpu.w_reg(R.A7, sp)
        cpu.w_pc(sym[label])
        while cpu.r_pc() != stop:
            cpu.execute(2000)

    while cpu.r_pc() != stop:                      # (the program's start: sim_wait)
        cpu.execute(2000)
    call("snd_init")
    model = Model()
    script = [[c] + [None] * 60 for c in range(0x80, 0x9B)]          # each alone, 60 calls (about 1.2 s)
    script += [[0x80, None, 0x86, None, None, 0x92] + [None] * 30, [0x95, 0x97] + [None] * 40]
    bad = calls = 0
    for seq in script:
        for c in seq:
            if c is not None:
                h = mem.r8(sym["snd_head"])
                mem.w8(sym["snd_ring"] + h, c)
                mem.w8(sym["snd_head"], (h + 1) & 0xFF)
                model.command(c)
            w = mem.r16(sym["snd_wpos"])
            call("snd_frame")
            got = [mem.r8(sym["snd_buf"] + ((w + i) & 1023)) for i in range(126)]
            want = model.samples(126)
            calls += 1
            if got != want:
                bad += 1
                if bad <= 5:
                    i = next(i for i in range(126) if got[i] != want[i])
                    print("call %d: sample %d %02X, model %02X" % (calls, i, got[i], want[i]))
    print("ADPCM: %d calls, %d differ" % (calls, bad))
    # the YM player: each tune and effect of music.pkl through snd_frame, its registers (ym_regs) against
    # engine/capsnd.py's Channel decoding the same streams
    import pickle
    import capsnd
    music = pickle.loads((build_dir("ddragon") / "music.pkl").read_bytes())
    import build as B
    ybad = yframes = 0
    for c in B.TUNES + B.EFFECTS:
        h = mem.r8(sym["snd_head"])
        mem.w8(sym["snd_ring"] + h, 0xFD)                   # (everything stopped first)
        mem.w8(sym["snd_ring"] + ((h + 1) & 0xFF), c)
        mem.w8(sym["snd_head"], (h + 2) & 0xFF)
        if c in B.TUNES:
            rows, loop = music["tunes"][c]
            chans = [capsnd.Channel(*capsnd.encode_channel([r[k] for r in rows] or [(0, 0)], loop)) for k in range(3)]
        else:
            chans = [None, None, capsnd.Channel(*capsnd.encode_channel(music["fx"][c] or [(0, 0)], -1))]
        for f in range(min(3000, 2 * len(rows) if c in B.TUNES else 400)):
            call("snd_frame")
            regs = [mem.r8(sym["ym_regs"] + i) for i in range(11)]
            for k, ch in enumerate(chans):
                if ch is None:
                    continue
                p, v = ch.step()
                got = (regs[2 * k] | regs[2 * k + 1] << 8, regs[8 + k])
                yframes += 1
                if got != (p, v) and not (v == 0 and got[1] == 0):
                    ybad += 1
                    if ybad <= 5:
                        print("command %02X frame %d voice %d: %s, model %s" % (c, f, k, got, (p, v)))
    print("YM: %d voice frames, %d differ" % (yframes, ybad))
    return int(bad != 0 or ybad != 0)


if __name__ == "__main__":
    sys.exit(main())
