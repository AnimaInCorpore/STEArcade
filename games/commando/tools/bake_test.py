"""get_object_bake (render.s) for every object the program can ask for: 65536 tile keys, the 12288 sprite shapes
(3 banks, 4 colours, 4 flips) and 65536 character keys, baked in the sim build and compared with the pixels of the
ROM through the colour map (machine.Gfx, build/commando/palmap.bin).  Tiles and characters: plane-major words (a
character's pixels in the high bytes), then a character's movep rows (the keep mask and the opaque plane bytes);
sprites: row-major in spr_order's row order (base rows; a vertically flipped image's routine takes row 15 - order[j])."""
from pathlib import Path
import sys
sys.path[:0]=[str(Path(__file__).resolve().parents[3]/'engine')]
import numpy as np
from machine68k import Register as R
from sim import Sim,TRAP1
from machine import Gfx,BUILD
from paths import ROOT


def planes(pixels,mapping):
    """(rows, width) pens -> (4, rows) STE plane words, the first pixel in the high bit of a 16 bit word"""
    colours=mapping[pixels].astype(np.uint16)
    width=pixels.shape[1]
    return np.array([sum(((colours[:,i]>>k)&1)<<(15-i) for i in range(width)) for k in range(4)],np.uint16)


def variant(t,flip):
    return t[::-1 if flip&1 else 1, ::-1 if flip&2 else 1]


def expected(g,mapping,order,kind,key):
    attr=key>>8;code=((attr&0xc0)<<2)|(key&255)
    if kind==1:
        colour,flip=(attr>>4)&3,(attr>>2)&3
        t=variant(g.sprites[code].T[::-1],flip)
        p=planes(t,mapping[128+colour*16:])
        rows=[15-b if flip&1 else b for b in order[code]]
        return p[:,rows].T.astype('>u2').tobytes()
    colour,flip=attr&15,(attr>>4)&3
    if kind==0:
        return planes(variant(g.tiles[code].T[::-1],flip),mapping[colour*8:]).astype('>u2').tobytes()
    t=variant(g.chars[code].T[::-1],flip)
    p=planes(t,mapping[192+colour*4:])
    out=bytearray(p.astype('>u2').tobytes())
    for r in range(8):
        opaque=sum(int(t[r,i]!=3)<<(7-i) for i in range(8))
        keep=(~(opaque*0x01010101))&0xffffffff
        data=sum(((int(p[k,r])>>8)&opaque)<<(24-8*k) for k in range(4))
        out+=keep.to_bytes(4,'big')+data.to_bytes(4,'big')
    return bytes(out)


def main():
    run=ROOT/'run/commando_sim';s=Sim(str(run/'COMMANDO.PRG'),ram_kib=16384,run_dir=run)
    mem,cpu=s.mem,s.cpu;mem.set_trace_mode(False)
    sym={k:v+s.base for k,v in s.symbols(BUILD/'commando_sim.map').items()}
    bad=sym['z80_badpc']
    def run_to(target):
        while True:
            cpu.execute(2000);pc=cpu.r_pc()
            if pc==target:return
            if pc in (bad,bad+4) or s.terminated:raise RuntimeError(f'CPU stopped at {pc-s.base:06x}')
            if pc==TRAP1:s.gemdos()
    mem.w16(sym['render_frame'],0x4e75);run_to(sym['sim_wait'])
    g=Gfx();mapping=np.frombuffer((BUILD/'palmap.bin').read_bytes(),np.uint8)
    order=np.frombuffer((BUILD/'spr_order.bin').read_bytes(),np.uint8).reshape(-1,16)
    ret=sym['sim_render_ret'];bake=sym['get_object_bake'];sp0=cpu.r_reg(R.A7)
    keys=[(0,k) for k in range(65536)]
    keys+=[(1,code|(attr<<8)) for attr in range(0,0xc0,4) for code in range(256)]
    keys+=[(2,k) for k in range(65536)]
    wrong=[]
    for kind,key in keys:
        mem.w32(sp0-4,ret);cpu.w_reg(R.A7,sp0-4)
        cpu.w_reg(R.D0,key);cpu.w_reg(R.D1,kind);cpu.w_pc(bake)
        run_to(ret)
        got=bytes(mem.r_block(mem.r32(sym['baked_ptr']),128))
        if got!=expected(g,mapping,order,kind,key):
            wrong.append((kind,hex(key)))
            if len(wrong)>=10:break
    if wrong:raise RuntimeError(f'baked objects differ: {wrong}')
    print(f'PASS: {len(keys)} baked objects (tiles, sprite shapes, characters) exact')


if __name__=='__main__':main()
