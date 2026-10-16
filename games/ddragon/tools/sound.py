"""Double Dragon's sound (the Technos driver on the sound 6809: a YM2151 and two MSM5205) recorded per command on the
reference board's sound part (tools/machine.py with the main CPU and the MCU held), as YM2149 channels.

The driver (21j-0-1): the latch IRQ ($880D) keeps a command in $0A; the main loop ($8012) starts it: 1-$7E through the
table at $9000, a tune (its first byte: the channels, from channel 0) or, first byte bit 7, an effect on FM channel 7;
$80-$EF ($88E5) the ADPCM samples; $F0-$FF controls ($FF / $FE / $FD stops).  The YM2151's timer FIRQ ($8885) steps the
sequencer.

    record(cmd, frames) -> [(frame, [(hz, amplitude) for the 8 FM channels])], adpcm starts
"""
from pathlib import Path
import sys

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
import machine as M
from opm import OPM


class SoundBoard(M.DDragon):
    """the board with the main CPU and the MCU held in reset (eating their cycles): the sound CPU alone, its YM2151
    and MSM5205 timers as in MAME"""

    def __init__(self):
        super().__init__()
        for i in (M.MAIN, M.SUB):
            self.suspend[i] = self.nextsuspend[i] = 1
            self.eat[i] = self.nexteat[i] = True
        self.order = [M.SND, M.MAIN, M.SUB]

    def command(self, v):
        self.timer(self.base, lambda: self.latch_write(v))


def booted(frames=60):
    b = SoundBoard()
    for _ in range(frames):
        b.run_frame()
    return b


def record(cmd, frames=600, board=None):
    """the 8 FM channels' (hz, amplitude) at the end of each frame after the command, and the ADPCM starts"""
    b = board or booted()
    w0, a0 = len(b.ym.writes), len(b.adpcm_log)
    t0 = b.base
    b.command(cmd)
    chip = OPM(M.YM_HZ)
    # (the chip's state before: every register written so far)
    for t, r, v in b.ym.writes[:w0]:
        chip.regs[r] = v
    k = w0
    out = []
    for f in range(frames):
        b.run_frame()
        end = b.base
        while k < len(b.ym.writes) and b.ym.writes[k][0] <= end:
            t, r, v = b.ym.writes[k]
            chip.advance(max(0, int((t - t0) * chip.eg_rate / M.AS) - chip.counter))
            chip.write(r, v)
            k += 1
        chip.advance(max(0, int((end - t0) * chip.eg_rate / M.AS) - chip.counter))
        out.append([chip.channel(ch) for ch in range(8)])
    return out, b.adpcm_log[a0:]


def kind(cmd):
    """the table's kind of a command 1-$7E: ("tune", channels) / ("fx", 7)"""
    rom = M.load("21j-0-1")
    p = rom[0x1000 + 2 * cmd] << 8 | rom[0x1000 + 2 * cmd + 1]
    first = rom[p - 0x8000]
    return ("fx", 7) if first & 0x80 else ("tune", first)


if __name__ == "__main__":
    for c in range(1, 0x7F):
        print("%02X" % c, kind(c))
