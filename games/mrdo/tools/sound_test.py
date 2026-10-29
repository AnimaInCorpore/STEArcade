"""The STE's sound player (src/sound.s on Musashi) against its model (tools/sound.py STESound), every arcade frame of a
game run.

    python sound_test.py [frames] [--seed N] [--tag mrdo_sim]

The game runs as in render_test.py (seeds as ref/cover.py; the reference logs the SN76489 bytes from the boot on).
The runtime runs snd_frame before each frame's IRQ, so after frame f the STE has the bytes of frames up to f - 1: the
model gets those; the two register files (snd_sn), the latches, the YM's channel choice (snd_ymch) and its registers
(snd_ym_cache) must be equal.
"""
from pathlib import Path
import argparse
import collections
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'ref'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
from render_test import Harness
from sound import STESound


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=3000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--tag', default='mrdo_sim')
    args = ap.parse_args()
    h = Harness(args.seed, tag=args.tag, sound=True)
    mem, sym = h.mem, h.sym
    b = STESound()
    byf = collections.defaultdict(list)
    done = 0                                  # (sound_log entries sorted into byf)
    writes = voices = 0
    for f in range(args.frames):
        h.frame()
        for fr, cyc, chip, v in h.m.sound_log[done:]:
            byf[fr].append((chip, v))
        done = len(h.m.sound_log)
        writes += len(b.frame(byf.pop(f - 1, [])))
        regs = [mem.r16(sym['snd_sn'] + 2 * i) for i in range(16)]
        want = b.sn[0].reg + b.sn[1].reg
        if regs != want:
            raise RuntimeError('frame %d: SN registers %s, model %s' % (f, regs, want))
        lat = list(mem.r_block(sym['snd_latch'], 2))
        if lat != [b.sn[0].latch, b.sn[1].latch]:
            raise RuntimeError('frame %d: latches %s, model %s' % (f, lat, [b.sn[0].latch, b.sn[1].latch]))
        ch = [x if x < 128 else x - 256 for x in mem.r_block(sym['snd_ymch'], 3)]
        if ch != b.ch:
            raise RuntimeError('frame %d: YM channels %s, model %s' % (f, ch, b.ch))
        ym = list(mem.r_block(sym['snd_ym_cache'], 11))
        if ym != b.cache[:11]:
            raise RuntimeError('frame %d: YM registers %s, model %s' % (f, ym, b.cache[:11]))
        voices += sum(1 for x in b.ch if x >= 0)
        if f % 1000 == 999:
            print('%d frames equal' % (f + 1), flush=True)
    print('PASS: %d frames (seed %d): SN registers, latches, YM channels and registers equal; %d SN bytes, %d YM '
          'writes, %.2f voices on the YM a frame' % (args.frames, args.seed, len(h.m.sound_log), writes,
                                                     voices / args.frames))


if __name__ == '__main__':
    main()
