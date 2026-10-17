"""engine/tms5220.py against MAME 0.289: replays a log of the gauntlet sound CPU's accesses (written by
engine/gauntlet_sound_log.lua: time of each access in attoseconds, the TMS5220C's internal state from MAME's save items)
into the model and compares, at every access to $1030-$103F and $1820-$182F, the READY bit the CPU read ($1030 bit 5)
and the chip's state (io_ready, FIFO count, IP, PC, subcycle, TALK, TALKD, SPEN, DDIS, /RS /WS, buffer low / empty,
command register, data latch, true timing).

The board around the chip as gauntlet.cpp wires it: the 74LS259 soundctl ($1030-$1037, data bit 7: Q1 /WS, Q2 /RS,
Q3 squeak) with its clear input from the main CPU's outlatch Q7 (sound reset, which also writes the mixer with 0),
the mixer at $1020 (bits 5-7 the TMS5220 gain), sound_manager's stream update every 1/50 s.  A timer fires before an
access whose 6502 cycle does not end by the timer's time (t + 1 cycle > expire): MAME's scheduler runs the 6502 only
for whole cycles that fit before the slice's target, so such a cycle runs in the slice after the timer, although its
time t (the cycle's start, what machine().time() says at the access) is earlier than the timer's.

    venv/bin/python engine/tms5220_test.py [LOG]        (default: a fresh MAME run, 3600 frames with a started game)
"""
import heapq
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tms5220 import TMS5220C, AS

CPU_AS = AS // 1789772                  # the 6502's cycle (14.318181 MHz / 8)
HERE = os.path.dirname(os.path.abspath(__file__))
FIELDS = ("io", "fc", "ip", "pc", "sc", "tk", "td", "sp", "dd", "rw", "bl", "be", "cr", "dl", "tt")
INPUTS = ("2000:COIN:Coin_1:1 2006:COIN:Coin_1:0 2300:803000:P1_Button_1:1 2306:803000:P1_Button_1:0 "
          "2500:803000:P1_Button_1:1 2506:803000:P1_Button_1:0 2700:803000:P1_Button_1:1 2706:803000:P1_Button_1:0")


def run_mame(out, frames=3600):
    sys.path.insert(0, os.path.join(HERE, "..", "games", "gauntlet", "tools"))
    from mame_roms import rompath
    env = dict(os.environ, OUT=out, FRAMES=str(frames), INPUTS=INPUTS)
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["mame", "gauntlet", "-rompath", str(rompath()), "-window", "-sound", "none", "-nothrottle",
                        "-skip_gameinfo", "-autoboot_script", os.path.join(HERE, "gauntlet_sound_log.lua")],
                       cwd=d, env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Board:
    """now() / timer() / cancel() as MAME's scheduler gives them to the chip, events replayed in time order"""

    def __init__(self):
        self.t = 0
        self.timers = []
        self.seq = 0

    def now(self):
        return self.t

    def timer(self, expire, fn):
        h = [expire, self.seq, fn]
        self.seq += 1
        heapq.heappush(self.timers, h)
        return h

    def cancel(self, h):
        h[2] = None

    def advance(self, t):
        while self.timers and self.timers[0][0] <= t:
            exp, _, fn = heapq.heappop(self.timers)
            if fn is not None:
                self.t = exp
                fn()
        self.t = t


class LS259:
    """addressable_latch_device (74259.cpp): q starts at 0xFF, device_reset clears; /CLR active low"""

    def __init__(self, cbs):
        self.cbs = cbs
        self.q = 0xFF
        self.clear = False
        self.enable = False
        self.address = 0
        self.data = 0

    def clear_outputs(self, new_q):
        changed = self.q ^ new_q
        self.q = new_q
        for i in range(8):
            if changed >> i & 1 and self.cbs[i]:
                self.cbs[i]((new_q >> i) & 1)

    def update_bit(self):
        if (self.q >> self.address) & 1 == self.data:
            return
        if not self.clear:
            self.q = (self.q & ~(1 << self.address)) | (self.data << self.address)
        else:
            self.clear_outputs(0)
            self.q = self.data << self.address
        if self.cbs[self.address]:
            self.cbs[self.address](self.data)

    def write_bit(self, offset, d):
        self.address, self.data = offset & 7, d
        if self.enable:
            if self.clear:
                self.clear_outputs(self.data << self.address)
            else:
                self.update_bit()
        self.enable = True                       # enable_w(0)
        self.update_bit()
        self.enable = False                      # enable_w(1)
        if self.clear:
            self.clear_outputs(0)

    def clear_w(self, state):
        self.clear = not state
        if self.clear:
            self.clear_outputs(self.data << self.address if self.enable else 0)

    def reset(self):
        self.clear_outputs(self.data << self.address if self.enable else 0)


