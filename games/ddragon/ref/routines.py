"""Where the main CPU's time goes, per routine (the reference board's port schedule, 6809 cycles): a shadow call
stack (JSR / BSR / LBSR push the target; a frame ends when S climbs back above its entry; the interrupts are their
own roots), each instruction's cycles exclusive to the routine on top and inclusive to every routine on the stack.

    python games/ddragon/ref/routines.py F0 F1 [--seed N] [--top 40] [--tree DEPTH]

The 68000 translation's cost follows the 6809's closely enough to pick the routines worth a native (tools/gen.py
NATIVES); tools/profile.py measures the 68000 side.
"""
from pathlib import Path
import argparse
import collections
import sys

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "tools"), str(HERE.parents[2] / "engine")]
from machine import DDragonPort, DSW0
import cover

CALLS = {0x8D: 2, 0x17: 3, 0x9D: 2, 0xAD: None, 0xBD: 3}     # BSR, LBSR, JSR direct / indexed / extended


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("f0", type=int)
    ap.add_argument("f1", type=int)
    ap.add_argument("--seed", type=int, default=-1)
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--tree", type=int, default=0, help="the call tree (inclusive cycles) this deep")
    args = ap.parse_args()
    dsw1, inputs = cover.schedule(args.seed)
    m = DDragonPort(DSW0, dsw1)
    c = m.main
    excl, incl, calls = collections.Counter(), collections.Counter(), collections.Counter()
    tree = collections.Counter()                 # (path of routines) -> inclusive cycles
    stack = []                                   # (routine, S at the call)
    on = [False]
    orig = c.step

    def virt(a):
        s = a >> 13
        return ((8 + 2 * m.bank + s - 2) << 13) | (a & 0x1FFF) if s in (2, 3) else a

    def step():
        pc, s = c.pc, c.s
        while stack and s >= stack[-1][1]:
            stack.pop()
        op = m.port_rd(pc) if pc >= 0x4000 else m.mem[pc]
        n = orig()
        if not on[0]:
            return n
        if not stack:
            stack.append(("root %05X" % virt(pc), 0x10000))
        top = stack[-1][0]
        excl[top] += n
        for r in {f[0] for f in stack}:
            incl[r] += n
        if args.tree:
            path = tuple(f[0] for f in stack)
            for k in range(1, min(len(path), args.tree) + 1):
                tree[path[:k]] += n
        if op in CALLS and c.s == (s - 2) & 0xFFFF:
            r = "%05X" % virt(c.pc)
            stack.append((r, s))
            calls[r] += 1
        return n
    c.step = step
    for f in range(args.f1):
        p1, p2, extra, coins = inputs(f)
        if coins:
            m.coin(coins)
        m.inputs[0], m.inputs[1], m.inputs[2] = p1, p2, extra
        cover.cheats(m, args.seed, f)
        on[0] = f >= args.f0
        stack.clear()
        m.run_frame_port()
    n = args.f1 - args.f0
    tot = sum(excl.values())
    print("%d frames, %.0f 6809 cycles a frame" % (n, tot / n))
    print("inclusive:")
    for r, v in incl.most_common(args.top):
        print("  %-12s %7.0f a frame %5.1f%%  calls %6.1f  excl %5.1f%%" % (r, v / n, 100 * v / tot, calls[r] / n,
                                                                         100 * excl[r] / tot))
    if args.tree:
        print("call tree:")

        def show(path, depth):
            kids = sorted(((v, p) for p, v in tree.items() if len(p) == len(path) + 1 and p[:-1] == path),
                          reverse=True)
            for v, p in kids:
                if v < tot * 0.01:
                    break
                print("  " + "  " * depth + "%-12s %5.1f%%  calls %5.1f" % (p[-1], 100 * v / tot, calls[p[-1]] / n))
                if depth + 1 < args.tree:
                    show(p, depth + 1)
        show((), 0)
    print("exclusive:")
    for r, v in excl.most_common(args.top):
        print("  %-12s %7.0f a frame %5.1f%%  calls %6.1f" % (r, v / n, 100 * v / tot, calls[r] / n))


if __name__ == "__main__":
    main()
