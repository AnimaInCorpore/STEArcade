"""Translated Black Tiger kernel against the same cooperative reference schedule."""
from pathlib import Path
import argparse, re
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
    ap.add_argument('--stage',type=int,help='start the game at this stage (0-7): the stage number $f3a1 set on both machines '
                    'while the game sets up, the lives $f3a0 kept at 3 (the cheats of ref/cover.py seeds 4-11)')
    args = ap.parse_args()
    run = ROOT / 'run' / 'blktiger_sim'
    sim = Sim(str(run / 'BLKTIGER.PRG'), run_dir=run)
    sim.mem.set_trace_mode(False)
    sym = {k:v+sim.base for k,v in sim.symbols(build_dir('blktiger')/'blktiger_sim.map').items()}
    stops = {sym[n]:n for n in ['sim_wait','sim_frame_done','z80_badpc']}
    mem, cpu = sim.mem, sim.cpu
    # (no drawing: render_frame only runs text_scan, whose rows the text check below compares)
    mem.w16(sym['render_frame'],0x4ef9)
    mem.w32(sym['render_frame']+2,sym['text_scan'])
    ref = BlackTiger()
    block = sym['g_block']
    # The translator merges `push rr / pop rr'` into a move (z80x: the stack word below SP is dead): the translated
    # program never writes those two bytes.  The reference's bytes written by such a push are not compared until
    # another instruction writes them.
    merged = set()
    for line in (build_dir('blktiger') / 'code_blktiger.s').read_text().splitlines():
        hit = re.match(r'^Z([0-9A-F]{4,5}):\t\t; push .* \(merged\)', line)
        if hit:
            merged.add(int(hit[1], 16))
    dead = set()
    site = [0]
    step0, write0 = ref.cpu.step, ref.cpu.wr8

    def ref_step():
        pc = ref.cpu.pc
        site[0] = 0x10000 + ref.bank*0x4000 + pc-0x8000 if 0x8000 <= pc < 0xc000 else pc
        return step0()

    def ref_write(a, v):
        if site[0] in merged:
            dead.add(a)
        else:
            dead.discard(a)
        return write0(a, v)

    ref.cpu.step, ref.cpu.wr8 = ref_step, ref_write

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
            got = mem.r_block(addr,len(want))
            # Dead stack bytes still carry unused H/N flags; only the live kernel
            # state and saved task stacks have architectural significance.
            diff = [i for i,(a,b) in enumerate(zip(got,want)) if a != b]
            if name == 'RAM':
                diff = [i for i in diff if 0xd000+i not in dead]
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

    # The renderer checks the background cells the translated writes noted (bg_note, gen.py win_check), all of them
    # after map_dirty, and the palette after a hooked writer (gen.PAL_WRITERS): a change without its note is a miss.
    regions = [('pal_dirty', block+0x5800, 0x800)]
    last = {}
    text_checked = [0]
    def hooks(frame):
        bg = bytes(mem.r_block(sym['g_bg'], 0x4000))
        if 'bg' in last and not mem.r8(sym['map_dirty']):
            noted = {mem.r16(sym['bg_noted'] + 2*i) for i in range(mem.r16(sym['bg_noted_n']))}
            miss = [i for i in range(0x4000) if bg[i] != last['bg'][i] and i >> 1 not in noted]
            if miss:
                print(f'frame {frame}: background byte {miss[0]:04x} changed without its note (bg_note)')
                return False
        last['bg'] = bg
        mem.w8(sym['map_dirty'], 0)
        mem.w16(sym['bg_noted_n'], 0)
        for flag, a, size in regions:
            now = bytes(mem.r_block(a, size))
            if flag in last and now != last[flag] and not mem.r8(sym[flag]):
                # (gen.PAL_PLAYER: the writers of entries $200-$209 set pal_player, the renderer compares those)
                changed = [i for i in range(size) if now[i] != last[flag][i]]
                missed = [i for i in changed if not (mem.r8(sym['pal_player']) and (i & 0x3ff) - 0x200 in range(10))]
                if missed:
                    print(f'frame {frame}: {flag} not set, {a:06x}+{missed[0]:04x} changed')
                    return False
            last[flag] = now
            mem.w8(sym[flag], 0)
            mem.w8(sym['pal_player'], 0)
        # The text layer rebuilds only the rows the hooked stores marked (gen.TEXT_WRITERS): right after the frame's
        # text_scan the renderer's copy of rows 2-29 must equal the text RAM, else a writer is missing there.
        if mem.r8(sym['text_valid']):
            text_checked[0] += 1
            for half in (0, 0x400):
                ram = mem.r_block(block+0x5000+half+64, 896)
                shadow = mem.r_block(sym['text_shadow']+half+64, 896)
                if ram != shadow:
                    i = next(i for i in range(896) if ram[i] != shadow[i])
                    print(f'frame {frame}: text {0xd000+half+64+i:04x} changed without a mark (a writer missing in gen.TEXT_WRITERS)')
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
        if args.stage is not None:
            for addr, value, f0, f1 in ((0xf3a1, args.stage, 939, 1060), (0xf3a0, 3, 1000, args.frames)):
                if f0 <= frame < f1:
                    ref.mem[addr] = value
                    mem.w8(block + addr - 0x8000, value)
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
        if not compare(frame) or not hooks(frame):
            return 1
        resume()
        stop = run_to_stop()
        if stop != 'sim_wait':
            raise RuntimeError(f'Unexpected stop {stop}')
        if frame % 100 == 0:
            print('frame',frame,'matched',flush=True)
    print(args.frames,'frames matched; the text layer checked in',text_checked[0])
    return 0


if __name__ == '__main__':
    sys.exit(main())
