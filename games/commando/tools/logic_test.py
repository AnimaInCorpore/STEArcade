"""Frame-by-frame translated CPU/reference comparison through attract and play."""
from pathlib import Path
import sys,random
sys.path[:0]=[str(Path(__file__).resolve().parents[3]/'engine'),str(Path(__file__).resolve().parents[1]/'ref')]
from machine68k import Register as R
from sim import Sim,TRAP1
from machine import Commando,BUILD
from paths import ROOT
from cover import inputs

def main():
    n=int(sys.argv[1]) if len(sys.argv)>1 else 3000
    # play: the recorded play (play_search.py) against a sim build with -D PLAYBACK=1, whose pb_inputs feeds the ticks
    play=None
    if len(sys.argv)>2 and sys.argv[2]=='play':
        import playbot;play=playbot.load(BUILD/'play_inputs.bin')
    run=ROOT/'run/commando_sim';s=Sim(str(run/'COMMANDO.PRG'),run_dir=run)
    sym={k:v+s.base for k,v in s.symbols(BUILD/'commando_sim.map').items()}
    mem,cpu=s.mem,s.cpu;s.mem.set_trace_mode(False)
    mem.w16(sym['render_frame'],0x4e75)
    wait,done=sym['sim_wait'],sym['sim_frame_done'];block=sym['g_block'];bad=sym['z80_badpc']
    m=Commando();m.cpu.afmask=0xc1;rnd=random.Random(1)
    def addr(a):return block+0x8000+(a if a<0x8000 else a-65536)
    def resume():
        sp=cpu.r_reg(R.A7);cpu.w_pc(mem.r32(sp));cpu.w_reg(R.A7,sp+4)
    def run_to(targets):
        total=0
        while total<100000000:
            result=cpu.execute(2000);total+=result.cycles;pc=cpu.r_pc()
            if pc in targets:return pc
            if pc in (bad,bad+4) or s.terminated:
                raise RuntimeError(f'CPU stopped at {pc-s.base:06x}, d7={cpu.r_reg(R.D7):08x}, log={s.log[-3:]}')
            if pc==TRAP1:s.gemdos()
        raise RuntimeError(f'CPU timeout at {cpu.r_pc()-s.base:06x}')
    def compare(f):
        want=bytes(m.mem[0xd000:]);got=bytes(mem.r_block(addr(0xd000),len(want)))
        differences=[i for i in range(len(want)) if want[i]!=got[i]]
        if differences:
            raise RuntimeError(f'frame {f}: {len(differences)} RAM differences '+str([(hex(0xd000+i),hex(got[i]),hex(want[i])) for i in differences[:10]]))
        for a,v in list(zip(range(0xc808,0xc80c),m.scroll))+[(0xc804,m.control)]:
            if mem.r8(addr(a))!=v:raise RuntimeError(f'Latch {a:04x} differs in frame {f}')
        if bytes(mem.r_block(sym['sprite_buffer'],384))!=m.sprites:raise RuntimeError(f'Sprite latch differs in frame {f}')
    # The renderer compares the tile and character RAM only after a hooked writer (gen.BG_WRITERS / FG_WRITERS):
    # a change without its flag is a writer missing there.
    regions=[('bg_written',0xd800,0x800),('fg_written',0xd000,0x800)];last={}
    def hooks(f):
        for flag,a,size in regions:
            now=bytes(mem.r_block(addr(a),size))
            if last.get(flag) is not None and now!=last[flag] and not mem.r8(sym[flag]):
                i=next(i for i in range(size) if now[i]!=last[flag][i])
                raise RuntimeError(f'frame {f}: {a+i:04x} changed without {flag} (a writer missing in gen.py)')
            last[flag]=now;mem.w8(sym[flag],0)
    run_to({wait});m.run_to_idle();m.booted=True;compare(-1);hooks(-1)
    for f in range(n):
        if play:
            m.inputs[:3]=[*play[f],255]
            if f>=780:m.mem[0xeda0]=3
        else:
            m.inputs[:3]=inputs(f,rnd)
            for a,v in zip(range(0xc000,0xc003),m.inputs[:3]):mem.w8(addr(a),v)
        mem.w8(sym['vbl_pending'],1)
        m.run_frame_port();resume();run_to({done});compare(f);resume();run_to({wait});hooks(f)
        if f%1000==999:print(f'{f+1} frames exact',flush=True)
    print(f'PASS: {n} frames; all video RAM, work RAM, sprite buffers and latches exact; every tile / character RAM change flagged')
if __name__=='__main__':main()
