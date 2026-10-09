"""Cost of a tick and of a frame on Musashi (the sim build): game logic, render_frame and the Blitter model, one frame drawn per tick,
with logic_test.py's inputs (coin, start, then walking right and attacking: the first stage scrolls).

    python perf_test.py [ticks] [first] [profile|logic [regions]|frames]   (first: ticks not counted; profile: render_frame's CPU cycles by routine;
                                                           frames: each frame's cost, map and palette changes, tiles baked)

Musashi counts the 68000's own cycles: Hatari takes about 1.35 times as many (bus alignment, interrupts, the Blitter's bus).
"""
from pathlib import Path
import sys,bisect,collections
sys.path[:0]=[str(Path(__file__).resolve().parent),str(Path(__file__).resolve().parents[3]/'engine')]
from machine68k import Register as R
from sim import Sim,TRAP1
from paths import ROOT,build_dir
from logic_test import inputs


REGS=[getattr(R,f'D{i}') for i in range(8)]+[getattr(R,f'A{i}') for i in range(8)]


def main():
    ticks=int(sys.argv[1]) if len(sys.argv)>1 else 1600
    first=int(sys.argv[2]) if len(sys.argv)>2 else 1000
    prof=len(sys.argv)>3 and sys.argv[3]=='profile'
    dbg=len(sys.argv)>3 and sys.argv[3]=='frames'
    lprof=len(sys.argv)>3 and sys.argv[3]=='logic'   # (the logic's cycles by routine; translated code as 'Z80')   # (per frame: map / palette changes, tiles baked)
    run=ROOT/'run/blktiger_sim';s=Sim(str(run/'BLKTIGER.PRG'),ram_kib=16384,run_dir=run)  # (16 MB: the sprite code reads Blitter registers back)
    mem,cpu=s.mem,s.cpu;mem.set_trace_mode(False)   # (the I/O trace only while drawing: the Blitter)
    sym={k:v+s.base for k,v in s.symbols(build_dir('blktiger')/'blktiger_sim.map').items()}
    wait,done,render,ret=sym['sim_wait'],sym['sim_frame_done'],sym['render_frame'],sym['sim_render_ret']
    bad=sym['z80_badpc']
    zreg=len(sys.argv)>4 and sys.argv[4]=='regions'   # (logic regions: translated code by 256-byte Z80 page, bank)
    def zname(k):
        if k[0]=='Z' and all(c in '0123456789ABCDEF' for c in k[1:]) and len(k)>1:
            if not zreg:return 'Z80'
            pc=int(k[1:],16);return f'Z80 {pc>>8:03X}xx' if pc<0x10000 else f'Z80 bank{(pc-0x10000)//0x4000} {0x8000+((pc-0x10000)&0x3fff)>>8:02X}xx'
        return k
    names=sorted((v,zname(k)) for k,v in sym.items() if not k.startswith('.'))
    addrs=[v for v,_ in names];by_name=collections.Counter()

    def resume():
        sp=cpu.r_reg(R.A7);cpu.w_pc(mem.r32(sp));cpu.w_reg(R.A7,sp+4)

    def run_to(targets,step=False):
        total=0
        while total<400000000:
            pc=cpu.r_pc()
            if pc in targets:return total
            if step:
                r=cpu.execute(1);c=r.cycles+s.blitter.cycles;s.blitter.cycles=0
                by_name[names[bisect.bisect_right(addrs,pc)-1][1]]+=c;total+=c
                continue
            r=cpu.execute(2000);total+=r.cycles+s.blitter.cycles;s.blitter.cycles=0;pc=cpu.r_pc()
            if pc in targets:return total
            if pc in (bad,bad+4) or s.terminated:raise RuntimeError(f"CPU stopped at {pc-s.base:06x}, terminated {s.terminated}")
            if pc==TRAP1:s.gemdos()
        raise RuntimeError('timeout')

    # render_frame is patched out while the game runs (sim_wait / sim_frame_done are loops the CPU stops in) and called at each
    # sim_frame_done with sim_render_ret (a loop too) as its return address, as in render_test.py.
    word=mem.r16(render);mem.w16(render,0x4e75);run_to({wait})
    logic,frames=[],[]
    for f in range(ticks):
        values=inputs(f)
        if f>=1000:values=values[0],255^1^16^(32 if f%90<15 else 0),255   # (logic_test --walk)
        for i,v in enumerate(values):mem.w8(sym['bt_inputs']+i,v)
        mem.w8(sym['vbl_pending'],1);resume()
        lc=run_to({done},step=lprof and f>=first)
        if dbg:dirty=mem.r8(sym['map_dirty']);bk=mem.r32(sym['bake_calls']);ep=mem.r8(sym['epoch_changed'])
        pc_done=cpu.r_pc();sp=cpu.r_reg(R.A7);regs=[cpu.r_reg(r) for r in REGS]   # (render_frame keeps no registers: the hook saved them)
        mem.w16(render,word);mem.set_trace_mode(True);cpu.w_reg(R.A7,sp-4);mem.w32(sp-4,ret);cpu.w_pc(render)
        try:rc=run_to({ret},step=prof and f>=first)
        except Exception:print(f'render_frame failed at tick {f}');raise
        mem.set_trace_mode(False);mem.w16(render,0x4e75);cpu.w_pc(pc_done)
        for r,v in zip(REGS,regs):cpu.w_reg(r,v);mem.w8(sym['frame_ready'],0)
        resume();lc+=run_to({wait},step=lprof and f>=first)
        if f>=first:logic.append(lc);frames.append(rc)
        if dbg and f>=first:print(f,'map',dirty,'epoch',ep,'bakes',mem.r32(sym['bake_calls'])-bk,'frame',rc,'scroll',bytes(mem.r_block(sym['g_scroll'],4)).hex())
    n=len(logic)
    print(f'{n} ticks: logic mean {sum(logic)//n} max {max(logic)}; frame (CPU + Blitter) mean {sum(frames)//n} max {max(frames)}')
    print(f'at 8 MHz: {8e6/(sum(logic)/n+sum(frames)/n):.1f} ticks+frames a second (Musashi cycles)')
    if prof or lprof:
        tot=sum(by_name.values())
        for k,v in by_name.most_common(25):print(f'{k:24s} {v//n:8d} {100*v/tot:5.1f}%')


if __name__=='__main__':main()
