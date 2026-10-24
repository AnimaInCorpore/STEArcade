"""Cost of a tick and of a frame on Musashi (the sim build): game logic, render_frame and the Blitter model, one frame drawn per tick,
with logic_test.py's inputs (coin, start, then walking right and attacking: the first stage scrolls).

    python perf_test.py [ticks] [first] [profile|logic [regions]|frames]   (first: ticks not counted; profile: render_frame's CPU cycles by routine;
                                                           frames: each frame's cost and Blitter cycles, the renderer's DEBUG counters:
                                                           bakes by kind, byte tables built, cells restored, tiles drawn and checked, sprites,
                                                           front cells, text runs drawn, text rectangles restored, full checks, sprite
                                                           rectangles, margin cells restored and blacked, text kept, text rows rebuilt)
    PERF_EVERY=n: a frame drawn every n-th tick only (Hatari draws about every 2.6th: MAX_SKIPS), the means per frame drawn
    PERF_PLAY=1: the recorded play's inputs (build/blktiger/play_inputs.bin) instead of the walk
    PERF_CPU=1: profile the 68000's own cycles (the Blitter's bus cycles are charged to the instructions starting the passes)

Musashi counts the 68000's own cycles: Hatari takes about 1.35 times as many (bus alignment, interrupts, the Blitter's bus).
"""
from pathlib import Path
import sys,bisect,collections
sys.path[:0]=[str(Path(__file__).resolve().parent),str(Path(__file__).resolve().parents[3]/'engine')]
from machine68k import Register as R
from sim import Sim,TRAP1
from paths import ROOT,build_dir
from logic_test import inputs
import os
EVERY=int(os.environ.get('PERF_EVERY','1'))
CPU_ONLY=os.environ.get('PERF_CPU')   # (profile: the 68000's cycles only, without the Blitter's bus cycles charged to the pass starts)
PLAY=os.environ.get('PERF_PLAY')   # (the recorded play build/blktiger/play_inputs.bin, e.g. marp_inputs.py's, lives kept at 3 from tick 1000)
SEL=os.environ.get('PERF_SEL')   # (map / nomap: profile only the frames after a background write, or the others)


REGS=[getattr(R,f'D{i}') for i in range(8)]+[getattr(R,f'A{i}') for i in range(8)]


def main():
    ticks=int(sys.argv[1]) if len(sys.argv)>1 else 1600
    first=int(sys.argv[2]) if len(sys.argv)>2 else 1000
    prof=len(sys.argv)>3 and sys.argv[3]=='profile'
    dbg=len(sys.argv)>3 and sys.argv[3]=='frames'
    COUNTERS=['bake_n_tile','bake_n_sprite','bake_n_char','dbg_byte_luts','dbg_restored','dbg_draws','dbg_checks','dbg_sprites','dbg_fronts',
              'dbg_runs','dbg_text_cells','dbg_full','dbg_sprite_cells','dbg_strip_cells','dbg_ands','dbg_text_kept','dbg_text_rows']
    lprof=len(sys.argv)>3 and sys.argv[3]=='logic'   # (the logic's cycles by routine; translated code as 'Z80')   # (per frame: map / palette changes, tiles baked)
    run=ROOT/'run/blktiger_sim';s=Sim(str(run/'BLKTIGER.PRG'),ram_kib=16384,run_dir=run)  # (16 MB: the sprite code reads Blitter registers back)
    mem,cpu=s.mem,s.cpu;mem.set_trace_mode(False)   # (the I/O trace only while drawing: the Blitter)
    sym={k:v+s.base for k,v in s.symbols(build_dir('blktiger')/'blktiger_sim.map').items()}
    COUNTERS=[c for c in COUNTERS if c in sym]   # (the dbg_ counters: build.py --sim --debug)
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
                r=cpu.execute(1);c=r.cycles+(0 if CPU_ONLY else s.blitter.cycles);s.blitter.cycles=0
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
    logic,frames=[],[];totals=collections.Counter()
    if PLAY:
        import playbot;play=playbot.load(build_dir('blktiger')/'play_inputs.bin')
    for f in range(ticks):
        values=inputs(f)
        if f>=1000:values=values[0],255^1^16^(32 if f%90<15 else 0),255   # (logic_test --walk)
        if PLAY:
            values=(*play[f],255)
            if f>=1000:mem.w8(sym['g_block']+0xf3a0-0x8000,3)
        for i,v in enumerate(values):mem.w8(sym['bt_inputs']+i,v)
        mem.w8(sym['vbl_pending'],1);resume()
        lc=run_to({done},step=lprof and f>=first)
        if dbg:dirty=mem.r8(sym['map_dirty']);bk=mem.r32(sym['bake_calls']);ep=mem.r8(sym['epoch_changed']);before={c:mem.r32(sym[c]) for c in COUNTERS};blit0=s.blitter.cycles
        if f%EVERY:                                   # (not drawn: on to the next tick)
            mem.w8(sym['frame_ready'],0);resume();lc+=run_to({wait},step=lprof and f>=first)
            if f>=first:logic.append(lc)
            continue
        pc_done=cpu.r_pc();sp=cpu.r_reg(R.A7);regs=[cpu.r_reg(r) for r in REGS]   # (render_frame keeps no registers: the hook saved them)
        mem.w16(render,word);mem.set_trace_mode(True);cpu.w_reg(R.A7,sp-4);mem.w32(sp-4,ret);cpu.w_pc(render)
        sel=SEL is None or (SEL=='map')==bool(mem.r8(sym['map_dirty']))
        try:rc=run_to({ret},step=prof and f>=first and sel)
        except Exception:print(f'render_frame failed at tick {f}');raise
        mem.set_trace_mode(False);mem.w16(render,0x4e75);cpu.w_pc(pc_done)
        for r,v in zip(REGS,regs):cpu.w_reg(r,v);mem.w8(sym['frame_ready'],0)
        resume();lc+=run_to({wait},step=lprof and f>=first)
        if f>=first:
            logic.append(lc)
            if sel:frames.append(rc)
        if dbg and f>=first:
            counts={c:mem.r32(sym[c])-before[c] for c in COUNTERS};totals.update(counts)
            print(f,'map',dirty,'epoch',ep,'bakes',mem.r32(sym['bake_calls'])-bk,'frame',rc,'scroll',bytes(mem.r_block(sym['g_scroll'],4)).hex(),
                  ' '.join(f"{c.replace('dbg_','').replace('bake_n_','bake_')} {v}" for c,v in counts.items() if v))
    n=len(logic);nf=len(frames);fs=sorted(frames)
    print(f'{n} ticks: logic mean {sum(logic)//n} max {max(logic)}; {nf} frames (CPU + Blitter) mean {sum(frames)//nf} median {fs[nf//2]} max {max(frames)}')
    print(f'at 8 MHz: {8e6/(sum(logic)/n+sum(frames)/n):.1f} ticks a second (Musashi cycles)')
    if dbg:print('a frame:',' '.join(f"{c.replace('dbg_','').replace('bake_n_','bake_')} {totals[c]/nf:.1f}" for c in COUNTERS))
    if prof or lprof:
        tot=sum(by_name.values())
        for k,v in by_name.most_common(25):print(f'{k:24s} {v//(n if lprof else nf):8d} {100*v/tot:5.1f}%')


if __name__=='__main__':main()
