"""tools/sound_hle.py against the reference board's real 6502.

    venv/bin/python games/gauntlet/tools/sound_hle_test.py [SEED:PLAYERS:FRAMES ...]

Default runs: the attract mode (0 players, 6000 frames), random play with 1, 2, 3 and 4 players (4000 frames each;
coins at frame 600 + 50 k for player k, again every 3000 frames; ref/cover.py's Player) and random coin pulses on
all four slots (PLAYERS -1, 4000 frames).  For each run:

  open loop   the reference board (machine.Gauntlet, the 6502 running) records the main CPU's commands, Q7 changes,
              response reads and the 6502's IRQ ticks with the coin switches; the same stream is fed to a SoundHLE and
              compared: the commands the 6502 consumed (values, order), the response the main CPU read at each of
              its reads (value and whether one was pending), the time of each reply, the status bits 4/5 at the
              main CPU's reads of $803008.
  closed loop a board without the sound CPU (HLEBoard: $803008 bits 4/5, $80300E/F, IRQ 6 and the command latch
              from the SoundHLE) runs in lock-step with the reference on the same inputs; compared every frame:
              the main CPU's variables ($904000-$904FFF without the stack), the sound commands per frame, the
              replies read.
"""
import bisect
import collections
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path[:0] = [str(HERE.parent), str(HERE.parents[3] / "engine"), str(HERE.parents[1] / "ref")]
import machine
import gauntlet_sound
from machine import Gauntlet, Timer, M68K_IRQ_6, AS
from sound_hle import SoundHLE
from cover import Player

US = AS // 10 ** 6
VARS = (0x904000, 0x905000)
STACK = (0x904C00, 0x904F00)            # the supervisor stack (initial SSP $904F00, about $904D90 deep in a frame)


def is_io(a):
    return (a >> 16) & 0xF0 in (0x80, 0xA0) and (a >> 12) & 0xF != 2


def coin_switches(board, line):
    """the frame's coin switches change at line 128, between the 6502's IRQs (lines 96 and 160): its IRQ handler
    updates the music and speech first and reads $1020 0.1 to over 1 ms after the IRQ, so a change at the frame's
    start (16 lines after the line-224 IRQ) would land before or after that read depending on the sound's load"""
    if line == 128 and hasattr(board, "next_coins"):
        board.coins = board.next_coins


_sound_rd = gauntlet_sound.SoundBoard.rd


def sound_rd(self, a):
    """the 6502's reads of $1020 (only in its IRQ's coin routine, $80D2 / $80F4), recorded for the exact replay"""
    v = _sound_rd(self, a)
    if a < 0x4000 and a & 0x1800 == 0x1000 and a & 0x30 == 0x20 and hasattr(self.b, "ev"):
        self.b.ev.append((self.b.now(), "coinread", v))
    return v


gauntlet_sound.SoundBoard.rd = sound_rd


class RefBoard(Gauntlet):
    """the reference board, recording the main CPU's side of the sound protocol"""

    def __init__(self):
        self.ev = []                       # (time, kind, value)
        super().__init__()
        orig = self.soundlatch.read

        def rd():
            if self.soundlatch.written:
                self.ev.append((self.now(), "consumed", self.soundlatch.value))
            return orig()
        self.soundlatch.read = rd

    def main_wr(self, a, v, mask):
        if is_io(a) and mask & 0xFF:
            if a & 0x171 == 0x170:
                self.ev.append((self.now(), "cmd", v & 0xFF))
        return super().main_wr(a, v, mask)

    def outlatch_changed(self, bit, state):
        if bit == 7:
            self.ev.append((self.now(), "q7", state))
        super().outlatch_changed(bit, state)

    def reply_written(self, v):
        self.ev.append((self.now(), "resp_w", v))
        super().reply_written(v)

    def main_rd(self, a, mask, kind):
        if a >> 12 & 0xF0F == 0x803:
            o = a & 0x10F
            if o == 0x0E and mask & 0xFF:
                pend = self.mainlatch.written
                v = super().main_rd(a, mask, kind)
                self.ev.append((self.now(), "read", (v & 0xFF, pend)))
                return v
            if o == 8:
                v = super().main_rd(a, mask, kind)
                self.ev.append((self.now(), "status", v & 0x30))
                return v
        return super().main_rd(a, mask, kind)

    def scanline(self, line):
        coin_switches(self, line)
        super().scanline(line)
        if line & 32:
            self.ev.append((self.now(), "tick", self.coins))


