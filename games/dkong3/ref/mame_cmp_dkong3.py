"""Compare tools/machine.py render_raw() with MAME pixel by pixel (the check every reference gets, docs/porting-guide.md).

    python games/dkong3/ref/mame_cmp_dkong3.py [frames...] [--keep DIR]       # default 700 1500 2500

One MAME run (engine/mame_frames.lua through engine/mame_cmp.py; MAME in the MAME environment variable, default the
wolfmame-0248 of the F030Arcade checkout; ROM zips in assets/roms) dumps $6000-$77FF and the screenshot at each frame and
logs the writes to the latches $7E81-$7E87 (gfx bank, flip, sprite bank, NMI mask, DMA ready, palette bank): the reference
renders the dumped memory with the latches' values at the frame's end and the number of differing pixels is printed
(0 = equal to MAME).  The screenshot is the rotated picture (224 x 256).
"""
import os
import sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "..", "tools"), os.path.join(HERE, "..", "..", "..", "engine")]
os.environ.setdefault("MAME", r"C:\Arbeit\F030Arcade\third_party\wolfmame-0248\mame.exe")
import mame_cmp
import machine

if __name__ == "__main__":
    frames, keep = mame_cmp.parse_args([700, 1500, 2500])
    d = mame_cmp.run_mame("dkong3", frames, ["maincpu:0x6000:0x77ff"], taps=["maincpu:0x7e81:0x7e87"], keep=keep)
    pal = mame_cmp.load_pens(d)[:256]
    for f in frames:
        shot = mame_cmp.load_shot(d, f)
        m = machine.DK3()
        m.gfx = machine.Gfx()
        mem = mame_cmp.load_dump(d, f, "maincpu", 0x6000)
        m.ram[:] = mem[0x6000:0x7800]
        state = mame_cmp.load_tap_state(d, f)
        reg = {a: state.get(("maincpu", a), 0) for a in range(0x7e81, 0x7e88)}
        for tag, line, off, data in mame_cmp.load_taps(d, f):
            reg[off] = data
        m.gfx_bank = ~reg[0x7e81] & 1
        m.flip = reg[0x7e82] & 1
        m.sprite_bank = reg[0x7e83] & 1
        m.palette_bank = (reg[0x7e86] & 1) | ((reg[0x7e87] & 1) << 1)
        rgb = pal[m.render_raw()][16:240].transpose(1, 0, 2)[::-1]
        n = mame_cmp.diff_pixels(rgb, shot)
        print("frame %d: gfx bank %d flip %d sprite bank %d palette bank %d: %d of %d pixels differ" % (
            f, m.gfx_bank, m.flip, m.sprite_bank, m.palette_bank, n, shot.shape[0] * shot.shape[1]))
        if n:
            mame_cmp.save_compare(os.path.join(str(d), "cmp%d.png" % f), rgb, shot)
    if frames:
        print("pens:", " ".join("%02x%02x%02x" % tuple(p) for p in pal[:8]), "...")
        np.save(os.path.join(str(d), "pens.npy"), pal)
