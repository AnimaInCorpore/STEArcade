"""Moon Patrol: the reference board (tools/machine.py) against MAME 0.286 (set MAME=<path to mpatrol.exe>).

    python games/mpatrol/ref/mame_cmp_mpatrol.py [frame ...] [--play] [--keep DIR]

--play: both MAME (engine/mame_frames.lua's INPUTS read taps on $D000-$D7FF) and the reference read the same
inputs and DIP switches each frame (play_inputs: coin, start, invulnerable random driving, the city from frame 5488).

One MAME run (engine/mame_frames.lua, PAL=:tx_palette) dumps the main CPU's $8000-$87FF (text RAM) and $E000-$E7FF
(RAM) at the frames and taps the write-only registers: the sprite RAM $C800-$CFFF, the sound / flip latches at
$D000-$D7FF and the I/O ports (text scroll, the backgrounds' positions and control); their state at a frame's end is
the tap state plus the frame's logged writes.  Two short runs take the sprite and background palettes' pens.
(1) render: the reference renderer draws MAME's memory and registers: 0 differing pixels and pens;
(2) logic: the reference machine runs from power-on to the same frames: its RAM, sprite RAM and registers against
    MAME's, and its sound commands of the frame against MAME's writes.
Run with MAME 0.286 (F030Arcade's source, mpatrol.exe; see the README).  Not usable with WolfMAME 0.162 / 0.184: their m52 video differs (background and sprite positions, sprite order, the
fill pen; MAME 0.183's video/m52.cpp) and their Lua has no snapshots.
"""
import os
from pathlib import Path
import random
import sys
import tempfile

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools"), str(Path(__file__).resolve().parents[3] / "engine")]
from machine import MoonPatrol, Video, DSW1, DSW2
import mame_cmp as C

RAM = [(0x8000, 0x87FF), (0xE000, 0xE7FF)]
DEFAULT = [60, 300, 600, 900, 1200, 1500, 1800, 2100, 2400, 2700, 3000, 3600]
PLAY = [420, 600, 1200, 2400, 3600, 4800, 5490, 5600, 6000, 7200, 8400]      # (--play; the city from 5488)
PORTS = {0x00: 0, 0x40: 1, 0x60: 2, 0x80: 3, 0xA0: 4, 0xC0: 5}     # I/O port (& $E0) -> machine.regs index


def registers(d, f):
    """MAME's sprite RAM, regs, flip and the frame's sound commands at the frame's end (from the taps)."""
    spr = bytearray(0x400)
    regs = [0] * 6
    flip = 0
    sound = []

    def put(tag, o, x, logged):
        nonlocal flip
        if tag == "maincpu" and 0xC800 <= o < 0xD000:
            spr[o & 0x3FF] = x
        elif tag == "maincpu" and 0xD000 <= o < 0xD800:
            if o & 3 == 0 and logged:
                sound.append(x)
            elif o & 3 == 1:
                flip = x
        elif tag == "maincpu:io" and (o & 0xE0) in PORTS:
            regs[PORTS[o & 0xE0]] = x

    for (tag, o), x in C.load_tap_state(d, f).items():
        put(tag, o, x, False)
    for tag, line, o, x in C.load_taps(d, f):
        put(tag, o, x, True)
    return spr[:0x100], regs, flip, sound


def pens_of(palette):
    os.environ["PAL"] = palette
    return C.load_pens(C.run_mame("mpatrol", [2], ["maincpu:0xe000:0xe0ff"]))