class HLEBoard(Gauntlet):
    """the board without the sound CPU: the main CPU's sound I/O from a SoundHLE"""

    def __init__(self):
        self.hle = SoundHLE(US)
        self.irq6 = False
        self.hle_timer = Timer(self.hle_event)
        super().__init__(sound=False)

    def make_main(self):
        """the 68010 core's state is global per library: this board takes the second copy (instance 1)"""
        cls = machine.M.M68010
        machine.M.M68010 = lambda rd, wr: cls(rd, wr, instance=1)
        try:
            super().make_main()
        finally:
            machine.M.M68010 = cls

    def sync_hle(self):
        s = bool(self.hle.status() & 0x10)
        if s != self.irq6:
            self.irq6 = s
            self.set_line(self.main, M68K_IRQ_6, s)
        t = self.hle.next_event()
        if t is None:
            self.cancel(self.hle_timer)
        elif not self.hle_timer.live or self.hle_timer.expire != t:
            self.adjust(self.hle_timer, t)

    def hle_event(self):
        self.hle.advance(self.cb_time)
        self.sync_hle()

    def sound_reset_w(self, state):
        super().sound_reset_w(state)
        self.hle.reset(state, self.now())
        self.sync_hle()

    def main_rd(self, a, mask, kind):
        if a >> 12 & 0xF0F == 0x803:
            o = a & 0x10F
            if o == 8:
                self.hle.advance(self.now())
                self.sync_hle()
                v = 0x0008 if not self.service else 0
                return v | self.hle.status() | (0 if self.vblank() else 0x40)
            if o == 0x0E:
                if mask & 0xFF:
                    v = self.hle.read_reply(self.now())
                    self.sync_hle()
                    self.reply_log.append((self.frame, v))
                    return 0xFF00 | v
                return 0xFFFF
        return super().main_rd(a, mask, kind)

    def main_wr(self, a, v, mask):
        if is_io(a) and a & 0x171 == 0x170:
            if mask & 0xFF:
                self.sound_log.append((self.frame, v & 0xFF))
                self.hle.command(v, self.now())
                self.sync_hle()
            return
        return super().main_wr(a, v, mask)

    def scanline(self, line):
        coin_switches(self, line)
        super().scanline(line)
        if line & 32:
            self.hle.irq_tick(self.coins)


def replay(ev, exact=False):
    """feed the reference's stream to a fresh SoundHLE; returns the comparisons.  exact: the coin ticks are the
    6502's own reads of $1020 in its IRQ (when its IRQ handler really ran, with the value it read) instead of the
    scanline timer's IRQs with the switches at that time (what the STE can do)"""
    h = SoundHLE(US)
    reads = []                             # (time, ref (value, pending), hle (value, pending))
    status = collections.Counter()
    last_status = None
    for t, kind, v in ev:
        h.advance(t)
        if kind == "cmd":
            h.command(v, t)
        elif kind == "q7":
            h.reset(v, t)
        elif kind == ("coinread" if exact else "tick"):
            h.irq_tick(v)
        elif kind == "read":
            pend = bool(h.status() & 0x10)
            reads.append((t, v, (h.read_reply(t), pend)))
        elif kind == "status":
            if (v, h.status()) != last_status:      # count the changes only (busy-wait loops read it often)
                status[(v, h.status())] += 1
                last_status = (v, h.status())
    ref_consumed = [v for t, k, v in ev if k == "consumed"]
    hle_consumed = [v for t, v in h.log]
    return h, reads, status, ref_consumed, hle_consumed


def effective_replies(ev):
    """the reference's replies as the main CPU can see them: a write that was overwritten before any read (the boot's
    $FF,$33,$00,$22,$0F burst) is dropped"""
    out = []
    pend = None
    for t, k, v in ev:
        if k == "resp_w":
            pend = (t, v)
        elif k == "read" and pend is not None and v[1]:
            out.append(pend)
            pend = None
        elif k == "q7" and not v:
            pend = None
    return out


def coin_pulses(rnd, frames):
    """PLAYERS -1: the coin switches of all four slots pressed at random from frame 500 on, 1-70 frames down, 1-120
    up (short presses that do not count, normal ones, jammed ones that do not count either).  Checked exactly by the
    replay with the 6502's own coin reads; with the timer's ticks (the STE's way, the closed loop) the counts can
    differ: while a speech phrase starts, the 6502's IRQ handler (TMS5220 feeding first, then the music, then the
    coins) overruns the next IRQ and one of the four coin samples of a frame is lost, which moves presses that are
    within a sample of a threshold (5 samples down, 8 up, the jam limit) to the other side"""
    out = [0xFF] * frames
    for k, bit in enumerate([0x08, 0x04, 0x02, 0x01]):
        f = 500 + 37 * k
        while f < frames:
            down = rnd.choice([1, 1, 2, 3, 4, 5, 6, 8, 12, 20, 40, 50, 51, 52, 53, 54, 55, 60, 70])
            for g in range(f, min(f + down, frames)):
                out[g] &= ~bit
            f += down + rnd.choice([1, 1, 2, 2, 3, 4, 6, 30, 120])
    return out


