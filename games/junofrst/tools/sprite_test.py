"""The blitter's fast path (src/render.s blit_run: prepared images, Blitter passes) against the reference blit
(machine.Juno.blit, MAME's blitter_w) on random pictures.

    python sprite_test.py [cases] [--seed N]

Each case: a random picture (sparse random pixels, so every pixel the blit leaves shows), a blit with a source address
(a prepared image, one that has none, an unaligned one), a destination at or near every edge (the arcade's lines 0-15 and
240-255 are not shown, x > 240 wraps into the next row: the slow path), copy or erase, all 16 shifts (the destination
row's low 4 bits).  The Blitter's work is compared on the whole picture, so a pixel outside the blit or in the bands
shows too.  Every blit's passes are short HOG passes (the simulator reports them with BLIT_STATS=256).
"""
from pathlib import Path
import argparse
import random
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
import numpy as np
from machine68k import Register as R
from sim import Sim
from machine import Juno
from paths import ROOT, build_dir
from logic_test import picture, expected
import pickle
import glob

BUILD = build_dir('junofrst')


def planar(pic):
    """pens [256 lines, 224] -> the 40,960 bytes of vram (160 bytes a line, the picture from byte 24)"""
    out = np.zeros((256, 160), np.uint8)
    for g in range(14):
        for j in range(4):
            w = np.zeros(256, np.uint16)
            for k in range(16):
                w |= ((pic[:, g * 16 + k] >> j) & 1).astype(np.uint16) << (15 - k)
            out[:, 24 + g * 8 + 2 * j] = w >> 8
            out[:, 24 + g * 8 + 2 * j + 1] = w & 255
    return out.tobytes()


def arcade_video(pic):
    """the picture -> the reference's video RAM (rows 16-239 set; the other rows 0)"""
    px = np.zeros((256, 256), np.uint8)
    px[16:240, :] = pic.T[:, ::-1]                      # [y, x]: x = 255 - line
    mem = bytearray(0x10000)
    v = np.zeros((256, 128), np.uint8)
    v[:] = px[:, 0::2] | (px[:, 1::2] << 4)
    mem[0:0x8000] = v.tobytes()
    return mem


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cases', nargs='?', type=int, default=400)
    ap.add_argument('--seed', type=int, default=1)
    args = ap.parse_args()
    rnd = random.Random(args.seed)
    run = ROOT / 'run' / 'junofrst_sim'
    s = Sim(str(run / 'JUNOFRST.PRG'), run_dir=run, ram_kib=16384)
    sym = {k: v + s.base for k, v in s.symbols(BUILD / 'junofrst_sim.map').items()}
    mem, cpu = s.mem, s.cpu
    m = Juno()
    m.blits = None
    seen = set()
    for f in glob.glob(str(BUILD / 'cover[0-9]*.pkl')):
        seen |= {src for (src, copy) in pickle.loads(open(f, 'rb').read())['blits']}
    seen = sorted(seen)
    rom_nibbles = 0xC000
    ret = sym['sim_render_ret']

    def call(label):
        sp = cpu.r_reg(R.A7) - 4
        mem.w32(sp, ret)
        cpu.w_reg(R.A7, sp)
        cpu.w_pc(sym[label])
        for _ in range(200000):
            cpu.execute(200)
            if cpu.r_pc() == ret:
                cpu.w_reg(R.A7, sp + 4)
                return
        raise RuntimeError('%s did not return' % label)

    # the program's start (the registers and stack set up): run to the first idle wait like logic_test
    cpu.w_pc(s.base + 0x100 if False else cpu.r_pc())
    ys = [0, 1, 15, 16, 17, 31, 32, 100, 207, 208, 223, 224, 225, 238, 239, 240, 241, 255]
    bad = 0
    changed = 0
    for case in range(args.cases):
        pic = np.where(np.random.RandomState(rnd.randrange(1 << 30)).rand(256, 224) < 0.35,
                       np.random.RandomState(rnd.randrange(1 << 30)).randint(1, 16, (256, 224)), 0).astype(np.uint8)
        kind = rnd.random()
        if kind < 0.75:
            src = rnd.choice(seen)
        elif kind < 0.9:
            src = rnd.randrange(0, 0xC000 // 4) * 4          # any address (most have no image)
        else:
            src = rnd.randrange(0xC000, 0x10000) & ~3        # beyond the ROM: transparent
        y0 = rnd.choice(ys) if rnd.random() < 0.7 else rnd.randrange(256)
        x0 = rnd.choice([0, 1, 2, 100, 239, 240, 241, 250, 255]) if rnd.random() < 0.3 else rnd.randrange(256)
        copy = rnd.randrange(2)
        dest = (y0 << 8) | x0
        reg = [dest >> 8, dest & 255, (src | copy) >> 8, (src | copy) & 255]
        ref = Juno()
        ref.blits = None
        ref.mem[:] = arcade_video(pic)
        ref.blt = list(reg)
        ref.blit()
        mem.w_block(sym['vram'], planar(pic))
        for i, v in enumerate(reg):
            mem.w8(sym['jf_blt'] + i, v)
        call('blit_run')
        got = picture(bytes(mem.r_block(sym['vram'], 256 * 160)))
        want = expected(ref.mem)
        # (the arcade's rows 0-15 and 240-255 are not kept: expected() takes rows 16-239 of the reference)
        n = int((got != want).sum())
        changed += int((want != picture(planar(pic))).any())
        if n:
            bad += 1
            ys_, xs_ = np.nonzero(got != want)
            print('case %d: src %04X dest y %d x %d copy %d: %d pixels differ (lines %d-%d, columns %d-%d)' % (
                case, src, y0, x0, copy, n, ys_.min(), ys_.max(), xs_.min(), xs_.max()))
            if bad >= 8:
                break
    print('%d of the cases changed the picture' % changed)
    print('%s: %d cases (prepared sources, others, beyond the ROM; edges, wrap, copy and erase)' % (
        'PASS' if not bad else 'FAIL', args.cases))
    return int(bad != 0)


if __name__ == '__main__':
    sys.exit(main())
