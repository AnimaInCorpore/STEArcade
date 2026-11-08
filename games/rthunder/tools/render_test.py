"""The STE renderer's pieces (src/render.s on Musashi) against the reference's pictures (tools/stemodel.py).

    python games/rthunder/tools/render_test.py [frames] [--seed N] [--every K]

The reference runs its port schedule; every K-th frame its state (tile RAMs, scroll registers, sprite RAM) goes into the
simulator, a renderer routine runs and its result is compared:
  bg   ren_bg_all: the virtual screen 512 x 256 = the three scrolling layers composed in priority order over the back
       colour, as STE colour indices (planar), against the reference's layers (machine.tilemap) and the fitted map
"""
import argparse
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / "ref"),
                str(Path(__file__).resolve().parents[3] / "engine")]
from machine68k import Register as R
from sim import Sim, TRAP1
from machine import RthunderRule
import cover
from paths import ROOT, build_dir


def planar_to_index(buf, lines, groups):
    w = np.frombuffer(buf, ">u2").reshape(lines, groups, 4)
    bits = ((w[:, :, None, :] >> (15 - np.arange(16))[None, None, :, None]) & 1)      # [line, group, pixel, plane]
    idx = bits[..., 0] | (bits[..., 1] << 1) | (bits[..., 2] << 2) | (bits[..., 3] << 3)
    return idx.reshape(lines, groups * 16).astype(np.uint8)


def expected_bg(m, flat):
    """the three scrolling layers over the back colour, as indices (256 x 512)"""
    lut = m.pen_table()
    out = np.full((256, 512), lut[8 * m.backcolor + 7], np.int32)
    order = sorted(range(3), key=lambda i: (((m.xscroll[i >> 1][i & 1] & 0x0E00) >> 9), 3 - i))
    for i in order:
        pens, opq = m.tilemap(i >> 1, i & 1)
        out[opq] = pens[opq]
    return flat[out]


RB_LB, LINES = 544, 544


def full_expected(want):
    """the whole buffer: the map twice with 64 pixels of margin each side and 32 lines of guard above and below"""
    ys = (np.arange(LINES) - 32) & 255
    xs = (np.arange(RB_LB * 2) - 64) & 511
    return want[ys][:, xs]


