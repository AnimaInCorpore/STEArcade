"""Compare STE Blitter output against reference pixels through the 16-colour map."""
from pathlib import Path
import sys,random,json
sys.path[:0]=[str(Path(__file__).resolve().parents[3]/'engine'),str(Path(__file__).resolve().parents[1]/'ref')]
import numpy as np
from PIL import Image
from machine68k import Register as R
from sim import Sim,TRAP1
from machine import Commando,Gfx,BUILD
from cover import inputs
from paths import ROOT

def window(mem,base):
    raw=np.frombuffer(bytes(mem.r_block(base,256*256)),np.uint8).reshape(256,256)
    area=raw[:,24:136].reshape(256,14,4,2)
    words=(area[...,0].astype(np.uint16)<<8)|area[...,1]
    out=np.zeros((256,224),np.uint8)
    for k in range(4):
        for b in range(16):out[:,b::16]|=((words[:,:,k]>>(15-b))&1).astype(np.uint8)<<k
    return out

def main():
    n=int(sys.argv[1]) if len(sys.argv)>1 else 20
    mode=sys.argv[2] if len(sys.argv)>2 else 'samples'
    run=ROOT/'run/commando_sim';s=Sim(str(run/'COMMANDO.PRG'),ram_kib=16384,run_dir=run)
    mem,cpu=s.mem,s.cpu
    sym={k:v+s.base for k,v in s.symbols(BUILD/'commando_sim.map').items()}
    mem.set_trace_mode(False)
    ret=sym['sim_render_ret'];bad=sym['z80_badpc']
    def run_to(target):
        cycles=0
        while cycles<100000000:
            result=cpu.execute(2000);cycles+=result.cycles
            pc=cpu.r_pc()
            if pc==target:return cycles
            if pc in (bad,bad+4) or s.terminated:raise RuntimeError(f'CPU stopped at {pc-s.base:06x}')
            if pc==TRAP1:s.gemdos()
        raise RuntimeError(f'CPU timeout {cpu.r_pc()-s.base:06x}')
    word=mem.r16(sym['render_frame']);mem.w16(sym['render_frame'],0x4e75)
    run_to(sym['sim_wait']);mem.w16(sym['render_frame'],word)
    m=Commando();rnd=random.Random(1)
    palette=json.loads((Path(__file__).resolve().parents[1]/'docs/palette.json').read_text())
    mapping=np.array(palette['map'],np.uint8);rgb=np.array(palette['rgb'],np.uint8)
    costs=[]
    for sample in range(n):
        target=700+sample if mode=='seq' else 100+sample*120
        while m.frame<target:
            m.inputs[:3]=inputs(m.frame,rnd);m.run_frame_port()
        if mode=='edges':
            if m.gfx is None:m.gfx=Gfx()
            empty=next(i for i,t in enumerate(m.gfx.chars) if np.all(t==3))
            m.mem[0xd000:0xd400]=bytes([empty&255])*1024
            m.mem[0xd400:0xd800]=bytes([(empty>>8)<<6])*1024
            m.sprites[:]=bytes([0,0xc0,0,0])*96
            code=next(i for i,t in enumerate(m.gfx.sprites) if np.count_nonzero(t!=15)>128)
            edge_x,edge_y=[(216,128),(-8,128),(100,-8),(100,248)][sample%4]
            raw_x=240-edge_y
            attr=(code>>8)<<6
            if raw_x<0:attr|=1
            m.sprites[:4]=bytes([code&255,attr,edge_x+16,raw_x&255])
        if mode=='scroll':
            sx=(sample*31)&511;sy=(sample*47)&511
            m.scroll[:]=bytes([sx&255,sx>>8,sy&255,sy>>8])
        block=sym['g_block']
        mem.w_block(block+0x5000,bytes(m.mem[0xd000:]))
        mem.w_block(block+0x4808,bytes(m.scroll))
        mem.w_block(sym['sprite_buffer'],bytes(m.sprites))
        sp=cpu.r_reg(R.A7)-4;mem.w32(sp,ret);cpu.w_reg(R.A7,sp);cpu.w_pc(sym['render_frame'])
        mem.set_trace_mode(True);cost=run_to(ret);mem.set_trace_mode(False)
        idx=mem.r16(sym['draw_idx']);base=mem.r32(sym['draw_base'])
        mine=window(mem,base);want=mapping[m.render_raw()[16:240].T[::-1]]
        if mode=='edges':
            raw=np.frombuffer(bytes(mem.r_block(base+edge_y*256,16*256)),np.uint8).reshape(16,32,4,2)
            words=(raw[...,0].astype(np.uint16)<<8)|raw[...,1]
            pixels=np.zeros((16,512),np.uint8)
            for k in range(4):
                for b in range(16):pixels[:,b::16]|=((words[:,:,k]>>(15-b))&1).astype(np.uint8)<<k
            sprite=m.gfx.sprites[code].T[::-1]
            got=pixels[:,48+edge_x:48+edge_x+16]
            mask=sprite!=15
            assert np.array_equal(got[mask],mapping[128+sprite][mask]), 'whole sprite was clipped in its guard area'
        diff=np.count_nonzero(mine!=want)
        if diff:
            out=BUILD/f'render_diff_{sample}.png'
            Image.fromarray(np.hstack((rgb[mine],rgb[want]))).save(out)
            positions=np.argwhere(mine!=want)[:10]
            raise RuntimeError(f'{diff} pixels differ at frame {target}, scroll {list(m.scroll)}, first {positions.tolist()}; {out}')
        mem.w16(sym['prev_idx'],mem.r16(sym['shown_idx']));mem.w16(sym['shown_idx'],idx);mem.w8(sym['frame_ready'],0)
        costs.append(cost+s.blitter.cycles);s.blitter.cycles=0
        print(f'frame {target}: exact, CPU {cost} cycles, cache misses {mem.r32(sym["cache_misses"])}',flush=True)
    print(f'PASS: {n} {mode} frames; CPU + Blitter median {int(np.median(costs))} cycles')
if __name__=='__main__':main()
