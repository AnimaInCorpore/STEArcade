"""Workload profile of the host reference: CPU duty cycle and per-frame colour use.

usage: python bbprofile.py [variant]     (default bublboblr)
Reproduces the numbers in docs/feasibility.md.  Idle = the known wait loops:
main `jr $` at $01ED, sub `jp $000A`.
"""
import collections
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from bubble import Bubble, FRAME_CYCLES   # noqa: E402
from bbvideo import Renderer, palette_rgb  # noqa: E402

IDLE = {"main": (0x01ED, 12), "sub": (0x000A, 10)}


def duty(variant, start=2000, n=300):
    b = Bubble(variant=variant)
    for _ in range(start):
        b.run_frame()
    cnt = {"main": collections.Counter(), "sub": collections.Counter()}
    cyc = {"main": 0, "sub": 0}
    for name, cpu in (("main", b.main), ("sub", b.sub)):
        st = cpu.step

        def step(st=st, cpu=cpu, name=name):
            pc, c0 = cpu.pc, cpu.cycles
            st()
            cnt[name][pc] += 1
            cyc[name] += cpu.cycles - c0
        cpu.step = step
    for _ in range(n):
        b.run_frame()
    for name in cnt:
        pc, t = IDLE[name]
        tot = sum(cnt[name].values())
        busy_i = tot - cnt[name][pc]
        busy_c = cyc[name] - cnt[name][pc] * t
        print("%s: %d non-idle Z80 instr/frame, %.1f%% of the CPU's T-states"
              % (name, busy_i // n, 100.0 * busy_c / n / FRAME_CYCLES))


def colours(variant, frames=range(700, 3601, 100)):
    b = Bubble(variant=variant)
    r = Renderer()
    worst = (0, 0)
    for f in range(1, max(frames) + 1):
        b.run_frame()
        if f in frames:
            idx = r.render_index(b)[16:240]
            pal = palette_rgb(b.palram)
            used = np.unique(idx)
            rgb = len({tuple(pal[i]) for i in used})
            grp = len({int(i) >> 4 for i in used})
            worst = (max(worst[0], rgb), max(worst[1], grp))
    print("worst frame in sample: %d distinct RGB, %d palette groups" % worst)


if __name__ == "__main__":
    v = sys.argv[1] if len(sys.argv) > 1 else "bublboblr"
    duty(v)
    colours(v)
