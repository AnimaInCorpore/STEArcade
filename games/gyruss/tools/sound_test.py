"""The STE's sound player (src/sound.s on Musashi: the translated driver, the AY register files, the YM mix-down)
against its model (tools/sound.py STEBoard), every arcade frame of a game run.

    python sound_test.py [frames] [--seed N] [--tag gyruss_snd]

The build: python tools/build.py --sim --tag gyruss_snd (with the sound).  The game runs as in render_test.py; each
frame the commands of the frame before go to the model, and the sound RAM (but the dead stack below SP), the five AYs'
registers, the YM's registers (snd_ym_cache)
and its channel choice must equal.
"""
from pathlib import Path
import argparse
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'ref'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
from render_test import Harness
from sound import STEBoard


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=3000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--tag', default='gyruss_snd')
    args = ap.parse_args()
    h = Harness(args.seed, tag=args.tag)
    mem, sym = h.mem, h.sym
    b = STEBoard()
    prev = [v for f, v in h.m.sound_log if f < 0]
    writes = 0
    for f in range(args.frames):
        h.frame()
        b.run_frame(prev)
        last = prev
        prev = [v for fr, v in h.m.sound_log if fr == f]
        ram = bytes(mem.r_block(sym['snd_g'] + 0xE000, 0x400))
        live = [i for i in range(0x400) if not 0x6300 <= 0x6000 + i < b.cpu.sp]   # (below SP: dead; the inlined
        if any(ram[i] != b.mem[0x6000 + i] for i in live):                      # rst helpers write no return address)
            d = [(hex(0x6000 + i), ram[i], b.mem[0x6000 + i]) for i in live if ram[i] != b.mem[0x6000 + i]]
            raise RuntimeError('frame %d: sound RAM (address, STE, model) %s; commands %s' % (f, d[:10], last))
        ay = bytes(mem.r_block(sym['snd_ay'], 80))
        want = bytes(x for chip in b.ay for x in chip)
        if ay != want:
            d = [(i >> 4, i & 15, ay[i], want[i]) for i in range(80) if ay[i] != want[i]]
            raise RuntimeError('frame %d: AY registers (chip, reg, STE, model) %s' % (f, d[:8]))
        ym = bytes(mem.r_block(sym['snd_ym_cache'], 14))
        if list(ym) != b.ym.cache[:14]:
            raise RuntimeError('frame %d: YM registers %s, model %s' % (f, list(ym), b.ym.cache[:14]))
        ch = [x if x < 128 else x - 256 for x in mem.r_block(sym['snd_ymch'], 3)]
        if ch != b.ym.ch:
            raise RuntimeError('frame %d: YM channels %s, model %s' % (f, ch, b.ym.ch))
        writes += len(b.ym_log[-1])
        if f % 1000 == 999:
            print('%d frames equal' % (f + 1), flush=True)
    print('PASS: %d frames (seed %d): AY registers, YM registers and channels equal; %d YM writes, %d i8039 effects'
          % (args.frames, args.seed, writes, len(b.dac_log)))


if __name__ == '__main__':
    main()
