"""STE virtual-screen pixels against the reference through its 16-colour map."""
from pathlib import Path
import argparse
import sys
import numpy as np
from PIL import Image
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from sim import Sim
from machine68k import Register as R
from machine import BlackTiger
from assets import Oracle
from logic_test import inputs
from paths import ROOT, build_dir


class Renderer:
    def __init__(self):
        run=ROOT/'run'/'blktiger_sim'
        self.sim=Sim(str(run/'BLKTIGER.PRG'),ram_kib=16384,run_dir=run)
        self.mem,self.cpu=self.sim.mem,self.sim.cpu
        self.sym={k:v+self.sim.base for k,v in self.sim.symbols(build_dir('blktiger')/'blktiger_sim.map').items()}
        self.mem.set_trace_mode(False)
        self.cpu.w_reg(R.A7,self.sym['own_stack_top'])
        self.cpu.w_sr(0x2700)
        self.call('init_video')

    def call(self,name):
        sp=self.cpu.r_reg(R.A7)-4
        ret=self.sym['sim_render_ret']
        self.mem.w32(sp,ret)
        self.cpu.w_reg(R.A7,sp)
        self.cpu.w_pc(self.sym[name])
        used=0
        self.mem.set_trace_mode(True)
        while used < 100_000_000:
            result=self.cpu.execute(2000)
            used+=result.cycles
            pc=self.cpu.r_pc()
            if pc==ret:
                self.mem.set_trace_mode(False)
                return used
            if pc==self.sym['z80_badpc']:
                break
        raise RuntimeError(f'{name} stopped at {self.cpu.r_pc():06x} after {used} cycles')

    def render(self,m):
        mem,sym=self.mem,self.sym
        mem.w_block(sym['g_block']+0x5000,bytes(m.mem[0xd000:]))
        mem.w8(sym['pal_dirty'],1)        # (the game's palette writers set it)
        if bytes(m.bg)!=getattr(self,'last_bg',None):
            # (the game's bg_flush flags a changed map for the renderer)
            self.last_bg=bytes(m.bg);mem.w_block(sym['g_bg'],self.last_bg);mem.w8(sym['map_dirty'],1)
        mem.w_block(sym['bt_sprites'],bytes(m.sprites))
        for name,value in [('g_layout',m.layout),('g_control',m.control),('g_video_enable',m.video_enable)]:
            mem.w8(sym[name],value)
        mem.w_block(sym['g_scroll'],bytes(m.scroll))
        used=self.call('render_frame')
        base=mem.r32(sym['work_base'])
        y=mem.r16(sym['physical_y'])+16
        x=mem.r16(sym['physical_x'])+64
        raw=np.frombuffer(bytes(mem.r_block(base+y*384,224*384)),np.uint8).reshape(224,48,4,2)
        words=(raw[...,0].astype(np.uint16)<<8)|raw[...,1]
        pixels=np.zeros((224,768),np.uint8)
        for plane in range(4):
            for bit in range(16):
                pixels[:,bit::16]|=(((words[:,:,plane]>>(15-bit))&1).astype(np.uint8)<<plane)
        # Hardware window and extra-fetch line offset must agree with the rendered viewport.
        flip=mem.r32(sym['flip_addr'])
        expected=base+y*384+((x-32)&~15)//2
        assert flip==expected,(hex(flip),hex(expected))
        self.call('vbl_video')
        assert self.sim.io[0x265]==x&15
        assert self.sim.io[0x20f]==112-(4 if x&15 else 0)
        # The 32-pixel side margins of the 320-pixel window are black (pen 0).
        assert not pixels[:,x-32:x].any() and not pixels[:,x+256:x+288].any(),'side margins not black'
        return pixels[:,x:x+256].copy(),used


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--frames',type=int,default=12)
    ap.add_argument('--first',type=int,default=700)
    ap.add_argument('--step',type=int,default=100)
    ap.add_argument('--scroll-sweep',action='store_true')
    ap.add_argument('--flip-layout-sweep',action='store_true')
    ap.add_argument('--sprite-edges',action='store_true')
    ap.add_argument('--consecutive',action='store_true',help='draw every frame from --first on (the incremental paths), compare every --step')
    ap.add_argument('--walk',action='store_true',help="logic_test's walk: right and attack from frame 1000")
    args=ap.parse_args()
    renderer=Renderer()
    ref=BlackTiger()
    oracle=Oracle()
    last=args.first+(args.frames-1)*args.step
    for frame in range(last+1):
        values=inputs(frame)
        if args.walk and frame>=1000:
            values=values[0],255^1^16^(32 if frame%90<15 else 0),255
        ref.inputs[:3]=values
        ref.run_frame_port()
        if args.consecutive and frame>=args.first and (frame-args.first)%args.step:
            renderer.render(ref)
            continue
        if frame<args.first or (frame-args.first)%args.step:
            continue
        states=[tuple(ref.scroll)]
        if args.scroll_sweep:
            states += [(x,3,x,7) for x in [*range(16),16,239,240,255]]
        original_control, original_layout = ref.control, ref.layout
        modes=[(ref.control,ref.layout)]
        if args.flip_layout_sweep:
            modes=[((ref.control&~64)|flip,layout) for flip in (0,64) for layout in (0,1)]
        for control,layout in modes:
            ref.control,ref.layout=control,layout
            for state in states:
                ref.scroll[:]=state
                mine,cycles=renderer.render(ref)
                want=oracle.frame(ref)
                diff=np.argwhere(mine!=want)
                if len(diff):
                    path=build_dir('blktiger')/'render_diff.png'
                    Image.fromarray(np.hstack((oracle.rgb[mine],oracle.rgb[want]))).save(path)
                    print('frame',frame,'scroll',state,'diff',len(diff),'first',diff[:10].tolist(),path,flush=True)
                    return 1
                print('frame',frame,'scroll',state,'matched, cycles',cycles,flush=True)
        ref.control,ref.layout=original_control,original_layout
    if args.sprite_edges:
        original_control = ref.control
        for flip in (0,64):
            ref.control=(original_control&~64)|flip
            for shift in range(16):
                ref.scroll[0]=shift
                ref.scroll[2]=shift
                ref.sprites[:]=bytes(512)
                positions=[(-15,1),(-1,15),(0,16),(1,224),(240,239),(255,240),(128,128)]
                for i,(x,y) in enumerate(positions):
                    attr=(0x10 if x<0 else 0)|(8 if i&1 else 0)
                    ref.sprites[4*i:4*i+4]=bytes([37,attr,y,x&255])
                mine,_=renderer.render(ref)
                want=oracle.frame(ref)
                if not np.array_equal(mine,want):
                    print('edge sprite mismatch:',flip,shift,int(np.count_nonzero(mine!=want)))
                    return 1
        print('32 edge-sprite and fine-scroll combinations matched',flush=True)
    return 0


if __name__=='__main__':
    sys.exit(main())