def squeak_clock(state):
    return int(14318181 / 2 / (16 - (5 | (2 if state else 0))) + 1e-3)     # XTAL::value()


def state_of(c):
    return dict(io=int(c.io_ready), fc=c.fifo_count, ip=c.IP, pc=c.PC, sc=c.subcycle, tk=int(c.TALK),
                td=int(c.TALKD), sp=int(c.SPEN), dd=int(c.DDIS), rw=c.rs_ws, bl=int(c.buffer_low),
                be=int(c.buffer_empty), cr=c.command_register, dl=int(c.data_latched), tt=int(c.true_timing))


def parse_state(words):
    d = {}
    for w in words:
        for f in FIELDS:
            if w.startswith(f) and w[len(f):].lstrip("-").isalnum():
                d[f] = int(w[len(f):], 16 if f == "cr" else 10)
                break
    return d


def main(path):
    b = Board()
    tms = TMS5220C(b)
    ctl = LS259([None, tms.wsq_w, tms.rsq_w, lambda s: tms.set_clock(squeak_clock(s)), None, None, None, None])

    def mixer_w(v):
        tms.set_output_gain(((v >> 5) & 7) / 7.0)

    def sound_reset_w(state):
        ctl.clear_w(state)
        if not state:
            mixer_w(0)

    outlatch = LS259([None] * 7 + [sound_reset_w])
    # machine reset at time 0, devices in gauntlet's config order: outlatch, ..., tms, soundctl
    outlatch.reset()
    tms.device_reset()
    ctl.reset()
    for k in range(1, 10 ** 6):                  # sound_manager::update every 1/50 s
        b.timer(k * (AS // 50), tms.stream_update)

    events = []
    with open(path) as f:
        for n, line in enumerate(f):
            w = line.split()
            if len(w) < 5:
                continue
            events.append((int(w[3]) * AS + int(w[4]), n, w))
    events.sort()
    checked = reads = bad = 0
    for t, n, w in events:
        kind = w[0]
        b.advance(t + CPU_AS - 1 if kind != "m" else t)
        b.t = t
        kind, a, v = w[0], int(w[1], 16), int(w[2], 16)
        if kind == "m":
            if 0x803120 <= a < 0x803130:
                outlatch.write_bit((a - 0x803120) >> 1, v & 1)
            continue
        a &= 0x1FFF
        if a & 0x1FF0 == 0x1030 or a & 0x1FF0 == 0x1820:
            if kind == "r" and a & 0x1FF0 == 0x1030:
                q = tms.readyq_r()
                reads += 1
                if q != (v >> 5) & 1:
                    bad += 1
                    if bad < 20:
                        print("line %d: READY bit %d, MAME %d" % (n + 1, q, (v >> 5) & 1))
            want = parse_state(w[7:])
            have = state_of(tms)
            checked += 1
            diff = {k: (have[k], want[k]) for k in want if have[k] != want[k]}
            if diff:
                bad += 1
                if bad < 20:
                    print("line %d (%s %x %x): model/MAME %s" % (n + 1, kind, a, v, diff))
            if kind == "w":
                if a & 0x1FF0 == 0x1030:
                    ctl.write_bit(a & 7, v >> 7)
                else:
                    tms.data_w(v)
        elif kind == "w" and a & 0x1FF0 == 0x1020:
            mixer_w(v)
    print("%d accesses checked (%d READY reads), %d mismatches" % (checked, reads, bad))
    return bad == 0


if __name__ == "__main__":
    if len(sys.argv) > 1:
        ok = main(sys.argv[1])
    else:
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "acc.txt")
            run_mame(log)
            ok = main(log)
    sys.exit(0 if ok else 1)
