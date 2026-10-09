"""Commando's sound effects as register streams, from the sound driver itself (tools/sound.py runs it).

The driver (audio ROM): IRQ 0038 reads the latch (0076: a new command != $FF starts through the table at 0088, rst 30),
then sequences (0530) and outputs (094E) the effects.  An effect command loads its slot ix and data hl and starts it
at 092E; command 0 (and $1C-$1F, both 00E6) clears every slot.  Per chip four slots ($4500-$4560 the first chip's,
$4600-$4660 the second's, 32 bytes): the sequencer (0537 / 0564) steps only the highest active one, the output
(0955 / 0A27) writes the SSG registers 0-10 from the highest active one, or the idle values (0A9B) when none is.
So a slot's output after n steps depends only on its effect: out[n] is recorded with the effect alone, until the
slot ends (its byte 0 becomes 0), or until its 32 bytes repeat (a loop: out[n] = out[start + (n - start) % period]).

The music commands ($20-$2C) are the FM part (02B3), not modelled here.

    python sound_sfx.py check [frames]    the model against the driver over the game run of ref/cover.py
"""
import os
import sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import sound
from machine import CYCLES_PER_LINE, LINES, region

TABLE = 0x0088                  # rst 30's table: the handler of command & $3F
STOP = 0x00E6                   # the handler that clears every slot
SLOTS = [(0x4500, 0x4520, 0x4540, 0x4560), (0x4600, 0x4620, 0x4640, 0x4660)]
IRQPROM = region("irqprom")


def handler(rom, cmd):
    return rom[TABLE + 2 * (cmd & 0x3F)] | rom[TABLE + 2 * (cmd & 0x3F) + 1] << 8


def effect_slot(rom, cmd):
    """(chip, slot index) of an effect command: its handler is `ld ix,slot; ld hl,data; jp $092E`, else None"""
    h = handler(rom, cmd)
    if rom[h:h + 2] == b"\xdd\x21" and rom[h + 7] == 0xC3 and rom[h + 8] | rom[h + 9] << 8 == 0x092E:
        ix = rom[h + 2] | rom[h + 3] << 8
        for chip in (0, 1):
            if ix in SLOTS[chip]:
                return chip, SLOTS[chip].index(ix)
    return None


def irqs(s, frames, latch_of, slot=None):
    """run the board: per IRQ, when its handler has returned to the main loop -> (frame, registers 0-10 of both
    chips, the 32 bytes of the slot at address `slot` then)"""
    out = []
    s.on_irq_done = lambda b: out.append((k, tuple(b.regs[0][:11]), tuple(b.regs[1][:11]),
                                          bytes(b.mem[slot:slot + 32]) if slot else None))
    for k in range(frames):
        s.latch = latch_of(k)
        target = s.cpu.cycles
        for line in range(LINES):
            target += CYCLES_PER_LINE
            s.run_line(target, bool(IRQPROM[line & 255] & 4))
            del s.writes[:]
        while out:
            yield out.pop(0)


def record(cmd, phase, limit=40000):
    """the effect alone, started at an IRQ whose counter ($4000, incremented first) & 3 is `phase`: the sequencer does
    part of its work only when it is 0 (05F8) -> (chip, slot, out list, loop start or None)"""
    rom = sound.SoundBoard().mem
    chip, slot = effect_slot(rom, cmd)
    s = sound.SoundBoard()
    for _ in irqs(s, 90, lambda k: 0xFF):      # (boot)
        pass
    s.mem[0x4000] = (phase - 1) & 0xFF        # (the start IRQ increments it to `phase`; nothing reads its other bits for effects)
    ix = SLOTS[chip][slot]
    out, seen = [], {}
    for k, r0, r1, state in irqs(s, limit, lambda k: cmd if k == 0 else 0xFF, ix):
        if not state[0]:
            return chip, slot, out, None
        if state in seen:
            return chip, slot, out, seen[state]
        seen[state] = len(out)
        out.append((r0, r1)[chip])
    raise RuntimeError("effect $%02X: no end or loop in %d frames" % (cmd, limit))


def idle_regs():
    s = sound.SoundBoard()
    for k, r0, r1, _ in irqs(s, 120, lambda k: 0xFF):
        pass
    return r0, r1


