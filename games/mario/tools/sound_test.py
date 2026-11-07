"""The STE sound driver (src/sound.s, run/mario_sim on Musashi) against the game's commands.

    python sound_test.py [frames] [--seed N]

The logic runs in lock-step with the reference (render_test.Harness); per arcade frame the reference's writes to $7E00
and $7F00-$7F07 (its state at the frame's end) give the clip the driver must have started: a changed non-zero tune
number with a clip, a rising edge of an effect's bit 0, the newest wins.  The DMA frame start registers of the simulator
must then name that clip (the driver runs one frame behind the NMI that wrote the commands).
"""
from pathlib import Path
import argparse
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
import render_test as rt


def dma_start(h):
    io = h.s.io
    return (io[0x903] << 16) | (io[0x905] << 8) | io[0x907]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=3000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--tag', default='mario_sim')
    a = ap.parse_args()
    h = rt.Harness(a.seed, a.tag)
    mem, sym = h.mem, h.sym
    base = sym['mm_sound']
    tunes = [(mem.r32(sym['sound_tunes'] + 8 * n), mem.r32(sym['sound_tunes'] + 8 * n + 4)) for n in range(40)]
    fx = [(mem.r32(sym['sound_fx'] + 8 * n), mem.r32(sym['sound_fx'] + 8 * n + 4)) for n in range(8)]
    state = {}                          # address -> the value at the last frame's end
    expect, started, checked, bad = {None}, 0, 0, 0
    seen = 0
    for f in range(a.frames):
        h.frame()
        # the 68k side of frame f played the commands of the frames before it: the reference's log up to f - 1
        batch = {}
        for fr, ad, v in h.m.sound_log[seen:]:
            batch[ad] = v
        seen = len(h.m.sound_log)
        # (the log now holds frame f's writes too: the driver sees them one frame later)
        if f:
            new = set()                  # (the commands of one frame: the driver takes the tune first, then the effects)
            for ad, v in pending.items():
                old = state.get(ad, 0)
                if ad == 0x7E00:
                    if v != old and v < 40 and tunes[v][1]:
                        new.add(tunes[v][0])
                        started += 1
                elif 0x7F00 <= ad <= 0x7F07:
                    n = ad - 0x7F00
                    if (v & 1) and not (old & 1) and fx[n][1]:
                        new.add(fx[n][0])
                        started += 1
                state[ad] = v
            if new:
                expect = new
            if expect != {None}:
                checked += 1
                got = dma_start(h) - base
                if got not in expect:
                    bad += 1
                    print('frame %d: DMA start %d, expected one of %s' % (f, got, sorted(expect)))
        pending = batch
    print('%s: %d clips started, %d frames checked (seed %d), %d differ' % ('PASS' if not bad else 'FAIL', started, checked, a.seed, bad))
    return int(bool(bad))


if __name__ == '__main__':
    sys.exit(main())
