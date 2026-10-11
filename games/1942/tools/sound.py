"""1942's sound on the STE's YM2149: the sound driver's output as recorded streams, mixed to three channels.

The board (MAME capcom/1942.cpp): a Z80 at 3 MHz, ROM sr-01.c11 at 0000-3FFF, RAM 4000-47FF, the latch at 6000 (the main
CPU's C800), two AY-3-8910 at 1.5 MHz (8000/8001, C000/C001), four IRQs a frame from the scanline PROM (IM 1).

The driver (audio ROM): IRQ 0038 counts ($4000), reads the latch (0067: a new value below $20 is a command, rst 30's
table at 007A), steps the music (01B4), the drums (0565), the effects (0516) and writes both chips (0826).
* Music: four slots, only the highest active one is stepped (01B4): $4480 and $4300 play six channels on both chips,
  $4580 and $4600 three channels on the first chip (the in-game drums, $11, and the tunes $14-$16, $1F).  Their
  sequencers start drum hits in slot $4280 (0418), which replace the first chip's whole output while they sound (08B3).
* Effects: slots $4100 > $4200 > $4180 > $4080 (and $4700, never started), only the highest active one is stepped and
  shown on the second chip (0516, 0A3F).  $4180 restarts its effect when the counter & $1F is 0, $4080 when & 7 is 0.
* Output (0826): $4480 or $4300 active: both chips from it; else the first chip from $4280 / $4580 / $4600, the second
  from the effects.  A chip with nothing to play gets mixer $FF.

What a program (a tune, an effect) outputs after n ticks depends only on itself and n, so each is recorded alone in
ticks of four IRQs (the STE runs the four of a tick at its start): its register images until its slot ends or its
RAM repeats (a loop).  The STE plays the recordings in the driver's scheme (slots, priorities, restarts, stop
commands: `Player`), and has three channels for the arcade's six:
* a two chip program: three fixed channels (`PICKS`: octave doublings dropped, the louder one kept);
* else the first chip (music, drums), and every channel the second chip (the effects) sounds on replaces the first
  chip's channel of the same letter.
Periods are scaled to the YM's 2 MHz (x 4/3; tones clamp at 4095, noise at 31).

    python sound.py check [frames]     Player against the driver over the game run (and random commands)
    python sound.py stats              the programs: ticks, loops, images, the size of the data
"""
import os
import pickle
import random
import sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from z80 import Z80
from machine import load
from paths import build_dir

IDLE = 0x0064               # the main loop: ei; jr $0064
TWO_CHIP = (0x4480, 0x4300)
MUSIC_SLOTS = (0x4480, 0x4300, 0x4580, 0x4600)
EFFECT_SLOTS = (0x4100, 0x4200, 0x4180, 0x4080)
RESTART = {0x4180: (0x1F, 0x00), 0x4080: (0x07, 0x0A)}      # slot: (counter mask, the effect it restarts)
MUSIC = {0x11: 0x4600, 0x14: 0x4600, 0x15: 0x4600, 0x1F: 0x4600, 0x16: 0x4580,
         0x12: 0x4480, 0x13: 0x4480, 0x18: 0x4480, 0x19: 0x4480, 0x1A: 0x4480, 0x17: 0x4300}
EFFECTS = {0x01: (0x4180, 0x00), 0x02: (0x4100, 0x01), 0x03: (0x4200, 0x02), 0x04: (0x4200, 0x03), 0x05: (0x4200, 0x04),
           0x06: (0x4100, 0x05), 0x07: (0x4100, 0x06), 0x08: (0x4100, 0x07), 0x09: (0x4100, 0x08), 0x0A: (0x4100, 0x09),
           0x0C: (0x4080, 0x0A), 0x0D: (0x4100, 0x0B), 0x0E: (0x4100, 0x0C), 0x1B: (0x4100, 0x0D)}
STOPS = {0x00: (0x4100, 0x4180, 0x4200), 0x0B: (0x4180,), 0x0F: (0x4080,),
         0x10: MUSIC_SLOTS, 0x1C: MUSIC_SLOTS, 0x1D: MUSIC_SLOTS, 0x1E: MUSIC_SLOTS}