def run(seed, nplayers, frames, verbose=True):
    rnd = random.Random(seed)
    players = [Player(rnd, k, 600 + 50 * k) for k in range(max(nplayers, 0))]
    pulses = coin_pulses(rnd, frames) if nplayers < 0 else None
    ref, hb = RefBoard(), HLEBoard()
    first_diff = None
    diff_frames = 0
    diff_addrs = collections.Counter()
    stack_diff_frames = 0
    t0 = time.time()
    for f in range(frames):
        coins = 0xFF
        for p in players:
            if p.coin(f):
                coins &= ~[0x08, 0x04, 0x02, 0x01][p.k]
            joy = p.joy(f)
            ref.inputs[p.k] = hb.inputs[p.k] = 0xFFFF & ~joy
        if pulses is not None:
            coins = pulses[f]
        ref.next_coins = hb.next_coins = coins
        ref.run_frame()
        hb.run_frame()
        a = ref.cpu.mem[VARS[0]:VARS[1]]
        b = hb.cpu.mem[VARS[0]:VARS[1]]
        d = [VARS[0] + int(i) for i in (a != b).nonzero()[0]]
        if any(STACK[0] <= x < STACK[1] for x in d):
            stack_diff_frames += 1
        d = [x for x in d if not STACK[0] <= x < STACK[1]]
        if d:
            diff_frames += 1
            diff_addrs.update(d)
            if first_diff is None:
                first_diff = (f, ["%06X" % x for x in d[:12]])
    dt = time.time() - t0
    ev = ref.ev
    hx, reads_x, status_x, rc_x, hc_x = replay(ev, exact=True)
    exact = dict(consumed_equal=rc_x == hc_x,
                 read_mismatch=sum(1 for t, r, x in reads_x if (r[0], bool(r[1])) != x and (r[1] or x[1])),
                 status_mismatch=sum(n for (r, x), n in status_x.items() if r != x))
    h, reads, status, rc, hc = replay(ev)
    # open loop results
    read_bad = [(t, r, x) for t, r, x in reads if (r[0], bool(r[1])) != (x[0], x[1]) and (r[1] or x[1])]
    eff = effective_replies(ev)
    hl = [(t, v) for t, v in h.replies]
    dts = []
    vals_ok = [v for t, v in eff] == [v for t, v in hl]
    if vals_ok:
        dts = [(b[0] - a[0]) / US for a, b in zip(eff, hl)]
    status_bad = sum(n for (r, x), n in status.items() if r != x)
    res = dict(seed=seed, players=nplayers, frames=frames, secs=round(dt, 1), exact_coin_replay=exact,
               commands=len([1 for e in ev if e[1] == "cmd"]),
               consumed_equal=rc == hc, consumed=(len(rc), len(hc)),
               replies=len(eff), reply_values_equal=vals_ok,
               reply_dt_us=(round(min(dts), 1), round(max(dts), 1)) if dts else None,
               reads=len(reads), read_mismatch=len(read_bad),
               status_changes=sum(status.values()), status_mismatch=status_bad,
               reply_hist=sorted(collections.Counter(v for t, v in eff).items()),
               closed_sound_equal=ref.sound_log == hb.sound_log,
               closed_replies_equal=ref.reply_log == hb.reply_log,
               closed_ram_diff_frames=diff_frames, closed_first_diff=first_diff,
               closed_stack_diff_frames=stack_diff_frames,
               closed_diff_addrs=sorted("%06X" % a for a in list(diff_addrs)[:20]))
    if not vals_ok:
        for k, (a, b) in enumerate(zip(eff, hl)):
            if a[1] != b[1]:
                res["first_reply_mismatch"] = (k, a[0] / US, a[1], b[0] / US, b[1])
                break
        res["reply_counts"] = (len(eff), len(hl))
    if not res["closed_sound_equal"]:
        k = next((i for i, (x, y) in enumerate(zip(ref.sound_log, hb.sound_log)) if x != y),
                 min(len(ref.sound_log), len(hb.sound_log)))
        res["closed_sound_first"] = (k, ref.sound_log[k:k + 3], hb.sound_log[k:k + 3])
    if not res["closed_replies_equal"]:
        k = next((i for i, (x, y) in enumerate(zip(ref.reply_log, hb.reply_log)) if x != y),
                 min(len(ref.reply_log), len(hb.reply_log)))
        res["closed_replies_first"] = (k, ref.reply_log[k:k + 3], hb.reply_log[k:k + 3])
    if verbose:
        for k, v in res.items():
            print("  %-22s %s" % (k, v))
    return res, ref, hb



if __name__ == "__main__":
    specs = sys.argv[1:] or ["0:0:6000", "1:1:4000", "2:2:4000", "3:3:4000", "4:4:4000", "5:-1:4000"]
    ok = True
    for s in specs:
        seed, n, frames = map(int, s.split(":"))
        print("seed %d, %d players, %d frames" % (seed, n, frames))
        res, ref, hb = run(seed, n, frames)
        x = res["exact_coin_replay"]
        good = x["consumed_equal"] and x["read_mismatch"] == 0 and x["status_mismatch"] == 0
        if n >= 0:      # random coin pulses: the timer ticks can differ (see coin_pulses)
            good &= (res["consumed_equal"] and res["reply_values_equal"] and res["read_mismatch"] == 0
                     and res["closed_sound_equal"] and res["closed_replies_equal"]
                     and res["closed_ram_diff_frames"] == 0)
        print("  ->", "OK" if good else "DIFFERENT")
        ok &= good
    sys.exit(0 if ok else 1)
