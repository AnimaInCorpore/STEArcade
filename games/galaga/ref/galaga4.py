"""Galaga reference: the colour codes the game uses for sprites and characters, their
transparent pens, and the palette entries that matter.  python ref/galaga4.py [frames]"""
import os, sys
from collections import Counter
sys.path[:0] = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from machine import Galaga, Gfx

frames = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
m = Galaga()
g = Gfx()
spr_colors = Counter()
chr_colors = Counter()
spr_codes = Counter()


def script(m, f):
    m.in0 = m.in1 = 0xff
    if 1500 <= f < 1506: m.in1 &= ~0x10
    if 1540 <= f < 1546: m.in1 &= ~0x04
    if f >= 1560:
        g = f - 1560
        if (g // 40) % 2: m.in0 &= ~0x02
        else: m.in0 &= ~0x08
        if g % 20 < 3: m.in1 &= ~0x01


for f in range(frames):
    script(m, f)
    m.run_frame()
    if f >= 800:
        ram = m.ram
        for o in range(0, 0x80, 2):
            if ram[0xb80 + o] | ram[0xb81 + o]:
                spr_colors[ram[0xb81 + o] & 0x3f] += 1
                spr_codes[ram[0xb80 + o] & 0x7f] += 1
        for i in range(0x400):
            chr_colors[ram[0x400 + i] & 0x3f] += 1
print("sprite colour codes used:", sorted(spr_colors))
print("char colour codes used:", sorted(chr_colors))
print("sprite codes used:", len(spr_codes))
for name, lut, trans, used in (("sprite", g.sprite_lut, 0x0f, spr_colors), ("char", g.char_lut, 0x1f, chr_colors)):
    classes = Counter()
    pens = set()
    for c in sorted(used):
        t = tuple(p for p in range(4) if lut[c * 4 + p] == trans)
        classes[t] += 1
        pens |= set(lut[c * 4 + p] for p in range(4) if lut[c * 4 + p] != trans)
        print("  %s colour %2d: transparent pens %s, palette %s" % (name, c, t, [lut[c * 4 + p] for p in range(4)]))
    print("%s transparent-pen classes: %s; palette entries used: %s" % (name, dict(classes), sorted(pens)))
