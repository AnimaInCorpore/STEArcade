"""Defender: the reference board (tools/machine.py) against MAME (WolfMAME 0.248: set MAME=...\\wolfmame-0248\\mame.exe).

    python games/defender/ref/mame_cmp_defender.py [frame ...] [--keep DIR] [--factory]

--factory: both boards boot with machine.factory_cmos() (MAME's from nvram/defender/nvram in its run folder): the
attract mode instead of the bookkeeping menu a blank CMOS opens.

One MAME run (engine/mame_frames.lua) dumps the main CPU's $0000-$BFFF (video RAM and work RAM), the screen (292 x 240)
and the pens at the frames.
(1) render: the reference renderer draws MAME's memory with MAME's 16 pens: 0 differing pixels;
(2) logic: the reference board runs from power-on to the same frames; its RAM (but the 64 bytes below S) against
    MAME's, and its own picture.
"""
from pathlib import Path
import os
import sys
import tempfile

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools"), str(Path(__file__).resolve().parents[3] / "engine")]
from machine import Defender, render_pixels, factory_cmos
import mame_cmp
import numpy as np


def main():
    factory = "--factory" in sys.argv
    if factory:
        sys.argv.remove("--factory")
    frames, keep = mame_cmp.parse_args([60, 300, 600, 900, 1200, 1800, 2400, 3600])
    keep = Path(os.path.abspath(keep) if keep else tempfile.mkdtemp(prefix="mame_defender_"))
    cmos = factory_cmos() if factory else None
    if cmos:
        (keep / "nvram" / "defender").mkdir(parents=True, exist_ok=True)
        (keep / "nvram" / "defender" / "nvram").write_bytes(cmos)
    d = mame_cmp.run_mame("defender", frames, ["maincpu:0x0:0xbfff"], keep=keep, pens_every=True)
    worst = 0
    m = Defender(cmos)
    for f in frames:
        mem = mame_cmp.load_dump(d, f, "maincpu", 0)
        mp = mame_cmp.load_pens(d, f)                       # MAME's 256 pens: the colours of the palette bytes
        shot = mame_cmp.load_shot(d, f)
        while m.frame < f:
            m.run_frame()
        pal_diff = int(np.any(mp != __import__("machine").PALETTE, axis=1).sum())
        # MAME's memory through the reference's pens: the palette RAM is write-only, take the board's
        rgb = mp[np.array(m.palette, np.uint8)][render_pixels(mem)]
        n = mame_cmp.diff_pixels(rgb, shot)
        sp = m.cpu.s
        # the stack below S is dead (interrupt entries at other instructions leave other bytes there)
        ram = [(0x0000, 0xBFFF)] if not 0x9800 < sp <= 0xC000 else [(0x0000, sp - 0x41), (sp, 0xBFFF)]
        k, tot, first = mame_cmp.ram_diff(m.mem, mem, ram)
        own = mame_cmp.diff_pixels(m.render_rgb(), shot)
        worst = max(worst, k, own, pal_diff)
        mame_cmp.save_compare(d / ("cmp%d.png" % f), m.render_rgb(), shot)
        print("frame %5d: %d of 256 pens differ; MAME's RAM drawn %5d pixels differ; logic RAM %5d of %d bytes differ "
              "%s; its own picture %d pixels" % (f, pal_diff, n, k, tot, " ".join(first), own))
    print("compare pictures (reference | MAME | differences) in", d)
    return int(worst != 0)


if __name__ == "__main__":
    sys.exit(main())
