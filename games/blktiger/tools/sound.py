"""Black Tiger's sound board (MAME capcom/blktiger.cpp): a Z80 at 3.58 MHz, ROM 0000-7FFF, RAM C000-C7FF, the latch at
C800 (the main CPU's port 0), two YM2203 at E000-E003 (3.58 MHz, the driver keeps the default prescaler 6: FM at
3.58 MHz / 72, the SSG at 3.58 MHz / 4).  The first chip's timers interrupt the CPU (IM 1): timer A (825, ~250 Hz)
and timer B (244, ~259 Hz); the handler (0038) runs the effects (0A50) and the music (039F) on timer A, reads the
latch (01FC) on timer B.  The chips are not emulated beyond their status (the timer flags; never busy): the
register writes are logged as (chip, register, value).

The driver (another Capcom one than Commando's): commands through the table at 0DC1 (01FC; $FF in the high byte: a
special command, 02EE: 00 stops everything, 01 the effects, 04 the music), each with a header byte:
* effects (bit 7): one slot a chip (bit 6: C530 on the second chip, else C500), SSG only; a priority (bits 0-3)
  against C020 / C021, which each step sets from the slot's byte 31 (the header; 0 when it ended, 0BB7): a new
  effect replaces the playing one unless that has a higher priority.  Part of the step runs when C022 & 3 == 0
  (0AEB): recorded in the four phases.  A start writes the idle registers (0329).
* tunes: six FM channels of 48 bytes, the main slot C100 (its header in C011) and a backup C300 (C012): a tune of
  the main one's priority replaces it, a higher one moves it to the backup first, a lower one goes to the backup
  unless that holds a higher one (0212-026E).  When the main tune ends (08DF) the backup becomes the main one
  (0348); a main tune with header bit 6 lets the backup step on silently meanwhile (03AA).

engine/capsnd.py records and encodes: each effect alone (12 values a step: the registers 0-10 and byte 31), each
tune's channels alone (period and volume a step through engine/opn.py); src/sound.s plays them five steps a VBL
(250 Hz) in this scheme (Player below is that code in Python).

    python sound.py writes CMD [secs]     the registers a command's sound writes (a summary)
    python sound.py record                 record the effects and tunes again (build/blktiger/fx.pkl, music.pkl)
    python sound.py check [secs]           the player against the driver: random commands, then the game's own
    python sound.py emit                   build/blktiger/bt_sound.s
    python sound.py wav XX [secs]          command $XX through the player as build/blktiger/sound_XX.wav
"""
import os
import sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import pickle
import random
from z80 import Z80
from paths import build_dir
import capsnd
from opn import OPN

CLOCK = 3579545
TA = 72 * (1024 - 825)          # CPU cycles a timer A period (the YM2203 at the CPU's clock)
TB = 1152 * (256 - 244)
IDLE = (0x0009, 0x000A)         # the main loop: ei / jr $