class Model:
    """the driver's effect logic on recorded streams"""
    def __init__(self, effects, idle):
        self.effects, self.idle = effects, idle
        self.last = 0                                  # the driver's $4001 (cleared at boot: 0)
        self.count = 0                                 # the driver's $4000 (& 3 is what matters)
        self.slots = [[None] * 4 for _ in range(2)]     # per slot: [cmd, steps, phase] or None

    def irq(self, latch):
        self.count = (self.count + 1) & 3
        if latch != self.last:
            self.last = latch
            if latch != 0xFF:
                h = latch & 0x3F
                if h in self.effects:
                    chip, slot = self.effects[h][:2]
                    self.slots[chip][slot] = [h, 0, self.count]
                elif h == 0 or 0x1C <= h <= 0x1F:
                    self.slots = [[None] * 4 for _ in range(2)]
        out = []
        for chip in (0, 1):
            top = next((i for i in (3, 2, 1, 0) if self.slots[chip][i]), None)
            if top is not None:
                st = self.slots[chip][top]
                st[2] = (self.count - st[1]) & 3        # (a paused slot resumes with another phase: that variant)
                stream, loop = self.effects[st[0]][2][st[2]], self.effects[st[0]][3][st[2]]
                st[1] += 1
                if st[1] > len(stream) and loop is None:
                    self.slots[chip][top] = None
                    top = next((i for i in (3, 2, 1, 0) if self.slots[chip][i]), None)
            if top is None:
                out.append(self.idle[chip])
                continue
            cmd, n, ph = self.slots[chip][top]
            stream, loop = self.effects[cmd][2][ph], self.effects[cmd][3][ph]
            if n == 0:
                out.append(None)                       # (started, not stepped yet: the slot's old registers)
            elif n <= len(stream):
                out.append(stream[n - 1])
            else:
                out.append(stream[loop + (n - 1 - loop) % (len(stream) - loop)])
        return out


def all_effects():
    """cmd -> (chip, slot, [the 4 phases' out lists], [their loop starts])"""
    rom = sound.SoundBoard().mem
    out = {}
    for cmd in range(64):
        if effect_slot(rom, cmd):
            rec = [record(cmd, ph) for ph in range(4)]
            out[cmd] = (rec[0][0], rec[0][1], [r[2] for r in rec], [r[3] for r in rec])
    return out


def check(frames, encoded=True):
    """the model (encoded: the STE player's decoder on the encoded data, in the STE's register values) against the
    driver, IRQ by IRQ, over the game run of tools/sound.py"""
    effects = all_effects()
    model = Decoded(encode(effects), idle_regs()) if encoded else Model(effects, idle_regs())
    conv = ste_regs if encoded else tuple
    total = bad = unknown = 0
    first = None
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ref"))
    import random
    from cover import inputs
    from machine import Commando
    m, s = Commando(), sound.SoundBoard()
    rnd = random.Random(1)
    def done(b):
        nonlocal total, bad, unknown, first
        want = model.irq(b.irq_latch)
        for chip in (0, 1):
            total += 1
            if want[chip] is None:
                unknown += 1
            elif conv(b.regs[chip][:11]) != want[chip]:
                bad += 1
                if first is None:
                    first = (m.frame, chip, conv(b.regs[chip][:11]), want[chip])
    s.on_irq_done = done
    for f in range(frames):
        system, p1, p2 = inputs(f, rnd)
        m.inputs[0], m.inputs[1], m.inputs[2] = system, p1, p2
        target = m.frame * CYCLES_PER_LINE * LINES
        for line in range(LINES):
            irq = m.irqprom[line & 255]
            if irq & 8:
                m.pending = 0xc7 | ((irq << 3) & 0x18)
            target += CYCLES_PER_LINE
            while m.cpu.cycles < target:
                m.step()
            s.latch = m.latch
            s.run_line(target, bool(irq & 4))
            del s.writes[:]
        m.frame += 1
    print("%d effects recorded: %s" % (len(effects), " ".join("$%02X:%d%s" % (c, len(e[2][0]), "L%d" % e[3][0] if e[3][0] is not None else "")
                                                                for c, e in sorted(effects.items()))))
    print("checked:", "the STE player's decoder on the encoded data" if encoded else "the recorded streams")
    print("%d chip-IRQs compared, %d differ, %d not known (started but not stepped)" % (total, bad, unknown))
    if first:
        print("first difference: frame %d chip %d driver %s model %s" % first)
    return bad




# ---- the STE's form: the YM2149 at 2 MHz plays the SSG of a YM2203 whose prescaler the driver sets to 3 at boot
# (0064: registers $2D then $2E, ymfm ym2203::write: 1/2 for the SSG), i.e. an AY at 1.5 MHz / 2: periods * 8 / 3.

