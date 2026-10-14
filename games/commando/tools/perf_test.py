"""Cost of a tick and of a frame on Musashi (the sim build): game logic, render_frame and the Blitter model, one frame drawn per tick,
with the seeded attract/play inputs of ref/cover.py.

    python perf_test.py [ticks] [first] [profile]   (first: ticks not counted; profile: render_frame's CPU cycles by routine)
    PLAY=1 python perf_test.py ...                 the recorded play's inputs (play_search.py, as bench.sh PLAY=1)
    PERF_PCS=1 (with profile)                      the hottest single instructions (CPU cycles a picture)
    PERF_CALLS=a,b (with profile)                  how often these routines run a picture
    PERF_LOGIC=1 (with profile)                    the logic's cycles by runtime routine (the translated code as Z)
    PERF_BLIT=1 (with profile)                     the Blitter's bus cycles by the routine that started the pass (blit:...)

Musashi counts the 68000's own cycles: Hatari takes about 1.35 times as many (bus alignment, interrupts, the Blitter's bus).
"""
from pathlib import Path
import sys,os,random,bisect,collections
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
    names=sorted((v,k) for k,v in sym.items() if not k.startswith('Z') and not k.startswith('.') and not k.isupper())  # (no constants)
    addrs=[v for v,_ in names];by_name=collections.Counter()
    split=bool(os.environ.get('PERF_BLIT'))
    pcs_prof=bool(os.environ.get('PERF_PCS'));by_pc=collections.Counter()
    calls={sym[k]:k for k in os.environ.get('PERF_CALLS','').split(',') if k in sym};ncalls=collections.Counter()
    logic_prof=bool(os.environ.get('PERF_LOGIC'));by_logic=collections.Counter()
    zl=sorted(v for k,v in sym.items() if k.startswith('Z') and k[1:].isalnum())
    zset=set()
    if logic_prof:                              # (the translated code: from its first Z label to its last)
        lo,hi=zl[0],zl[-1]+64
        zset=range(lo,hi)
    code_lo,code_hi=sym['render_frame']-0x10000,sym['render_frame']+0x80000

    def resume():
        sp=cpu.r_reg(R.A7);cpu.w_pc(mem.r32(sp));cpu.w_reg(R.A7,sp+4)

    def run_to(targets,step=False,into=None):
        total=0
        while total<200000000:
            pc=cpu.r_pc()
            if pc in targets:return total
            if step and into is not None:      # (PERF_LOGIC=1: the logic's runtime by routine, the translated code as Z)
                r=cpu.execute(1);total+=r.cycles+s.blitter.cycles;s.blitter.cycles=0
                into['Z' if pc in zset else names[bisect.bisect_right(addrs,pc)-1][1]]+=r.cycles
                if pcs_prof and pc not in zset:by_pc[pc]+=r.cycles
                continue
            if step:
                if pc in calls:ncalls[calls[pc]]+=1
                r=cpu.execute(1);b=s.blitter.cycles;s.blitter.cycles=0
                by_name[names[bisect.bisect_right(addrs,pc)-1][1]]+=r.cycles+b*(not split);total+=r.cycles+b
                if pcs_prof:by_pc[pc]+=r.cycles
                if b and split:                 # (PERF_BLIT=1: a pass's bus cycles to the routine that asked for it)
                    sp=cpu.r_reg(R.A7)
                    for k in range(0,96,2):
                        v=mem.r32(sp+k)
                        if code_lo<=v<code_hi:
                            n=names[bisect.bisect_right(addrs,v)-1][1]
                            if not n.startswith(('blit_go','bd_')):break
                    else:n='?'
                    by_name['blit:'+n]+=b
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
    play=None
    if os.environ.get('PLAY'):
        import playbot;play=playbot.load(BUILD/'play_inputs.bin')
    for f in range(ticks):
        if play:
            (system,p1),p2=play[f],255
            if f>=780:mem.w8(block+0x8000+0xeda0-0x10000,3)
        else:system,p1,p2=inputs(f,rnd)
        for a,v in zip((0xc000,0xc001,0xc002),(system,p1,p2)):mem.w8(block+0x8000+a-0x10000,v)
        mem.w8(sym['vbl_pending'],1);resume()
        lc=run_to({done},step=prof and logic_prof and f>=first,into=by_logic);rc=0
        pc_done=cpu.r_pc();sp=cpu.r_reg(R.A7)
        mem.w16(render,word);cpu.w_reg(R.A7,sp-4);mem.w32(sp-4,ret);cpu.w_pc(render)
        try:rc=run_to({ret},step=prof and f>=first)
        except Exception:print(f'render_frame failed at tick {f}');raise
        mem.w16(render,0x4e75);cpu.w_reg(R.A7,sp);cpu.w_pc(pc_done)
        mem.w16(sym['prev_idx'],mem.r16(sym['shown_idx']));mem.w16(sym['shown_idx'],mem.r16(sym['draw_idx']));mem.w8(sym['frame_ready'],0)
        resume();lc+=run_to({wait},step=prof and logic_prof and f>=first,into=by_logic)
        if f>=first:logic.append(lc);frames.append(rc)
    n=len(logic)
    print(f'{n} ticks: logic mean {sum(logic)//n} max {max(logic)}; frame (CPU + Blitter) mean {sum(frames)//n} max {max(frames)}')
    print(f'at 8 MHz: {8e6/(sum(logic)/n+sum(frames)/n):.1f} ticks+frames a second (Musashi cycles)')
    fs=sorted(frames);q=lambda p:fs[min(n-1,int(p*n))]
    print(f'pictures: median {q(.5)}, 90% {q(.9)}, 99% {q(.99)}; over 300k: {sum(f>300000 for f in fs)} '
          f'({sum(f for f in fs if f>300000)*100//max(1,sum(fs))}% of the cycles)')
    focus=os.environ.get('PERF_FOCUS')           # (PERF_PCS=1 PERF_FOCUS=draw_sprites: that routine's instructions in order)
    if focus:
        for pc in sorted(by_pc):
            i=bisect.bisect_right(addrs,pc)-1
            if names[i][1]==focus:print(f'pc {focus}+{pc-addrs[i]:<5d} {by_pc[pc]//n:7d}  {cpu.disassemble(pc)[1]}')
    for pc,v in by_pc.most_common(0 if focus else 40):
        i=bisect.bisect_right(addrs,pc)-1
        print(f'pc {names[i][1]}+{pc-addrs[i]:<5d} {v//n:7d}  {cpu.disassemble(pc)[1] if hasattr(cpu,"disassemble") else ""}')
    for k,v in ncalls.most_common():print(f'calls {k:24s} {v/n:8.1f} a picture')
    if prof and logic_prof:
        tot=sum(by_logic.values())
        for k,v in by_logic.most_common(25):print(f'logic {k:24s} {v//n:8d} {100*v/tot:5.1f}%')
    if prof:
        tot=sum(by_name.values())
        for k,v in by_name.most_common(25):print(f'{k:24s} {v//n:8d} {100*v/tot:5.1f}%')


if __name__=='__main__':main()
