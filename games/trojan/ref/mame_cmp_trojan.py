"""Trojan: the reference board (tools/machine.py) against MAME 0.289 (set trojanr).

    python games/trojan/ref/mame_cmp_trojan.py [frame ...] [--keep DIR] [--every N]

One MAME run (engine/mame_frames.lua, ROMs from build/trojan/mame_roms: tools/prepare.py) dumps the main CPU's
$C000-$EFFF at each frame, logs the writes to the video/sound registers $F800-$F80E and to the stack page (with the
beam's line), copies
the sprite RAM at each write to $F808 (the sprite DMA, MAME's buffered sprite RAM), and takes the screen and the pens.
(1) render: the reference renderer draws MAME's memory, the sprite buffer and the registers as they stand at the
    frame's end (MAME draws the whole screen at the start of the vertical blank: no partial updates), the colours from
    MAME's pens: 0 differing pixels;
(2) logic: the reference machine runs from power-on to the same frames: its RAM, sprite buffer, registers and pens
    (from its palette RAM, RGBx_444; the pens the game wrote) against MAME's; the sound latch writes against MAME's;
    the cycle timing: every write to the stack page $CF80-$CFFF in the dumped frames (interrupt pushes, calls) with
    its beam position, against MAME's write log.
--every N adds every N-th frame up to the last one (logic only: the first divergence).
"""
from pathlib import Path
import sys

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools"), str(Path(__file__).resolve().parents[3] / "engine")]
from machine import Trojan, Video, FP, SCANTIME, APC, LINES
from prepare import MAME_ROMS
import mame_cmp as C

RAM = [(0xC000, 0xCF7F), (0xD000, 0xEFFF)]
STACK = [(0xCF80, 0xCFFF)]          # (SP stays in $CFD0-$CFFF: the bytes below it are old pushes)
DEFAULT = [60, 120, 300, 600, 900, 1200, 1500, 1800, 2100, 2400, 2700, 3000, 3300, 3600]


def regs_at(d, f):
    """The register writes ($F800-$F80E) as they stand at frame f's end: {address: value} and the sound latch writes
    of the frame."""
    r = {o: v for (t, o), v in C.load_tap_state(d, f).items() if o >= 0xF800}
    sound = []
    for t, line, o, v in C.load_taps(d, f):
        if o < 0xF800:
            continue
        r[o] = v
        if o == 0xF80C:
            sound.append(v)
    return r, sound


def as_regs(r):
    return dict(scroll1x=r.get(0xF800, 0) | r.get(0xF801, 0) << 8, scroll1y=r.get(0xF802, 0) | r.get(0xF803, 0) << 8,
                scroll2x=r.get(0xF804, 0), image=r.get(0xF805, 0), flip=not r.get(0xF80E, 1) & 1)


def main():
    args = sys.argv[1:]
    every = 0
    if "--every" in args:
        i = args.index("--every")
        every = int(args[i + 1])
        del args[i:i + 2]
    sys.argv[1:] = args
    frames, keep = C.parse_args(DEFAULT)
    logic_only = set()
    if every:
        logic_only = set(range(every, max(frames) + 1, every)) - set(frames)
    allf = sorted(set(frames) | logic_only)
    d = C.run_mame("trojanr", allf, ["maincpu:0xc000:0xefff"], ["maincpu:0xf800:0xf80e", "maincpu:0xcf80:0xcfff"],
                   keep=keep,
                   rompath=MAME_ROMS, snaps=["maincpu:program:0xf808=maincpu:0xde00:0xdf7f"], pens_every=True,
                   timeout=3600)
    v = Video()
    m = Trojan()
    stack_log = []                      # (frame, beam line, offset, value) of the machine's stack writes
    write = m.cpu._wr

    def wr(a, x):
        if STACK[0][0] <= a <= STACK[0][1]:
            t = m.time() * APC - m.frame * FP
            stack_log.append((m.frame + 1, (248 + t / SCANTIME) % LINES, a, x))
        write(a, x)
    m.cpu._wr = wr
    timing_bad = []
    worst = 0
    first_bad = None
    sound_m, sound_r = [], []
    for f in allf:
        mem = C.load_dump(d, f, "maincpu", 0xC000)
        spr = C.load_snap(d, f)
        r, snd = regs_at(d, f)
        regs = as_regs(r)
        pens = C.load_pens(d, f)
        while m.frame < f:
            m.run_frame()
        k, tot, first = C.ram_diff(m.mem, mem, RAM)
        ks = C.ram_diff(m.mem, mem, STACK)[0]
        sk = int(np.sum(np.frombuffer(bytes(m.sprites), np.uint8) != np.frombuffer(spr, np.uint8)))
        rk = [n for n in regs if regs[n] != m.regs[n]]
        pk = int((np.any(m.pens() != pens, axis=1) & m.pal_written).sum())
        sound_m.append((f, snd))
        # cycle timing: the stack writes of the frame (interrupt pushes, calls) with their beam positions
        ms = [(line, o, x) for t, line, o, x in C.load_taps(d, f) if o < 0xF800]
        rs = [(line, o, x) for fr, line, o, x in stack_log if fr == f]
        if f > 1 and (len(ms) != len(rs) or any(a[1:] != b[1:] or abs(a[0] - b[0]) > 0.002 for a, b in zip(ms, rs))):
            timing_bad.append(f)
        stack_log.clear()
        bad = k or sk or rk or pk
        if bad and first_bad is None:
            first_bad = f
        if f in logic_only:
            if bad:
                print("frame %5d: logic RAM %4d of %d bytes differ %s (stack %d); sprites %d; regs %s; pens %d" % (
                    f, k, tot, " ".join(first), ks, sk, ",".join(rk) or "-", pk))
            continue
        rgb = v.render_rgb(mem, spr, regs, pens)
        shot = C.load_shot(d, f)
        n = C.diff_pixels(rgb, shot)
        worst = max(worst, n)
        C.save_compare(d / ("cmp%d.png" % f), rgb, shot)
        own = C.diff_pixels(m.render_rgb(), shot)
        print("frame %5d: render %5d pixels differ; logic RAM %4d of %d bytes differ %s (stack %d); sprite buffer "
              "%d, regs %s, pens %d differ; its own picture %d pixels" % (f, n, k, tot, " ".join(first), ks, sk, ",".join(rk) or "-",
                                                             pk, own))
    # the sound latch: MAME's writes in each dumped frame (the taps since the previous frame's end) against the machine's
    bad = [f for f, snd in sound_m[1:] if snd != [x for fr, x in m.sound_log if fr == f - 1]]
    print("sound latch writes: %d of %d dumped frames differ%s" % (len(bad), len(sound_m) - 1,
                                                                  " (first %d)" % bad[0] if bad else ""))
    print("stack writes (value and beam position, 0.002 lines): %d of %d dumped frames differ%s" % (
        len(timing_bad), len(allf) - 1, " (first %d)" % timing_bad[0] if timing_bad else ""))
    print("first frame with a logic difference: %s" % first_bad)
    print("compare pictures (reference | MAME | differences) in", d)
    return int(worst != 0)


if __name__ == "__main__":
    sys.exit(main())
