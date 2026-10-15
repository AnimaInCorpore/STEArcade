"""The dispatch table gen.py builds as data (z80_dispatch_sw), as the sim build loaded it: every Z80 entry (and the
interrupt token) on its label, every other address on z80_badpc."""
from pathlib import Path
import sys
sys.path[:0]=[str(Path(__file__).resolve().parents[3]/'engine')]
from sim import Sim
from machine import BUILD
from paths import ROOT
import gen


def main():
    text,em,code,missing=gen.generate()
    want=gen.entries(code,em)
    run=ROOT/'run/commando_sim';s=Sim(str(run/'COMMANDO.PRG'),run_dir=run)
    sym={k:v+s.base for k,v in s.symbols(BUILD/'commando_sim.map').items()}
    table=bytes(s.mem.r_block(sym['z80_dispatch_sw'],65536*4));bad=sym['z80_badpc'];wrong=[]
    for swapped in range(65536):
        pc=((swapped&255)<<8)|(swapped>>8)
        got=int.from_bytes(table[swapped*4:swapped*4+4],'big')
        expect=sym[want[pc]] if pc in want else bad
        if got!=expect:wrong.append(pc)
    if wrong:raise RuntimeError(f'{len(wrong)} dispatch entries wrong, first {[hex(p) for p in wrong[:8]]}')
    print(f'PASS: dispatch table: {len(want)} entries on their labels, {65536-len(want)} on z80_badpc')


if __name__=='__main__':main()
