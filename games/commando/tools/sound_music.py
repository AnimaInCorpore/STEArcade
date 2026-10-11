"""Commando's music as square waves: the sound driver's FM tunes recorded per channel, for src/music.s.

The driver (audio ROM): commands $20-$2C start a tune (their handlers: `call` 01F7 / 0200 / 0209, which clear a slot's
six channels, then 0224 loads them), $2D / $2E stop the music (0101: the first channel of every slot cleared, the
keys off).  Four slots of six channels (32 bytes each): $4100, $4200, $4300, $4400; the IRQ (02B3) steps only the
highest slot whose first channel is active, so a lower tune pauses while a higher one plays (and resumes when it
ends).  Channel n of a slot is FM channel n % 3 of chip n // 3; the music uses no SSG.

A channel's output depends only on its own 32 bytes (and the counter's parity, 02F6, which is the same at every
tick's start on the STE: four IRQs a tick): each channel is recorded alone with its own loop (the tune's channels loop
independently, so the whole tune would repeat only after the product of their lengths).  Recorded per arcade tick
through engine/opn.py: the pitch and the loudness of the channel's carriers, as a YM2149 period and volume.  A
tune that ends gets the release of its notes as a tail (played while no other tune plays).

The STE has three square-wave channels for the six FM channels (and the effects): src/music.s plays the loudest
three each tick (a channel that played the tick before is preferred), on the channels the effect leaves free.

    python sound_music.py record        the 13 tunes (cached in build/commando/music.pkl) and their sizes
    python sound_music.py check         the encoded streams through the STE player's decoder against the recording
    python sound_music.py emit          build/commando/music_data.s
    python sound_music.py wav XX [ticks] tune $XX through the STE player as build/commando/music_XX.wav (to listen)
"""
import math
import os
import pickle
import sys
from pathlib import Path
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import sound
from opn import OPN
from paths import build_dir
from machine import CYCLES_PER_LINE, LINES, region

IRQPROM = region("irqprom")
TABLE = 0x0088
SLOTS = (0x4100, 0x4200, 0x4300, 0x4400)
CLEAR = {0x01F7: 0x4100, 0x0200: 0x4200, 0x0209: 0x4300, 0x0212: 0x4400}
TUNES = range(0x20, 0x2D)
STOPS = (0x2D, 0x2E)
EG_PER_TICK = 1500000 / 36 / 3 / (3000000 / (CYCLES_PER_LINE * LINES))    # envelope clocks a tick (233)
GAIN = 14                                       # the YM volume of one carrier at full level: ymfm peaks an FM
                                                # carrier like an SSG square at 15 (16382), a sine 3 dB below the
                                                # square; MAME mixes FM and SSG alike (0.15)
TAIL = 180                                      # ticks of release recorded after a tune ends, at most


def tune_slot(rom, cmd):
    h = rom[TABLE + 2 * cmd] | rom[TABLE + 2 * cmd + 1] << 8
    assert rom[h] == 0xCD, "$%02X" % cmd
    return CLEAR[rom[h + 1] | rom[h + 2] << 8]


def ym_period(hz):
    return 0 if hz <= 0 else max(1, min(4095, round(125000 / hz)))       # YM2149 at 2 MHz: hz = 2e6 / (16 * period)


def ym_volume(amp):
    return 0 if amp <= 0 else max(0, min(15, round(GAIN + 2 * math.log2(amp))))   # (3 dB a step)


