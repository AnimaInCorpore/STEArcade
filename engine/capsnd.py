"""Capcom's sound driver of the mid-80s (Commando, Gun.Smoke, 1943) on the STE's YM2149: its output recorded per
command, played back by engine/rt/capsnd.s in the driver's own scheme.  Generalised from Commando's
games/commando/tools/sound_sfx.py and sound_music.py (which hold the derivation; Commando keeps its own copy).

The board: a Z80 at 3 MHz, ROM, 2 KB of RAM, the sound latch, two YM2203 at 1.5 MHz, four IRQs an arcade frame (IM 1).
The driver (the same code at other addresses in each game): the IRQ counts in RAM (`counter`), reads the latch (a new
value != $FF: command value & $3F through the rst 30 table that follows the dispatch), steps the music (FM only), then
sequences and outputs the effects (SSG only):

* Effects: per chip N slots of 32 bytes; a command's handler is `ld ix,slot / ld hl,data / jp start`.  The sequencer
  steps only the highest active slot of each chip, the output writes SSG registers 0-10 from the highest active one
  (or idle values).  Part of the sequencer runs only when counter & 3 == 0, so each effect is recorded alone in the
  four phases.  Some drivers (Gun.Smoke, 1943) end the lower slots under the one shown unless their byte `kill`
  (31) is $FF: that byte is recorded with the output (as a twelfth register).  Only an effect opcode sets it to $FF
  and nothing clears it (but the boot), so a slot keeps it for all later effects: the player ORs it in.
* Music: four slots of six FM channels (32 bytes each, channel n: FM channel n % 3 of chip n // 3); a tune command
  clears its slot (a `call` in its handler) and loads it; only the highest slot whose first channel is active steps.
  Each channel is recorded alone (pitch and loudness of its carriers through engine/opn.py, as a YM2149 period and
  volume) until its 32 bytes repeat (a loop, confirmed over a period more) or the tune ends (then its release as a
  tail).
* Stops: the commands whose handler clears effect slots or music slots, found by running every handler.

A game describes its driver with `Driver(...)` (addresses), its tools call record / check / emit.
"""
import math
import os
import pickle
import random
import sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from z80 import Z80
import z80dis
from opn import OPN


class Driver:
    """the addresses of a game's driver.  rom: the audio CPU's 64 KB region; idle: the pcs of the main loop
    (`ei / jr $`); counter: the IRQ count; last: the last latch value seen; table: the rst 30 table of the commands;
    fx_slots: per chip its effect slots, lowest first; mus_slots: the four music slots, lowest first; kill: the slot
    byte that keeps a lower effect alive ($FF) under a higher one, or None; irq_lines: the lines of a frame with an
    IRQ (262 lines of `line_cycles`); mask: what the dispatch keeps of a command ($3F; Trojan's driver: $7F, then the
    port defines CS_CMDMASK = $7F for engine/rt/capsnd.s)."""
    def __init__(self, name, rom, ram, latch, ym, idle, counter, last, table, fx_slots, mus_slots, kill=None,
                 irq_lines=(32, 96, 160, 224), line_cycles=192, lines=262, build=None, mask=0x3F):
        self.mask = mask
        self.name, self.rom, self.ram, self.latch, self.ym = name, rom, ram, latch, ym
        self.idle, self.counter, self.last, self.table = idle, counter, last, table
        self.fx_slots, self.mus_slots, self.kill = fx_slots, mus_slots, kill
        self.irq_lines, self.line_cycles, self.lines = set(irq_lines), line_cycles, lines
        self.build = Path(build) if build else None
        self.fps = 3000000 / (line_cycles * lines)
        self._kinds = None

    def handler(self, cmd):
        return self.rom[self.table + 2 * (cmd & self.mask)] | self.rom[self.table + 2 * (cmd & self.mask) + 1] << 8

    def kinds(self):
        """cmd (0-63) -> ("fx", chip, slot) / ("mus", slot) / ("stop", fx slots cleared [(chip, slot)], music slots
        cleared) / None"""
        if self._kinds is None:
            self._kinds = {c: classify(self, c) for c in range(self.mask + 1)}
        return self._kinds


