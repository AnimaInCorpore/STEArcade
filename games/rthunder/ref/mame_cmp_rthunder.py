"""Rolling Thunder: the reference board (tools/machine.py) against MAME (`rthunder`, WolfMAME 0.248: set MAME to its mame.exe).

    python games/rthunder/ref/mame_cmp_rthunder.py [frame ...] [--keep DIR] [--logic]

One MAME run (engine/mame_frames.lua) dumps at the frames cpu1's tile RAMs ($0000-$3FFF), the CUS30 / shared RAM /
sprite RAM ($4000-$5FFF), the pens, the snapshot, and taps the write-only registers ($8800-$9406: tile bank, scrolls and
priorities; $A000: back colour).
(1) render: the reference renderer draws MAME's memory and registers: pixels and pens that differ from MAME's
    snapshot / palette (both must be 0);
(2) logic (--logic): the reference board runs from power-on to the same frames and its RAM is compared with MAME's.
"""
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools"), str(Path(__file__).resolve().parents[3] / "engine")]
from machine import Rthunder, VIS_X0
import mame_cmp as C

DEFAULT = [300, 600, 900, 1200, 1800, 2400, 3000, 4000, 5000, 6000]


def registers(d, f):
    reg = {o: x for (tag, o), x in C.load_tap_state(d, f).items()}
    for tag, line, o, x in C.load_taps(d, f):
        reg[o] = x
    return reg


def load_video(m, d, f):
    mem = C.load_dump(d, f, "cpu1", 0x0000)
    C.load_dump(d, f, "cpu1", 0x4000, into=mem)
    m.vram[0][:] = mem[0:0x2000]
    m.vram[1][:] = mem[0x2000:0x4000]
    m.cus30[:] = mem[0x4000:0x4400]
    m.shared[:] = mem[0x4000:0x5800]
    m.spriteram[:] = mem[0x5800:0x6000]
    m.flip = bool(m.spriteram[0x7F6] & 1)
    reg = registers(d, f)
    for dev, base in ((0, 0x9000), (1, 0x9400)):
        for lay in (0, 1):
            b = base + 4 * lay
            m.xscroll[dev][lay] = (reg.get(b, 0) << 8) | reg.get(b + 1, 0)
            m.yscroll[dev][lay] = reg.get(b + 2, 0)
    m.tilebank = 0
    for o, x in reg.items():
        if 0x8800 <= o < 0x9000:
            m.tilebank = (o - 0x8800) >> 10 & 1       # (the last write: approximated by the dict order; see below)
    m.backcolor = reg.get(0xA000, 0)
    return mem, reg


def main():
    logic = "--logic" in sys.argv
    if logic:
        sys.argv.remove("--logic")
    frames, keep = C.parse_args(DEFAULT)
    d = C.run_mame("rthunder", frames, ["cpu1:0x0000:0x3fff", "cpu1:0x4000:0x5fff"], ["cpu1:0x8800:0x9406", "cpu1:0xa000:0xa000"],
                   keep=keep, pens_every=True)
    m = Rthunder(cpus=False)
    worst = 0
    for f in frames:
        load_video(m, d, f)
        pens = C.load_pens(d, f)
        mine = m.palette(True)[m.pen_table()]       # (0.248's integer weights; machine.palette)
        pd = int(np.any(mine != pens[:4096], axis=1).sum())
        shot = C.load_shot(d, f)
        rgb = m.render_rgb(True)
        n = C.diff_pixels(rgb, shot)
        worst = max(worst, n, pd)
        C.save_compare(d / ("cmp%d.png" % f), rgb, shot)
        print("frame %5d: %d pixels differ, %d pens differ (tilebank %d backcolor %02X flip %d)" % (
            f, n, pd, m.tilebank, m.backcolor, m.flip), flush=True)
    bad = 0
    if logic:
        r = Rthunder()
        for f in frames:
            while r.frame < f:
                r.run_frame()
            mem = C.load_dump(d, f, "cpu1", 0x0000)
            C.load_dump(d, f, "cpu1", 0x4000, into=mem)
            mine = bytearray(0x6000)
            mine[0:0x2000], mine[0x2000:0x4000] = r.vram[0], r.vram[1]
            mine[0x4000:0x4400] = r.cus30
            mine[0x4400:0x5800] = r.shared[0x400:0x1800]
            mine[0x5800:0x6000] = r.spriteram
            k, tot, first = C.ram_diff(mine, mem, [(0, 0x57DF), (0x5800, 0x5FFF)])      # (the stacks aside)
            st, _, _ = C.ram_diff(mine, mem, [(0x57E0, 0x57FF)])
            bad += k
            print("frame %5d: logic %d of %d bytes differ %s; stack area $57E0-$57FF: %d" % (f, k, tot, " ".join(first), st))
    print("compare pictures (reference | MAME | differences) in", d)
    return int(worst != 0 or bad != 0)


if __name__ == "__main__":
    sys.exit(main())
