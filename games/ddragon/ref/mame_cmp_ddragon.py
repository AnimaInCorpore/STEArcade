"""Double Dragon: the reference board (tools/machine.py) against MAME 0.289 (`ddragonj`).

    python games/ddragon/ref/mame_cmp_ddragon.py [frame ...] [--keep DIR]

One MAME run (engine/mame_frames.lua, PENS_EVERY) dumps at the frames the main CPU's RAM, palette, fg, sprites and
bg ($0000-$1FFF, $2800-$37FF), the shared RAM and the MCU's internal RAM through the sub CPU ($8000-$81FF,
$40-$13F) and the sound CPU's RAM, and taps the write-only registers $3808-$380F (bank and scroll bits 8, scroll,
the sound latch).
(1) render: the reference renderer draws MAME's memory and scroll: 0 differing pixels against MAME's snapshot and
    0 differing pens;
(2) logic: the reference board runs from power-on to the same frames: every dumped byte against MAME's, the scroll
    and the frame's sound commands.
"""
import os
from pathlib import Path
import sys

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools"), str(Path(__file__).resolve().parents[3] / "engine")]
from machine import DDragon, Video
import mame_cmp as C

MAIN_RAM = [(0x0000, 0x13FF), (0x1800, 0x1FFF), (0x2800, 0x37FF)]
DEFAULT = [2, 10, 30, 60, 120, 300, 600, 900, 1200, 1500, 1800, 2400, 3000, 3600]


def registers(d, f):
    """MAME's $3808-$380A at the frame's end and the frame's sound commands ($380E writes)."""
    reg = {o: x for (tag, o), x in C.load_tap_state(d, f).items()}
    sound = []
    for tag, line, o, x in C.load_taps(d, f):
        reg[o] = x
        if o == 0x380E:
            sound.append(x)
    bank = reg.get(0x3808, 0)
    sx = ((bank & 1) << 8) | reg.get(0x3809, 0)
    sy = ((bank & 2) << 7) | reg.get(0x380A, 0)
    return bank, sx, sy, sound


def main():
    frames, keep = C.parse_args(DEFAULT)
    d = C.run_mame("ddragonj", frames, ["maincpu:0x0000:0x1fff", "maincpu:0x2800:0x37ff", "sub:0x8000:0x81ff",
                                        "sub:0x40:0x13f", "soundcpu:0x0000:0x0fff"],
                   ["maincpu:0x3808:0x380f"], keep=keep, pens_every=True)
    v = Video()
    m = DDragon()
    worst = 0
    first_bad = None
    for f in frames:
        mem = C.load_dump(d, f, "maincpu", 0x0000)
        C.load_dump(d, f, "maincpu", 0x2800, into=mem)
        sub = C.load_dump(d, f, "sub", 0x8000)
        C.load_dump(d, f, "sub", 0x40, into=sub)
        snd = C.load_dump(d, f, "soundcpu", 0x0000)
        bank, sx, sy, sound = registers(d, f)
        pens = C.load_pens(d, f)
        pd = int(np.any(v.pens(mem)[:384] != pens[:384], axis=1).sum())     # (384-511: no layer's)
        shot = C.load_shot(d, f)
        rgb = v.render_rgb(mem, sx, sy)
        n = C.diff_pixels(rgb, shot)
        worst = max(worst, n, pd)
        C.save_compare(d / ("cmp%d.png" % f), rgb, shot)
        while m.frame < f:
            m.run_frame()
        km, tot, first = C.ram_diff(m.mem, mem, MAIN_RAM)
        kc, _, fc = C.ram_diff(m.comram, sub[0x8000:0x8200], [(0, 0x1FF)])
        ki, _, fi = C.ram_diff(m.sub.ram256, sub[0x40:0x140], [(0, 0xFF)])
        ks, _, fs = C.ram_diff(m.snd_ram, snd, [(0, 0xFFF)])
        mine = [x for fr, x in m.sound_log if fr == f - 1]
        ok = not (km or kc or ki or ks) and (m.scrollx, m.scrolly) == (sx, sy) and mine == sound
        if not ok and first_bad is None:
            first_bad = f
        own = C.diff_pixels(m.render_rgb(), shot)
        print("frame %5d: render %5d px, %d pens (scroll %03X %03X bank %02X) | logic main %d of %d %s, shared %d %s, "
              "mcu %d %s, sound RAM %d %s, scroll %s, sound %s | own picture %d px" % (
                  f, n, pd, sx, sy, bank, km, tot, " ".join(first), kc, " ".join(fc), ki, " ".join(fi), ks,
                  " ".join(fs), "ok" if (m.scrollx, m.scrolly) == (sx, sy) else "%03X %03X" % (m.scrollx, m.scrolly),
                  "ok" if mine == sound else "%s vs %s" % (mine, sound), own))
    print("compare pictures (reference | MAME | differences) in", d)
    if first_bad is not None:
        print("logic: first differing frame checked", first_bad)
    return int(worst != 0 or first_bad is not None)


if __name__ == "__main__":
    sys.exit(main())