def play_inputs(frames, seed=3):
    """[frames + 1] records (IN0, IN1, IN2, DSW1, DSW2): MAME's defaults at frame 0, then the invulnerability DIP
    switch on, a coin at 300, start at 400, from 450 random driving (right, jump, fire) changing every 10 frames."""
    rnd = random.Random(seed)
    out = [bytes((0xFF, 0xFF, 0xFF, DSW1, DSW2))]
    held = 0xFF
    for f in range(1, frames + 1):
        if f >= 450 and f % 10 == 0:
            held = 0xFF & ~rnd.choice([0x01, 0x01, 0x81, 0x21, 0xA1, 0x80, 0])
        in0 = 0xF7 if 300 <= f < 330 else (0xFE if 400 <= f < 410 else 0xFF)
        out.append(bytes((in0, held if f >= 450 else 0xFF, 0xFF, DSW1, DSW2 & ~0x40)))
    return out


def main():
    play = "--play" in sys.argv
    if play:
        sys.argv.remove("--play")
    frames, keep = C.parse_args(PLAY if play else DEFAULT)
    inputs = None
    if play:
        inputs = play_inputs(max(frames))
        path = Path(tempfile.mkdtemp(prefix="mpatrol_in_")) / "inputs.bin"
        path.write_bytes(b"".join(inputs))
        os.environ.update(INPUTS=str(path), INPUT_WIDTH="5", READS="maincpu:0xd000:0xd7ff:7")
    saved = {k: os.environ.pop(k, None) for k in ("INPUTS", "INPUT_WIDTH", "READS")}
    sp_pens = pens_of(":sp_palette")
    bg_pens = pens_of(":bg_palette")
    os.environ.update({k: v for k, v in saved.items() if v is not None})
    os.environ["PAL"] = ":tx_palette"
    d = C.run_mame("mpatrol", frames, ["maincpu:0x8000:0x87ff", "maincpu:0xe000:0xe7ff"],
                   ["maincpu:0xc800:0xcfff", "maincpu:0xd000:0xd7ff", "maincpu:io:0x00:0xff"], keep=keep)
    pens = np.vstack((C.load_pens(d), sp_pens, bg_pens))
    v = Video()
    pen_diff = int(np.any(v.pens != pens, axis=1).sum()) if v.pens.shape == pens.shape else len(pens)
    print("pens: %d of %d differ (ours %d)" % (pen_diff, len(pens), len(v.pens)))
    worst = pen_diff
    m = MoonPatrol()
    first_bad = None
    for f in frames:
        mem = C.load_dump(d, f, "maincpu", 0x8000)
        C.load_dump(d, f, "maincpu", 0xE000, into=mem)
        spr, regs, flip, sound = registers(d, f)
        if flip & 1:
            print("frame %d: flip latch written 1" % f)
        rgb = v.render_rgb(mem[0x8000:0x8400], mem[0x8400:0x8800], spr, regs)
        shot = C.load_shot(d, f)
        n = C.diff_pixels(rgb, shot)
        worst = max(worst, n)
        C.save_compare(d / ("cmp%d.png" % f), rgb, shot)
        while m.frame < f:
            if inputs is not None:
                m.in0, m.in1, m.in2, m.dsw1, m.dsw2 = inputs[m.frame]
            m.run_frame()
        kr, tot, first = C.ram_diff(m.mem, mem, RAM)
        ks = sum(a != b for a, b in zip(m.sprite_ram[:0x100], spr))
        mine = [x for fr, x in m.sound_log if fr == f - 1]
        bad = kr or ks or m.regs != regs or mine != sound
        if bad and first_bad is None:
            first_bad = f
        own = C.diff_pixels(m.render_rgb(), shot)
        print("frame %5d: render %5d pixels differ (regs %s); logic RAM %4d of %d bytes differ %s, sprite RAM %3d, "
              "regs %s, sound %s (%d); its own picture %d pixels" % (
                  f, n, regs, kr, tot, " ".join(first), ks, "ok" if m.regs == regs else m.regs,
                  "ok" if mine == sound else "%s vs %s" % (mine, sound), len(sound), own))
    print("compare pictures (reference | MAME | differences) in", d)
    if first_bad is not None:
        print("logic: first differing frame checked", first_bad)
    return int(worst != 0 or first_bad is not None)


if __name__ == "__main__":
    sys.exit(main())