# the three (chip, channel) of a two chip tune the YM plays: the channels in octaves of another one (or the same notes)
# dropped, the louder one kept; then melody, the voice with the most notes, bass
PICKS = {0x12: ((0, 0), (1, 0), (1, 2)), 0x13: ((0, 0), (0, 2), (1, 2)), 0x17: ((0, 1), (1, 0), (1, 2)),
         0x18: ((0, 0), (1, 0), (1, 2)), 0x19: ((0, 0), (0, 2), (1, 0)), 0x1A: ((0, 0), (0, 1), (0, 2))}


class SoundBoard:
    def __init__(self):
        self.mem = bytearray(65536)
        self.mem[:0x4000] = load("sr-01.c11")
        self.latch = 0xFF
        self.addr = [0, 0]
        self.regs = [[0] * 16, [0] * 16]        # both chips' registers as last written
        self.cpu = Z80(self.rd8, self.wr8)
        self.cpu.im = 1
        n = 0
        while self.cpu.pc != IDLE + 1:          # the boot: RAM cleared, ei
            self.cpu.step()
            n += 1
            assert n < 2000000

    def rd8(self, a):
        if a == 0x6000:
            return self.latch
        return self.mem[a] if a < 0x4800 else 0xFF

    def wr8(self, a, v):
        if 0x4000 <= a < 0x4800:
            self.mem[a] = v
        elif a in (0x8000, 0x8001, 0xC000, 0xC001):
            chip = a >> 14 & 1
            if a & 1:
                if self.addr[chip] < 16:
                    self.regs[chip][self.addr[chip]] = v
            else:
                self.addr[chip] = v

    def irq(self):
        """one IRQ, run to the end of its handler"""
        c = self.cpu
        c.iff1 = c.iff2 = 0
        c.halted = False
        c.push(IDLE)
        c.pc = 0x38
        n = 0
        while True:
            c.step()
            n += 1
            if c.pc == IDLE:
                break
            assert n < 100000
        c.iff1 = c.iff2 = 1

    def tick(self, latch=0xFF):
        self.latch = latch
        for _ in range(4):
            self.irq()

    def call(self, addr, a=0, ix=0):
        """call a driver routine (to start an effect: 04E6 with ix = the slot, A = the effect)"""
        c = self.cpu
        c.a, c.ix = a, ix
        c.push(0xFFF0)
        c.pc = addr
        while c.pc != 0xFFF0:
            c.step()

    def chips(self):
        return tuple(self.regs[0][:11]), tuple(self.regs[1][:11])


# ---- the YM's view ------------------------------------------------------------------------------------------------------

