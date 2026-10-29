"""Kung-Fu Master's sound board: the model (tools/sound.py) against MAME 0.289.

    python ref/mame_sound_kungfum.py [frames] [--keep DIR] [--play]

MAME (ref/mame_sound.lua) logs, frame by frame, the M6803's writes to its port registers ($00-$03: the two AYs'
buses), the IRQ acknowledge and the ADPCM nibbles ($0800-$0802), and the main CPU's sound commands with the beam's
line.  The model runs from power-on with the same commands at the same moments (frame + line / 284) and logs the same
writes; compared frame by frame (the writes in order, and the AY register writes they make) and as one stream (a
write near a frame's end may fall into the other frame: MAME's frame_done comes while the 6803's slice runs).
--play: MAME plays (Lua sets the inputs: a coin, start, walking left with punches and kicks).
"""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'tools'), str(Path(__file__).resolve().parents[3] / 'engine')]
import mamewin                       # (MAME runs minimized)
import sound
from paths import ROMS

LUA = Path(__file__).resolve().parent / 'mame_sound.lua'


def run_mame(frames, keep=None, play=False):
    out = Path(keep) if keep else Path(tempfile.mkdtemp(prefix='mame_kfsnd_'))
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'sound.txt').exists() and keep:
        return out
    env = dict(os.environ, OUT=str(out), FRAMES=str(frames), PLAY='1' if play else '0')
    with (out / 'mame.log').open('w') as log:
        mamewin.run([shutil.which('mame'), 'kungfum', '-rompath', str(ROMS), '-window', '-sound', 'none',
                        '-nothrottle', '-seconds_to_run', '250', '-skip_gameinfo', '-autoboot_script', str(LUA)],
                       cwd=out, env=env, stdout=log, stderr=log, timeout=3000)
    return out


def parse(path):
    """-> {frame: [(kind, addr, value)]}, [(frame, beam, command)]"""
    per, cmds = {}, []
    for line in path.read_text().splitlines():
        p = line.split()
        f, kind, a, v = int(p[0]), p[1], int(p[2]), int(p[3])
        if kind == 'c':
            cmds.append((f, float(p[4]), v))
        else:
            per.setdefault(f, []).append((kind, a, v))
    return per, cmds


def ay_stream(writes):
    """the AY register writes a list of port writes makes (the board's latch protocol): [(chip, reg, value)]"""
    ddr = [0, 0]
    data = [0, 0]
    port2 = 0
    addr = [0, 0]
    out = []
    for kind, a, v in writes:
        if kind != 'p':
            continue
        if a < 2:
            ddr[a] = v
            continue
        data[a - 2] = v
        p1 = (data[0] & ddr[0]) | (~ddr[0] & 0xFF)
        new = (data[1] & ddr[1]) | (~ddr[1] & 0xFF)
        if a == 3:
            if port2 & 1 and not new & 1:
                for chip, bit in ((0, 8), (1, 16)):
                    if port2 & bit:
                        if port2 & 4:
                            addr[chip] = p1 & 15
                        else:
                            out.append((chip, addr[chip], p1))
            port2 = new
    return out


class Logged(sound.Board):
    def __init__(self):
        self.log = []
        super().__init__()
        cpu = self.cpu
        wr0 = cpu.wr

        def wr(a, v):
            a &= 0xFFFF
            if a < 4:
                self.log.append(('p', a, v & 0xFF))
            elif a in (0x0800, 0x0801, 0x0802):
                self.log.append(('m', a & 3, v & 0xFF))
            return wr0(a, v)
        cpu.wr = wr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=600)
    ap.add_argument('--keep')
    ap.add_argument('--play', action='store_true', help='MAME plays: coin, start, walking left and fighting (Lua)')
    ap.add_argument('--show', type=int, default=0, help='print the first differing frame\'s writes')
    ap.add_argument('--beam', action='store_true', help='the commands at the lines MAME logged, not at the reference '
                    'machine\'s exact times')
    args = ap.parse_args()
    d = run_mame(args.frames, args.keep, args.play)
    per, cmds = parse(d / 'sound.txt')
    b = Logged()
    fe = sound.FRAME_E
    if not args.beam:
        # the commands' exact times: the reference main board (machine.KungFuMaster, MAME's schedule) with the inputs
        # of mame_sound.lua; its commands must be MAME's
        from machine import KungFuMaster, AS
        km = KungFuMaster()
        km.sound_times = []
        for k in range(args.frames):
            km.system, km.p1 = 0xFF, 0xFF
            if args.play:
                km.system &= ~(0x08 if 700 <= k < 704 else 0) & ~(0x01 if 760 <= k < 764 else 0)
                if k > 900:
                    km.p1 &= ~((0x02 if k % 200 < 150 else 0) | (0x80 if k % 8 < 3 else 0) |
                               (0x20 if k % 50 > 44 else 0))
            km.run_frame()
        exact = [(t * sound.E_HZ / AS, v) for t, v in km.sound_times]
        mine = [v for t, v in exact if 1 * fe <= t]
        theirs = [v for _, _, v in cmds]
        print('commands: %d, MAME %d, %s' % (len(mine), len(theirs), 'equal' if mine == theirs[:len(mine)] and
                                                  len(mine) >= len(theirs) - 2 else 'DIFFERENT'))
        cmds = [(int(t // fe), None, v, t) for t, v in exact if t >= fe]
    ci = 0
    same = differ = ay_same = 0
    first = None
    all_mine, all_theirs = [], []
    b.run(fe - b.cpu.cycles)                  # (frame 0: MAME's taps come at its end)
    b.log = []
    for f in range(1, args.frames - 1):
        # the writes labelled f are the ones between frame_done f and f + 1 (MAME's frame_done N is at time N
        # frames): the model's time f .. f + 1 frames
        end = (f + 1) * fe
        while ci < len(cmds) and cmds[ci][0] == f:
            if args.beam:
                cf, beam, v = cmds[ci]
                t = f * fe + ((beam - 256) % 284) / 284 * fe     # (the frame starts at the VBLANK, line 256)
            else:
                cf, beam, v, t = cmds[ci]
            b.command_at(t, v)
            ci += 1
        b.run(end - b.cpu.cycles)
        mine, theirs = b.log, per.get(f, [])
        all_mine += mine
        all_theirs += theirs
        b.log = []
        if mine == theirs:
            same += 1
        else:
            differ += 1
            if first is None:
                first = (f, mine, theirs)
        ay_same += ay_stream(mine) == ay_stream(theirs)
    print('frames 1-%d: %d with the port writes equal, %d differ; the AY register writes equal in %d' % (
        args.frames - 2, same, differ, ay_same))
    n = next((i for i, (x, y) in enumerate(zip(all_mine, all_theirs)) if x != y), min(len(all_mine), len(all_theirs)))
    print('the whole stream: %d writes, MAME %d; equal up to %d%s' % (len(all_mine), len(all_theirs), n,
          ' (all)' if n == len(all_mine) == len(all_theirs) else ''))
    if first and args.show:
        f, mine, theirs = first
        print('first difference: frame %d (%d writes, MAME %d)' % (f, len(mine), len(theirs)))
        for i, (x, y) in enumerate(zip(mine, theirs)):
            if x != y:
                print(' at %d: model %s, MAME %s' % (i, mine[i:i + 6], theirs[i:i + 6]))
                break
    print('MAME log in', d)


if __name__ == '__main__':
    main()
