"""Seeded attract/play coverage for Commando's whole-program translator."""
from pathlib import Path
import sys, random, pickle
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from machine import Commando, BUILD

def inputs(f,rnd):
    system,player=255,255
    phase=f%2400
    if 700<=phase<710:system &=127
    if 740<=phase<750:system &=254
    if phase>=780:
        player=rnd.choice([255,254,253,251,247,250,246,249,245])
        player &=~16
        if phase%90<3:player &=~32
    return system,player,255

def main():
    seed=int(sys.argv[1]) if len(sys.argv)>1 else 1
    frames=int(sys.argv[2]) if len(sys.argv)>2 else 20000
    rnd=random.Random(seed);m=Commando();m.cpu.afmask=0xc1;pcs=set();writes=set();current=0
    m.watch=lambda pc,a,v:writes.add((current,a))
    original=m.cpu.step
    def step():
        nonlocal current
        current=m.cpu.pc;pcs.add(current);return original()
    m.cpu.step=step
    for f in range(frames):
        m.inputs[:3]=inputs(f,rnd);m.run_frame_port()
    (BUILD/f'cover_{seed}.pkl').write_bytes(pickle.dumps(dict(pcs=pcs,writes=writes)))
    print(f'seed {seed}: {frames} frames, {len(pcs)} PCs, {len(writes)} write sites',flush=True)
if __name__=='__main__':main()
