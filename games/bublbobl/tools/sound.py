"""Bubble Bobble's sound board (MAME taito/bublbobl.cpp): a Z80 at 3 MHz, ROM 0000-7FFF (a78-07.46), RAM 8000-8FFF,
a YM2203 at 9000/9001 (3 MHz; its timers interrupt the CPU, IM 1) and a YM3526 at A000/A001 (3 MHz), the latch from
the main CPU at B000 (its write raises the NMI while B001 / B002 allow it), the reply at B000 (written), the semaphores
at B001.  The chips are not emulated beyond the YM2203's status (its timer flags; never busy): the register writes are
logged as (chip, register, value), chip 0 the YM2203, 1 the YM3526.

The driver: the NMI (0066) queues a command (< $F0) in a ring of 16 at 8F82 (8F80 / 8F81); the main loop (016D)
takes them (02A3: 00-34 sounds through the table at 329C, E0-EF 03B0, F0-FE 044B); timer A (8FA3, the tempo:
0150 at boot) runs 04D8 and 0535, timer B (D5) 125E and 225B.

    python sound.py writes CMD [secs]     the registers a command's sound writes (a summary)
"""
import math
import os
import pickle
import random
import sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from z80 import Z80
from paths import EXTRACTED, build_dir
import capsnd
from opn import OPN
from opl import OPL

CLOCK = 3000000


class Board:
    def __init__(self):
        self.mem = bytearray(65536)
        rom = (EXTRACTED / "bublbobl" / "a78-07.46").read_bytes()
        self.mem[:len(rom)] = rom
        self.latch = 0
        self.writes = []
        self.addr = [0, 0]
        self.regs = [[0] * 256, [0] * 256]
        self.flags = 0
        self.ctrl = 0
        self.ta = self.tb = 0                   # the timers' values (registers 24/25, 26)
        self.next_a = self.next_b = None
        self.nmi_ok = False
        self.pending = False                    # the main CPU wrote the latch (the semaphore)
        self.opl_t1 = None                      # when the YM3526's timer 1 expires
        self.tick_writes = []
        self.cpu = Z80(self.rd8, self.wr8)
        self.hooks = {}

    def rd8(self, a):
        if a < 0x9000:
            return self.mem[a]
        if 0x9000 <= a < 0xA000:                # (the data port reads back the SSG's registers: the driver checks it, 017A)
            return self.flags if not a & 1 else self.regs[0][self.addr[0]] if self.addr[0] < 16 else 0
        if 0xA000 <= a < 0xB000:                # the YM3526's status: timer 1's flag (the first IRQ waits for it, 022B)
            if self.opl_t1 is not None and self.cpu.cycles >= self.opl_t1:
                return 0xC0
            return 0
        if 0xB000 <= a < 0xC000:
            if a & 3 == 0:
                self.pending = False
                return self.latch
            if a & 3 == 1:
                return 0xFF & ~(2 if self.pending else 0) & ~1
            return 0xFF
        return 0xFF                             # (E000: no diagnostic ROM)

    def wr8(self, a, v):
        if 0x8000 <= a < 0x9000:
            self.mem[a] = v
        elif 0x9000 <= a < 0xB000:
            chip = 0 if a < 0xA000 else 1
            if a & 1:
                r = self.addr[chip]
                self.writes.append((chip, r, v))
                self.tick_writes.append((chip, r, v))
                self.regs[chip][r] = v
                if chip == 0:
                    self.timer_write(r, v)
                elif r == 4:
                    if v & 0x80:
                        self.opl_t1 = None
                    elif v & 1:
                        self.opl_t1 = self.cpu.cycles + 240 * (256 - self.regs[1][2])     # (80 us a count)
            else:
                self.addr[chip] = v
        elif 0xB000 <= a < 0xC000:
            if a & 3 == 1:
                self.nmi_ok = True
            elif a & 3 == 2:
                self.nmi_ok = False

    def timer_write(self, r, v):
        c = self.cpu.cycles
        if r == 0x27:
            self.ctrl = v
            self.flags &= ~(v >> 4) & 3
            if v & 1 and self.next_a is None:
                self.next_a = c + self.period_a()
            if not v & 1:
                self.next_a = None
            if v & 2 and self.next_b is None:
                self.next_b = c + self.period_b()
            if not v & 2:
                self.next_b = None

    def period_a(self):
        na = self.regs[0][0x24] << 2 | self.regs[0][0x25] & 3
        return 72 * (1024 - na)

    def period_b(self):
        return 1152 * (256 - self.regs[0][0x26])

    def command(self, v):
        """the main CPU writes the latch: the NMI when allowed (else when it is allowed again)"""
        self.latch = v
        self.pending = True

    def run(self, cycles):
        c = self.cpu
        end = c.cycles + cycles
        while c.cycles < end:
            if self.next_a is not None and c.cycles >= self.next_a:
                self.next_a += self.period_a()
                if self.ctrl & 4:
                    self.flags |= 1
            if self.next_b is not None and c.cycles >= self.next_b:
                self.next_b += self.period_b()
                if self.ctrl & 8:
                    self.flags |= 2
            if self.pending and self.nmi_ok:
                self.pending = False
                c.halted = False
                c.push(c.pc)
                c.pc = 0x66
                c.iff1 = 0
                c.cycles += 11
                self.nmi_ok = False                 # (the edge: the merger's output drops when the handler clears it)
            elif self.flags and c.iff1 and not c.ei_delay:
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


