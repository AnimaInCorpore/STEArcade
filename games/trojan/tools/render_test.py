"""The STE picture (run/trojan_sim, engine/sim.py: the translated program and the renderer) against the reference's
picture through the fixed palette (tools/assets.py Oracle), frame by frame in lock-step with the port schedule.

    python games/trojan/tools/render_test.py [FRAMES] [--seed N | --auto] [--first F] [--every K] [--shots DIR]

Every drawn picture from frame F on (every K-th compared) must equal the reference's 240 x 256 colours exactly; the
side bands (the screen's words 0, 1 and 18, 19: the 32 pixels left and right of the picture) must be black but where
a sprite clipped at the black words' boundary or drawn whole into the masked word shows (render.s).  Reports the
68000 cycles a picture (Musashi: CPU and Blitter).
"""
from pathlib import Path
import argparse
import sys

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine'),
                str(Path(__file__).resolve().parents[1] / 'ref')]
from sim import Sim, TRAP1
from machine68k import Register as R
from machine import TrojanPort, DSWA
from assets import Oracle
from paths import ROOT, build_dir
from logic_test import auto_inputs
import cover

STRIDE = 416


def picture(mem, sym):
    """the shown picture [240, 320] colour indices (the ring at flip_addr, the fine scroll flip_fine)"""
    base = mem.r32(sym['flip_addr'])
    f = mem.r8(sym['flip_fine'])
    raw = np.frombuffer(bytes(mem.r_block(base, 240 * STRIDE)), np.uint8).reshape(240, STRIDE)[:, :21 * 8]
    words = raw.reshape(240, 21, 4, 2)
    w = (words[..., 0].astype(np.uint16) << 8) | words[..., 1]
    pix = np.zeros((240, 21 * 16), np.uint8)
    for p in range(4):
        for b in range(16):
            pix[:, b::16] |= (((w[:, :, p] >> (15 - b)) & 1).astype(np.uint8) << p)
    return pix[:, f:f + 320]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=1500)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--auto', action='store_true')
    ap.add_argument('--first', type=int, default=0)
    ap.add_argument('--every', type=int, default=1)
    ap.add_argument('--shots', default=None)
    args = ap.parse_args()
    run = ROOT / 'run' / 'trojan_sim'
    sim = Sim(str(run / 'TROJAN.PRG'), ram_kib=16384, run_dir=run)     # (the trace on: the Blitter's registers)
    sym = {k: v + sim.base for k, v in sim.symbols(build_dir('trojan') / 'trojan_sim.map').items()}
    stops = {sym[n]: n for n in ['sim_wait', 'sim_frame_done', 'z80_badpc']}
    mem, cpu = sim.mem, sim.cpu
    oracle = Oracle()
    level, cheats, inputs = cover.schedule(args.seed)
    if args.auto:
        level, cheats = None, False
    dswb = 0x1C | cover.LEVEL_DSW[level] if level else 0xFC
    ref = TrojanPort(DSWA, dswb)
    mem.w8(sym['tr_dsw'], dswb)
    block = sym['g_block']

    def z(a):
        return block + 0x8000 + (a if a < 0x8000 else a - 0x10000)

    def run_to_stop():
        used = 0
        while used < 2_000_000_000:
            r = cpu.execute(4000)
            used += r.cycles
            pc = cpu.r_pc()
            if pc in stops:
                return stops[pc], used
            if pc == TRAP1:
                sim.gemdos()
            if sim.terminated:
                raise RuntimeError('terminated at %06x: %s' % (pc, sim.log[-3:]))
        raise RuntimeError('68000 budget exceeded at %06x' % cpu.r_pc())

    def resume():
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp))
        cpu.w_reg(R.A7, sp + 4)

    if run_to_stop()[0] != 'sim_wait':
        raise RuntimeError('did not reach the idle point')
    ref.run_to_idle()
    ref.booted = True
    cycles, pictures, worst = 0, 0, 0
    for f in range(args.frames):
        if args.auto:
            s, p, lives = auto_inputs(f)
        else:
            s, p = inputs(f)
            lives = cheats and f >= 1000
        ref.inputs[0], ref.inputs[1] = s, p
        mem.w8(sym['tr_inputs'], s)
        mem.w8(sym['tr_inputs'] + 1, p)
        if lives:
            for a, v in ((0xCDA0, 3), (0xC078, 0), (0xC079, 0x99)) if cheats else ((0xCDA0, 3),):
                ref.mem[a] = v
                mem.w8(z(a), v)
        mem.w8(sym['vbl_pending'], 1)
        ref.run_frame_port()
        resume()
        stop, used = run_to_stop()
        if stop != 'sim_frame_done':
            raise RuntimeError('frame %d: stopped at %s' % (f, stop))
        if f >= args.first:
            cycles += used
            pictures += 1
            worst = max(worst, used)
        if f >= args.first and (f - args.first) % args.every == 0 and not ref.regs['flip']:
            mine = picture(mem, sym)
            want = oracle.frame(ref)
            diff = np.argwhere(mine[:, 32:288] != want)
            # (the band part of the masked words w0 + 2 and w0 + 18, screen x 32 - f .. 31 and 288 .. 303 - f, shows
            # sprites drawn whole there: the picture's edge is not on a 16-pixel group there, AGENTS.md)
            fine = mem.r8(sym['flip_fine'])
            band = np.argwhere(np.hstack((mine[:, :32 - fine], mine[:, 304 - fine:] if fine else mine[:, 288:])) != 0)
            if args.shots and f % 100 == 0:
                from PIL import Image
                Image.fromarray(np.hstack((oracle.rgb[mine], oracle.rgb[np.hstack((np.zeros((240, 32), np.uint8), want,
                                                                                  np.zeros((240, 32), np.uint8)))]))
                                ).save(Path(args.shots) / ('render%05d.png' % f))
            if len(diff) or len(band):
                from PIL import Image
                out = build_dir('trojan') / 'render_diff.png'
                full = np.hstack((np.zeros((240, 32), np.uint8), want, np.zeros((240, 32), np.uint8)))
                marked = oracle.rgb[mine].copy()
                marked[mine != full] = (255, 0, 255)
                Image.fromarray(np.hstack((oracle.rgb[mine], oracle.rgb[full], marked))).save(out)
                raise RuntimeError('frame %d: %d pixels differ (first %s), %d band pixels not black; %s' % (
                    f, len(diff), diff[:6].tolist(), len(band), out))
        resume()
        if run_to_stop()[0] != 'sim_wait':
            raise RuntimeError('frame %d: not back at the idle point' % f)
        if f % 100 == 99:
            print('%d frames: pictures equal; %.0f cycles a frame (logic + picture), worst %d' % (
                f + 1, cycles / max(pictures, 1), worst), flush=True)
    print('PASS: %d frames, every compared picture equal' % args.frames)


if __name__ == '__main__':
    main()