def ste_regs(r):
    t = list(r)
    for ch in range(3):
        p = min((r[2 * ch] | (r[2 * ch + 1] & 15) << 8) * 8 // 3, 4095)
        t[2 * ch], t[2 * ch + 1] = p & 255, p >> 8
    t[6] = min((r[6] & 31) * 8 // 3, 31)          # (the noise period has 5 bits: lower noises come out higher)
    t[7] = r[7] | 0xC0                             # (the STE's ports A and B stay outputs)
    return tuple(t)


def encode(effects):
    """-> {cmd: (chip, slot, length, loop or -1, runs bytes, [exceptions bytes of phases 1-3])}.  runs: records of
    (steps 1-255, mask word of the registers that change, their values); the first record and the loop's are whole.
    exceptions: (stream index word, mask word, the masked registers) where a phase's output differs from phase 0's,
    then $FFFF."""
    out = {}
    for cmd, (chip, slot, streams, loops) in effects.items():
        st = [[ste_regs(r) for r in streams[ph]] for ph in range(4)]
        loop = loops[0]
        runs = bytearray()
        prev, i = None, 0
        while i < len(st[0]):
            j = i
            while j + 1 < len(st[0]) and st[0][j + 1] == st[0][i] and j + 1 != loop and j + 1 - i < 255:
                j += 1
            whole = prev is None or i == loop
            mask = sum(1 << k for k in range(11) if whole or st[0][i][k] != prev[k])
            runs += bytes([j - i + 1, mask >> 8, mask & 255]) + bytes(st[0][i][k] for k in range(11) if mask >> k & 1)
            prev, i = st[0][i], j + 1
        exc = []
        for ph in (1, 2, 3):
            e = bytearray()
            for n, (a, b) in enumerate(zip(st[0], st[ph])):
                if a != b:
                    mask = sum(1 << k for k in range(11) if a[k] != b[k])
                    e += bytes([n >> 8, n & 255, mask >> 8, mask & 255]) + bytes(b[k] for k in range(11) if mask >> k & 1)
            exc.append(bytes(e) + b"\xff\xff")
        out[cmd] = (chip, slot, len(st[0]), -1 if loop is None else loop, bytes(runs), exc)
    return out


class Decoded:
    """the player of the STE (src/sfx.s) on the encoded data: the same steps as Model"""
    def __init__(self, enc, idle):
        self.enc, self.idle = enc, [ste_regs(i) for i in idle]
        self.last, self.count, self.serial = 0, 0, 0
        self.slots = [[None] * 4 for _ in range(2)]

    def start(self, chip, slot, cmd):
        e = self.enc[cmd]
        self.serial += 1
        self.slots[chip][slot] = {"cmd": cmd, "n": 0, "phase": self.count, "pos": 0, "left": 0,
                                  "regs": [0] * 11, "serial": self.serial, "exc_phase": None, "exc": 0, "loop_pos": 0}

    def seek_exc(self, s):
        """the exception pointer of the slot's phase at its next index"""
        s["exc"] = 0
        if s["phase"]:
            e = self.enc[s["cmd"]][5][s["phase"] - 1]
            while not (e[s["exc"]] == 0xFF and e[s["exc"] + 1] == 0xFF) and (e[s["exc"]] << 8 | e[s["exc"] + 1]) < s["n"]:
                s["exc"] += 4 + bin(e[s["exc"] + 2] << 8 | e[s["exc"] + 3]).count("1")
        s["exc_phase"] = s["phase"]

    def step(self, s):
        """one step of a slot: -> False when it ended"""
        chip, slot, length, loop, runs, exc = self.enc[s["cmd"]]
        if s["n"] >= length:
            if loop < 0:
                return False
            s["n"] = loop
            s["pos"], s["left"] = s["loop_pos"], 0
            s["exc_phase"] = None                       # (seek again from the loop's index)
        if s["left"] == 0:
            if s["n"] == loop:
                s["loop_pos"] = s["pos"]
            p = s["pos"]
            s["left"] = runs[p]
            mask = runs[p + 1] << 8 | runs[p + 2]
            p += 3
            for k in range(11):
                if mask >> k & 1:
                    s["regs"][k] = runs[p]
                    p += 1
            s["pos"] = p
        s["left"] -= 1
        if s["exc_phase"] != s["phase"]:
            self.seek_exc(s)
        out = tuple(s["regs"])
        if s["phase"]:
            e = exc[s["phase"] - 1]
            q = s["exc"]
            if not (e[q] == 0xFF and e[q + 1] == 0xFF) and (e[q] << 8 | e[q + 1]) == s["n"]:
                mask = e[q + 2] << 8 | e[q + 3]
                o, r = list(out), q + 4
                for k in range(11):
                    if mask >> k & 1:
                        o[k] = e[r]
                        r += 1
                out = tuple(o)
                s["exc"] = r
        s["out"] = out
        s["n"] += 1
        return True

    def irq(self, latch):
        self.count = (self.count + 1) & 3
        if latch != self.last:
            self.last = latch
            if latch != 0xFF:
                h = latch & 0x3F
                if h in self.enc:
                    self.start(self.enc[h][0], self.enc[h][1], h)
                elif h == 0 or 0x1C <= h <= 0x1F:
                    self.slots = [[None] * 4 for _ in range(2)]
        out = []
        for chip in (0, 1):
            top = next((i for i in (3, 2, 1, 0) if self.slots[chip][i]), None)
            if top is not None:
                s = self.slots[chip][top]
                s["phase"] = (self.count - s["n"]) & 3
                if not self.step(s):
                    self.slots[chip][top] = None
                    top = next((i for i in (3, 2, 1, 0) if self.slots[chip][i]), None)
            if top is None:
                out.append(self.idle[chip])
            elif self.slots[chip][top]["n"] == 0:
                out.append(None)
            else:
                out.append(self.slots[chip][top]["out"])
        return out


if __name__ == "__main__":
    if sys.argv[1:2] == ["check"]:
        sys.exit(1 if check(int(sys.argv[2]) if len(sys.argv) > 2 else 3000) else 0)
