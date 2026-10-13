"""Where the translated main CPU spends its 68000 cycles: the lock-step run of logic_test.py, single-stepped over a
window of frames, cycles summed per V30 instruction (its label's code), per runtime routine and per 256 bytes of code.

    venv/bin/python games/rtype/tools/profile.py [--seed 4] [--start 600] [--frames 30] [--top 40]
"""
import argparse
import bisect
import collections
import re
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
import logic_test
from paths import build_dir


MARKS_REPORT = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=4)
    ap.add_argument("--start", type=int, default=600)
    ap.add_argument("--frames", type=int, default=30)
    ap.add_argument("--top", type=int, default=40)
    args = ap.parse_args()
    prof = collections.Counter()
    counts = collections.Counter()

    def stepper(cpu, mem, sym, labels, stop):
        lv = [v for v, k in labels]
        code_syms = {m[1] for m in re.finditer(r"0x[0-9a-f]{8} (\S+?): \S+ reloc", (build_dir("rtype") / "rtype_sim.map").read_text())}
        names = sorted((v, k) for k, v in sym.items() if k in code_syms and not (k[:1] == "R" and len(k) == 6))
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
    sys.argv = [sys.argv[0], "%d" % (args.start + args.frames), "--seed", str(args.seed)]
    logic_test.main()
    total = sum(prof.values())
    print("%d cycles in %d frames: %.0f a frame" % (total, args.frames, total / args.frames))
    groups = collections.Counter()
    for k, n in prof.items():
        groups["translated" if not k.startswith("rt:") else k] += n
    print("translated code / runtime routines:")
    for k, n in groups.most_common(16):
        print("  %-24s %5.1f%%" % (k, 100 * n / total))
    regions = collections.Counter()
    for k, n in prof.items():
        if not k.startswith("rt:"):
            regions[k[:4]] += n
    print("by 256 bytes of code (linear):")
    for k, n in regions.most_common(20):
        print("  %s00-%sFF  %5.1f%%" % (k[1:], k[1:], 100 * n / total))
    text = {}
    for line in (build_dir("rtype") / "code_main.s").read_text().splitlines():
        hit = re.match(r"^(R[0-9A-F]{5}):\t\t; (.*)$", line)
        if hit:
            text[hit[1]] = hit[2]
    kinds = collections.Counter()
    kcount = collections.Counter()
    for k, n in prof.items():
        if k in text:
            mn = text[k].split()[1] if len(text[k].split()) > 1 else "?"
            kinds[mn] += n
            kcount[mn] += counts.get(k, 0)
    print("by V30 instruction (share, executions, cycles per execution):")
    for k, n in kinds.most_common(16):
        print("  %-8s %5.1f%% %8d %6.1f" % (k, 100 * n / total, kcount[k], n / max(1, kcount[k])))
    if "--marks" in sys.argv[0:0] or MARKS_REPORT:
        code = (build_dir("rtype") / "code_main.s").read_text().split("\n")
        marked, cur = set(), None
        for line in code:
            hit = re.match(r"^(R[0-9A-F]{5}):", line)
            if hit:
                cur = hit[1]
            elif "v30_vmarks" in line or "mark_range" in line:
                marked.add(cur)
        print("instructions with a store mark:")
        for k, n in sorted(((k, n) for k, n in prof.items() if k in marked), key=lambda x: -x[1])[:15]:
            print("  %-10s %5.2f%% %8d  %s" % (k, 100 * n / total, counts.get(k, 0), text.get(k, "")))
    print("top instructions (share, executions, 68000 cycles per execution):")
    for k, n in prof.most_common(args.top):
        c = counts.get(k, 0)
        print("  %-10s %5.2f%% %8d %7.1f  %s" % (k, 100 * n / total, c, n / c if c else 0, text.get(k, "")))


if __name__ == "__main__":
    main()
