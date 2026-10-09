"""Seeded main-Z80 code, bank-window read, and mapped-write coverage."""
import pickle
import random
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from machine import Game1943
from paths import build_dir


def main():
    seed = int(sys.argv[1]) if len(sys.argv)>1 else 1
    frames = int(sys.argv[2]) if len(sys.argv)>2 else 20000
    rng = random.Random(seed)
    m = Game1943()
    pcs, reads, writes = set(), set(), set()
    site = [(-1, 0)]
    old_step, old_read, old_write = m.cpu.step, m.rd8, m.wr8
    def step():
        pc = m.cpu.pc
        site[0] = (m.bank if 0x8000 <= pc < 0xc000 else -1, pc)
        pcs.add(site[0])
        return old_step()
    def read(addr):
        if 0x8000 <= addr < 0xc000: reads.add(site[0])
        return old_read(addr)
    def write(addr, value):
        if addr in (0xc800,0xc804,0xc806,0xc807,0xd806): writes.add((*site[0],addr))
        return old_write(addr,value)
    m.cpu.step, m.cpu.rd8, m.cpu.wr8 = step, read, write
    for frame in range(frames):
        if frame >= 700:
            m.inputs[0] = 255 & ~(64 if frame%180 < 5 else 0) & ~(1 if frame%120 < 5 else 0)
            if frame%30 == 0: m.inputs[1] = 255 ^ rng.choice([0,1,2,4,8,16,32,17,18,20,24])
        m.run_frame()
        if frame%500 == 0: print(f'frame {frame}: {len(pcs)} bank/PC pairs',flush=True)
    out = build_dir('1943') / f'cover{seed}.pkl'
    with out.open('wb') as f:
        pickle.dump(dict(pcs=pcs,wread=reads,writes=writes,seed=seed,frames=frames,set=m.set_name),f)
    print(out)


if __name__ == '__main__': main()
