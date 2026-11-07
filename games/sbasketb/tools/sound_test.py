"""The STE sound driver (src/sound.s, run/sbasketb_sim on Musashi) against the game's commands.

    python sound_test.py [frames] [--seed N]

The logic runs in lock-step with the reference (render_test.Harness); the reference's sound log (every write of the
trigger $3D80 with the latch's value) gives, per command in order, what the driver must have done by the end of the
next frame (the driver runs before the IRQ that follows the commands' frame): 0 stops the clip, $01-$7F start that
effect's clip (looping ones repeat), $80-$FE with a clip wait as the pending phrase, $FF starts the pending phrase's clip.
The simulator's DMA registers (frame start, control) must name that clip.
"""
from pathlib import Path
import argparse
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
import render_test as rt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=3000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--tag', default='sbasketb_sim')
    a = ap.parse_args()
    h = rt.Harness(a.seed, False, a.tag)
    mem, sym, io = h.mem, h.sym, h.s.io
    base = sym['sb_sound']
    table = [(mem.r32(sym['sound_cmds'] + 12 * n), mem.r32(sym['sound_cmds'] + 12 * n + 4),
              mem.r32(sym['sound_cmds'] + 12 * n + 8)) for n in range(256)]
    seen = 0
    cur, pend = None, 0
    started = checked = bad = 0
    for f in range(a.frames):
        h.frame()
        log = h.m.sound_log
        todo = [v for fr, v in log[seen:] if fr < f]       # (frame f's own commands wait for frame f + 1's driver)
        seen += len(todo)
        for v in todo:
            if v == 0:
                cur = None
            elif v == 255:
                if pend:
                    s, e, c = table[pend]
                    cur, pend = (s, c), 0
                    started += 1
            elif v >= 128:
                if table[v][1]:
                    pend = v
            elif table[v][1]:
                cur = (table[v][0], table[v][2])
                started += 1
        got_start = (io[0x903] << 16) | (io[0x905] << 8) | io[0x907]
        got_ctl = io[0x901] & 3
        if cur is None:
            ok = got_ctl == 0 or started == 0 and got_ctl == 0
            # (stopped: the control register's play bits are 0, unless nothing was ever commanded)
        else:
            ok = got_start == base + cur[0] and got_ctl == cur[1]
        checked += 1
        if not ok:
            bad += 1
            if bad <= 5:
                print('frame %d: DMA start %06x ctl %d, expected %s' % (f, got_start, got_ctl,
                      'stopped' if cur is None else '%06x ctl %d' % (base + cur[0], cur[1])))
    print('%s: %d frames checked (seed %d), %d clip starts, %d mismatches' % ('PASS' if not bad else 'FAIL', checked,
                                                                           a.seed, started, bad))
    return int(bad != 0)


if __name__ == '__main__':
    sys.exit(main())
