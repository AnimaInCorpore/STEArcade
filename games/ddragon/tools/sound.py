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


def record(cmd, frames=600, board=None, offsets=None):
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
        if offsets is not None:
            offsets.append(tuple(b.snd_ram[0x1B + 2 * k] << 8 | b.snd_ram[0x1C + 2 * k] for k in range(8)))
    return out, b.adpcm_log[a0:]


def kind(cmd):
    """the table's kind of a command 1-$7E: ("tune", channels) / ("fx", 7)"""
    rom = M.load("21j-0-1")
    p = rom[0x1000 + 2 * cmd] << 8 | rom[0x1000 + 2 * cmd + 1]
    first = rom[p - 0x8000]
    return ("fx", 7) if first & 0x80 else ("tune", first)




# ---- the ADPCM samples, decoded at build time -------------------------------------------------------------------
ADPCM_RATIO = 81815                              # 7812.5 / 6258 in 16.16 (the STE's DMA rate)
MSM_SHIFT = [-1, -1, -1, -1, 2, 4, 6, 8]


def msm_diff():
    """MAME's msm5205 diff_lookup (49 steps x 16 nibbles)"""
    import math
    nbl = [[1 - 2 * (n >> 3), (n >> 2) & 1, (n >> 1) & 1, n & 1] for n in range(16)]
    out = []
    for step in range(49):
        sv = math.floor(16.0 * pow(11.0 / 10.0, step))
        for n in range(16):
            s, b2, b1, b0 = nbl[n]
            out.append(s * (sv * b2 + sv // 2 * b1 + sv // 4 * b0 + sv // 8))
    return out


class Voice:
    """one MSM5205 as MAME decodes it (msm5205.cpp: the 12-bit signal, the step table, the high nibble of a byte
    first; the sample's end resets signal and step), read at 6258 Hz from its 7812.5 Hz"""

    def __init__(self, rom, diff):
        self.rom, self.diff = rom, diff
        self.on = False

    def start(self, a, b):
        self.pos, self.end = a, b
        self.acc = self.sig = self.step = 0
        self.half = False
        self.on = True

    def sample(self):
        if not self.on:
            return 0
        self.acc += ADPCM_RATIO
        while self.acc >= 0x10000:
            self.acc -= 0x10000
            if self.half:
                n = self.byte & 15
                self.half = False
            else:
                if self.pos >= self.end:
                    self.on = False
                    self.sig = self.step = 0
                    return 0
                self.byte = self.rom[self.pos]
                self.pos += 1
                n = self.byte >> 4
                self.half = True
            self.sig = max(-2048, min(2047, self.sig + self.diff[self.step * 16 + n]))
            self.step = max(0, min(48, self.step + MSM_SHIFT[n & 7]))
        return self.sig


def adpcm_commands():
    """[(chip, start, end) for the commands $80-$9A]: the driver's table at $8966 (21j-0-1): bit 0 of the first
    byte set chip 0 (21j-6), else chip 1 (21j-7); the start and the end >> 1 in 512-byte units"""
    table = M.load("21j-0-1")[0x0966:0x0966 + 27 * 3]
    out = []
    for c in range(27):
        e = table[3 * c:3 * c + 3]
        chip = 0 if e[0] & 1 else 1
        base = 0 if chip == 0 else 0x10000
        out.append((chip, base + (((e[1] >> 1) & 0x7F) << 9), base + (((e[2] >> 1) & 0x7F) << 9)))
    return out


def adpcm_stream(chip, a, b, rom=None, diff=None):
    """a command's samples at 6258 Hz, each the 12-bit signal >> 4 (-128..127), up to the sample's end"""
    rom = rom or (M.load("21j-6") + M.load("21j-7"))
    v = Voice(rom, diff or msm_diff())
    v.start(a, b)
    out = []
    while True:
        s = v.sample()
        if not v.on:
            return out
        out.append(s >> 4)


# ---- the music on the YM2149 ------------------------------------------------------------------------------------
import capsnd
from capsnd import ym_period, ym_volume, encode_channel


def voices(frames, channels=range(8)):
    """[(period, volume) x 3] a frame: the loudest FM channels (of `channels`), a channel whose YM period another chosen
    one has left out (an echo, a doubled line), each kept on its YM voice while it stays chosen"""
    out, held = [], [None, None, None]
    for chans in frames:
        cand = sorted(((a, ch, ym_period(hz)) for ch, (hz, a) in enumerate(chans) if ch in channels and ym_volume(a)),
                      reverse=True)
        pick, periods = [], set()
        for a, ch, p in cand:
            if p in periods:
                continue
            pick.append((ch, p, ym_volume(a)))
            periods.add(p)
            if len(pick) == 3:
                break
        chosen = {ch for ch, p, v in pick}
        held = [h if h in chosen else None for h in held]
        for ch, p, v in pick:
            if ch not in held:
                held[held.index(None)] = ch
        row = []
        for h in held:
            e = next(((p, v) for ch, p, v in pick if ch == h), None)
            row.append(e if e else (0, 0))
        out.append(row)
    return out


def record_tune(cmd, frames):
    """(the 8 channels' (hz, amplitude) a frame, the driver's channel offsets a frame: $1B + 2k)"""
    b = booted()
    offs = []
    chip_rows, _ = [], None
    out, _ = record(cmd, frames, board=b, offsets=offs)
    return out, offs


def find_loop(offs, least=300):
    """(start, length) of the tune's loop from the driver's channel offsets: the length at which the offset vectors
    match best (the YM2151's timer drifts a frame against the frame), the start the first frame of the matching
    stretch; None when they never repeat"""
    T = len(offs)
    best = None
    for n in range(least, T // 2):
        m = sum(1 for f in range(T - 2 * n, T - n) if offs[f] == offs[f + n]) / n
        if best is None or m > best[0]:
            best = (m, n)
    if best is None or best[0] < 0.5:
        return None
    m, n = best
    for s in range(0, T - 2 * n):
        w = range(s, s + 200)
        if sum(1 for f in w if offs[f] == offs[f + n]) >= 0.8 * 200 * m and offs[s] == offs[s + n]:
            return s, n
    return T - 2 * n, n


def tune(cmd, frames=12000):
    """a tune's three voices: (rows up to the loop's second start or its end, loop start or -1)"""
    out, offs = record_tune(cmd, frames)
    rows = [tuple(r) for r in voices(out)]
    on = [i for i in range(len(rows)) if any(v for p, v in rows[i])]
    end = on[-1] + 1 if on else 0
    if end < len(rows) - 60:                     # (it ended: no loop)
        return rows[:end], -1
    loop = find_loop(offs)
    if loop is None:
        return rows[:3600], 0
    s, n = loop
    return rows[:s + n], s


def effect(cmd, frames=600):
    """an FM effect (channel 7) as one voice, up to its end"""
    out, _ = record(cmd, frames)
    rows = [(ym_period(hz), ym_volume(a)) if ym_volume(a) else (0, 0) for hz, a in (f[7] for f in out)]
    on = [i for i, (p, v) in enumerate(rows) if v]
    return rows[:on[-1] + 1] if on else []


def emit(path, tunes, effects):
    """music_data.s for src/sound.s: mu_table (128 longs: the command's tune header or 0), fx_table (128 longs: the
    effect's header or 0); a tune header: three stream pointers, three loop offsets (words, -1: none); an effect
    header: its stream, its loop (-1).  The streams in engine/capsnd.py's encoding (encode_channel)."""
    lines = ["\tsection data,data", "\teven", "mu_table:"]
    lines += ["\tdc.l %s" % ("mu_%02X" % c if c in tunes else "0") for c in range(128)]
    lines += ["fx_table:"]
    lines += ["\tdc.l %s" % ("fx_%02X" % c if c in effects else "0") for c in range(128)]
    size = 0
    for c, (rows, loop) in sorted(tunes.items()):
        enc = [encode_channel([r[k] for r in rows] or [(0, 0)], loop) for k in range(3)]
        lines += ["\teven", "mu_%02X:" % c, "\tdc.l " + ",".join("mu_%02X_%d" % (c, k) for k in range(3)),
                  "\tdc.w " + ",".join(str(e[1]) for e in enc)]
        for k, (data, lp) in enumerate(enc):
            lines += ["mu_%02X_%d:" % (c, k)] + ["\tdc.b " + ",".join(str(x) for x in data[i:i + 32])
                                                for i in range(0, len(data), 32)]
            size += len(data)
    for c, rows in sorted(effects.items()):
        data, lp = encode_channel(rows or [(0, 0)], -1)
        lines += ["\teven", "fx_%02X:" % c, "\tdc.l fx_%02X_s" % c, "\tdc.w -1", "fx_%02X_s:" % c]
        lines += ["\tdc.b " + ",".join(str(x) for x in data[i:i + 32]) for i in range(0, len(data), 32)]
        size += len(data)
    lines += ["\teven"]
    Path(path).write_text("\n".join(lines) + "\n")
    return size


def build_music(build, tune_cmds, fx_cmds, again=False):
    """records the tunes and effects (cached in build/ddragon/music.pkl), emits music_data.s"""
    import pickle
    cache = build / "music.pkl"
    data = pickle.loads(cache.read_bytes()) if cache.exists() and not again else {"tunes": {}, "fx": {}}
    from multiprocessing import Pool
    todo_t = [c for c in tune_cmds if c not in data["tunes"]]
    todo_f = [c for c in fx_cmds if c not in data["fx"]]
    if todo_t or todo_f:
        with Pool(8) as p:
            for c, r in zip(todo_t, p.map(tune, todo_t)):
                data["tunes"][c] = r
            for c, r in zip(todo_f, p.map(effect, todo_f)):
                data["fx"][c] = r
        cache.write_bytes(pickle.dumps(data))
    tunes = {c: data["tunes"][c] for c in tune_cmds}
    effects = {c: data["fx"][c] for c in fx_cmds}
    return emit(build / "music_data.s", tunes, effects)


if __name__ == "__main__":
    for c in range(1, 0x7F):
        print("%02X" % c, kind(c))
