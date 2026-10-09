"""Seeded main-Z80 code, bank-window read, and mapped-write coverage.

    cover.py seed [frames]

Seeds 1-3: random play on the arcade schedule (run_frame).  The rest run the port's schedule (run_frame_port):
seed 4 the attract mode alone (no coin), seed 5 logic_test.py's default inputs, seeds 6-20 random play with MAME's
cheats (1943.xml: infinite energy F206, invincibility F214, "select next level" E450 = seed - 6 while the game
starts), one stage each.
"""
import pickle
import random
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from machine import Game1943
from paths import build_dir

CHEAT_SEEDS = range(6, 21)


def main():
    seed = int(sys.argv[1]) if len(sys.argv)>1 else 1
    frames = int(sys.argv[2]) if len(sys.argv)>2 else 20000
    rng = random.Random(seed)
    m = Game1943()
    pcs, reads, writes, twrites = set(), set(), set(), set()
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
        if 0xd000 <= addr < 0xd800: twrites.add(site[0])     # (the character RAM's writers: gen.py's chr_written)
        return old_write(addr,value)
    m.cpu.step, m.cpu.rd8, m.cpu.wr8 = step, read, write
    port = seed >= 4
    if port:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
        from logic_test import inputs
    for frame in range(frames):
        if seed == 5:
            m.inputs[:3] = inputs(frame)
        elif seed != 4 and frame >= 700:
            m.inputs[0] = 255 & ~(64 if frame%180 < 5 else 0) & ~(1 if frame%120 < 5 else 0)
            if frame%30 == 0: m.inputs[1] = 255 ^ rng.choice([0,1,2,4,8,16,32,17,18,20,24,33,34])
        if seed in CHEAT_SEEDS:
            if 700 <= frame < 1100:
                m.mem[0xe450] = seed - 6
            m.mem[0xf206] = 0x40
            m.mem[0xf214] = 2
        m.run_frame_port() if port else m.run_frame()
        if frame%500 == 0: print(f'frame {frame}: {len(pcs)} bank/PC pairs',flush=True)
    out = build_dir('1943') / f'cover{seed}.pkl'
    with out.open('wb') as f:
        pickle.dump(dict(pcs=pcs,wread=reads,writes=writes,twrites=twrites,seed=seed,frames=frames,set=m.set_name),f)
    print(out)


if __name__ == '__main__': main()