class Board:
    def __init__(self):
        self.mem = bytearray(65536)
        self.mem[:0x8000] = (build_dir("blktiger") / "audiocpu.rom").read_bytes()[:0x8000]
        self.latch = 0xFF
        self.writes = []
        self.addr = [0, 0]
        self.regs = [[0] * 256, [0] * 256]
        self.flags = 0              # chip 0's timer flags (bit 0 A, bit 1 B)
        self.enable = 0             # register 27: bits 2/3 enable the flags' IRQ, 0/1 run the timers
        self.cpu = Z80(self.rd8, self.wr8)
        self.next_a = self.next_b = None
        self.in_irq = False
        self.on_irq_done = None
        self.hooks = {}             # pc -> f(board): called before the instruction

    def rd8(self, a):
        if a == 0xC800:
            return self.latch
        if a < 0xC800:
            return self.mem[a]
        if a in (0xE000, 0xE001):
            return self.flags
        if a in (0xE002, 0xE003):
            return 0
        return 0xFF

    def wr8(self, a, v):
        if 0xC000 <= a < 0xC800:
            self.mem[a] = v
        elif 0xE000 <= a <= 0xE003:
            chip = (a - 0xE000) >> 1
            if a & 1:
                r = self.addr[chip]
                self.writes.append((chip, r, v))
                self.regs[chip][r] = v
                if chip == 0 and r == 0x27:
                    self.enable = v
                    self.flags &= ~(v >> 4) & 3          # (bits 4 / 5: reset the flags)
                    c = self.cpu.cycles
                    if v & 1 and self.next_a is None:
                        self.next_a = c + TA
                    if v & 2 and self.next_b is None:
                        self.next_b = c + TB
            else:
                self.addr[chip] = v

    def run(self, cycles):
        c = self.cpu
        end = c.cycles + cycles
        while c.cycles < end:
            if self.next_a is not None and c.cycles >= self.next_a:
                self.next_a += TA
                if self.enable & 4:
                    self.flags |= 1
            if self.next_b is not None and c.cycles >= self.next_b:
                self.next_b += TB
                if self.enable & 8:
                    self.flags |= 2
            if self.flags and c.iff1 and not c.ei_delay:
                self.in_irq = True
                c.iff1 = c.iff2 = 0
                c.halted = False
                c.push(c.pc)
                c.pc = 0x38
                c.cycles += 13
            c.ei_delay = False
            h = self.hooks.get(c.pc)
            if h:
                h(self)
            c.step()
            if self.in_irq and c.pc in IDLE:
                self.in_irq = False
                if self.on_irq_done:
                    self.on_irq_done(self)


TABLE = 0x0DC1
STEP_END = 0x004A               # after the effects (0A50) and the music (039F) of a timer A step
ACCEPT = 0x0208                 # 01FC: a new latch value is taken
FX_SLOT = (0xC500, 0xC530)
FX_PRI = (0xC020, 0xC021)
MAIN, BACKUP = 0xC100, 0xC300
STEPS = CLOCK / TA              # timer A steps a second (249.8)
PER_VBL = 5                     # the STE: five steps a 50 Hz VBL
SSG = (8000000, CLOCK)          # the SSG at 3.58 MHz / 4 on the YM2149 at 2 MHz: periods * 2.235
IDLE_REGS = (0, 0, 0, 0, 0, 0, 0, 0xF8, 0, 0, 0)     # (033A: what a start writes)


def entry(rom, cmd):
    return rom[TABLE + 2 * cmd] | rom[TABLE + 2 * cmd + 1] << 8


def kinds():
    """cmd -> ("fx", chip, header) / ("mus", header) / ("stop", fx, music) / None, for the commands 00-43"""
    rom = Board().mem
    out = {}
    for cmd in range(0x44):
        e = entry(rom, cmd)
        if e >> 8 == 0xFF:
            special = {0: (True, True), 1: (True, False), 4: (False, True)}.get(e & 0xFF)
            out[cmd] = ("stop",) + special if special else None
        else:
            h = rom[e]
            out[cmd] = ("fx", h >> 6 & 1, h) if h & 0x80 else ("mus", h)
    return out


KINDS = kinds()


def audible(v):
    """a music channel's (period, volume): the longest period (30 Hz or lower: an FM channel without a frequency, its
    carriers' level left from the tune before) is silent"""
    return (0, 0) if v[0] >= 4095 else v


def ste_regs(r):
    return capsnd.ste_regs(r, *SSG)


