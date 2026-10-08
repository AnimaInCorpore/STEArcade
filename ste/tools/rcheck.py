"""Renderer check: the planar buffer the STE runtime drew vs the reference renderer.

The Z80 RAM of the simulated machine (video RAM, sprite list, palette bank) is loaded
into the reference model and rendered there; the pixels must match the simulated screen.
    python rcheck.py [frames] [every]
"""
import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sim import Sim, RUN, STE
from dkong import DKong
from PIL import Image

frames = int(sys.argv[1]) if len(sys.argv) > 1 else 700
every = int(sys.argv[2]) if len(sys.argv) > 2 else 50
s = Sim(RUN / "DKSIM.PRG")
syms = s.symbols(STE / "build" / "dkong.map")
base = s.base
blk = base + syms["z80_block"]
ref = DKong()
ref.render_rgb()    # loads graphics
ref.flip = 1
pal_ste = None


import random
rnd = random.Random(7)
joy = [0, 0]


def set_input(f):
    s.mem.w8(base + syms["in2_kbd"], 0x80 if 40 <= f < 50 else (0x04 if 80 <= f < 90 else 0))
    if f % 12 == 0:
        joy[0] = rnd.choice([0, 0, 1, 2, 4, 8, 16, 17, 18])
    s.mem.w8(base + syms["in0_kbd"], joy[0])
    if f > 300 and f % 1500 == 800:
        s.mem.w8(blk + 0x6227, rnd.choice([1, 2, 3, 4]))
        s.mem.w8(blk + 0x6229, rnd.choice([1, 2, 3, 4]))


def frame_done():
    return s.mem.r8(base + syms["vbl_busy"]) == 0


bad = 0
checked = 0
while s.frames < frames:
    set_input(s.frames)
    s.run_frames(1)
    # let the VBL handler finish
    r0 = s.cpu.execute(60)
    s._total = getattr(s, '_total', 0) + r0.cycles
    guard = 0
    while not frame_done() and guard < 5000:
        s.run_frames(0)
        r = s.cpu.execute(100)
        s._total = getattr(s, "_total", 0) + r.cycles + s.blitter.cycles
        s.blitter.cycles = 0
        guard += 1
    if s.frames % every:
        continue
    # reference render of the simulated Z80 RAM
    ram = bytes(s.mem.r_block(blk, 0x8000))
    ref.mem[0x6000:0x7800] = ram[0x6000:0x7800]
    ref.mem[0x7000:0x7000 + 0x180] = ram[0x6900:0x6900 + 0x180]
    ref.palette_bank = (ram[0x7D86] & 1) | ((ram[0x7D87] & 1) << 1)
    img_ref = ref.render_rgb()                       # 256 x 224 (display, rot180 for flip)
    drawn = s.mem.r32(base + syms["draw_screen_address"])
    # planar buffer -> palette indices
    buf = np.frombuffer(bytes(s.mem.r_block(drawn, 256 * 256)), np.uint8).reshape(256, 256)
    words = buf[:, :160].reshape(256, 20, 4, 2)
    idx = np.zeros((256, 320), np.uint8)
    for p in range(4):
        w = (words[:, :, p, 0].astype(np.uint16) << 8) | words[:, :, p, 1]
        for b in range(16):
            idx[:, b::16] |= (((w >> (15 - b)) & 1).astype(np.uint8) << p)
    pal = s.palette()
    got = np.array(pal, np.uint8)[idx][:, 48:272]    # 256 rows x 224 columns
    exp = img_ref
    # compare in STE colours (the reference is RGB from the PROMs: compare after palette mapping)
    diff = np.any(np.abs(got.astype(int) - exp.astype(int)) > 40, axis=2)
    n = int(diff.sum())
    checked += 1
    print("frame %4d  differing pixels: %5d" % (s.frames, n))
    if n:
        bad += 1
        Image.fromarray(got).save(RUN / ("rc_got_%04d.png" % s.frames))
        Image.fromarray(exp).save(RUN / ("rc_exp_%04d.png" % s.frames))
print("checked", checked, "frames with differences:", bad)
