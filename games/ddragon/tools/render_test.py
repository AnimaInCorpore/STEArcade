"""The STE picture (run/ddragon_sim, render.s) against the reference picture through the fixed palette
(tools/assets.py Oracle), after arcade frames of the port schedule.

    python games/ddragon/tools/render_test.py FRAMES [--seed N] [--first F] [--every K] [--save DIR]

The program runs every frame (the logic: tools/logic_test.py checks it); from frame F on, every K-th it draws its
picture (render_frame), which is compared pixel for pixel (the 256 x 240 picture: ring pixels 32 + sx .. of the
window's lines) with the reference's colour indices.  The side bands are not part of the picture.  --save: PNGs of
the differing frames (STE | reference | differences).
"""
from pathlib import Path
import argparse
import sys

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine"),
                str(Path(__file__).resolve().parents[1] / "ref")]
from sim import Sim, TRAP1
from machine68k import Register as R
from machine import DDragonPort, DSW0
from paths import ROOT, build_dir
import assets
import cover

STRIDE = 416


def picture(mem, sym):
    """the 240 x 256 colour indices of the drawn ring (flip_addr: the window's first word at the picture's line 0)"""
    base = mem.r32(sym["flip_addr"])
    fine = mem.r8(sym["flip_fine"])
    data = np.frombuffer(bytes(mem.r_block(base, 240 * STRIDE)), np.uint8).reshape(240, STRIDE)
    words = data.reshape(240, STRIDE // 8, 4, 2)
    planes = (words[..., 0].astype(np.uint16) << 8) | words[..., 1]      # [240, 52, 4]
    bits = np.unpackbits(planes.astype(">u2").view(np.uint8).reshape(240, STRIDE // 8, 4, 2), axis=3)
    bits = bits.reshape(240, STRIDE // 8, 4, 16)                          # [line, word, plane, pixel]
    pix = (bits * (1 << np.arange(4))[None, None, :, None]).sum(2)          # [line, word, pixel]
    pix = pix.reshape(240, STRIDE // 8 * 16)
    return pix[:, fine + 32:fine + 32 + 256].astype(np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames", type=int)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--first", type=int, default=30)
    ap.add_argument("--every", type=int, default=5)
    ap.add_argument("--save", default=None)
    args = ap.parse_args()
    run = ROOT / "run" / "ddragon_sim"
    sim = Sim(str(run / "DDRAGON.PRG"), ram_kib=16384, run_dir=run)     # (the trace on: the Blitter's registers)
    sym = {k: v + sim.base for k, v in sim.symbols(build_dir("ddragon") / "ddragon_sim.map").items()}
    stops = {sym[n]: n for n in ["sim_wait", "sim_frame_done", "sim_render_ret", "sim_badpc"]}
    mem, cpu = sim.mem, sim.cpu
    g = sym["g_mem"]
    dsw1, inputs = cover.schedule(args.seed)
    ref = DDragonPort(DSW0, dsw1)
    mem.w8(sym["dd_dsw"] + 1, dsw1)          # (the start code copies it into in_bytes)
    oracle = assets.Oracle()
    save = Path(args.save) if args.save else None
    if save:
        save.mkdir(parents=True, exist_ok=True)

    def run_to_stop():
        used = 0
        while used < 3_000_000_000:
            r = cpu.execute(4000)
            used += r.cycles
            pc = cpu.r_pc()
            if pc in stops:
                return stops[pc], used
            if pc == TRAP1:
                sim.gemdos()
        raise RuntimeError("68000 budget exceeded at %06x" % (cpu.r_pc() - sim.base))

    def resume():
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp))
        cpu.w_reg(R.A7, sp + 4)

    if run_to_stop()[0] != "sim_wait":
        raise RuntimeError("did not reach sim_wait")
    bad = checked = 0
    cyc = []
    for f in range(args.frames):
        p1, p2, extra, coins = inputs(f)
        if coins:
            ref.coin(coins)
            mem.w8(sym["port_coins"], mem.r8(sym["port_coins"]) | coins)
        ref.inputs[0], ref.inputs[1], ref.inputs[2] = p1, p2, extra
        for k, v in enumerate((p1, p2, extra)):
            mem.w8(sym["in_bytes"] + k, v)
        for a, v in cover.cheats(ref, args.seed, f):
            mem.w8(g + a, v)
        ref.run_frame_port()
        draw = f >= args.first and (f - args.first) % args.every == 0
        mem.w8(sym["sim_render"], 1 if draw else 0)
        resume()
        stop, _ = run_to_stop()
        if stop != "sim_frame_done":
            raise RuntimeError("frame %d: stopped at %s" % (f, stop))
        resume()
        if draw:
            stop, used = run_to_stop()
            if stop != "sim_render_ret":
                raise RuntimeError("frame %d: the picture stopped at %s" % (f, stop))
            cyc.append(used)
            got = picture(mem, sym)
            want = oracle.frame(ref)
            checked += 1
            n = int((got != want).sum())
            if n:
                bad += 1
                if bad <= 10:
                    ys, xs = np.nonzero(got != want)
                    print("frame %d: %d pixels differ (first at x %d y %d: %d / %d)" % (f, n, xs[0], ys[0],
                                                                                       got[ys[0], xs[0]],
                                                                                       want[ys[0], xs[0]]), flush=True)
                if save:
                    from PIL import Image
                    rgb = oracle.rgb
                    diff = rgb[want].copy()
                    diff[got != want] = (255, 0, 255)
                    Image.fromarray(np.hstack((rgb[got], rgb[want], diff))).save(save / ("f%05d.png" % f))
            resume()
        if run_to_stop()[0] != "sim_wait":
            raise RuntimeError("frame %d: not back at sim_wait" % f)
    print("%d pictures compared, %d differ; 68000 cycles a picture (Musashi): mean %.0f, max %d" % (
        checked, bad, np.mean(cyc) if cyc else 0, max(cyc) if cyc else 0))
    return int(bad != 0)


if __name__ == "__main__":
    sys.exit(main())