class Board:
    """the sound board: the Z80, the latch, the YM2203 writes logged as (chip, register, value), the SSG registers"""
    def __init__(self, d):
        self.d = d
        self.mem = bytearray(65536)
        self.mem[:d.ram[0]] = d.rom[:d.ram[0]]
        self.latch = 0xFF
        self.writes = []
        self.addr = [0, 0]
        self.regs = [[0] * 16, [0] * 16]
        self.cpu = Z80(self.rd8, self.wr8)
        self.irq = False
        self.in_irq = False
        self.on_irq_done = None
        self.irq_latch = 0

    def rd8(self, a):
        if a == self.d.latch:
            return self.latch
        if a < self.d.ram[0] + self.d.ram[1]:
            return self.mem[a]
        return 0xFF

    def wr8(self, a, v):
        d = self.d
        if d.ram[0] <= a < d.ram[0] + d.ram[1]:
            self.mem[a] = v
        elif d.ym <= a <= d.ym + 3:
            chip = (a - d.ym) >> 1
            if a & 1:
                self.writes.append((chip, self.addr[chip], v))
                if self.addr[chip] < 16:
                    self.regs[chip][self.addr[chip]] = v
            else:
                self.addr[chip] = v

    def run_line(self, target, irq_now):
        c = self.cpu
        if irq_now:
            self.irq = True
        while c.cycles < target:
            if self.irq and c.iff1 and not c.ei_delay:
                self.irq = False
                self.in_irq = True
                self.irq_latch = self.latch
                c.iff1 = c.iff2 = 0
                c.halted = False
                c.push(c.pc)
                c.pc = 0x38
                c.cycles += 13
            c.ei_delay = False
            c.step()
            if self.in_irq and c.pc in self.d.idle:
                self.in_irq = False
                if self.on_irq_done:
                    self.on_irq_done(self)

    def frame(self, keep_writes=False):
        """an arcade frame with its IRQs on their lines"""
        t = self.cpu.cycles
        for line in range(self.d.lines):
            t += self.d.line_cycles
            self.run_line(t, line in self.d.irq_lines)
            if not keep_writes:
                del self.writes[:]

    def irq_now(self):
        """one IRQ, run to its end (the STE's model: the four of a tick one after the other)"""
        done = [False]
        old = self.on_irq_done
        self.on_irq_done = lambda b: done.__setitem__(0, True)
        self.run_line(self.cpu.cycles + self.d.line_cycles, True)
        while not done[0]:
            self.run_line(self.cpu.cycles + self.d.line_cycles, False)
        self.on_irq_done = old
        if old:
            old(self)

    def call(self, addr, limit=200000):
        """run the routine at addr to its return (interrupts off)"""
        c = self.cpu
        sp = c.sp
        c.push(0xFFFF)
        c.pc = addr
        for _ in range(limit):
            if c.pc == 0xFFFF and c.sp == sp:
                return
            c.step()
        raise RuntimeError("%s: no return from %04X" % (self.d.name, addr))


def booted(d, frames=90):
    b = Board(d)
    for _ in range(frames):
        b.frame()
    return b


def classify(d, cmd):
    rom = d.rom
    h = d.handler(cmd)
    ins = []
    pc = h
    for _ in range(3):
        r = z80dis.decode(rom, pc)
        ins.append(r)
        pc += r.length
    if rom[h:h + 2] == b"\xdd\x21" and rom[h + 4] == 0x21 and rom[h + 7] == 0xC3:
        ix = rom[h + 2] | rom[h + 3] << 8
        for chip in (0, 1):
            if ix in d.fx_slots[chip]:
                return ("fx", chip, d.fx_slots[chip].index(ix))
    if rom[h] == 0xCD and rom[h + 3] == 0x21 and rom[h + 6] == 0xC3:
        b = booted(d, 10)
        for s in d.mus_slots:
            for ch in range(6):
                b.mem[s + 32 * ch] = 1
        b.call(rom[h + 1] | rom[h + 2] << 8)
        cleared = [i for i, s in enumerate(d.mus_slots) if not b.mem[s]]
        if len(cleared) == 1:
            return ("mus", cleared[0])
    b = booted(d, 10)
    for chip in (0, 1):
        for s in d.fx_slots[chip]:
            b.mem[s] = 1
    for s in d.mus_slots:
        for ch in range(6):
            b.mem[s + 32 * ch] = 1
    try:
        b.call(h)
    except Exception:
        return None
    fx = [(chip, i) for chip in (0, 1) for i, s in enumerate(d.fx_slots[chip]) if not b.mem[s]]
    mus = [i for i, s in enumerate(d.mus_slots) if not b.mem[s]]
    return ("stop", fx, mus) if fx or mus else None


# ================================================================================================= the effects

