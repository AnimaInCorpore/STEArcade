"""Collect bank-aware main-Z80 coverage with reproducible random controls."""
import pickle
import random
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from machine import GunSmoke
from paths import build_dir


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    frames = int(sys.argv[2]) if len(sys.argv) > 2 else 20000
    rng = random.Random(seed)
    m = GunSmoke()
    seen = set()
    wread = set()
    original_read = m.rd8
    site = [(-1, 0)]

    def rd8(a):
        if 0x8000 <= a < 0xc000:
            wread.add(site[0])
        return original_read(a)

    m.cpu.rd8 = rd8
    original = m.cpu.step

    def step():
        pc = m.cpu.pc
        site[0] = (m.bank if 0x8000 <= pc < 0xc000 else -1, pc)
        seen.add(site[0])
        return original()

    m.cpu.step = step
    for frame in range(frames):
        if frame > 700 and frame % 30 == 0:
            m.inputs[0] = 0xff & ~(0x40 if frame % 180 == 0 else 0) & ~(1 if frame % 120 == 0 else 0)
            m.inputs[1] = 0xff ^ rng.choice([0, 1, 2, 4, 8, 16, 32, 17, 33, 65, 18, 34, 66])
        m.run_frame_port()
        if frame % 1000 == 0:
            print(f'frame {frame}: {len(seen)} bank/PC pairs', flush=True)
    output = build_dir('gunsmoke') / f'cover{seed}.pkl'
    with output.open('wb') as f:
        pickle.dump({'pcs': seen, 'wread': wread, 'io': m.io_log, 'seed': seed, 'frames': frames}, f)
    print(output)


if __name__ == '__main__':
    main()