# ================================================================================================= the tracks

ROM = (EXTRACTED / "bublbobl" / "a78-07.46").read_bytes()
VBL = CLOCK // 50                       # the STE samples the sound once a VBL
TABLE = 0x329C                          # the commands
TCBS = 0x0378                           # the tracks' control blocks, by (track id - $84) / 2


def tcb(track):
    i = (track - 0x84) // 2
    return ROM[TCBS + 2 * i] | ROM[TCBS + 2 * i + 1] << 8


def track_kind(t):
    """-> (kind, channel, set): "L" an OPL channel, "F" a YM2203 FM channel, "S" the SSG; set 0 (A: wins while it
    plays, 0535) or 1 (B)"""
    if t in (0x84, 0x86):
        return "S", 0, (t - 0x84) // 2
    if 0x8C <= t <= 0x96:
        return "F", (t - 0x8C) // 4, (t - 0x8C) // 2 & 1
    return "L", (t - 0x98) // 4, (t - 0x98) // 2 & 1


def items(cmd):
    """the command's items: [(track, priority byte, item address)] and the commands it queues ([cmd])"""
    e = ROM[TABLE + 2 * cmd] | ROM[TABLE + 2 * cmd + 1] << 8
    n = ROM[e]
    if n == 0:
        return [], []
    if n >= 0x1B:
        return [(ROM[e], ROM[e + 1], e)], []
    out, chain = [], []
    for k in range(n):
        p = ROM[e + 1 + 2 * k] | ROM[e + 2 + 2 * k] << 8
        if p < 0x100:
            chain.append(p)
        else:
            out.append((ROM[p], ROM[p + 1], p))
    return out, chain


SOUNDS = [c for c in range(0x35) if items(c)[0] or items(c)[1]]


