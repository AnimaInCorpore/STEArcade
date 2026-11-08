"""Compare tools/machine.py with MAME (docs/porting-guide.md, "Against MAME's picture"): MAME 0.248+ (MAME=<exe>; the
authoritative source is 0.286, the pens are checked against the binary's).

Three checks at the dump frames (frame k = k frames after power-on; the reference runs in MAME's phase, frame_line 224):
  pens     the 544 pens (characters 0-31, sprites 32-287, background 288-543) equal MAME's palette
  render   the reference renderer draws MAME's RAM ($8000-$9FFF) and must give MAME's picture: 0 differing pixels
  game     the reference machine from power-on (the real 51XX / 53XX, no input): its own picture against MAME's (0
           pixels) and its RAM (a few bytes of the stacks' residue differ: the CPUs' phase is not MAME's to the cycle)

    python games/digdug/ref/mame_cmp_digdug.py [frames ...] [--keep DIR]       # default 400 800 1200 1800 2400
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "..", "tools"), os.path.join(HERE, "..", "..", "..", "engine")]
import machine
import mame_cmp as mc
from paths import ROMS

DEFAULT_EXE = r"C:\Arbeit\F030Arcade\third_party\wolfmame-0248\mame.exe"
frames, keep = mc.parse_args([400, 800, 1200, 1800, 2400])
os.environ.setdefault("MAME", DEFAULT_EXE)

rompath = Path(tempfile.mkdtemp(prefix="digdug_roms_", dir=(r"F:aude	mpdigdug" if os.path.isdir("F:\claude") else None)))
for z in ("digdug.zip", "namco51.zip", "namco53.zip"):
    shutil.copy(ROMS / z, rompath / z)
d = mc.run_mame("digdug", frames, ["maincpu:0x8000:0x9fff"], keep=keep, rompath=rompath)
pens = mc.load_pens(d)

g = machine.Gfx()
mine = [g.palette[0], g.palette[0]] * 0
want = []
for i in range(16):
    want += [g.palette[0], g.palette[i]]
want += [g.palette[v] for v in g.sprite_lut] + [g.palette[v] for v in g.bg_lut]
bad = [i for i in range(len(pens)) if len(want) <= i or tuple(pens[i]) != want[i]]
print("pens: %d of %d differ" % (len(bad), len(pens)), [(i, tuple(pens[i]), want[i]) for i in bad[:4]])
worst = len(bad)

m = machine.DigDug()
m.gfx = g
worst_game = 0
for f in frames:
    while m.frame < f:
        m.run_frame()
    mem = mc.load_dump(d, f, "maincpu", 0x8000)
    shot = mc.load_shot(d, f)
    k = sum(a != b for a, b in zip(bytes(m.ram), mem[0x8000:0xa000]))
    own = mc.diff_pixels(m.render_rgb(), shot)
    # the renderer on MAME's own RAM (the video latch is write-only: the reference's, which the game set the same way)
    saved = bytes(m.ram)
    m.ram[:] = mem[0x8000:0xa000]
    rgb = m.render_rgb()
    m.ram[:] = saved
    n = mc.diff_pixels(rgb, shot)
    mc.save_compare(d / ("cmp%d.png" % f), rgb, shot)
    worst = max(worst, n, own)
    print("frame %5d: render of MAME's RAM %d pixels differ; game picture %d pixels differ; game RAM %d of %d bytes "
          "differ (%s)" % (f, n, own, k, 0x2000, " ".join("%04X" % (0x8000 + i) for i, (x, y) in
                                                          enumerate(zip(bytes(m.ram), mem[0x8000:0xa000])) if x != y)[:60]))
print("compare pictures (reference | MAME | differences) in", d)
sys.exit(int(worst != 0))
