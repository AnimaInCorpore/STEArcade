"""Where the translated main and sub CPU spend their 68000 cycles: the lock-step run of logic_test.py, single-stepped
over a window of frames, cycles summed per 6809 instruction (its label's code) and per routine group.

    venv/bin/python games/splatter/tools/profile.py [--seed 5] [--start 600] [--frames 30] [--top 40]
"""
import argparse
import bisect
import collections
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
import logic_test


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--start", type=int, default=600)
    ap.add_argument("--frames", type=int, default=30)
    ap.add_argument("--top", type=int, default=40)
    args = ap.parse_args()
    prof = collections.Counter()
    counts = collections.Counter()
    state = {}

    def stepper(cpu, mem, sym, labels, stop):
        lv = [v for v, k in labels]
        names = sorted((v, k) for k, v in sym.items())
        nv = [v for v, k in names]
        total = 0
        while True:
            pc = cpu.r_pc()
            if pc == stop:
                return total
            n = cpu.execute(1).cycles
            total += n
            i = bisect.bisect_right(lv, pc) - 1
            j = bisect.bisect_right(nv, pc) - 1
            if i >= 0 and (j < 0 or nv[j] <= lv[i]):
                prof[labels[i][1]] += n
                if lv[i] == pc:
                    counts[labels[i][1]] += 1
            elif j >= 0:
                prof["rt:" + names[j][1]] += n
    logic_test.PROFILE = dict(start=args.start, frames=args.frames, stepper=stepper)
    logic_test.main_args = ["%d" % (args.start + args.frames), "--seed", str(args.seed)]
    sys.argv = [sys.argv[0]] + logic_test.main_args
    logic_test.main()
    total = sum(prof.values())
    print("%d cycles in %d frames: %.0f a frame" % (total, args.frames, total / args.frames))
    groups = collections.Counter()
    for k, n in prof.items():
        groups[k[:4] if not k.startswith("rt:") else k] += n
    print("by page / runtime routine:")
    for k, n in groups.most_common(16):
        print("  %-24s %5.1f%%" % (k, 100 * n / total))
    regions = collections.Counter()
    for k, n in prof.items():
        if not k.startswith("rt:"):
            regions[k[:5]] += n                 # (the CPU letter + the virtual address's top 4 digits: 256 bytes)
    print("by 256 byte region of code:")
    for k, n in regions.most_common(24):
        print("  %s00-%sFF  %5.1f%%" % (k, k[1:], 100 * n / total))
    import re
    from paths import build_dir
    text = {}
    for f in ("code_main.s", "code_sub.s"):
        for line in (build_dir("splatter") / f).read_text().splitlines():
            hit = re.match(r"^([MS][0-9A-F]{6}):\t\t; (.*)$", line)
            if hit:
                text[hit[1]] = hit[2]
    print("top instructions (share, executions, 68000 cycles per execution):")
    for k, n in prof.most_common(args.top):
        c = counts.get(k, 0)
        print("  %-10s %5.2f%% %8d %7.1f  %s" % (k, 100 * n / total, c, n / c if c else 0, text.get(k, "")))


if __name__ == "__main__":
    main()