def window_diff(mem, sym, m, flat, name="dbuf0"):
    """the display window of a buffer (as the Shifter shows it: ren_voff, ren_fine, 320 x 224) against the reference's map"""
    buf = bytes(mem.r_block(sym[name], RB_LB * LINES))
    full = planar_to_index(buf, LINES, RB_LB // 8)
    voff = mem.r32(sym["ren_voff"])
    fine = mem.r16(sym["ren_fine"])
    line0, group0 = voff // RB_LB, (voff % RB_LB) // 8
    x0 = group0 * 16 + fine
    win = np.stack([full[line0 + r, x0:x0 + 320] for r in range(224)])
    tiled = np.tile(expected_bg(m, flat), (1, 2))
    sx = m.xscroll[0][0] & 0x1FF
    wx, wy = (4 + sx) & 511, (25 + (m.yscroll[0][0] & 255)) & 255
    exp = np.stack([tiled[(wy + r) & 255, wx:wx + 320] for r in range(224)])
    return int((win != exp).sum())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames", nargs="?", type=int, default=600)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--every", type=int, default=100)
    ap.add_argument("--sprites", action="store_true", help="ren_update + ren_sprites every K-th frame; the picture's 288 columns against stemodel (without the fixed layer)")
    ap.add_argument("--nol3", action="store_true", help="with --sprites: the model without the fixed layer")
    ap.add_argument("--dump", help="with --sprites: the first differing picture (ours left, the model right) as a PNG, then stop")
    ap.add_argument("--update", action="store_true", help="ren_update every frame (marks set), the window compared every frame")
    args = ap.parse_args()
    run = ROOT / "run" / "rthunder_sim"
    s = Sim(str(run / "RTHUNDER.PRG"), run_dir=run)
    s.mem.set_trace_mode(False)
    sym = {k: v + s.base for k, v in s.symbols(build_dir("rthunder") / "rthunder_sim.map").items()}
    mem, cpu = s.mem, s.cpu

    def run_to(stop, limit=2_000_000_000):
        total = 0
        while total < limit:
            total += cpu.execute(20000).cycles
            pc = cpu.r_pc()
            if pc == stop:
                return total
            if pc == sym["sim_badpc"]:
                raise RuntimeError("badpc")
            if pc == TRAP1:
                s.gemdos()
        raise RuntimeError("timeout")

    def call(name):
        sp = cpu.r_reg(R.A7) - 4
        mem.w32(sp, sym["sim_wait"])
        cpu.w_reg(R.A7, sp)
        cpu.w_pc(sym[name])
        return run_to(sym["sim_wait"])

    def put_state(m):
        mem.w_block(sym["vram0"], bytes(m.vram[0]))
        mem.w_block(sym["vram1"], bytes(m.vram[1]))
        hw = bytearray(0x40)
        for dev in (0, 1):
            for layer in (0, 1):
                x = m.xscroll[dev][layer]
                b = dev * 16 + layer * 4
                hw[b], hw[b + 1], hw[b + 2] = x >> 8, x & 0xFF, m.yscroll[dev][layer]
        hw[0x20], hw[0x30] = m.backcolor, m.tilebank
        mem.w_block(sym["hwregs"], bytes(hw))

    run_to(sym["sim_wait"])
    d = np.load(build_dir("rthunder") / "palfit.npz")
    flat = d["flat"]
    dswa, dswb, inputs = cover.schedule(args.seed)
    m = RthunderRule()
    m.dsw = [dswa, dswb]
    m.boot()
    bad = 0
    ucyc, upic, uworst = 0, 0, 0
    for f in range(args.frames):
        m.in0, m.in1, m.in2 = inputs(f)
        m.run_frame_port()
        if args.update:
            put_state(m)
            for i in range(3):
                mem.w8(sym["tile_written"] + i, 1)
            mem.w16(sym["ren_buf"], f & 1)
            cyc = call("ren_update")
            ucyc += cyc
            uworst = max(uworst, cyc)
            upic += 1
            d = window_diff(mem, sym, m, flat, "dbuf%d" % (f & 1))
            if d:
                print("frame %d: ren_update, %d window pixels differ" % (m.frame, d))
                bad += 1
            continue
        if args.sprites:
            if f % args.every != args.every - 1:
                continue
            put_state(m)
            mem.w_block(sym["shared"] + 0x1800, bytes(m.spriteram))
            for i in range(4):
                mem.w8(sym["tile_written"] + i, 1)
            mem.w16(sym["ren_buf"], f % 3)
            call("ren_update")
            mem.set_trace_mode(True)                      # (the simulator's Blitter runs on the trace hook)
            c0 = call("ren_sprites")
            mem.set_trace_mode(False)
            buf = bytes(mem.r_block(sym["dbuf%d" % (f % 3)], RB_LB * LINES))
            full = planar_to_index(buf, LINES, RB_LB // 8)
            voff = mem.r32(sym["ren_voff"])
            fine = mem.r16(sym["ren_fine"])
            line0, group0 = voff // RB_LB, (voff % RB_LB) // 8
            x0 = group0 * 16 + fine
            win = np.stack([full[line0 + r, x0:x0 + 320] for r in range(224)])[:, 16:304]
            import stemodel
            exp = stemodel.picture(m, flat, True, l3=not args.nol3)
            n = int((win != exp).sum())
            print("frame %d: ren_sprites %d cycles, %d misses, %d pixels differ (of %d sprites drawn)" % (
                m.frame, c0, mem.r32(sym["pm_miss"]), n, mem.r16(sym["spl_n"])))
            bad += n != 0
            if n and args.dump:
                from PIL import Image
                pal = np.load(build_dir("rthunder") / "palfit.npz")["palette"].astype(np.uint8)
                both = np.concatenate([pal[win], pal[exp]], axis=1)
                Image.fromarray(both).resize((both.shape[1] * 2, both.shape[0] * 2), Image.NEAREST).save(args.dump)
                return 1
            continue
        if f % args.every != args.every - 1:
            continue
        put_state(m)
        miss0 = mem.r32(sym["tc_miss"])
        cyc = call("ren_bg_all")
        miss = mem.r32(sym["tc_miss"]) - miss0
        buf = bytes(mem.r_block(sym["ren_bg"], RB_LB * LINES))
        full = planar_to_index(buf, LINES, RB_LB // 8)
        diff = int((full != full_expected(expected_bg(m, flat))).sum())
        for b in (0, 1):                                      # both display buffers synced from the clean one
            mem.w16(sym["ren_buf"], b)
            call("ren_sync")
            diff += window_diff(mem, sym, m, flat, "dbuf%d" % b)
        print("frame %d: ren_bg_all %d cycles (%d tile conversions), %d pixels differ" % (m.frame, cyc, miss, diff))
        bad += diff != 0
    if args.update:
        print("ren_update: %d frames, %d differ, mean %.0f cycles, worst %d" % (upic, bad, ucyc / max(upic, 1), uworst))
    print("bg: %d pictures differ" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
