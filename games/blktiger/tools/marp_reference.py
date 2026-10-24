"""Play a MARP recording on the reference board (tools/machine.py, MAME's frame timing) and save its state a frame.

    python tools/marp_reference.py rec.zip out.npy [--frames N] [--shift S]

The reference runs the board's frames (the interrupt at line 240 of each 100,608-cycle frame) with frame f + shift of
the recording's inputs (tools/marp_inputs.py) during frame f.  Its highest score equal to MARP's listed one shows it
followed the recorded game as WolfMAME did, without a WolfMAME: then its states are the ground truth that
tools/marp_replay.py's port states are compared with (--compare).  About 78 frames a second (pure Python Z80).

Saved per frame (uint8): $E000-$E00F (the frame counter $E003, the random generator $E008), the score digits
$E1E8-$E1EF, lives $F3A0, stage $F3A1.
"""
import argparse
from pathlib import Path
import sys
import time

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine import BlackTiger  # noqa: E402
from marp_inputs import inp_inputs  # noqa: E402

COLS = [*range(0xe000, 0xe010), *range(0xe1e8, 0xe1f0), 0xf3a0, 0xf3a1]


def score(row):
    d = row[16:24]
    return int(''.join(map(str, d))) * 10 if (d < 10).all() else -1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('src', type=Path)
    ap.add_argument('out', type=Path)
    ap.add_argument('--frames', type=int)
    ap.add_argument('--shift', type=int, default=0)
    ap.add_argument('--mame184', action='store_true', help="MAME 0.184's timing, the recording's: a 60 Hz screen, so "
                    "100,000 cycles a frame (today's driver: 384 x 262 at 6 MHz, 100,608), the interrupt held from the frame's "
                    "start (the VBLANK at the end of the frame before, where MAME's inputs change; none before frame 0)")
    ap.add_argument('--dsw1', type=lambda v: int(v, 0), help='DSW1 (fw666 recorded $2F: no continue; the default here $6F)')
    ap.add_argument('--ram', help='first-last frame: also save $E000-$FFFF and the PC at each of these frames\' ends '
                    '(out with .ram.npz)')
    a = ap.parse_args()
    ram_lo, ram_hi = map(int, a.ram.split('-')) if a.ram else (-1, -1)
    rams, pcs = [], []
    frames = inp_inputs(a.src)
    n = min(a.frames or len(frames), len(frames) - max(a.shift, 0))
    b = BlackTiger()
    if a.dsw1 is not None:
        b.inputs[4] = a.dsw1
    cpu = b.cpu
    out = np.zeros((n, len(COLS)), np.uint8)
    t0, best = time.monotonic(), 0
    for f in range(n):
        g = max(f + a.shift, 0)
        b.inputs[0], b.inputs[1] = int(frames[g, 0]), int(frames[g, 1])
        if a.mame184:
            target = (f + 1) * 100000
            if f:                               # (the VBLANK ends each frame: frame 0, the boot, has none before it)
                b.sprites[:] = b.mem[0xfe00:]
                b.pending_irq = True
            while cpu.cycles < target:
                if b.pending_irq and not cpu.ei_delay and cpu.irq():
                    b.pending_irq = False
                cpu.ei_delay = False
                cpu.step()
            b.frame += 1
        else:
            b.run_frame()
        m = b.mem
        out[f] = [m[c] for c in COLS]
        if ram_lo <= f <= ram_hi:
            rams.append(bytes(m[0xe000:]))
            pcs.append(cpu.pc)
            if f == ram_hi:
                np.savez_compressed(a.out.with_suffix('.ram.npz'), first=ram_lo, ram=np.frombuffer(b''.join(rams), np.uint8)
                                    .reshape(len(rams), -1), pc=np.array(pcs))
                if not a.frames:
                    pass
        if f % 6000 == 5999:
            best = max(best, max(score(r) for r in out[f - 5999:f + 1]))
            print(f'frame {f + 1}: lives {out[f, -2]} stage {out[f, -1]} score {score(out[f])} best {best} '
                  f'({(f + 1) / (time.monotonic() - t0):.0f} frames/s)', flush=True)
            np.save(a.out, out[:f + 1])
    np.save(a.out, out)
    print('best score', max(score(r) for r in out))


if __name__ == '__main__':
    main()
