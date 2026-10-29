"""The STE build's sound (run/pacman_sim on Musashi) against tools/sound.py:

1. a played game (render_test.Harness: the reference's port schedule, ref/cover.py's inputs and cheats): after each
   arcade frame the YM's registers 0-10 as snd_update wrote them (snd_ym) must be ym_image of the WSG registers and the
   sound enable the reference had when that frame began (snd_update runs as the frame is delivered);
2. snd_update alone on random WSG registers and enables, against ym_image.

    python sound_test.py [frames] [--seed N]
"""
from pathlib import Path
import argparse
import collections
import random
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'ref'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
from machine68k import Register as R
from render_test import Harness
import sound


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=3000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--random', type=int, default=2000, help='random register sets for snd_update alone')
    args = ap.parse_args()
    h = Harness(args.seed)
    m, mem, sym = h.m, h.mem, h.sym
    voices = collections.Counter()
    for f in range(args.frames):
        regs, enable = bytes(m.sound), m.latch[1]
        h.frame()
        want = sound.ym_image(regs, enable)
        got = list(mem.r_block(sym['snd_ym'], 11))
        if got != want:
            raise SystemExit('FAIL frame %d: YM %s, model %s (WSG %s, enable %d)' % (f, got, want, regs.hex(), enable))
        voices[sum(1 for ch in range(3) if want[8 + ch])] += 1
    print('game: %d frames, the YM as the model every frame; frames by voices sounding: %s' % (
        args.frames, dict(sorted(voices.items()))))
    # snd_update alone
    rnd = random.Random(args.seed)
    cpu = h.cpu
    for k in range(args.random):
        regs = bytes(rnd.randrange(256) if rnd.randrange(4) else rnd.randrange(16) for _ in range(32))
        enable = rnd.randrange(4) != 0
        mem.w_block(h.addr(0x5040), regs)
        mem.w8(h.addr(0x5001), int(enable) | (rnd.randrange(128) << 1))
        a7 = cpu.r_reg(R.A7)
        sp = a7 - 64
        mem.w32(sp, sym['sim_render_ret'])
        cpu.w_reg(R.A7, sp)
        cpu.w_pc(sym['snd_update'])
        h.run_to({sym['sim_render_ret']})
        cpu.w_reg(R.A7, a7)
        want = sound.ym_image(regs, int(enable))
        got = list(mem.r_block(sym['snd_ym'], 11))
        if got != want:
            raise SystemExit('FAIL random set %d: YM %s, model %s (WSG %s, enable %d)' % (k, got, want, regs.hex(),
                                                                                      enable))
    print('PASS: %d game frames and %d random register sets: snd_update equals tools/sound.py' % (args.frames,
                                                                                               args.random))


if __name__ == '__main__':
    main()
