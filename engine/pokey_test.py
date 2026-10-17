"""engine/pokey.py against MAME 0.289: replays a log of the gauntlet sound CPU's accesses (written by
engine/gauntlet_sound_log.lua: each access's time in attoseconds and, at POKEY accesses, the chip's m_totalcycles,
m_localtime, channel counters and borrows, polynomial indices, prescalers, pot counter, ALLPOT, SKCTL, IRQST, IRQEN
from MAME's save items) and compares the model's state and the value of every read.

The POKEY is run to the logged m_totalcycles before each access (the scheduler's slicing is the board's business);
a write takes effect when its synchronize() timer fires, after the scheduler ran the POKEY to the 6502's local time
at the end of the writing cycle (t + 1 cycle): MAME's cycle count from the logged local time.  Timers the POKEY
raises while running (sync_pot) fire right after the clock that raised them (that clock ends its slice).

Then selfcheck(): run()'s closed-form skips against MAME's step_one_clock() clock by clock, random writes.

    venv/bin/python engine/pokey_test.py [LOG]          (default: a fresh MAME run, see engine/tms5220_test.py)
    venv/bin/python engine/pokey_test.py --selfcheck
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pokey import POKEY, AS, CLOCK_AS, DIVSHIFT, DIVISOR

CPU_AS = AS // 1789772


class Board:
    def __init__(self):
        self.pending = []
        self.dev = None
        self.executing = False

    def now(self):                               # only used for timer times, which the test does not need
        return 0

    def synchronize(self, fn):
        self.pending.append(fn)
        if self.executing:
            self.dev.abort()

    def timer(self, expire, fn):
        self.synchronize(fn)
        return fn

    def cancel(self, t):
        if t in self.pending:
            self.pending.remove(t)


def run_to(p, b, n):
    while p.cycles < n:
        b.executing = True
        p.run(n - p.cycles)
        b.executing = False
        fire(b)


def fire(b):
    while b.pending:
        b.pending.pop(0)()


def state_of(p):
    return [p.counter[0], p.counter[1], p.counter[2], p.counter[3], p.borrow[0], p.borrow[1], p.borrow[2],
            p.borrow[3], p.p17, p.p9, p.p4, p.p5, p.clock_cnt[0], p.clock_cnt[1], p.clock_cnt[2], p.pot_counter,
            p.ALLPOT, p.SKCTL, p.IRQST, p.IRQEN]


def parse(w):
    """r/w addr data sec atto cpu_cycles pokey_cycles lt X ch a b c d b a b c d p17 x p9 x p4 x p5 x cc a b c pot x
    all x sk x irqst x irqen x"""
    v = w[7:]
    lt = int(v[1])
    nums = [int(v[i]) for i in (3, 4, 5, 6, 8, 9, 10, 11, 13, 15, 17, 19, 21, 22, 23, 25)]
    nums += [int(v[i], 16) for i in (27, 29, 31, 33)]
    return lt, nums


def selfcheck(rounds=300, seed=1):
    """run() (closed-form skips) against step_one_clock() clock by clock, random AUDCTL / AUDF / SKCTL / IRQEN /
    STIMER / POTGO writes between random stretches: the skips must give the same state as MAME's per-clock code"""
    import random
    rnd = random.Random(seed)
    bad = 0
    for r in range(rounds):
        ba, bb = Board(), Board()
        a, b = POKEY(ba), POKEY(bb)
        ba.dev, bb.dev = a, b
        bb.dev = b
        for _ in range(12):
            writes = []
            for _ in range(rnd.randrange(4)):
                o = rnd.choice((0, 1, 2, 3, 4, 5, 6, 7, 8, 8, 9, 11, 14, 15))
                v = rnd.randrange(256)
                if o == 15:
                    v = rnd.choice((0, 3, 3, 3, 7, 2, 1))
                elif o == 14:
                    v = rnd.choice((0, 0, 0, 1, 2, 4, 7))
                elif o in (0, 2, 4, 6) and rnd.random() < 0.5:
                    v = rnd.choice((0, 1, 2, 255))
                writes.append((o, v))
            for o, v in writes:
                a.write_internal(o, v)
                b.write_internal(o, v)
            n = rnd.choice((1, 7, 100, 3000, 30000, 70000))
            run_to(a, ba, a.cycles + n)
            for _ in range(n):
                bb.executing = True
                b.step_one_clock()
                b.cycles += 1
                bb.executing = False
                fire(bb)
            sa, sb = state_of(a) + [a.kbd_cnt], state_of(b) + [b.kbd_cnt]
            if sa != sb:
                bad += 1
                if bad < 10:
                    print("selfcheck round %d: run %s\n                 step %s (AUDCTL %02x SKCTL %02x AUDF %s)" % (
                        r, sa, sb, b.AUDCTL, b.SKCTL, b.AUDF))
                break
    print("selfcheck: %d rounds, %d mismatches" % (rounds, bad))
    return bad == 0


def main(path):
    b = Board()
    p = POKEY(b)
    b.dev = p
    writes = []                                  # (cycle, offset, data)
    checked = reads = bad = 0
    with open(path) as f:
        for n, line in enumerate(f):
            w = line.split()
            if len(w) < 8 or w[0] == "m":
                continue
            a = int(w[1], 16) & 0x1FFF
            if a & 0x1FF0 != 0x1800:
                continue
            t = int(w[3]) * AS + int(w[4])
            total = int(w[6])
            lt, want = parse(w)
            writes.sort()
            while writes and writes[0][0] <= total:
                c, o, d = writes.pop(0)
                run_to(p, b, c)
                p.write_internal(o, d)
            run_to(p, b, total)
            checked += 1
            have = state_of(p)
            if lt != (total * CLOCK_AS) % AS or have != want:
                bad += 1
                if bad < 20:
                    print("line %d: model %s\n          MAME  %s (lt %d)" % (n + 1, have, want, lt))
            v = int(w[2], 16)
            if w[0] == "r":
                reads += 1
                if p.peek(a) != v:
                    bad += 1
                    if bad < 20:
                        print("line %d: read %x: model %02x, MAME %02x" % (n + 1, a, p.peek(a), v))
            else:
                delta = t + CPU_AS - total * CLOCK_AS
                ran = (delta >> DIVSHIFT) // DIVISOR if delta >= CLOCK_AS else 0
                writes.append((total + ran, a & 15, v))
    print("%d POKEY accesses checked (%d reads), %d mismatches" % (checked, reads, bad))
    return bad == 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selfcheck":
        sys.exit(0 if selfcheck() else 1)
    if len(sys.argv) > 1:
        ok = main(sys.argv[1]) and selfcheck()
    else:
        from tms5220_test import run_mame
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "acc.txt")
            run_mame(log)
            ok = main(log) and selfcheck()
    sys.exit(0 if ok else 1)
