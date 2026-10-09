"""Translated Black Tiger kernel against the same cooperative reference schedule."""
from pathlib import Path
import argparse
import random
import sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from sim import Sim, TRAP1
from machine68k import Register as R
from machine import BlackTiger
from paths import ROOT, build_dir


def inputs(frame):
    system = 0xff
    player = 0xff
    if 900 <= frame < 905:
        system &= ~0x40
    if 940 <= frame < 945:
        system &= ~1
    if frame >= 1000:
        player &= ~(1 if frame//90 % 2 == 0 else 2)
        player &= ~16
        if frame % 90 < 15:
            player &= ~32
    return system, player, 0xff


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='?', type=int, default=1600)
    ap.add_argument('--seed',type=int)
    ap.add_argument('--walk',action='store_true',help='hold right and attack through the first stage')
    args = ap.parse_args()
    run = ROOT / 'run' / 'blktiger_sim'
    sim = Sim(str(run / 'BLKTIGER.PRG'), run_dir=run)
    sim.mem.set_trace_mode(False)
    sym = {k:v+sim.base for k,v in sim.symbols(build_dir('blktiger')/'blktiger_sim.map').items()}
    stops = {sym[n]:n for n in ['sim_wait','sim_frame_done','z80_badpc']}
    mem, cpu = sim.mem, sim.cpu
    mem.w16(sym['render_frame'],0x4e75)
    ref = BlackTiger()
    block = sym['g_block']

    def run_to_stop():
        used = 0
        while used < 400_000_000:
            result = cpu.execute(2000)
            used += result.cycles
            pc = cpu.r_pc()
            if pc in stops:
                return stops[pc]
            if pc == TRAP1:
                sim.gemdos()
            if sim.terminated or pc == 0x600:
                raise RuntimeError(f'Runtime terminated at {pc:06x}: {sim.log[-3:]}')
        raise RuntimeError('68000 exceeded execution budget')

    def resume():
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp))
        cpu.w_reg(R.A7, sp+4)

    def compare(frame):
        for name, addr, want in [('RAM', block+0x5000, ref.mem[0xd000:]),
                                 ('background',sym['g_bg'],ref.bg),
                                 ('sprites',sym['bt_sprites'],ref.sprites)]:
            if name == 'background':
                got = bytearray(mem.r_block(addr,len(want)))
                bank = mem.r8(sym['g_bg_bank'])
                got[bank*0x1000:(bank+1)*0x1000] = mem.r_block(block+0x4000,0x1000)
            else:
                got = mem.r_block(addr,len(want))
            # Dead stack bytes still carry unused H/N flags; only the live kernel
            # state and saved task stacks have architectural significance.
            diff = [i for i,(a,b) in enumerate(zip(got,want)) if a != b]
            if diff:
                print(frame,name,'diff',len(diff),[(hex(i),got[i],want[i]) for i in diff[:12]])
                return False
        for name, want in [('g_bank',ref.bank),('g_bg_bank',ref.bg_bank),('g_control',ref.control),
                           ('g_video_enable',ref.video_enable),('g_layout',ref.layout),('g_mcu_response',ref.mcu.response)]:
            if mem.r8(sym[name]) != want:
                print(frame,name,mem.r8(sym[name]),want)
                return False
        if bytes(mem.r_block(sym['g_scroll'],4)) != ref.scroll:
            print(frame,'scroll mismatch')
            return False
        return True

    ref.run_to_idle()
    ref.booted = True
    stop = run_to_stop()
    if stop != 'sim_wait':
        raise RuntimeError(f'Boot stopped at {stop}, Z80 PC {cpu.r_reg(R.D7)&65535:04x}')
    if not compare(-1):
        return 1
    print('boot matched',flush=True)
    rng = random.Random(args.seed)
    values = (255,255,255)
    for frame in range(args.frames):
        if args.seed is None:
            values = inputs(frame)
        elif frame > 700 and frame % 30 == 0:
            system = 255 & ~(0x40 if frame % 180 == 0 else 0) & ~(1 if frame % 120 == 0 else 0)
            values = system, 255 ^ rng.choice([0,1,2,4,8,16,32,17,33,18,34]),255
        if args.walk and frame >= 1000:
            values = values[0], 255 ^ 1 ^ 16 ^ (32 if frame%90<15 else 0), 255
        ref.inputs[:3] = values
        for i,value in enumerate(values):
            mem.w8(sym['bt_inputs']+i,value)
        ref.run_frame_port()
        mem.w8(sym['vbl_pending'],1)
        resume()
        stop = run_to_stop()
        if stop != 'sim_frame_done':
            print(f'frame {frame}: stopped {stop}, target={mem.r16(sym["g_dispatch_pc"]):04x}, d7={cpu.r_reg(R.D7):08x}, bank={mem.r8(sym["g_bank"])}')
            return 1
        if not compare(frame):
            return 1
        resume()
        stop = run_to_stop()
        if stop != 'sim_wait':
            raise RuntimeError(f'Unexpected stop {stop}')
        if frame % 100 == 0:
            print('frame',frame,'matched',flush=True)
    print(args.frames,'frames matched')
    return 0


if __name__ == '__main__':
    sys.exit(main())
