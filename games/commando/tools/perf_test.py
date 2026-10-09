"""Cost of a tick and of a frame on Musashi (the sim build): game logic, render_frame and the Blitter model, one frame drawn per tick,
with the seeded attract/play inputs of ref/cover.py.

    python perf_test.py [ticks] [first] [profile]   (first: ticks not counted; profile: render_frame's CPU cycles by routine)

Musashi counts the 68000's own cycles: Hatari takes about 1.35 times as many (bus alignment, interrupts, the Blitter's bus).
"""
from pathlib import Path
import sys,random,bisect,collections
sys.path[:0]=[str(Path(__file__).resolve().parents[3]/'engine'),str(Path(__file__).resolve().parents[1]/'ref')]
from machine68k import Register as R
from sim import Sim,TRAP1
from machine import BUILD
from paths import ROOT
from cover import inputs


def main():
    ticks=int(sys.argv[1]) if len(sys.argv)>1 else 2000
    first=int(sys.argv[2]) if len(sys.argv)>2 else 300
    prof=len(sys.argv)>3 and sys.argv[3]=='profile'
    run=ROOT/'run/commando_sim';s=Sim(str(run/'COMMANDO.PRG'),ram_kib=16384,run_dir=run)  # (16 MB: the hardware registers read back, the sprite code adds to the Blitter's address)
    mem,cpu=s.mem,s.cpu;mem.set_trace_mode(True)
    sym={k:v+s.base for k,v in s.symbols(BUILD/'commando_sim.map').items()}
    wait,done,render=sym['sim_wait'],sym['sim_frame_done'],sym['render_frame']
    bad=sym['z80_badpc'];block=sym['g_block']
    names=sorted((v,k) for k,v in sym.items() if not k.startswith('Z') and not k.startswith('.'))
    addrs=[v for v,_ in names];by_name=collections.Counter()

    def resume():
        sp=cpu.r_reg(R.A7);cpu.w_pc(mem.r32(sp));cpu.w_reg(R.A7,sp+4)

    def run_to(targets,step=False):
        total=0
        while total<200000000:
            pc=cpu.r_pc()
            if pc in targets:return total
            if step:
                r=cpu.execute(1);c=r.cycles+s.blitter.cycles;s.blitter.cycles=0
                by_name[names[bisect.bisect_right(addrs,pc)-1][1]]+=c;total+=c
                continue
            r=cpu.execute(2000);total+=r.cycles+s.blitter.cycles;s.blitter.cycles=0;pc=cpu.r_pc()
            if pc in targets:return total
            if pc in (bad,bad+4) or s.terminated:raise RuntimeError(f'CPU stopped at {pc-s.base:06x}')
            if pc==TRAP1:s.gemdos()
        raise RuntimeError('timeout')

    # The game runs with render_frame patched out (sim_wait / sim_frame_done are loops the CPU stops in); render_frame
    # is then called at each sim_frame_done with sim_render_ret (a loop too) as its return address, as in render_test.py.
    word=mem.r16(render);mem.w16(render,0x4e75);run_to({wait})
    rnd=random.Random(1);logic,frames=[],[];ret=sym['sim_render_ret']
    for f in range(ticks):
        system,p1,p2=inputs(f,rnd)
        for a,v in zip((0xc000,0xc001,0xc002),(system,p1,p2)):mem.w8(block+0x8000+a-0x10000,v)
        mem.w8(sym['vbl_pending'],1);resume()
        lc=run_to({done});rc=0
        pc_done=cpu.r_pc();sp=cpu.r_reg(R.A7)
        mem.w16(render,word);cpu.w_reg(R.A7,sp-4);mem.w32(sp-4,ret);cpu.w_pc(render)
        try:rc=run_to({ret},step=prof and f>=first)
        except Exception:print(f'render_frame failed at tick {f}');raise
        mem.w16(render,0x4e75);cpu.w_reg(R.A7,sp);cpu.w_pc(pc_done)
        mem.w16(sym['prev_idx'],mem.r16(sym['shown_idx']));mem.w16(sym['shown_idx'],mem.r16(sym['draw_idx']));mem.w8(sym['frame_ready'],0)
        resume();lc+=run_to({wait})
        if f>=first:logic.append(lc);frames.append(rc)
    n=len(logic)
    print(f'{n} ticks: logic mean {sum(logic)//n} max {max(logic)}; frame (CPU + Blitter) mean {sum(frames)//n} max {max(frames)}')
    print(f'at 8 MHz: {8e6/(sum(logic)/n+sum(frames)/n):.1f} ticks+frames a second (Musashi cycles)')
    if prof:
        tot=sum(by_name.values())
        for k,v in by_name.most_common(25):print(f'{k:24s} {v//n:8d} {100*v/tot:5.1f}%')


if __name__=='__main__':main()
