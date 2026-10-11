"""Collect bank-aware main-Z80 coverage with reproducible random controls.

Seeds 4-11 play with cheats so that every stage is covered: the game starts at stage seed-4 (the stage number $F3A1,
forced while the game sets up), the lives ($F3A0) stay at 3, and the play mixes walking right with random moves
(ladders, jumps, turns).  Code reached only in later stages (object scripts in the banks) is otherwise missed: the
runtime stops at z80_badpc there.
"""
import pickle
import random
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from machine import BlackTiger
from paths import build_dir


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    walk = "--walk" in sys.argv[3:]
    stage = seed - 4 if 4 <= seed <= 11 else None    # (cheats: see above)
    auto = "--auto" in sys.argv[3:]     # the AUTOPLAY schedule of tools/bench.sh (period 3000 ticks)
    from logic_test import inputs
    rng = random.Random(seed)
    m = BlackTiger()
    seen = set()
    wread = set()
    original_read = m.rd8
    site = [(-1, 0)]

    def rd8(a):
        if 0x8000 <= a < 0xd000:         # the banked window and the background bank: the sites gen.py guards
            wread.add(site[0])
        return original_read(a)

    m.cpu.rd8 = rd8
    wwrite = set()                       # the sites that write the background bank (gen.py guards them: bg_note)
    original_write = m.cpu.wr8

    def wr8_bg(a, v):
        if 0xc000 <= a < 0xd000:
            wwrite.add(site[0])
        return original_write(a, v)

    m.cpu.wr8 = wr8_bg
    original = m.cpu.step

    fresh = []                           # (the pairs first seen in the current frame)

    def step():
        pc = m.cpu.pc
        site[0] = (m.bank if 0x8000 <= pc < 0xc000 else -1, pc)
        if site[0] not in seen:
            seen.add(site[0])
            fresh.append(site[0])
        return original()

    m.cpu.step = step
    if stage is not None:
        write0 = m.cpu.wr8
        setup = [True]

        def wr8(a, v):
            if setup[0] and a == 0xf3a1:
                v = stage                # the stage the game sets up
            return write0(a, v)

        m.cpu.wr8 = wr8
    for frame in range(frames):
        if stage is not None:
            m.inputs[:3] = inputs(frame) if frame < 1000 else m.inputs[:3]      # (a coin at 900, the start at 940)
            if frame == 1060:
                setup[0] = False
            if frame >= 1000:
                m.mem[0xf3a0] = 3        # the lives
                if frame % 30 == 0:
                    if rng.random() < 0.6:
                        m.inputs[1] = 255 ^ 1 ^ 16 ^ (32 if rng.random() < 0.3 else 0)
                    else:
                        m.inputs[1] = 0xff ^ rng.choice([0, 1, 2, 4, 8, 16, 32, 17, 33, 18, 34, 9, 5])
            fresh.clear()
            try:
                m.run_frame_port()
            except RuntimeError as e:
                # (a state the cheats made can send the CPU astray: that frame's new pairs are not code)
                seen.difference_update(fresh)
                print(f'stage {stage} frame {frame}: {e}; stopped, {len(fresh)} pairs of the frame dropped', flush=True)
                break
            if frame % 1000 == 0:
                print(f'stage {stage} frame {frame}: {len(seen)} bank/PC pairs, stage now {m.mem[0xf3a1]}', flush=True)
            continue
        if frame > 700 and frame % 30 == 0:
            m.inputs[0] = 0xff & ~(0x40 if frame % 180 == 0 else 0) & ~(1 if frame % 120 == 0 else 0)
            m.inputs[1] = 0xff ^ rng.choice([0, 1, 2, 4, 8, 16, 32, 17, 33, 18, 34])
        if walk:
            m.inputs[:3] = inputs(frame)
            if frame >= 1000:
                m.inputs[1] = 255 ^ 1 ^ 16 ^ (32 if frame%90<15 else 0)
        if auto:
            t = (frame + 1) % 3000
            m.inputs[0] = 0xff & ~(0x40 if 900 <= t < 905 else 0) & ~(1 if 940 <= t < 945 else 0)
            m.inputs[1] = 255 ^ 1 ^ 16 ^ (32 if t % 90 < 15 else 0) if t >= 1000 else 255
        m.run_frame_port()
        if frame % 1000 == 0:
            print(f'frame {frame}: {len(seen)} bank/PC pairs', flush=True)
    output = build_dir('blktiger') / ('cover_auto.pkl' if auto else 'cover_walk.pkl' if walk else f'cover{seed}.pkl')
    with output.open('wb') as f:
        pickle.dump({'pcs': seen, 'wread': wread, 'wwrite': wwrite, 'bg_sites': True, 'io': m.io_log, 'seed': seed,
                     'frames': frames}, f)
    print(output)


if __name__ == '__main__':
    main()
