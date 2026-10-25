"""Where the logic's cycles go (run/timeplt_sim on Musashi, the render_test harness: ref/cover.py's inputs).

    python tools/perf_test.py [frames] [--start F] [--seed N] [--top N] [--ranges]

Every 68000 instruction of the logic (from the frame's start to the picture) is stepped and charged to the nearest
label: a translated Z80 instruction (Zxxxx) or a runtime routine.  Prints the cycles a frame, the hottest Z80
instructions, the runtime routines, and with --ranges the cycles per 32-byte block of the Z80 program.
"""
from pathlib import Path
import argparse
import bisect
import collections
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'ref'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
import render_test as rt
import z80dis
from machine import load


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=1600)
    ap.add_argument('--start', type=int, default=1000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--top', type=int, default=30)
    ap.add_argument('--ranges', action='store_true')
    ap.add_argument('--tag', default='timeplt_sim')
    a = ap.parse_args()
    h = rt.Harness(a.seed, tag=a.tag)
    sym, cpu, mem = h.sym, h.cpu, h.mem
    mem.w16(sym['render_frame'], 0x4e75)
    import re as _re
    mp = (Path(__file__).resolve().parents[3] / 'build' / 'timeplt' / (a.tag + '.map')).read_text()
    absolute = {m[1] for m in _re.finditer(r'\s0x[0-9a-f]{8} (\S+?): \S+ abs', mp)}
    labels = sorted((v, k) for k, v in sym.items() if not k.startswith('.') and k not in absolute)
    lv = [v for v, _ in labels]
    by = collections.Counter()
    orig = h.run_to
    stop = {sym['sim_render_start']}

    def run_to(targets, count=None):
        if count != 'logic' or h.f < a.start:
            return orig(targets, count)
        total = 0
        while True:
            pc = cpu.r_pc()
            if pc in targets:
                h.cyc[count] += total
                return pc
            n = cpu.execute(1).cycles
            total += n
            i = bisect.bisect_right(lv, pc) - 1
            by[labels[i][1]] += n
    h.run_to = run_to
    for f in range(a.frames):
        h.frame()
    n = a.frames - a.start
    tot = sum(by.values())
    rom = load('tm1') + load('tm2') + load('tm3') + bytes(0xA000)
    z = collections.Counter({k: c for k, c in by.items() if k[0] == 'Z' and len(k) == 5})
    zt = sum(z.values())
    print('logic: %d cycles a frame (Musashi), translated code %d, runtime %d' % (tot // n, zt // n, (tot - zt) // n))
    print('-- the hottest Z80 instructions (cycles a frame)')
    for k, c in z.most_common(a.top):
        pc = int(k[1:], 16)
        print('%s %-20s %6d' % (k, z80dis.decode(rom, pc).text, c // n))
    print('-- runtime')
    for k, c in collections.Counter({k: c for k, c in by.items() if k not in z}).most_common(12):
        print('%-24s %6d' % (k, c // n))
    import os
    for rg in filter(None, os.environ.get('RANGES', '').split(',')):
        lo, hi = (int(x, 16) for x in rg.split('-'))
        print('range %04X-%04X: %d cycles a frame' % (lo, hi, sum(c for k, c in z.items() if lo <= int(k[1:], 16) <= hi) // n))
    if a.ranges:
        r = collections.Counter()
        for k, c in z.items():
            r[int(k[1:], 16) & ~31] += c
        print('-- 32-byte blocks')
        for b, c in r.most_common(a.top):
            print('%04X %6d' % (b, c // n))


if __name__ == '__main__':
    main()