def record(cmd, limit=40000, verify=600):
    """the tune alone -> (slot, [per channel: (outputs [(period, volume)], loop start or None)], end tick or None).
    A channel's loop: its 32 bytes at a tick's end (and its output) are those of an earlier tick, and the bytes
    repeat with that period for a period more (at least `verify` ticks): they alone are not all of its state, a short
    repeat can part again."""
    s = sound.SoundBoard()
    slot = tune_slot(s.mem, cmd)
    chips = [OPN(), OPN()]
    done = [0]

    def boot_frame():
        t = s.cpu.cycles
        for line in range(LINES):
            t += CYCLES_PER_LINE
            s.run_line(t, bool(IRQPROM[line & 255] & 4))
        for f, l, chip, reg, v in s.writes:
            chips[chip].write(reg, v)
        del s.writes[:]

    def tick(latch):
        """the four IRQs of a tick as the STE runs them: each to its end (the arcade loses one when a handler runs
        too long, which shifts the counter's parity); a quarter of the tick's envelope clocks after each, the
        loudness sampled there"""
        s.latch = latch
        amps = [0.0] * 6
        hz = [0.0] * 6
        for q in range(4):
            ret = [False]
            s.on_irq_done = lambda b: ret.__setitem__(0, True)
            s.run_line(s.cpu.cycles + CYCLES_PER_LINE, True)
            while not ret[0]:
                s.run_line(s.cpu.cycles + CYCLES_PER_LINE, False)
            for f, l, chip, reg, v in s.writes:
                chips[chip].write(reg, v)
            del s.writes[:]
            done[0] += EG_PER_TICK / 4
            n = int(done[0])
            done[0] -= n
            for c in chips:
                c.advance(n)
            for ch in range(6):
                h, a = chips[ch // 3].channel(ch % 3)
                amps[ch] += a / 4
                hz[ch] = h
        return [(ym_period(hz[ch]), ym_volume(amps[ch])) for ch in range(6)]

    for _ in range(90):
        boot_frame()
    s.mem[0x4000] = 0           # (the STE's count: the first IRQ of every tick makes it 1 mod 4)
    out = [[] for _ in range(6)]
    states = [[] for _ in range(6)]
    last = [{} for _ in range(6)]       # (state, output) -> the tick it was last seen at
    cands = [[] for _ in range(6)]      # [j, period]: state k == state k - period for every k since j + period
    loop = [None] * 6                   # the confirmed (j, k): states j and k equal
    end = None
    for k in range(limit):
        o = tick(cmd if k == 0 else 0xFF)
        for ch in range(6):
            out[ch].append(o[ch])
        if end is None and not s.mem[slot]:
            end = k + 1
        if end is not None:
            if k + 1 - end >= TAIL or all(v == 0 for p, v in o):
                return slot, [(out[ch][:k + 1], None) for ch in range(6)], end
            continue
        for ch in range(6):
            st = bytes(s.mem[slot + 32 * ch:slot + 32 * ch + 32])
            states[ch].append(st)
            if loop[ch] is not None:
                continue
            cands[ch] = [c for c in cands[ch] if states[ch][k - c[1]] == st]
            for j, period in cands[ch]:
                if k - (j + period) >= max(verify, period):
                    loop[ch] = (j, j + period)
                    break
            key = (st, o[ch])               # (with the output: a released note has settled)
            j = last[ch].get(key)
            if j is not None and all(c[1] != k - j for c in cands[ch]):
                cands[ch].append([j, k - j])
            last[ch][key] = k
        if all(l is not None for l in loop):
            chans = []
            for ch in range(6):
                j, kk = loop[ch]
                period = kk - j
                stream = out[ch][:kk + 1]
                bad = sum(out[ch][i] != stream[j + 1 + (i - j - 1) % period] for i in range(kk + 1, k + 1))
                if bad:
                    print("  $%02X channel %d: %d of %d ticks after its loop differ from the loop's" % (cmd, ch, bad, k - kk))
                chans.append((stream, j + 1))
            return slot, chans, None
    raise RuntimeError("tune $%02X: no end or loop in %d ticks" % (cmd, limit))


def all_tunes(again=False):
    path = build_dir("commando") / "music.pkl"
    if path.exists() and not again:
        return pickle.loads(path.read_bytes())
    tunes = {}
    for cmd in TUNES:
        tunes[cmd] = record(cmd)
        slot, chans, end = tunes[cmd]
        print("$%02X slot %04X %s: %s" % (cmd, slot, "ends at %d" % end if end else "loops",
                                         " ".join("%d%s" % (len(o), "L%d" % l if l is not None else "") for o, l in chans)))
    path.write_bytes(pickle.dumps(tunes))
    return tunes


# ---- the STE's form.  A channel's stream is bytes, each tick one step of the decoder:
#   $00-$7F      the current period and volume for n + 1 ticks
#   $80-$8F      volume n & 15, one tick
#   $90-$9F      volume - 1, then n & 15 + 1 ticks
#   $A0-$AF, b   period (n & 15) << 8 | b (no tick: a volume byte follows)
#   $FF          the end: the loop (its first step sets period and volume), or silence
# A tune: its slot (0-3 for $4100-$4400), the tick it ends at (0: it loops), six channels' streams and loop offsets.

HOLD, VOL, DOWN, PERIOD, END = 0x00, 0x80, 0x90, 0xA0, 0xFF


def encode_channel(out, loop):
    """-> (bytes, loop offset or -1)"""
    b = bytearray()
    cur = None
    loop_at = -1
    i = 0
    while i < len(out):
        p, v = out[i]
        whole = cur is None or i == loop
        if i == loop:
            loop_at = len(b)
        j = i + 1                                       # (a run: the same output, not across the loop's start)
        while j < len(out) and out[j] == out[i] and j != loop:
            j += 1
        n = j - i
        if whole or p != cur[0]:
            b += bytes([PERIOD | p >> 8, p & 255, VOL | v])
            n -= 1
        elif v == cur[1] - 1:
            k = min(n, 16)
            b.append(DOWN | (k - 1))
            n -= k
        elif v != cur[1]:
            b.append(VOL | v)
            n -= 1
        while n > 0:
            k = min(n, 128)
            b.append(HOLD | (k - 1))
            n -= k
        cur = (p, v)
        i = j
    b.append(END)
    return bytes(b), loop_at


class Channel:
    """the STE's decoder of one stream (src/music.s mus_chan), step for step"""
    def __init__(self, data, loop):
        self.data, self.loop = data, loop
        self.pos, self.left, self.period, self.vol = 0, 0, 0, 0

    def step(self):
        if self.left:
            self.left -= 1
            return self.period, self.vol
        while True:
            c = self.data[self.pos]
            self.pos += 1
            if c == END:
                if self.loop < 0:
                    self.pos -= 1
                    self.vol = 0
                    return self.period, 0
                self.pos = self.loop
            elif c >= PERIOD:
                self.period = (c & 15) << 8 | self.data[self.pos]
                self.pos += 1
            elif c >= DOWN:
                self.vol -= 1
                self.left = c & 15
                return self.period, self.vol
            elif c >= VOL:
                self.vol = c & 15
                return self.period, self.vol
            else:
                self.left = c
                return self.period, self.vol


def encode(tunes):
    """cmd -> (slot index, end tick or 0, [(bytes, loop offset)] x 6)"""
    return {cmd: (SLOTS.index(slot), end or 0, [encode_channel(o, l) for o, l in chans])
            for cmd, (slot, chans, end) in tunes.items()}


class Mixer:
    """the STE's choice of the music's channels (src/music.s mus_mix): the loudest of the six (one that played the
    tick before wins a tie of a volume step), on the YM channels the effect leaves free, each on the YM channel it had
    if it can"""
    def __init__(self):
        self.ym = [-1] * 6              # the YM channel each music channel played on last tick

    def mix(self, vals, used):
        """vals: six (period, volume); used: the YM channels the effect sounds on (bits) -> {ym channel: (period,
        volume)} of the music"""
        free = [c for c in range(3) if not used >> c & 1]
        key = lambda ch: vals[ch][1] * 2 + (self.ym[ch] >= 0)
        picked = sorted((ch for ch in range(6) if vals[ch][0] and vals[ch][1]), key=lambda ch: (-key(ch), ch))[:len(free)]
        out, new = {}, [-1] * 6
        for ch in picked:                   # (the ones that keep their YM channel first)
            if self.ym[ch] in free:
                out[self.ym[ch]], new[ch] = vals[ch], self.ym[ch]
        for ch in picked:
            if new[ch] < 0:
                c = next(c for c in free if c not in out)
                out[c], new[ch] = vals[ch], c
        self.ym = new
        return out


class Player:
    """the STE's music (src/music.s): the slots, the commands, the highest active slot steps its six channels"""
    def __init__(self, enc):
        self.enc = enc
        self.slots = [None] * 4         # per slot: {"cmd", "n", "chans", "tail"}
        self.last = 0
        self.mixer = Mixer()

    def tick(self, latch):
        if latch != self.last:
            self.last = latch
            if latch in self.enc:
                slot, end, chans = self.enc[latch]
                self.slots[slot] = {"n": 0, "end": end, "chans": [Channel(d, l) for d, l in chans], "tail": False}
            elif latch in STOPS:
                self.slots = [None] * 4
        top = next((s for s in (3, 2, 1, 0) if self.slots[s] and not self.slots[s]["tail"]), None)
        if top is None:
            top = next((s for s in (3, 2, 1, 0) if self.slots[s]), None)
            if top is None:
                return [(0, 0)] * 6
        sl = self.slots[top]
        vals = [c.step() for c in sl["chans"]]
        sl["n"] += 1
        if sl["tail"] and all(v == 0 for p, v in vals):
            self.slots[top] = None
        if sl["end"] and sl["n"] == sl["end"]:
            sl["tail"] = True
        for s in range(4):                  # (a tail ends when another tune plays)
            if s != top and self.slots[s] and self.slots[s]["tail"] and not sl["tail"]:
                self.slots[s] = None
        return vals


def check(tunes=None):
    """every tune's encoded channels through the decoder against the recording (and around its loop again)"""
    tunes = tunes or all_tunes()
    enc = encode(tunes)
    bad = total = 0
    for cmd, (slot, chans, end) in sorted(tunes.items()):
        for ch, (out, loop) in enumerate(chans):
            d = Channel(*enc[cmd][2][ch])
            n = len(out) + (2 * (len(out) - loop) if loop is not None else 30)
            for i in range(n):
                want = out[i] if i < len(out) else out[loop + (i - loop) % (len(out) - loop)] if loop is not None else (out[-1][0], 0)
                got = d.step()
                total += 1
                if got != want and not (want[1] == 0 and got[1] == 0):
                    bad += 1
                    if bad < 5:
                        print("$%02X channel %d tick %d: decoder %s recording %s" % (cmd, ch, i, got, want))
    size = sum(len(d) for e in enc.values() for d, l in e[2])
    print("%d tunes, %d channel ticks checked, %d differ; the streams take %d bytes" % (len(enc), total, bad, size))
    return bad


def combine(eff, mixer, vals):
    """the YM's registers 0-10 (src/music.s mus_mix): the effect's registers `eff` on the channels it sounds on, the
    music (`vals`, six (period, volume)) through `mixer` on the others"""
    r = list(eff)
    mix, used = r[7], 0
    for c in range(3):
        if r[8 + c] & 0x1F and (mix >> c) & 9 != 9:
            used |= 1 << c
        else:
            r[8 + c] = 0
            mix |= 9 << c
    for c, (p, v) in mixer.mix(vals, used).items():
        r[2 * c], r[2 * c + 1], r[8 + c] = p & 255, p >> 8, v
        mix &= ~(1 << c)
    r[7] = mix
    return r


def emit(path):
    """build/commando/music_data.s for src/music.s: mus_table (commands $20-$2F, ME_SIZE bytes each), the streams"""
    enc = encode(all_tunes())
    L = ["; generated by tools/sound_music.py: the music of the sound driver as square-wave streams (see there)",
         "\tsection data,data", "\tcnop 0,2", "ME_SIZE = 52", "mus_table:"]
    for cmd in range(0x20, 0x30):
        if cmd in enc:
            slot, end, chans = enc[cmd]
            L.append("\tdc.b %d,0\n\tdc.w %d" % (slot, end))
            L.append("\tdc.l " + ",".join("mus_%02X_%d" % (cmd, ch) for ch in range(6)))
            L.append("\tdc.l " + ",".join("mus_%02X_%d+%d" % (cmd, ch, l) if l >= 0 else "0" for ch, (d, l) in enumerate(chans)))
        else:
            L.append("\tdc.b $%02X,0\n\tdc.w 0\n\tdcb.l 12,0" % (0xFE if cmd in STOPS else 0xFF))
    for cmd in sorted(enc):
        for ch, (d, l) in enumerate(enc[cmd][2]):
            L.append("mus_%02X_%d:" % (cmd, ch))
            for i in range(0, len(d), 24):
                L.append("\tdc.b " + ",".join(str(b) for b in d[i:i + 24]))
    L.append("\teven")
    Path(path).write_text("\n".join(L) + "\n")
    return 16 * 52 + sum(len(d) for e in enc.values() for d, l in e[2])


YM_LEVELS = [0, 78, 178, 262, 369, 509, 701, 965, 1334, 1853, 2576, 3576, 5000, 7023, 9963, 14132]  # (ymfm's table, odd steps)


def wav(path, ticks_regs, rate=44100):
    """the YM's registers a tick (11 each) as a mono 16-bit wav: the tones (no noise: the music alone)"""
    import struct
    import wave
    out = bytearray()
    phase = [0.0] * 3
    per_tick = rate / (3000000 / (CYCLES_PER_LINE * LINES))
    acc = 0.0
    for r in ticks_regs:
        acc += per_tick
        n = int(acc)
        acc -= n
        chans = []
        for c in range(3):
            p = r[2 * c] | (r[2 * c + 1] & 15) << 8
            if p and not r[7] >> c & 1 and r[8 + c] & 15:
                chans.append((125000 / p / rate, YM_LEVELS[r[8 + c] & 15]))
            else:
                chans.append(None)
        for _ in range(n):
            v = 0
            for c, ch in enumerate(chans):
                if ch:
                    phase[c] = (phase[c] + ch[0]) % 1.0
                    v += ch[1] if phase[c] < 0.5 else 0
            out += struct.pack("<h", int(v * 0.6) - 13000)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(out))


def play(latches):
    """the music alone (no effect) through the STE's player: the YM's registers a tick"""
    p, mixer = Player(encode(all_tunes())), Mixer()
    idle = [0] * 7 + [0xFF, 0, 0, 0]
    return [combine(idle, mixer, p.tick(l)) for l in latches]


if __name__ == "__main__":
    if sys.argv[1:2] == ["record"]:
        all_tunes(True)
        sys.exit(1 if check() else 0)
    if sys.argv[1:2] == ["check"]:
        sys.exit(1 if check() else 0)
    if sys.argv[1:2] == ["emit"]:
        print("music_data.s: %d bytes" % emit(build_dir("commando") / "music_data.s"))
    if sys.argv[1:2] == ["wav"]:
        cmd = int(sys.argv[2], 16)
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 3600
        path = build_dir("commando") / ("music_%02X.wav" % cmd)
        wav(path, play([cmd] + [0xFF] * (n - 1)))
        print(path)