def ym_image(r):
    """an AY's registers 0-10 -> the YM's (a tuple of 11): periods x 4/3, the channels that make no sound blanked"""
    out = [0] * 11
    mix = 0xC0 | 0x3F
    noise = False
    for k in range(3):
        vol = r[8 + k] & 0x1F
        assert not vol & 0x10, "envelope mode"
        tone, nse = not r[7] >> k & 1, not r[7] >> (k + 3) & 1
        if not vol or not (tone or nse):
            continue
        out[8 + k] = vol
        if tone:
            p = min(4095, ((r[2 * k] | (r[2 * k + 1] & 15) << 8) * 4 + 1) // 3)
            out[2 * k], out[2 * k + 1] = p & 255, p >> 8
            mix &= ~(1 << k)
        if nse:
            mix &= ~(8 << k)
            noise = True
    if noise:
        out[6] = min(31, ((r[6] & 31) * 4 + 1) // 3)
    out[7] = mix
    return tuple(out)


SILENT = ym_image((0,) * 7 + (0xFF, 0, 0, 0))


def sounds(img, k):
    return img[8 + k] != 0


def overlay(music, effect):
    """the effect's sounding channels over the music's (images of ym_image; None: nothing)"""
    if effect is None:
        return music or SILENT
    if music is None:
        return effect
    out = list(music)
    mix = music[7]
    noise_from_effect = False
    for k in range(3):
        if sounds(effect, k):
            out[2 * k], out[2 * k + 1], out[8 + k] = effect[2 * k], effect[2 * k + 1], effect[8 + k]
            mix = (mix & ~(9 << k)) | (effect[7] & (9 << k))
            if not effect[7] >> (k + 3) & 1:
                noise_from_effect = True
    out[7] = mix
    if noise_from_effect:
        out[6] = effect[6]
    elif mix & 0x38 == 0x38:
        out[6] = 0
    return tuple(out)


def pick(c0, c1, picks):
    """three channels of a two chip program (ym_image of each chip) -> one image"""
    out = [0] * 11
    mix = 0xFF
    src = (c0, c1)
    for k, (chip, j) in enumerate(picks):
        s = src[chip]
        out[2 * k], out[2 * k + 1], out[8 + k] = s[2 * j], s[2 * j + 1], s[8 + j]
        if not s[7] >> j & 1:
            mix &= ~(1 << k)
        if not s[7] >> (j + 3) & 1:
            mix &= ~(8 << k)
            out[6] = s[6]
    out[7] = mix
    return tuple(out)


# ---- recording ----------------------------------------------------------------------------------------------------------

def record(start, slot, chip_of, limit=20000):
    """a program alone from a fresh board: start(board) at the first tick -> (images after each tick, loop, end).
    loop: images[n] for n >= len is images[loop + (n - len) % (len - loop)]; or end = (j, image): in the last tick the
    slot ended in its IRQ j (0-3) with this image in its RAM (shown only when the driver restarts it in that IRQ)."""
    s = SoundBoard()
    s.tick()
    s.tick()
    s.mem[0x4000] = 0                           # (the counter: four IRQs a tick from 0)
    out, seen = [], {}
    latch = start(s)
    for t in range(limit):
        s.latch = latch if t == 0 else 0xFF
        for j in range(4):
            s.irq()
            if not s.mem[slot]:
                out.append(ym_image(s.mem[slot + 2:slot + 13]) if slot in EFFECT_SLOTS else SILENT)
                return out, None, j
        key = bytes(s.mem[0x4001:0x4800])
        if key in seen:
            return out, seen[key], None
        seen[key] = len(out)
        out.append(chip_of(s.chips()))
    raise RuntimeError("no end or loop in %d ticks" % limit)


def record_music(cmd):
    slot = MUSIC[cmd]
    if slot in TWO_CHIP:
        chip_of = lambda c: pick(ym_image(c[0]), ym_image(c[1]), PICKS[cmd])
    else:
        chip_of = lambda c: ym_image(c[0])
    return record(lambda s: cmd, slot, chip_of)


def record_effect(prog):
    def start(s):
        s.call(0x04E6, a=prog, ix=0x4100)
        return 0xFF
    return record(start, 0x4100, lambda c: ym_image(c[1]))


def programs():
    """{('m', cmd) | ('e', prog): (images, loop, end)}, cached in build/1942/sound_rec.pkl"""
    path = build_dir("1942") / "sound_rec.pkl"
    if path.exists():
        return pickle.loads(path.read_bytes())
    out = {}
    for cmd in sorted(MUSIC):
        out[("m", cmd)] = record_music(cmd)
    for prog in sorted({p for s, p in EFFECTS.values()}):
        out[("e", prog)] = record_effect(prog)
    path.write_bytes(pickle.dumps(out))
    return out


# ---- the encoding (sound_data.s) ----------------------------------------------------------------------------------------
# images: 12 bytes each (registers 0-10, a pad byte), shared by all programs.  A program: words, per tick
#   0000 nnnnnnnnnnnn  image n for one tick
#   1rrr nnnnnnnnnnnn  image n for r + 2 ticks (r = 0-6)
#   1111 0000 0000 0000 then a word w: go to word w of this program (a loop)
#   1111 1111 1111 1jjj then a word n: the last tick, the slot ends in its IRQ j with image n

END, JUMP = 0xFFF8, 0xF000


def encode(progs):
    images = {}
    streams = {}

    def index(im):
        if im not in images:
            images[im] = len(images)
        return images[im]

    for key, (imgs, loop, end) in sorted(progs.items()):
        idx = [index(im) for im in (imgs if end is None else imgs[:-1])]
        words, at = [], {}
        i = 0
        while i < len(idx):
            at[i] = len(words)
            n = 1
            while i + n < len(idx) and idx[i + n] == idx[i] and n < 8 and i + n != loop:
                n += 1
            words.append(idx[i] if n == 1 else 0x8000 | (n - 2) << 12 | idx[i])
            i += n
        if end is None:
            words += [JUMP, at[loop]]
        else:
            words += [END | end, index(imgs[-1])]
        streams[key] = words
    assert len(images) <= 4096
    return [im for im, _ in sorted(images.items(), key=lambda x: x[1])], streams


class Stream:
    """a slot's position in a program (the 68000 player's state)"""
    def __init__(self, words):
        self.words, self.pos, self.left, self.img = words, 0, 0, None

    def step(self):
        """one tick -> (image index, None) or at the end (the last image, the IRQ the slot ended in)"""
        if self.left:
            self.left -= 1
            return self.img, None
        w = self.words[self.pos]
        if w == JUMP:
            self.pos = self.words[self.pos + 1]
            w = self.words[self.pos]
        if w >= END:
            return self.words[self.pos + 1], w & 3
        self.pos += 1
        self.img = w & 0xFFF
        self.left = (w >> 12 & 7) + 1 if w & 0x8000 else 0
        return self.img, None


class Player:
    """the driver's scheme over the encoded programs, a tick at a time (src/sound.s does the same)"""
    def __init__(self, images, streams):
        self.images, self.streams = images, streams
        self.slot = {}          # slot -> Stream (active)
        self.cur = {}           # slot -> image index of its last step
        self.prog = {}          # music slot -> command
        self.last = 0
        self.count = 0

    def start(self, slot, key):
        self.slot[slot] = Stream(self.streams[key])
        self.cur.setdefault(slot, None)

    def top(self, slots):
        for s in slots:
            if s in self.slot:
                return s
        return None

    def tick(self, latch):
        if latch != self.last:
            self.last = latch
            if latch < 0x20:
                if latch in MUSIC:
                    self.start(MUSIC[latch], ("m", latch))
                    self.prog[MUSIC[latch]] = latch
                elif latch in EFFECTS:
                    slot, prog = EFFECTS[latch]
                    self.start(slot, ("e", prog))
                for s in STOPS.get(latch, ()):
                    self.slot.pop(s, None)
        self.count = (self.count + 4) & 255
        self.advance(MUSIC_SLOTS)
        self.advance(EFFECT_SLOTS)
        return self.output()

    def advance(self, slots, again=True):
        """the highest active slot steps.  $4180 / $4080 restart after the step of an IRQ whose counter & mask is 0
        (the fourth of a tick), also when the step ended them.  A slot that ended earlier in the tick (IRQ 0 or 1)
        hands the rest of the tick to the next one: it steps a tick (the driver: three or two IRQs)."""
        s = self.top(slots)
        if s is None:
            return
        img, end = self.slot[s].step()
        self.cur[s] = img
        restart = s in RESTART and not self.count & RESTART[s][0] and end in (None, 3)
        if restart:
            self.start(s, ("e", RESTART[s][1]))
            self.cur[s] = img                   # (the tick shows the step)
        elif end is not None:
            del self.slot[s]
            if end <= 1 and again:
                self.advance(slots, False)

    def image(self, slot):
        i = self.cur.get(slot) if slot is not None else None
        return None if i is None else self.images[i]

    def output(self):
        m = self.top(MUSIC_SLOTS)
        if m in TWO_CHIP:
            return self.image(m) or SILENT
        return overlay(self.image(m), self.image(self.top(EFFECT_SLOTS)))


def driver_output(s, prog_of):
    """the YM image of the driver's state after a tick (the same mixing): prog_of(slot) = the two chip tune in it"""
    c0, c1 = s.chips()
    for slot in TWO_CHIP:
        if s.mem[slot]:
            return pick(ym_image(c0), ym_image(c1), PICKS[prog_of(slot)])
    a = ym_image(c0) if c0[7] != 0xFF or any(c0[8:11]) else None
    b = ym_image(c1) if c1[7] != 0xFF or any(c1[8:11]) else None
    return overlay(a, b)


# ---- checks -------------------------------------------------------------------------------------------------------------

def game_latches(frames, seed=1):
    """the latch after each tick of the game run (attract mode, coin, start, random play) in the port's schedule"""
    from machine import Machine1942
    m = Machine1942()
    rnd = random.Random(seed)
    out, state, coin_at, joy, t0 = [], "attract", 700, 0xFF, 0
    for f in range(frames):
        m.sys_in = m.p1 = m.p2 = 0xFF
        if state == "attract" and f >= coin_at:
            state, t0 = "coin", f
        if state == "coin":
            if f < t0 + 4:
                m.sys_in &= 0x7F
            elif 30 <= f - t0 < 34:
                m.sys_in &= 0xFE
            elif f - t0 >= 34:
                state, t0 = "play", f
        if state == "play":
            g = f - t0
            if g % 25 == 0:
                joy = rnd.choice([0xFF, 0xFE, 0xFD, 0xFB, 0xF7, 0xFA, 0xF6, 0xF9, 0xF5])
            m.p1 = joy
            if rnd.random() < 0.3:
                m.p1 &= ~0x10
            if rnd.random() < 0.02:
                m.p1 &= ~0x20
            if seed >= 5:
                m.ram[0x101] = 6
                m.ram[0x0A5] = 2
                if g > 600 and g % 400 == 0:
                    m.ram[0xBD0], m.ram[0x099], m.ram[0x102] = 7, 1, 0x43
        m.run_frame_port()
        out.append(m.latch)
    return out


def random_latches(ticks, seed):
    rnd = random.Random(seed)
    cmds = sorted(set(MUSIC) | set(EFFECTS) | set(STOPS))
    out = []
    for t in range(ticks):
        if rnd.random() < 0.04:
            out.append(rnd.choice(cmds))
        else:
            out.append(0xFF)
    return out


def compare(latches, images, streams, label):
    s, p = SoundBoard(), Player(images, streams)
    s.tick()
    s.tick()
    s.mem[0x4000] = 0
    progs = {}
    bad = total = 0
    first = []
    for t, v in enumerate(latches):
        if v != s.mem[0x4002] and v in MUSIC:
            progs[MUSIC[v]] = v
        s.tick(v)
        want = driver_output(s, progs.get)
        got = p.tick(v)
        total += 1
        if got != want:
            bad += 1
            if len(first) < 5:
                first.append("  tick %d (latch %02X): player %s driver %s" % (t, v, got, want))
    print("%s: %d ticks, %d differ" % (label, total, bad))
    for f in first:
        print(f)
    return bad


def check(frames):
    images, streams = encode(programs())
    lat = game_latches(frames)
    bad = compare(lat, images, streams, "game run (%d frames)" % frames)
    for seed in (1, 2):
        bad += compare(random_latches(frames, seed), images, streams, "random commands (seed %d)" % seed)
    return bad


def stats():
    progs = programs()
    images, streams = encode(progs)
    for (kind, n), (imgs, loop, end) in sorted(progs.items()):
        print("%s %02X  ticks %5d  loop %-5s end %-4s words %d" % (kind, n, len(imgs), loop, end, len(streams[(kind, n)])))
    words = sum(len(w) for w in streams.values())
    print("%d images (%d bytes), %d words (%d bytes)" % (len(images), 12 * len(images), words, 2 * words))


def emit(path):
    images, streams = encode(programs())
    keys = sorted(streams)
    lines = ["; generated by games/1942/tools/sound.py: the sound programs (see src/sound.s)", "", "\teven", "snd_images:"]
    for im in images:
        lines.append("\tdc.b\t" + ",".join("$%02X" % b for b in im) + ",0")
    for kind, n in keys:
        lines.append("snd_%s%02X:" % (kind, n))
        w = streams[(kind, n)]
        for i in range(0, len(w), 16):
            lines.append("\tdc.w\t" + ",".join("$%04X" % x for x in w[i:i + 16]))
    order = MUSIC_SLOTS + EFFECT_SLOTS
    lines.append("")
    lines.append("snd_cmd_tab:\t\t\t\t; per command $00-$1F: the slot it starts (-1: none), the slots it stops, the program")
    for c in range(32):
        slot, prog = (MUSIC[c], "snd_m%02X" % c) if c in MUSIC else (EFFECTS[c][0], "snd_e%02X" % EFFECTS[c][1]) if c in EFFECTS \
            else (None, "0")
        stops = sum(1 << order.index(x) for x in STOPS.get(c, ()))
        lines.append("\tdc.w\t%d,$%02X\n\tdc.l\t%s" % (order.index(slot) if slot else -1, stops, prog))
    path.write_text("\n".join(lines) + "\n")
    return 12 * len(images) + 2 * sum(len(w) for w in streams.values())


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if what == "check":
        sys.exit(1 if check(int(sys.argv[2]) if len(sys.argv) > 2 else 3000) else 0)
    stats()
