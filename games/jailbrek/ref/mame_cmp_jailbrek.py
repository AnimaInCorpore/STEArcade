"""Jail Break: the reference board (tools/machine.py) against MAME (wolfmame-0248 here; 0.286 source is the truth).

    python games/jailbrek/ref/mame_cmp_jailbrek.py [frame ...] [--keep DIR]

One MAME run (engine/mame_frames.lua) dumps the main CPU's $0000-$203F, the writes to the 005849's ctrl registers
($2040-$2047, write-only: logged by a tap), the screen and the pens at the frames.
(1) render: the reference renderer draws MAME's memory: 0 differing pixels and pens;
(2) logic: the reference machine runs from power-on to the same frames; its RAM against MAME's.
"""
from pathlib import Path
import os
import sys

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools"), str(Path(__file__).resolve().parents[3] / "engine")]
os.environ.setdefault("MAME", r"C:\Arbeit\F030Arcade\third_party\wolfmame-0248\mame.exe")
import numpy as np
from machine import JailBreak, Video
import mame_cmp as M


def ctrl_at(d, f):
    regs = {o: v for (t, o), v in M.load_tap_state(d, f).items()}
    for t, line, o, x in M.load_taps(d, f):
        regs[o] = x
    return regs


if __name__ == "__main__":
    frames, keep = M.parse_args([60, 300, 600, 900, 1200, 1800, 2400, 3600])
    d = M.run_mame("jailbrek", frames, ["maincpu:0x0:0x203f"], taps=["maincpu:0x2040:0x2047"], keep=keep)
    video = Video()
    pens = M.load_pens(d)
    pen_diff = int(np.any(video.pens != pens[:512], axis=1).sum())
    print("pens: %d of %d differ" % (pen_diff, len(pens)))
    worst = pen_diff
    m = JailBreak()
    m.mame248 = os.environ.get("JB248") == "1"       # the 0.248 binary's interrupt schedule (see README)
    state = {}
    for f in frames:
        mem = M.load_dump(d, f, "maincpu", 0)
        # taps accumulate: the registers at this frame's end = the state at the end of the previous dumped frame
        # plus its writes; tapstate is the value at the previous *frame* (every frame is dumped when taps are on)
        regs = ctrl_at(d, f)
        for o, v in regs.items():
            mem[0x2040 + o] = v
        rgb = video.render_rgb(mem, bool(mem[0x2044] & 8))
        shot = M.load_shot(d, f)
        n = M.diff_pixels(rgb, shot)
        worst = max(worst, n)
        M.save_compare(d / ("cmp%d.png" % f), rgb, shot)
        while m.frame < f:
            m.run_frame()
        k, tot, first = M.ram_diff(m.mem, mem, [(0x0000, 0x203F)])
        own = M.diff_pixels(m.render_rgb(), shot)
        print("frame %5d: render %5d pixels differ; logic RAM %4d of %d bytes differ %s; its own picture %d pixels" % (
            f, n, k, tot, " ".join(first), own))
    print("compare pictures (reference | MAME | differences) in", d)
    sys.exit(int(worst != 0))