def irqs(b, ticks, latch_of, slot=None):
    """run the board four IRQs a tick (each to its end) -> per IRQ (tick, chip 0's registers 0-10, chip 1's, the 32
    bytes of the slot at `slot`)"""
    out = []
    b.on_irq_done = lambda x: out.append((k, tuple(x.regs[0][:11]), tuple(x.regs[1][:11]),
                                          bytes(x.mem[slot:slot + 32]) if slot else None))
    for k in range(ticks):
        b.latch = latch_of(k)
        for _ in range(4):
            b.irq_now()
            del b.writes[:]
        while out:
            yield out.pop(0)


def fx_record(d, cmd, phase, limit=40000):
    """the effect alone, started at an IRQ whose counter & 3 is `phase` -> (out list: 12 values a step (the
    registers 0-10 and the kill byte after the step), loop start or None)"""
    _, chip, slot = d.kinds()[cmd]
    b = booted(d)
    b.mem[d.counter] = (phase - 1) & 0xFF
    ix = d.fx_slots[chip][slot]
    out, seen = [], {}
    for k, r0, r1, state in irqs(b, limit, lambda k: cmd if k == 0 else 0xFF, ix):
        if not state[0]:
            return out, None
        if state in seen:
            return out, seen[state]
        seen[state] = len(out)
        out.append((r0, r1)[chip] + ((state[d.kill],) if d.kill is not None else (0,)))
    raise RuntimeError("effect $%02X: no end or loop in %d IRQs" % (cmd, limit))


def idle_regs(d):
    b = booted(d)
    last = None
    for k, r0, r1, _ in irqs(b, 30, lambda k: 0xFF):
        last = (r0, r1)
    return last


def all_effects(d, again=False):
    """cmd -> (chip, slot, [the 4 phases' out lists], [their loop starts]) (cached in build/fx.pkl)"""
    path = d.build / "fx.pkl" if d.build else None
    if path and path.exists() and not again:
        return pickle.loads(path.read_bytes())
    jobs = [(cmd, ph) for cmd, k in d.kinds().items() if k and k[0] == "fx" for ph in range(4)]
    rec = dict(zip(jobs, pool_map(_fx_job, [(d, c, ph) for c, ph in jobs])))
    out = {}
    for cmd, k in d.kinds().items():
        if k and k[0] == "fx":
            r = [rec[cmd, ph] for ph in range(4)]
            out[cmd] = (k[1], k[2], [x[0] for x in r], [x[1] for x in r])
    if path:
        path.write_bytes(pickle.dumps(out))
    return out


def _fx_job(a):
    return fx_record(*a)


def pool_map(f, args):
    """f over args in processes (the recordings are independent; the Z80 in Python is slow)"""
    import multiprocessing
    with multiprocessing.get_context("fork").Pool(min(len(args), os.cpu_count() or 4) or 1) as p:
        return p.map(f, args, chunksize=1)


