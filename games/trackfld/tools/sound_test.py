"""The STE's sound player (src/sound.s on Musashi: the translated driver, the SN register file, the YM mix-down, the
VLM's and the tunes' DMA requests) against its model (tools/sound.py STEBoard), every arcade frame of a game run.
Hyper Sports' tools/sound_test.py runs the same with its harness (run()).

    python sound_test.py [frames] [--seed N] [--tag trackfld_sim]

The build: python tools/build.py --sim.  The game runs as in render_test.py (seeds as ref/cover.py); each frame the
commands of the frame before go to the model (the runtime runs snd_frame before the IRQ that writes the next ones), and
must be equal: the sound RAM $4000-$43FF (Hyper Sports $4000-$4FFF; but the dead stack below SP), the SN's registers,
the YM's registers (snd_ym_cache) and its channel choice, the schedule's time, the VLM's busy time and the DMA's last
request (a phrase, a tune, a stop).
"""
from pathlib import Path
import argparse
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'ref'),
                str(Path(__file__).resolve().parents[3] / 'engine')]
from sound import STEBoard

KIND = {'phrase': 1, 'tune': 2, 'stop': 3}


def s32(v):
    return v - (1 << 32) if v & 0x80000000 else v


def run(game, h, frames, seed, ram_end):
    mem, sym = h.mem, h.sym
    g = sym['snd_g'] + 0x8000                 # (the sound CPU's address 0)
    b = STEBoard(game)
    prev = [v for f, v in h.m.sound_log if f < 0]
    n0 = len(h.m.sound_log)
    writes = phrases = 0
    tunes = set()
    for f in range(frames):
        h.frame()
        ev0 = len(b.events)
        b.run_frame(prev)
        last = prev
        prev = [v for fr, v in h.m.sound_log[n0:]]
        n0 = len(h.m.sound_log)
        ram = bytes(mem.r_block(g + 0x4000, ram_end - 0x4000))
        live = [i for i in range(ram_end - 0x4000) if not 0x4300 <= 0x4000 + i < b.cpu.sp]
        if any(ram[i] != b.mem[0x4000 + i] for i in live):
            d = [(hex(0x4000 + i), ram[i], b.mem[0x4000 + i]) for i in live if ram[i] != b.mem[0x4000 + i]]
            raise RuntimeError('frame %d: sound RAM (address, STE, model) %s; commands %s' % (f, d[:10], last))
        sn = [mem.r16(sym['snd_sn'] + 2 * i) for i in range(8)]
        if sn != b.sn.reg:
            raise RuntimeError('frame %d: SN registers %s, model %s; commands %s' % (f, sn, b.sn.reg, last))
        ym = list(mem.r_block(sym['snd_ym_cache'], 11))
        if ym != b.ym.cache[:11]:
            raise RuntimeError('frame %d: YM registers %s, model %s' % (f, ym, b.ym.cache[:11]))
        ch = [x if x < 128 else x - 256 for x in mem.r_block(sym['snd_ymch'], 3)]
        if ch != b.ym.ch:
            raise RuntimeError('frame %d: YM channels %s, model %s' % (f, ch, b.ym.ch))
        acc, busy = s32(mem.r32(sym['snd_acc'])), s32(mem.r32(sym['snd_busy']))
        if (acc, busy) != (b.acc, b.busy):
            raise RuntimeError('frame %d: time %d, busy %d; model %d, %d; commands %s' % (f, acc, busy, b.acc, b.busy,
                                                                                         last))
        ev = b.events[ev0:]
        if ev:
            want = KIND[ev[-1][1]] << 8 | (ev[-1][2] if ev[-1][1] != 'stop' else 0)
            got = mem.r16(sym['snd_dma_last'])
            if got != want:
                raise RuntimeError('frame %d: the DMA request %04X, model %04X (%s)' % (f, got, want, ev))
            phrases += sum(1 for e in ev if e[1] == 'phrase')
            tunes |= {e[2] for e in ev if e[1] == 'tune'}
        writes += len(b.ym_log[-1])
        if f % 1000 == 999:
            print('%d frames equal' % (f + 1), flush=True)
    if b.odd:
        print('model: unexpected accesses', sorted(set(b.odd))[:10])
    n = sum(1 for fr, v in h.m.sound_log if fr < frames - 1)
    print('PASS: %d frames (seed %d): sound RAM, SN and YM registers, YM channels, time, VLM busy and DMA requests '
          'equal; %d commands, %d YM writes, %d phrases, tunes %s' % (frames, seed, n, writes, phrases, sorted(tunes)))


def main():
    from render_test import Harness
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=3000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--tag', default='trackfld_sim')
    args = ap.parse_args()
    run('trackfld', Harness(args.seed, tag=args.tag), args.frames, args.seed, 0x4400)


if __name__ == '__main__':
    main()