def booted():
    b = Board()
    b.run(CLOCK // 2)
    del b.writes[:]
    return b


def fx_record(cmd, phase, limit=200000):
    """the effect alone, its first step with C022 & 3 == phase -> (out: 12 values a step, the registers after the
    step it ended in, None)"""
    _, chip, hdr = KINDS[cmd]
    b = booted()
    ix = FX_SLOT[chip]
    st = {"started": False, "out": [], "end": None}

    def accept(x):
        x.mem[0xC022] = (phase - 1) & 0xFF

    def step(x):
        if not x.mem[ix + 0] and not st["started"]:
            return
        st["started"] = True
        regs = tuple(x.regs[chip][:11])
        if not x.mem[ix + 0]:
            st["end"] = regs
        else:
            st["out"].append(regs + (x.mem[ix + 31],))
    b.hooks = {ACCEPT: accept, STEP_END: step}
    b.latch = cmd
    while st["end"] is None and len(st["out"]) < limit:
        b.run(TA)
    if st["end"] is None:
        raise RuntimeError("effect $%02X: no end in %d steps" % (cmd, limit))
    return st["out"], st["end"]


def _fx_job(a):
    return fx_record(*a)


def compact(streams, maxp=4096):
    """the four phases' streams of an effect -> (streams cut to a loop's end, loop start, total) when they end in
    a stretch that repeats a period P (all phases alike, the same length): $14 repeats 564 steps for 144 s, $3C 68 steps
    255 times.  None when it saves less than 1000 steps."""
    import numpy as np
    n = len(streams[0])
    if any(len(st) != n for st in streams) or n < 2000:
        return None
    ids = {}
    arrs = [np.array([ids.setdefault(x, len(ids)) for x in st]) for st in streams]
    best = None
    for p in range(1, min(maxp, n // 2)):
        last = -1
        for a in arrs:
            bad = np.nonzero(a[p:] != a[:-p])[0]
            if len(bad):
                last = max(last, int(bad[-1]))
        start = last + 1
        if best is None or start + p < best[0] + best[1]:
            best = (start, p)
    start, p = best
    if n - (start + p) < 1000:
        return None
    return [st[:start + p] for st in streams], start, n


def all_effects(again=False):
    """cmd -> (chip, 0, [the 4 phases' out lists], [their loops], total steps or 0, the end registers)"""
    path = build_dir("blktiger") / "fx.pkl"
    if path.exists() and not again:
        return pickle.loads(path.read_bytes())
    jobs = [(c, ph) for c, k in KINDS.items() if k and k[0] == "fx" for ph in range(4)]
    rec = dict(zip(jobs, capsnd.pool_map(_fx_job, jobs)))
    out = {}
    for c, k in KINDS.items():
        if k and k[0] == "fx":
            r = [rec[c, ph] for ph in range(4)]
            ends = {x[1] for x in r}
            if len(ends) != 1:
                print("  effect $%02X: the phases end with other registers" % c)
            streams = [x[0] for x in r]
            cut = compact(streams)
            if cut:
                streams, loop, total = cut
                out[c] = (k[1], 0, streams, [loop] * 4, total, r[0][1])
                print("  effect $%02X: %d steps, a loop of %d from %d" % (c, total, len(streams[0]) - loop, loop))
            else:
                out[c] = (k[1], 0, streams, [None] * 4, 0, r[0][1])
    path.write_bytes(pickle.dumps(out))
    return out


def mus_record(cmd, limit=200000, verify=3000):
    """the tune alone in the main slot -> ([per channel: (outputs [(period, volume)] a step, loop start or None)], end
    step or None)"""
    b = booted()
    chips = [OPN(CLOCK, 6), OPN(CLOCK, 6)]
    eg = chips[0].eg_rate / STEPS
    done = [0.0]
    out = [[] for _ in range(6)]
    states = [[] for _ in range(6)]
    seen = [{} for _ in range(6)]
    cands = [[] for _ in range(6)]
    loop = [None] * 6
    st = {"k": 0, "end": None, "started": False}
    hdr = KINDS[cmd][1]

    def step(x):
        for chip, reg, v in x.writes:
            chips[chip].write(reg, v)
        del x.writes[:]
        if not st["started"]:
            if x.mem[0xC011] != hdr:
                return
            st["started"] = True
        done[0] += eg
        n = int(done[0])
        done[0] -= n
        for c in chips:
            c.advance(n)
        k = st["k"]
        if x.mem[0xC011] != hdr:
            st["end"] = k
            return
        for ch in range(6):
            hz, amp = chips[ch // 3].channel(ch % 3)
            o = (capsnd.ym_period(hz), capsnd.ym_volume(amp))
            out[ch].append(o)
            if loop[ch] is not None:
                continue
            s = bytes(x.mem[MAIN + 48 * ch:MAIN + 48 * ch + 48])
            states[ch].append(s)
            cands[ch] = [c for c in cands[ch] if states[ch][k - c[1]] == s]
            for j, period in cands[ch]:
                if k - (j + period) >= max(verify, period):
                    loop[ch] = (j, j + period)
                    break
            key = (s, o)
            j = seen[ch].get(key)
            if j is not None and all(c[1] != k - j for c in cands[ch]):
                cands[ch].append([j, k - j])
            seen[ch][key] = k
        st["k"] = k + 1
    b.hooks = {STEP_END: step}
    b.latch = cmd
    while st["end"] is None and not all(l is not None for l in loop):
        b.run(TA)
        if st["k"] > limit:
            raise RuntimeError("tune $%02X: no end or loop in %d steps" % (cmd, limit))
    if st["end"] is not None:
        return [(out[ch][:st["end"]], None) for ch in range(6)], st["end"]
    chans = []
    for ch in range(6):
        j, kk = loop[ch]
        chans.append((out[ch][:kk + 1], j + 1))
    return chans, None


def _mus_job(c):
    return mus_record(c)


def all_tunes(again=False):
    """cmd -> (header, channels, end)"""
    path = build_dir("blktiger") / "music.pkl"
    if path.exists() and not again:
        return pickle.loads(path.read_bytes())
    cmds = [c for c, k in KINDS.items() if k and k[0] == "mus"]
    tunes = {}
    for c, (chans, end) in zip(cmds, capsnd.pool_map(_mus_job, cmds)):
        tunes[c] = (KINDS[c][1], chans, end)
        print("$%02X header %02X %s: %s" % (c, KINDS[c][1], "ends at %d" % end if end is not None else "loops",
                                          " ".join("%d%s" % (len(o), "L%d" % l if l is not None else "") for o, l in chans)))
    path.write_bytes(pickle.dumps(tunes))
    return tunes


class Player:
    """the STE's player (src/sound.s), a step at a time"""
    def __init__(self, fx, tunes):
        self.fxenc = capsnd.fx_encode(fx, conv=ste_regs)
        self.fxend = {c: ste_regs(v[5] + (0,))[:11] for c, v in fx.items()}
        self.mus = capsnd.mus_encode({c: (0, [([audible(v) for v in o], l) for o, l in ch], e)
                                      for c, (h, ch, e) in tunes.items()})
        self.hdr = {c: h for c, (h, ch, e) in tunes.items()}
        self.count = 0                                  # C022
        self.slot = [None, None]
        self.pri = [0, 0]
        self.regs = [ste_regs(IDLE_REGS + (0,))[:11]] * 2
        self.serial = [0, 0]
        self.serials = 0
        self.main = self.backup = None                  # {"cmd", "chans", "n", "end"}

    def tune(self, c):
        slot, end, chans = self.mus[c]
        return {"cmd": c, "hdr": self.hdr[c], "n": 0, "end": end, "chans": [capsnd.Channel(d, l) for d, l in chans]}

    def command(self, c):
        k = KINDS.get(c)
        if not k:
            return
        if k[0] == "fx":
            chip, hdr = k[1], k[2]
            if (hdr & 15) >= (self.pri[chip] & 15):
                self.slot[chip] = capsnd.new_slot(c, 0)
                self.pri[chip] = hdr
                self.regs[chip] = ste_regs(IDLE_REGS + (0,))[:11]
                self.serials += 1
                self.serial[chip] = self.serials
        elif k[0] == "mus":
            p = k[1] & 15
            pm = self.main["hdr"] & 15 if self.main else 0
            pb = self.backup["hdr"] & 15 if self.backup else 0
            if p == pm:
                self.main = self.tune(c)
            elif p > pm:
                self.backup, self.main = self.main, self.tune(c)
            elif pb <= p:
                self.backup = self.tune(c)
        else:
            if k[1]:
                self.slot = [None, None]
                self.pri = [0, 0]
                self.regs = [ste_regs(IDLE_REGS + (0,))[:11]] * 2     # (0301 / 0314: the idle registers)
            if k[2]:
                self.main = self.backup = None

    def step_tune(self, t):
        """-> (the six channels' values, the tune ended at this step: 08DF / 0348, silent)"""
        if t["end"] and t["n"] >= t["end"]:
            return [(0, 0)] * 6, True
        vals = [ch.step() for ch in t["chans"]]
        t["n"] += 1
        return vals, False

    def step(self):
        """a timer A step -> (the effect registers of each chip, the six music channels' (period, volume))"""
        self.count = (self.count + 1) & 3
        for chip in (0, 1):
            s = self.slot[chip]
            if s is None:
                continue
            s["phase"] = (self.count - s["n"]) & 3
            if capsnd.fx_step(self.fxenc, s):
                self.regs[chip] = s["out"][:11]
                self.pri[chip] = s["out"][11]
            else:
                self.regs[chip] = self.fxend[s["cmd"]]
                self.slot[chip] = None
                self.pri[chip] = 0
        vals = [(0, 0)] * 6
        if self.main:
            m = self.main
            vals, ended = self.step_tune(m)
            if ended:
                self.main, self.backup = self.backup, None
            elif m["hdr"] & 0x40 and self.backup:
                v, ended = self.step_tune(self.backup)
                if ended:
                    self.backup = None
        return self.regs, vals

    def shown(self):
        """the chip whose effect started last"""
        return 1 if self.serial[1] > self.serial[0] else 0


def driver_run(latch_at, steps):
    """the driver on a latch value per VBL (latch_at(vbl)) -> per timer A step: (the step's index, both chips'
    SSG registers, the six channels' (period, volume), the commands it accepted before the step)"""
    b = booted()
    chips = [OPN(CLOCK, 6), OPN(CLOCK, 6)]
    for chip, reg, v in b.writes:
        pass
    eg = chips[0].eg_rate / STEPS
    done = [0.0]
    out = []
    pending = []

    def accept(x):
        pending.append(x.latch)

    def step(x):
        for chip, reg, v in x.writes:
            chips[chip].write(reg, v)
        del x.writes[:]
        done[0] += eg
        n = int(done[0])
        done[0] -= n
        for c in chips:
            c.advance(n)
        vals = []
        for ch in range(6):
            hz, amp = chips[ch // 3].channel(ch % 3)
            vals.append((capsnd.ym_period(hz), capsnd.ym_volume(amp)))
        out.append((tuple(x.regs[0][:11]), tuple(x.regs[1][:11]), vals, list(pending)))
        del pending[:]
    b.hooks = {ACCEPT: accept, STEP_END: step}
    b.count0 = b.mem[0xC022]
    v = 0
    while len(out) < steps:
        b.latch = latch_at(v)
        b.run(CLOCK // 50)
        v += 1
    return out[:steps], b.count0


def check(secs, latch_at, label):
    fx, tunes = all_effects(), all_tunes()
    steps = int(secs * STEPS)
    run, count0 = driver_run(latch_at, steps)
    p = Player(fx, tunes)
    p.count = count0 & 3
    fx_bad = mus_bad = mus_n = 0
    first = []
    for i, (r0, r1, vals, cmds) in enumerate(run):
        for c in cmds:
            if c != 0xFF:
                p.command(c)
        regs, mv = p.step()
        for chip, r in enumerate((r0, r1)):
            if capsnd.audible(ste_regs(r + (0,))[:11]) != capsnd.audible(regs[chip]):
                fx_bad += 1
                if len(first) < 3:
                    first.append("step %d chip %d: driver %s player %s" % (i, chip, ste_regs(r + (0,))[:11], regs[chip]))
        for ch in range(6):
            a, b = audible(vals[ch]), audible(mv[ch])
            if a[1] or b[1]:
                mus_n += 1
                if a != b and not (a[1] == 0 and b[1] == 0):
                    mus_bad += 1
    print("%s: %d steps; effects: %d chip-steps differ audibly; music: %d of %d sounding channel-steps differ" % (
        label, steps, fx_bad, mus_bad, mus_n))
    for f in first:
        print("  " + f)
    return fx_bad, mus_bad


def random_commands(seed=1):
    rnd = random.Random(seed)
    fx = [c for c, k in KINDS.items() if k and k[0] == "fx"]
    mus = [c for c, k in KINDS.items() if k and k[0] == "mus"]
    stops = [c for c, k in KINDS.items() if k and k[0] == "stop"]
    seq = {}
    v = 10
    while v < 100000:
        r = rnd.random()
        seq[v] = rnd.choice(fx) if r < 0.75 else rnd.choice(mus) if r < 0.95 else rnd.choice(stops)
        v += rnd.choice((1, 3, 10, 25, 60, 200))
    return lambda vbl: seq.get(vbl, 0xFF)


def game_commands(vbls):
    """the latch per VBL: the reference's in the port's schedule (logic_test.py's inputs), a game tick a VBL"""
    from machine import BlackTiger
    from logic_test import inputs
    m = BlackTiger()
    seq = []
    for f in range(vbls):
        m.inputs[:3] = inputs(f)
        m.run_frame_port()
        seq.append(m.sound_latch)
    return lambda vbl: seq[vbl] if vbl < len(seq) else seq[-1]


def emit(path):
    """build/blktiger/bt_sound.s for src/sound.s"""
    fx, tunes = all_effects(), all_tunes()
    p = Player(fx, tunes)
    L = ["; generated by tools/sound.py: Black Tiger's sound driver as streams (engine/capsnd.py's forms)",
         "\tsection data,data", "\tcnop 0,2", "CS_FXSLOTS = 1", "CS_KILL = 0", "bt_cmds:"]
    size = 0x80 * 8 + 12
    # a command (8 bytes): .b kind (0 none, 1 effect, 2 tune, 3 stop), .b header (stop: bit 0 effects, bit 1 music),
    # .b chip, .b 0, .l the effect or the tune
    for c in range(0x80):
        k = KINDS.get(c)
        if k and k[0] == "fx":
            L.append("\tdc.b 1,%d,%d,0\n\tdc.l bt_fx%02X" % (k[2], k[1], c))
        elif k and k[0] == "mus":
            L.append("\tdc.b 2,%d,0,0\n\tdc.l bt_mu%02X" % (k[1], c))
        elif k:
            L.append("\tdc.b 3,%d,0,0\n\tdc.l 0" % (k[1] | k[2] << 1))
        else:
            L.append("\tdc.b 0,0,0,0\n\tdc.l 0")
    L.append("bt_idle:\tdc.b " + ",".join(str(x) for x in ste_regs(IDLE_REGS + (0,))[:11]))
    L.append("\teven")
    for c in sorted(p.fxenc):
        chip, slot, length, loop, runs, exc, total = p.fxenc[c]
        # an effect: .w length, loop, .l runs, exceptions x 3, .w total, then its end registers (11 bytes)
        L.append("bt_fx%02X:\tdc.w %d,%d\n\tdc.l bt_r%02X,bt_e%02X_1,bt_e%02X_2,bt_e%02X_3\n\tdc.w %d" % (
            c, length, loop, c, c, c, c, total))
        L.append("\tdc.b " + ",".join(str(x) for x in p.fxend[c]) + "\n\teven")
        size += 32
        for name, data in [("bt_r%02X" % c, runs)] + [("bt_e%02X_%d" % (c, ph + 1), exc[ph]) for ph in range(3)]:
            L.append(name + ":")
            for i in range(0, len(data), 24):
                L.append("\tdc.b " + ",".join(str(x) for x in data[i:i + 24]))
            size += len(data)
        L.append("\teven")
    import lz
    biggest = 0
    for c in sorted(p.mus):
        slot, end, chans = p.mus[c]
        # a tune: .w end, unpacked size, the channels' offsets x 6, their loops' offsets x 6 (-1: none), the packed data
        raw = b"".join(x for x, l in chans)
        offs, o = [], 0
        for x, l in chans:
            offs.append(o)
            o += len(x)
        packed = lz.compress(raw)
        assert lz.decompress(packed) == raw
        biggest = max(biggest, len(raw))
        L.append("bt_mu%02X:\tdc.w %d,%d" % (c, end, len(raw)))
        L.append("\tdc.w " + ",".join(str(x) for x in offs))
        L.append("\tdc.w " + ",".join(str(offs[ch] + l) if l >= 0 else "-1" for ch, (x, l) in enumerate(chans)))
        for i in range(0, len(packed), 24):
            L.append("\tdc.b " + ",".join(str(v) for v in packed[i:i + 24]))
        L.append("\teven")
        size += 28 + len(packed)
    L.insert(5, "BT_TUNE_MAX = %d" % ((biggest + 1) & ~1))
    from pathlib import Path
    Path(path).write_text("\n".join(L) + "\n")
    return size


def play(latch_at, vbls):
    """the player as the STE runs it: the latch at each VBL, five steps, the YM's registers -> a list per VBL"""
    p = Player(all_effects(), all_tunes())
    mixer = capsnd.Mixer()
    last = 0
    out = []
    for v in range(vbls):
        c = latch_at(v)
        if c != last:
            last = c
            if c != 0xFF:
                p.command(c)
        for _ in range(PER_VBL):
            regs, vals = p.step()
        out.append(capsnd.combine(list(regs[p.shown()]), mixer, vals))
    return out


if __name__ == "__main__":
    import collections
    if sys.argv[1:2] == ["record"]:
        all_effects(True)
        all_tunes(True)
    if sys.argv[1:2] == ["check"]:
        secs = float(sys.argv[2]) if len(sys.argv) > 2 else 120
        bad = check(secs, random_commands(), "random commands")
        bad2 = check(secs, game_commands(int(secs * 50) + 10), "the game (logic_test.py's play)")
        sys.exit(0)
    if sys.argv[1:2] == ["emit"]:
        print("bt_sound.s: %d bytes" % emit(build_dir("blktiger") / "bt_sound.s"))
    if sys.argv[1:2] == ["wav"]:
        cmd = int(sys.argv[2], 16)
        secs = float(sys.argv[3]) if len(sys.argv) > 3 else 60
        path = build_dir("blktiger") / ("sound_%02X.wav" % cmd)
        capsnd.wav(path, play(lambda v: cmd if v < 2 else 0xFF, int(secs * 50)), 50)
        print(path)
    if sys.argv[1:2] == ["writes"]:
        cmd = int(sys.argv[2], 16)
        secs = float(sys.argv[3]) if len(sys.argv) > 3 else 3
        b = Board()
        b.run(CLOCK)                    # (boot)
        del b.writes[:]
        b.latch = cmd
        b.run(int(CLOCK * secs))
        kinds = collections.Counter()
        for chip, r, v in b.writes:
            k = "SSG %02X" % r if r < 16 else "key 28" if r == 0x28 else "timer %02X" % r if r < 0x30 else "FM %02X" % (r & 0xF0)
            kinds[(chip, k)] += 1
        print("$%02X: %d writes in %.1f s" % (cmd, len(b.writes), secs))
        for (chip, k), n in sorted(kinds.items()):
            print("  YM%d %-10s %6d" % (chip + 1, k, n))