def ste_regs(r, num=8, den=3):
    """an SSG of a YM2203 at 1.5 MHz with the prescaler the driver sets (3: the SSG at 750 kHz) on the YM2149 at 2 MHz:
    periods * 8 / 3 (num / den: the clock ratio), noise clamped to 5 bits; ports A and B outputs.  (The twelfth value
    passes.)"""
    t = list(r)
    for ch in range(3):
        p = min((r[2 * ch] | (r[2 * ch + 1] & 15) << 8) * num // den, 4095)
        t[2 * ch], t[2 * ch + 1] = p & 255, p >> 8
    t[6] = min((r[6] & 31) * num // den, 31)
    t[7] = r[7] | 0xC0
    return tuple(t)


NREG = 12                       # the registers 0-10 and the kill byte


EXC_LIMIT = 8192                # the phases' exceptions of an effect above this many bytes: phase 0 alone (see fx_encode)


def fx_encode(effects, exc_limit=EXC_LIMIT, conv=ste_regs):
    """effects: {cmd: (chip, slot, the 4 phases' streams, their loops[, the steps in all: its loop repeated])}
    -> {cmd: (chip, slot, length, loop or -1, runs bytes, [exceptions of phases 1-3], total or 0)}.  runs: records of (steps
    1-255, a mask word of the values that change (bit k: value k), those values); the first record and the loop's are
    whole.  exceptions: (index word, mask word, the masked values) where a phase differs from phase 0, then $FFFF.
    An effect whose exceptions would take more than exc_limit bytes plays phase 0 in every phase (1943's $0A: 64 s of
    notes whose volume steps come up to 3 IRQs, 12 ms, earlier or later in the other phases; 50 KB)."""
    out = {}
    for cmd, (chip, slot, streams, loops, *more) in effects.items():
        total = more[0] if more else 0
        st = [[conv(r) for r in streams[ph]] for ph in range(4)]
        loop = loops[0]
        runs = bytearray()
        prev, i = None, 0
        while i < len(st[0]):
            j = i
            while j + 1 < len(st[0]) and st[0][j + 1] == st[0][i] and j + 1 != loop and j + 1 - i < 255:
                j += 1
            whole = prev is None or i == loop
            mask = sum(1 << k for k in range(NREG) if whole or st[0][i][k] != prev[k])
            runs += bytes([j - i + 1, mask >> 8, mask & 255]) + bytes(st[0][i][k] for k in range(NREG) if mask >> k & 1)
            prev, i = st[0][i], j + 1
        exc = []
        for ph in (1, 2, 3):
            e = bytearray()
            for n, (a, b) in enumerate(zip(st[0], st[ph])):
                if a != b:
                    mask = sum(1 << k for k in range(NREG) if a[k] != b[k])
                    e += bytes([n >> 8, n & 255, mask >> 8, mask & 255]) + bytes(b[k] for k in range(NREG) if mask >> k & 1)
            exc.append(bytes(e) + b"\xff\xff")
        if sum(len(e) for e in exc) > exc_limit:
            exc = [b"\xff\xff"] * 3
        out[cmd] = (chip, slot, len(st[0]), -1 if loop is None else loop, bytes(runs), exc, total)
    return out


def new_slot(cmd, phase, serial=0):
    return {"cmd": cmd, "n": 0, "t": 0, "phase": phase, "pos": 0, "left": 0, "regs": [0] * NREG, "serial": serial,
            "exc_phase": None, "exc": 0, "loop_pos": 0, "out": None}


def fx_seek(enc, s):
    s["exc"] = 0
    if s["phase"]:
        e = enc[s["cmd"]][5][s["phase"] - 1]
        while not (e[s["exc"]] == 0xFF and e[s["exc"] + 1] == 0xFF) and (e[s["exc"]] << 8 | e[s["exc"] + 1]) < s["n"]:
            s["exc"] += 4 + bin(e[s["exc"] + 2] << 8 | e[s["exc"] + 3]).count("1")
    s["exc_phase"] = s["phase"]


def fx_step(enc, s):
    """one step of an effect slot s (new_slot) on the encoded data: -> False when it ended; s["out"] its values"""
    chip, slot, length, loop, runs, exc, total = enc[s["cmd"]]
    if total and s["t"] >= total:
        return False
    s["t"] += 1
    if s["n"] >= length:
        if loop < 0:
            return False
        s["n"] = loop
        s["pos"], s["left"] = s["loop_pos"], 0
        s["exc_phase"] = None
    if s["left"] == 0:
        if s["n"] == loop:
            s["loop_pos"] = s["pos"]
        p = s["pos"]
        s["left"] = runs[p]
        mask = runs[p + 1] << 8 | runs[p + 2]
        p += 3
        for k in range(NREG):
            if mask >> k & 1:
                s["regs"][k] = runs[p]
                p += 1
        s["pos"] = p
    s["left"] -= 1
    if s["exc_phase"] != s["phase"]:
        fx_seek(enc, s)
    out = list(s["regs"])
    if s["phase"]:
        e = exc[s["phase"] - 1]
        q = s["exc"]
        if not (e[q] == 0xFF and e[q + 1] == 0xFF) and (e[q] << 8 | e[q + 1]) == s["n"]:
            mask = e[q + 2] << 8 | e[q + 3]
            r = q + 4
            for k in range(NREG):
                if mask >> k & 1:
                    out[k] = e[r]
                    r += 1
            s["exc"] = r
    s["out"] = tuple(out)
    s["n"] += 1
    return True


class FxPlayer:
    """the STE's effect player (engine/rt/capsnd.s cs_irq) on the encoded data, step for step"""
    def __init__(self, d, enc, idle):
        self.d, self.enc, self.idle = d, enc, [ste_regs(i) for i in idle]
        self.nslots = len(d.fx_slots[0])
        self.last, self.count, self.serial = 0, 0, 0
        self.slots = [[None] * self.nslots for _ in range(2)]
        self.flag = [[0] * self.nslots for _ in range(2)]      # the kill byte of each slot (stays when it ends)

    def start(self, chip, slot, cmd):
        self.serial += 1
        self.slots[chip][slot] = new_slot(cmd, self.count, self.serial)

    def step(self, s):
        return fx_step(self.enc, s)


    def top(self, chip):
        return next((i for i in range(self.nslots - 1, -1, -1) if self.slots[chip][i]), None)

    def irq(self, latch):
        """one IRQ -> per chip its output registers 0-10 (None: started, not stepped: the slot's old registers)"""
        self.count = (self.count + 1) & 3
        if latch != self.last:
            self.last = latch
            if latch != 0xFF:
                k = self.d.kinds()[latch & self.d.mask]
                if k and k[0] == "fx" and (latch & self.d.mask) in self.enc:
                    self.start(k[1], k[2], latch & self.d.mask)
                elif k and k[0] == "stop":
                    for chip, i in k[1]:
                        self.slots[chip][i] = None
        out = []
        for chip in (0, 1):
            top = self.top(chip)
            if top is not None:
                s = self.slots[chip][top]
                s["phase"] = (self.count - s["n"]) & 3
                if self.step(s):
                    if s["out"][11] == 0xFF:            # (only an effect's opcode sets it, nothing clears it: the
                        self.flag[chip][top] = 0xFF     # slot keeps it for every later effect)
                else:
                    self.slots[chip][top] = None
                    top = self.top(chip)
            if top is None:
                out.append(self.idle[chip][:11])
                continue
            if self.d.kill is not None:
                for i in range(top):
                    if self.slots[chip][i] and self.flag[chip][i] != 0xFF:
                        self.slots[chip][i] = None
            s = self.slots[chip][top]
            out.append(None if s["n"] == 0 else s["out"][:11])
        return out


def audible(r):
    """the registers 0-10 as far as they sound: a channel with tone and noise off is silent (its period and volume
    zeroed, as combine treats it), a tone period without the tone and the noise period without any noise do not count"""
    r = list(r)
    for c in range(3):
        if (r[7] >> c) & 9 == 9:
            r[2 * c] = r[2 * c + 1] = r[8 + c] = 0
        elif r[7] >> c & 1:
            r[2 * c] = r[2 * c + 1] = 0
    if r[7] & 0x38 == 0x38:
        r[6] = 0
    return tuple(r)


def fx_check(d, latches):
    """the player on the encoded data against the driver, IRQ by IRQ, on a latch value per tick -> differences"""
    model = FxPlayer(d, fx_encode(all_effects(d)), idle_regs(d))
    b = booted(d)
    model.count = b.mem[d.counter] & 3              # (the boot took some IRQs: the phases in step)
    total = bad = raw = unknown = 0
    first = []
    for k, r0, r1, _ in irqs(b, len(latches), lambda k: latches[k]):
        want = model.irq(b.irq_latch)
        for chip, r in enumerate((r0, r1)):
            total += 1
            if want[chip] is None:
                unknown += 1
            elif ste_regs(r)[:11] != want[chip]:
                raw += 1
                if audible(ste_regs(r)[:11]) != audible(want[chip]):
                    bad += 1
                    if len(first) < 3:
                        first.append((k, chip, ste_regs(r)[:11], want[chip]))
    print("effects: %d chip-IRQs compared, %d differ audibly (%d in any register: values left in silent channels), "
          "%d not known (started, not stepped)" % (total, bad, raw, unknown))
    for f in first:
        print("  tick %d chip %d driver %s player %s" % f)
    return bad


# ================================================================================================= the music

GAIN = 14                       # the YM volume of one carrier at full level (see Commando's sound_music.py)
TAIL = 180


def ym_period(hz):
    return 0 if hz <= 0 else max(1, min(4095, round(125000 / hz)))


def ym_volume(amp):
    return 0 if amp <= 0 else max(0, min(15, round(GAIN + 2 * math.log2(amp))))


def mus_record(d, cmd, limit=40000, verify=600):
    """the tune alone -> (slot index, [per channel: (outputs [(period, volume)], loop start or None)], end tick or
    None); see Commando's sound_music.record"""
    slot_i = d.kinds()[cmd][1]
    slot = d.mus_slots[slot_i]
    b = Board(d)
    chips = [OPN(), OPN()]
    eg_per_tick = 1500000 / 36 / 3 / d.fps
    done = [0]

    for _ in range(90):
        b.frame(keep_writes=True)
        for chip, reg, v in b.writes:
            chips[chip].write(reg, v)
        del b.writes[:]

    def tick(latch):
        b.latch = latch
        amps = [0.0] * 6
        hz = [0.0] * 6
        for q in range(4):
            b.irq_now()
            for chip, reg, v in b.writes:
                chips[chip].write(reg, v)
            del b.writes[:]
            done[0] += eg_per_tick / 4
            n = int(done[0])
            done[0] -= n
            for c in chips:
                c.advance(n)
            for ch in range(6):
                h, a = chips[ch // 3].channel(ch % 3)
                amps[ch] += a / 4
                hz[ch] = h
        return [(ym_period(hz[ch]), ym_volume(amps[ch])) for ch in range(6)]

    b.mem[d.counter] = 0
    out = [[] for _ in range(6)]
    states = [[] for _ in range(6)]
    last = [{} for _ in range(6)]
    cands = [[] for _ in range(6)]
    loop = [None] * 6
    end = None
    for k in range(limit):
        o = tick(cmd if k == 0 else 0xFF)
        for ch in range(6):
            out[ch].append(o[ch])
        if end is None and not b.mem[slot]:
            end = k + 1
        if end is not None:
            if k + 1 - end >= TAIL or all(v == 0 for p, v in o):
                return slot_i, [(out[ch][:k + 1], None) for ch in range(6)], end
            continue
        for ch in range(6):
            st = bytes(b.mem[slot + 32 * ch:slot + 32 * ch + 32])
            states[ch].append(st)
            if loop[ch] is not None:
                continue
            cands[ch] = [c for c in cands[ch] if states[ch][k - c[1]] == st]
            for j, period in cands[ch]:
                if k - (j + period) >= max(verify, period):
                    loop[ch] = (j, j + period)
                    break
            key = (st, o[ch])
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
            return slot_i, chans, None
    raise RuntimeError("tune $%02X: no end or loop in %d ticks" % (cmd, limit))


def _mus_job(a):
    return mus_record(*a)


def all_tunes(d, again=False, log=True):
    path = d.build / "music.pkl" if d.build else None
    if path and path.exists() and not again:
        return pickle.loads(path.read_bytes())
    cmds = [cmd for cmd, k in d.kinds().items() if k and k[0] == "mus"]
    tunes = dict(zip(cmds, pool_map(_mus_job, [(d, c) for c in cmds])))
    for cmd in cmds:
        slot, chans, end = tunes[cmd]
        if log:
            print("$%02X slot %d %s: %s" % (cmd, slot, "ends at %d" % end if end else "loops",
                                           " ".join("%d%s" % (len(o), "L%d" % l if l is not None else "") for o, l in chans)))
    if path:
        path.write_bytes(pickle.dumps(tunes))
    return tunes


# The STE's form of a channel: bytes, each tick one step of the decoder:
#   $00-$7F hold n + 1 ticks, $80-$8F volume n, $90-$9F volume - 1 then hold n & 15 + 1 ticks,
#   $A0-$AF b: period (n & 15) << 8 | b (no tick), $FF the end (the loop, or silence)
HOLD, VOL, DOWN, PERIOD, END = 0x00, 0x80, 0x90, 0xA0, 0xFF


def encode_channel(out, loop):
    b = bytearray()
    cur = None
    loop_at = -1
    i = 0
    while i < len(out):
        p, v = out[i]
        whole = cur is None or i == loop
        if i == loop:
            loop_at = len(b)
        j = i + 1
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


def mus_encode(tunes):
    return {cmd: (slot, end or 0, [encode_channel(o, l) for o, l in chans]) for cmd, (slot, chans, end) in tunes.items()}


class Mixer:
    """the music's YM channels: the loudest of the six (n) on the channels the effect leaves free (capsnd_core.s
    cs_mix); boost: per channel a number added to its key (Bubble Bobble's effects on the FM channels before its
    music)"""
    def __init__(self, n=6, boost=None):
        self.n = n
        self.boost = boost or [0] * n
        self.ym = [-1] * n

    def mix(self, vals, used):
        free = [c for c in range(3) if not used >> c & 1]
        key = lambda ch: vals[ch][1] * 2 + (self.ym[ch] >= 0) + self.boost[ch]
        picked = sorted((ch for ch in range(self.n) if vals[ch][0] and vals[ch][1]), key=lambda ch: (-key(ch), ch))[:len(free)]
        out, new = {}, [-1] * self.n
        for ch in picked:
            if self.ym[ch] in free:
                out[self.ym[ch]], new[ch] = vals[ch], self.ym[ch]
        for ch in picked:
            if new[ch] < 0:
                c = next(c for c in free if c not in out)
                out[c], new[ch] = vals[ch], c
        self.ym = new
        return out


class MusPlayer:
    """the STE's music (capsnd.s cs_mus_tick): the slots, the commands, the highest slot that plays steps"""
    def __init__(self, d, enc):
        self.d, self.enc = d, enc
        self.slots = [None] * 4
        self.last = 0

    def tick(self, latch):
        if latch != self.last:
            self.last = latch
            if latch != 0xFF:
                k = self.d.kinds()[latch & self.d.mask]
                if k and k[0] == "mus" and (latch & self.d.mask) in self.enc:
                    slot, end, chans = self.enc[latch & self.d.mask]
                    self.slots[slot] = {"n": 0, "end": end, "chans": [Channel(dd, l) for dd, l in chans], "tail": False}
                elif k and k[0] == "stop":
                    for i in k[2]:
                        self.slots[i] = None
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
        for s in range(4):
            if s != top and self.slots[s] and self.slots[s]["tail"] and not sl["tail"]:
                self.slots[s] = None
        return vals


def mus_check(d, tunes=None):
    tunes = tunes or all_tunes(d)
    enc = mus_encode(tunes)
    bad = total = 0
    for cmd, (slot, chans, end) in sorted(tunes.items()):
        for ch, (out, loop) in enumerate(chans):
            dd = Channel(*enc[cmd][2][ch])
            n = len(out) + (2 * (len(out) - loop) if loop is not None else 30)
            for i in range(n):
                want = out[i] if i < len(out) else out[loop + (i - loop) % (len(out) - loop)] if loop is not None else (out[-1][0], 0)
                got = dd.step()
                total += 1
                if got != want and not (want[1] == 0 and got[1] == 0):
                    bad += 1
                    if bad < 5:
                        print("$%02X channel %d tick %d: decoder %s recording %s" % (cmd, ch, i, got, want))
    size = sum(len(x) for e in enc.values() for x, l in e[2])
    print("music: %d tunes, %d channel ticks checked, %d differ; the streams take %d bytes" % (len(enc), total, bad, size))
    return bad


def combine(eff, mixer, vals):
    """the YM's registers 0-10: the effect's on the channels it sounds on, the music through the mixer on the others"""
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


class Ste:
    """the whole STE player a tick (capsnd.s cs_tick): the four IRQs of the effects, the chip whose shown effect started
    last, the music on the channels it leaves -> the YM's registers 0-10"""
    def __init__(self, d):
        self.fx = FxPlayer(d, fx_encode(all_effects(d)), idle_regs(d))
        self.mus = MusPlayer(d, mus_encode(all_tunes(d)))
        self.mixer = Mixer()
        self.eff = list(self.fx.idle[0][:11])

    def tick(self, latch):
        for _ in range(4):
            outs = self.fx.irq(latch)
        serial = [max((sl["serial"] for sl in self.fx.slots[chip] if sl), default=0) for chip in (0, 1)]
        chip = 1 if serial[1] > serial[0] else 0
        if outs[chip] is not None:
            self.eff = list(outs[chip])
        return combine(self.eff, self.mixer, self.mus.tick(latch))


# ================================================================================================= the STE's data

def emit(d, path):
    """the data of engine/rt/capsnd.s: cs_cmds (64 commands: kind, slot, the effect's or the tune's entry), the effects'
    runs and exceptions, the idle registers, the tunes' channels"""
    effects = all_effects(d)
    fx = fx_encode(effects)
    mus = mus_encode(all_tunes(d))
    idle = [ste_regs(i)[:11] for i in idle_regs(d)]
    L = ["; generated by engine/capsnd.py for %s: the sound driver's effects and music as streams" % d.name,
         "\tsection data,data", "\tcnop 0,2",
         "CS_FXSLOTS = %d" % len(d.fx_slots[0]), "CS_KILL = %d" % (d.kill is not None), "cs_cmds:"]
    # a command: .b kind (0 none, 1 effect, 2 tune, 3 stop), .b chip/slot, .w the effect slots a stop clears (bit
    # chip * 8 + slot), .b the music slots it clears, .b 0, .l the effect's or the tune's entry
    for cmd in range(d.mask + 1):
        k = d.kinds()[cmd]
        if k and k[0] == "fx" and cmd in fx:
            L.append("\tdc.b 1,%d\n\tdc.w 0\n\tdc.b 0,0\n\tdc.l cs_fx%02X" % (k[1] * 8 + k[2], cmd))
        elif k and k[0] == "mus" and cmd in mus:
            L.append("\tdc.b 2,%d\n\tdc.w 0\n\tdc.b 0,0\n\tdc.l cs_mu%02X" % (k[1], cmd))
        elif k and k[0] == "stop":
            L.append("\tdc.b 3,0\n\tdc.w %d\n\tdc.b %d,0\n\tdc.l 0" % (sum(1 << (c * 8 + i) for c, i in k[1]),
                                                                     sum(1 << i for i in k[2])))
        else:
            L.append("\tdc.b 0,0\n\tdc.w 0\n\tdc.b 0,0\n\tdc.l 0")
    L.append("cs_idle:")
    for chip in (0, 1):
        L.append("\tdc.b " + ",".join(str(v) for v in idle[chip]))
    L.append("\teven")
    size = (d.mask + 1) * 10 + 22
    for cmd in sorted(fx):
        chip, slot, length, loop, runs, exc, total = fx[cmd]
        L.append("cs_fx%02X:\tdc.w %d,%d\n\tdc.l cs_r%02X,cs_e%02X_1,cs_e%02X_2,cs_e%02X_3\n\tdc.w %d" % (
            cmd, length, loop, cmd, cmd, cmd, cmd, total))
        size += 22
        for name, data in [("cs_r%02X" % cmd, runs)] + [("cs_e%02X_%d" % (cmd, ph + 1), exc[ph]) for ph in range(3)]:
            L.append(name + ":")
            for i in range(0, len(data), 24):
                L.append("\tdc.b " + ",".join(str(x) for x in data[i:i + 24]))
            size += len(data)
        L.append("\teven")
    for cmd in sorted(mus):
        slot, end, chans = mus[cmd]
        L.append("cs_mu%02X:\tdc.w %d" % (cmd, end))
        L.append("\tdc.l " + ",".join("cs_m%02X_%d" % (cmd, ch) for ch in range(6)))
        L.append("\tdc.l " + ",".join("cs_m%02X_%d+%d" % (cmd, ch, l) if l >= 0 else "0" for ch, (x, l) in enumerate(chans)))
        size += 50
        for ch, (x, l) in enumerate(chans):
            L.append("cs_m%02X_%d:" % (cmd, ch))
            for i in range(0, len(x), 24):
                L.append("\tdc.b " + ",".join(str(v) for v in x[i:i + 24]))
            size += len(x)
        L.append("\teven")
    Path(path).write_text("\n".join(L) + "\n")
    return size


# ================================================================================================= listening

YM_LEVELS = [0, 78, 178, 262, 369, 509, 701, 965, 1334, 1853, 2576, 3576, 5000, 7023, 9963, 14132]


def wav(path, ticks_regs, fps, rate=44100):
    """the YM's registers a tick (11 each) as a mono 16-bit wav (tones and noise)"""
    import struct
    import wave
    out = bytearray()
    phase = [0.0] * 3
    noise_ph, lfsr, nbit = 0.0, 1, 0
    per_tick = rate / fps
    acc = 0.0
    for r in ticks_regs:
        acc += per_tick
        n = int(acc)
        acc -= n
        chans = []
        for c in range(3):
            p = r[2 * c] | (r[2 * c + 1] & 15) << 8
            tone = p and not r[7] >> c & 1
            noise = not r[7] >> (c + 3) & 1
            chans.append((125000 / max(p, 1) / rate, YM_LEVELS[r[8 + c] & 15], tone, noise))
        nstep = 125000 / max(r[6] & 31, 1) / rate
        for _ in range(n):
            noise_ph += nstep
            while noise_ph >= 1:
                noise_ph -= 1
                nbit = lfsr & 1
                lfsr = (lfsr >> 1) | (((lfsr ^ (lfsr >> 3)) & 1) << 16)
            v = 0
            for c, (st, lvl, tone, noise) in enumerate(chans):
                phase[c] = (phase[c] + st) % 1.0
                on = (phase[c] < 0.5 if tone else True) and (nbit if noise else True)
                if lvl and (tone or noise) and on:
                    v += lvl
            out += struct.pack("<h", int(v * 0.6) - 13000)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(out))


def random_latches(d, ticks, seed=1):
    """commands every 1-400 ticks: effects, tunes, stops; $FF between them (the main CPU's idle value)"""
    rnd = random.Random(seed)
    kinds = d.kinds()
    fx = [c for c, k in kinds.items() if k and k[0] == "fx"]
    mus = [c for c, k in kinds.items() if k and k[0] == "mus"]
    stops = [c for c, k in kinds.items() if k and k[0] == "stop"]
    out = []
    while len(out) < ticks:
        r = rnd.random()
        cmd = rnd.choice(fx) if r < 0.75 or not mus else rnd.choice(mus) if r < 0.95 or not stops else rnd.choice(stops)
        out += [cmd] * rnd.choice((1, 1, 2)) + [0xFF] * rnd.choice((1, 3, 10, 30, 100, 400))
    return out[:ticks]
