"""The STE's sound player (src/sound.s on Musashi: the translated driver, the SN register files, the YM mix-down) against
its model (tools/sound.py STEBoard), every arcade frame of a game run.

    python sound_test.py [frames] [--seed N] [--tag mikie_sim] [--random]

The build: python tools/build.py --sim.  The game runs as in render_test.py (seeds as ref/cover.py; the drawing is
switched off); each frame the commands of the frame before go to the model (the runtime runs snd_frame before the IRQ that
writes the next ones), and must be equal: the sound RAM $4000-$43FF (but the dead stack below SP), both SN chips' registers,
the YM's registers (snd_ym_cache) and its channel choice, the schedule's time.  --random: random commands (ref/cover_sound.py
random_commands) added to the game's own, put into the player's ring before the frame.
"""
from pathlib import Path
import argparse
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'ref'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
from sound import STEBoard


def s32(v):
    return v - (1 << 32) if v & 0x80000000 else v


def main():
    from render_test import Harness
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=3000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--tag', default='mikie_sim')
    ap.add_argument('--random', action='store_true')
    args = ap.parse_args()
    h = Harness(args.seed, tag=args.tag)
    mem, sym = h.mem, h.sym
    mem.w16(sym['render_frame'], 0x4e75)          # (no drawing)
    g = sym['snd_g'] + 0x8000                     # (the sound CPU's address 0)
    b = STEBoard()
    if args.random:
        from cover_sound import random_commands
        rc = random_commands(100 + args.seed, args.frames + 1)
    prev = []
    n0 = len(h.m.sound_log)
    writes = 0
    cmds = 0
    for f in range(args.frames):
        if args.random:                           # (the player's ring: the commands for the next frame's snd_frame)
            for v in rc[f]:
                head = mem.r8(sym['snd_head'])
                mem.w8(sym['snd_ring'] + head, v)
                mem.w8(sym['snd_head'], (head + 1) & 255)
        h.frame()
        if args.random:                           # (the game's own commands of the frame before, then the random ones)
            prev = prev + rc[f]
        b.run_frame(prev)
        last = prev
        prev = [v for fr, v in h.m.sound_log[n0:]]
        cmds += len(prev)
        n0 = len(h.m.sound_log)
        ram = bytes(mem.r_block(g + 0x4000, 0x400))
        live = [i for i in range(0x400) if not 0x4300 <= 0x4000 + i < b.cpu.sp]
        if any(ram[i] != b.mem[0x4000 + i] for i in live):
            d = [(hex(0x4000 + i), ram[i], b.mem[0x4000 + i]) for i in live if ram[i] != b.mem[0x4000 + i]]
            raise RuntimeError('frame %d: sound RAM (address, STE, model) %s; commands %s' % (f, d[:10], last))
        for c in (0, 1):
            sn = [mem.r16(sym['snd_sn'] + 18 * c + 2 * i) for i in range(8)]
            if sn != b.sn[c].reg:
                raise RuntimeError('frame %d: SN%d registers %s, model %s; commands %s' % (f, c + 1, sn, b.sn[c].reg,
                                                                                         last))
        ym = list(mem.r_block(sym['snd_ym_cache'], 11))
        if ym != b.ym.cache[:11]:
            raise RuntimeError('frame %d: YM registers %s, model %s' % (f, ym, b.ym.cache[:11]))
        ch = [x if x < 128 else x - 256 for x in mem.r_block(sym['snd_ymch'], 3)]
        if ch != b.ym.ch:
            raise RuntimeError('frame %d: YM channels %s, model %s' % (f, ch, b.ym.ch))
        if s32(mem.r32(sym['snd_acc'])) != b.acc:
            raise RuntimeError('frame %d: time %d, model %d' % (f, s32(mem.r32(sym['snd_acc'])), b.acc))
        writes += len(b.ym_log[-1])
        if f % 1000 == 999:
            print('%d frames equal' % (f + 1), flush=True)
    if b.odd:
        print('model: unexpected accesses', sorted(set(b.odd))[:10])
    print('PASS: %d frames (seed %d%s): sound RAM, both SN chips, YM registers and channels, time equal; %d commands, '
          '%d YM writes' % (args.frames, args.seed, ', random commands' if args.random else '', cmds, writes))


if __name__ == '__main__':
    main()