def booted():
    b = Board()
    b.run(CLOCK)
    b.command(0xEF)                     # (what the game sends first: the sound on)
    b.run(CLOCK // 5)
    del b.writes[:]
    return b


class Chips:
    """the YM2203's FM and the YM3526 through engine/opn.py and opl.py: per channel (YM2149 period, volume)"""
    def __init__(self):
        self.opn, self.opl = OPN(CLOCK, 6), OPL(CLOCK)
        self.done = [0.0, 0.0]

    def feed(self, writes):
        for chip, r, v in writes:
            (self.opn if chip == 0 else self.opl).write(r, v)
        del writes[:]

    def advance(self, cycles):
        for i, c in enumerate((self.opn, self.opl)):
            self.done[i] += c.eg_rate * cycles / CLOCK
            n = int(self.done[i])
            self.done[i] -= n
            c.advance(n)

    def value(self, kind, ch):
        hz, amp = (self.opn if kind == "F" else self.opl).channel(ch)
        p = capsnd.ym_period(hz)
        return (0, 0) if p >= 4095 else (p, capsnd.ym_volume(amp))


def ssg_regs(b):
    return capsnd.ste_regs(tuple(b.regs[0][:11]) + (0,))[:11]


def record(cmd, limit=15000, verify=600):
    """the command alone, a VBL at a time -> ({track: (priority, values a VBL (an OPL / FM channel: (period,
    volume); the SSG: its 11 registers), loop start VBL or None)}, the commands it queues); a track's values end when
    it ends.  A loop: the chip writes of the timer ticks repeat with a period (the tracks' blocks hold a counter that
    never repeats), confirmed over `verify` ticks or one period, whichever is longer"""
    its, chain = items(cmd)
    b = booted()
    chips = Chips()
    tracks = [t for t, p, a in its]
    ticks = {"A": [], "B": []}          # per timer tick: (cycles, a hash of the writes of its routines)
    logs = {"A": [], "B": []}
    cur = ["A"]

    def start(timer):
        def f(x):
            cur[0] = timer
            x.tick_writes = logs[timer]
        return f

    def tick(timer):
        def f(x):
            ticks[timer].append((x.cpu.cycles, hash(tuple(logs[timer]))))
            del logs[timer][:]
        return f
    b.hooks = {0x01AB: start("A"), 0x01C5: tick("A"), 0x01CA: start("B"), 0x01E4: tick("B")}
    timer = "A" if any(track_kind(t)[0] == "L" for t in tracks) else "B"
    t0 = b.cpu.cycles
    b.command(cmd)
    out = {t: [] for t in tracks}
    busy_seen = {t: False for t in tracks}
    ended = {t: None for t in tracks}
    loop = None
    for v in range(limit):
        b.run(VBL)
        chips.feed(b.writes)
        chips.advance(VBL)
        for t in tracks:
            if ended[t] is not None:
                continue
            busy = b.mem[tcb(t)] & 3
            if busy:
                busy_seen[t] = True
            elif busy_seen[t]:
                ended[t] = v
                continue
            kind, ch, _ = track_kind(t)
            out[t].append(ssg_regs(b) if kind == "S" else chips.value(kind, ch))
        if all(ended[t] is not None for t in tracks):
            break
        if v % 250 == 249 and len(ticks[timer]) > 2 * verify:
            tk = ticks[timer]
            h = [x[1] for x in tk]
            n = len(h)
            for per in range(1, n // 2):
                w = max(verify, per)
                if n - per - w < 1:
                    break
                if h[n - w:] == h[n - w - per:n - per]:
                    # the earliest tick the repetition reaches back to
                    j = n - w - per
                    while j > 0 and h[j - 1] == h[j - 1 + per]:
                        j -= 1
                    loop = (tk[j][0] - t0, tk[j + per][0] - t0)
                    break
            if loop:
                break
    pri = {t: p for t, p, a in its}
    res = {}
    for t in tracks:
        lp = None
        if loop is not None and ended[t] is None:
            a, z = loop
            start = math.ceil(a / VBL)
            period = max(1, round((z - a) / VBL))
            n = start + period
            if n > len(out[t]):
                raise RuntimeError("$%02X: the loop is longer than the recording" % cmd)
            out[t], lp = out[t][:n], start
        elif ended[t] is None:
            raise RuntimeError("$%02X track %02X: no end or loop in %d VBLs" % (cmd, t, limit))
        res[t] = (pri[t], out[t], lp)
    return res, chain


def _job(c):
    return c, record(c)


def all_sounds(again=False):
    path = build_dir("bublbobl") / "sound.pkl"
    if path.exists() and not again:
        return pickle.loads(path.read_bytes())
    out = dict(capsnd.pool_map(_job, SOUNDS))
    for c in sorted(out):
        tr, chain = out[c]
        print("$%02X: %s%s" % (c, " ".join("%02X:%d%s" % (t, len(o), "L%d" % l if l is not None else "")
                                         for t, (p, o, l) in sorted(tr.items())), " then %s" % chain if chain else ""))
    path.write_bytes(pickle.dumps(out))
    return out


# ================================================================================================= the STE's player

OPL_A = [0x98 + 4 * k for k in range(9)]          # each OPL channel's A track (it wins while it plays) and B track
FM_A = [0x8C + 4 * k for k in range(3)]
BOOST = [0] * 9 + [64] * 3                          # the mixer: the FM channels (effects) before the OPL (music)
SSG_IDLE = capsnd.ste_regs((0,) * 7 + (0xFF, 0, 0, 0, 0))[:11]


class Player:
    """the STE's player (src/sound.s), a VBL at a time: per track the stream of the command that started it last
    (unless a playing one has a lower priority number: 0357), the A track of a channel over its B track (0535)"""
    def __init__(self, sounds):
        self.sounds = sounds
        self.enc = {}
        for c, (tr, chain) in sounds.items():
            for t, (pri, vals, loop) in tr.items():
                if track_kind(t)[0] == "S":
                    stream = [tuple(v) + (0,) for v in vals]
                    self.enc[c, t] = capsnd.fx_encode({0: (0, 0, [stream] * 4, [loop] * 4)}, conv=lambda r: r)[0]
                else:
                    self.enc[c, t] = capsnd.encode_channel(vals, loop if loop is not None else None)
        self.tracks = {}
        self.ssg = SSG_IDLE

    def command(self, c):
        if c not in self.sounds:
            return
        tr, chain = self.sounds[c]
        for t, (pri, vals, loop) in tr.items():
            cur = self.tracks.get(t)
            if cur and cur["pri"] < (pri & 0xF0):
                continue
            if track_kind(t)[0] == "S":
                st = capsnd.new_slot((c, t), 0)
            else:
                st = capsnd.Channel(*self.enc[c, t])
            self.tracks[t] = {"pri": pri, "st": st, "cmd": c, "n": 0, "len": len(vals), "loop": loop}
        for c2 in chain:
            self.command(c2)

    def step(self):
        """a VBL -> (the SSG's registers, the twelve channels' (period, volume): OPL 0-8, FM 0-2)"""
        vals = {}
        for t in list(self.tracks):
            tk = self.tracks[t]
            if tk["loop"] is None and tk["n"] >= tk["len"]:
                del self.tracks[t]
                continue
            tk["n"] += 1
            if track_kind(t)[0] == "S":
                capsnd.fx_step(self.enc, tk["st"])
                vals[t] = tuple(tk["st"]["out"][:11])
            else:
                vals[t] = tk["st"].step()
        out = []
        for k in range(9):
            out.append(vals.get(OPL_A[k], vals.get(OPL_A[k] + 2, (0, 0))))
        for k in range(3):
            out.append(vals.get(FM_A[k], vals.get(FM_A[k] + 2, (0, 0))))
        ssg = vals.get(0x84, vals.get(0x86))
        if ssg is not None:
            self.ssg = ssg
        elif 0x84 not in self.tracks and 0x86 not in self.tracks:
            self.ssg = tuple(self.ssg[:8]) + (0, 0, 0)
        return self.ssg, out


def driver_run(cmds, vbls):
    """the driver a VBL at a time with cmds[v] (or nothing) sent at VBL v -> per VBL (the SSG's registers, the twelve
    channels' values)"""
    b = booted()
    chips = Chips()
    out = []
    for v in range(vbls):
        if v in cmds:
            b.command(cmds[v])
        b.run(VBL)
        chips.feed(b.writes)
        chips.advance(VBL)
        out.append((ssg_regs(b), [chips.value("L", k) for k in range(9)] + [chips.value("F", k) for k in range(3)]))
    return out


def random_commands(vbls, seed=1):
    rnd = random.Random(seed)
    music = [c for c in SOUNDS if any(track_kind(t)[0] == "L" for t, p, a in items(c)[0])]
    fx = [c for c in SOUNDS if c not in music]
    out, v = {}, 5
    while v < vbls:
        out[v] = rnd.choice(music) if rnd.random() < 0.1 else rnd.choice(fx)
        v += rnd.choice((2, 5, 10, 25, 50, 150))
    return out


def game_commands(frames):
    """the commands of the reference's attract mode and play (logic_test.py's inputs), a game frame a VBL"""
    import machine
    from logic_test import inputs
    m = machine.Bublbobl()
    for f in range(frames):
        m.in0, m.in1, m.in2 = inputs(f)
        m.run_frame_port()
    out = {}
    for f, v in m.snd_log:
        if f in out:
            f += 1
        out[f] = v
    return out


def check(vbls, cmds, label):
    sounds = all_sounds()
    p = Player(sounds)
    run = driver_run(cmds, vbls)
    bad_ch = total = bad_ssg = near = 0
    first = []
    model = []
    for v in range(vbls):
        if v in cmds:
            p.command(cmds[v])
        model.append(p.step())
    for v in range(vbls):
        ssg, vals = model[v]
        dssg, dvals = run[v]
        if capsnd.audible(ssg) != capsnd.audible(dssg):
            bad_ssg += 1
        for k in range(12):
            a, b = dvals[k], vals[k]
            if a[1] or b[1]:
                total += 1
                if a != b:
                    # (the driver's timer ticks fall elsewhere in the VBL than in the recording: a VBL early or late,
                    # a volume step from an envelope carried over)
                    if any(model[u][1][k] == a for u in (v - 1, v + 1) if 0 <= u < vbls) or \
                            any(run[u][1][k] == b for u in (v - 1, v + 1) if 0 <= u < vbls) or (a[0] == b[0] and abs(a[1] - b[1]) <= 1):
                        near += 1
                        continue
                    bad_ch += 1
                    if len(first) < 8:
                        first.append("VBL %d channel %d: driver %s player %s" % (v, k, a, b))
    print("%s: %d VBLs, %d commands; SSG: %d VBLs differ audibly; FM / OPL: %d of %d sounding channel-VBLs differ "
          "(%d more a VBL early / late or a volume step off)" % (label, vbls, len(cmds), bad_ssg, bad_ch, total, near))
    for f in first:
        print("  " + f)


def play(cmds, vbls):
    """the STE's player as it runs (a VBL: the commands sent, a step, the mixer) -> the YM's registers 0-10 a VBL"""
    p = Player(all_sounds())
    mixer = capsnd.Mixer(12, BOOST)
    out = []
    for v in range(vbls):
        for c in cmds.get(v, ()):
            p.command(c)
        ssg, vals = p.step()
        out.append(capsnd.combine(list(ssg), mixer, vals))
    return out


def emit(path):
    """build/bublbobl/bb_sound.s for src/sound.s: bb_cmds (a long a command: its record or 0); a record: .b the items,
    the chained commands; per item .b the track (0-27: ($84-$BA) / 2), the priority, the kind (0 a channel stream,
    1 SSG registers), 0, .w the VBLs (0: it loops), .l the stream (a channel's bytes / an effect entry), .l the loop
    (0: none); then the chained commands (bytes)"""
    sounds = all_sounds()
    p = Player(sounds)
    L = ["; generated by tools/sound.py: Bubble Bobble's sound driver as streams (engine/capsnd.py's forms)",
         "\tsection data,data", "\tcnop 0,2", "CS_FXSLOTS = 1", "CS_KILL = 0", "bb_cmds:"]
    size = 0x35 * 4
    for c in range(0x35):
        L.append("\tdc.l %s" % ("bb_c%02X" % c if c in sounds else "0"))
    for c in sorted(sounds):
        tr, chain = sounds[c]
        L.append("bb_c%02X:\tdc.b %d,%d" % (c, len(tr), len(chain)))
        for t, (pri, vals, loop) in tr.items():
            kind = 1 if track_kind(t)[0] == "S" else 0
            n = 0 if loop is not None else len(vals)
            if kind:
                L.append("\tdc.b %d,%d,1,0\n\tdc.w %d\n\tdc.l bb_f%02X_%02X,0" % ((t - 0x84) // 2, pri, n, c, t))
            else:
                d, l = p.enc[c, t]
                L.append("\tdc.b %d,%d,0,0\n\tdc.w %d\n\tdc.l bb_s%02X_%02X,%s" % (
                    (t - 0x84) // 2, pri, n, c, t, "bb_s%02X_%02X+%d" % (c, t, l) if l >= 0 else "0"))
            size += 12
        if chain:
            L.append("\tdc.b " + ",".join(str(x) for x in chain))
        L.append("\teven")
        for t, (pri, vals, loop) in tr.items():
            if track_kind(t)[0] == "S":
                chip, slot, length, lp, runs, exc, total = p.enc[c, t]
                L.append("bb_f%02X_%02X:\tdc.w %d,%d\n\tdc.l bb_r%02X_%02X,bb_none,bb_none,bb_none\n\tdc.w 0" % (
                    c, t, length, lp, c, t))
                L.append("bb_r%02X_%02X:" % (c, t))
                data = runs
            else:
                L.append("bb_s%02X_%02X:" % (c, t))
                data = p.enc[c, t][0]
            for i in range(0, len(data), 24):
                L.append("\tdc.b " + ",".join(str(x) for x in data[i:i + 24]))
            L.append("\teven")
            size += len(data)
    L.append("bb_none:\tdc.b $FF,$FF")
    L.append("cs_boost:\tdc.b " + ",".join(str(x) for x in BOOST))
    L.append("bb_ssg_idle:\tdc.b " + ",".join(str(x) for x in SSG_IDLE))
    L.append("\teven")
    from pathlib import Path
    Path(path).write_text("\n".join(L) + "\n")
    return size


if __name__ == "__main__":
    import collections
    if sys.argv[1:2] == ["record"]:
        all_sounds(True)
    if sys.argv[1:2] == ["emit"]:
        print("bb_sound.s: %d bytes" % emit(build_dir("bublbobl") / "bb_sound.s"))
    if sys.argv[1:2] == ["check"]:
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
        check(n, random_commands(n), "random commands")
    if sys.argv[1:2] == ["writes"]:
        cmd = int(sys.argv[2], 16)
        secs = float(sys.argv[3]) if len(sys.argv) > 3 else 3
        b = Board()
        b.run(CLOCK)
        boot = len(b.writes)
        del b.writes[:]
        b.command(cmd)
        b.run(int(CLOCK * secs))
        kinds = collections.Counter()
        for chip, r, v in b.writes:
            if chip == 0:
                k = "SSG %02X" % r if r < 16 else "key 28" if r == 0x28 else "timer %02X" % r if r < 0x30 else "FM %02X" % (r & 0xF0)
            else:
                k = "OPL %02X" % (r & 0xF0) if r >= 0x20 else "OPL %02X" % r
            kinds[(chip, k)] += 1
        print("$%02X: %d writes in %.1f s (boot %d)" % (cmd, len(b.writes), secs, boot))
        for (chip, k), n in sorted(kinds.items()):
            print("  %s %-10s %6d" % ("YM2203" if chip == 0 else "YM3526", k, n))
