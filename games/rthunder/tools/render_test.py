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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames", nargs="?", type=int, default=600)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--every", type=int, default=100)
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

    run_to(sym["sim_wait"])
    d = np.load(build_dir("rthunder") / "palfit.npz")
    flat = d["flat"]
    dswa, dswb, inputs = cover.schedule(args.seed)
    m = RthunderRule()
    m.dsw = [dswa, dswb]
    m.boot()
    bad = 0
    for f in range(args.frames):
        m.in0, m.in1, m.in2 = inputs(f)
        m.run_frame_port()
        if f % args.every != args.every - 1:
            continue
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
        miss0 = mem.r32(sym["tc_miss"])
        cyc = call("ren_bg_all")
        miss = mem.r32(sym["tc_miss"]) - miss0
        got = planar_to_index(bytes(mem.r_block(sym["ren_bg"], 256 * 256)), 256, 32)
        want = expected_bg(m, flat)
        diff = int((got != want).sum())
        print("frame %d: ren_bg_all %d cycles (%d tile conversions), %d pixels differ" % (m.frame, cyc, miss, diff))
        bad += diff != 0
    print("bg: %d pictures differ" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
