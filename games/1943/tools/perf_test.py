"""Cost of a tick on Musashi (the sim build): the game logic (translated Z80, i8751 interpreter), render_frame and the
Blitter model, one frame drawn per tick, logic_test.py's inputs.

    python perf_test.py [ticks] [first] [--cheat stage] [--profile]    (first: ticks not counted; --profile: cycles by
                                                                         routine, the translated code as 'Z80')

Musashi counts the 68000's own cycles: Hatari takes about 1.35 times as many (bus alignment, interrupts, the Blitter's bus).
"""
from pathlib import Path
import argparse, bisect, collections, re, sys
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine68k import Register as R
from sim import Sim, TRAP1
from paths import ROOT, build_dir
from logic_test import inputs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('ticks', nargs='?', type=int, default=1600)
    ap.add_argument('first', nargs='?', type=int, default=1200)
    ap.add_argument('--cheat', type=int)
    ap.add_argument('--profile', action='store_true')
    args = ap.parse_args()
    run = ROOT / 'run' / '1943_sim'
    s = Sim(str(run / '1943.PRG'), ram_kib=16384, run_dir=run)
    mem, cpu = s.mem, s.cpu
    mem.set_trace_mode(True)                  # (the Blitter)
    sym = {k: v + s.base for k, v in s.symbols(build_dir('1943') / '1943_sim.map').items()}
    wait, done, bad = sym['sim_wait'], sym['sim_frame_done'], sym['z80_badpc']
    block = sym['g_block'] + 0x8000 - 0x10000

    def name(k):
        if k[0] == 'Z' and len(k) > 1 and all(c in '0123456789ABCDEF' for c in k[1:]) or re.fullmatch(r'Lx\d+|BK[0-9A-F]+', k):
            return 'Z80'
        return k
    reloc = {m[2] for m in re.finditer(r'\s+0x([0-9a-f]{8})\s+(\S+?): \S+ reloc', (build_dir('1943') / '1943_sim.map').read_text())}
    names = sorted((v, name(k)) for k, v in sym.items() if k in reloc)
    addrs = [v for v, _ in names]
    by_name = collections.Counter()
    in_render = [False]
    render, render_end = sym['render_frame'], None

    def resume():
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp))
        cpu.w_reg(R.A7, sp + 4)

    def run_to(target, step, measure=True):
        logic = frame = 0
        while logic + frame < 400_000_000:
            pc = cpu.r_pc()
            if pc == target:
                return logic, frame
            if pc == bad or s.terminated:
                raise RuntimeError(f'stopped at {pc - s.base:06x}')
            if pc == TRAP1:
                s.gemdos()
            if not measure:
                r = cpu.execute(2000)
                if cpu.r_pc() == target:
                    return 0, 0
                continue
            if pc == render:
                in_render[0] = True
                stack_ret[0] = mem.r32(cpu.r_reg(R.A7))
            elif in_render[0] and pc == stack_ret[0]:
                in_render[0] = False
            r = cpu.execute(1 if measure else 2000)
            c = r.cycles + s.blitter.cycles
            s.blitter.cycles = 0
            if step:
                by_name[names[bisect.bisect_right(addrs, pc) - 1][1]] += c
            if in_render[0]:
                frame += c
            else:
                logic += c
        raise RuntimeError('timeout')

    stack_ret = [0]
    run_to(wait, False, False)
    logic, frames = [], []
    for f in range(args.ticks):
        values = inputs(f)
        if args.cheat is not None:
            for addr, value, f0 in ((0xe450, args.cheat, 700), (0xf206, 0x40, 0), (0xf214, 2, 0)):
                if f0 <= f and (addr != 0xe450 or f < 1100):
                    mem.w8(block + addr, value)
        vbl = mem.r8(sym['g_inputs']) & 8
        mem.w8(sym['g_inputs'], values[0] & ~8 | vbl)
        mem.w8(sym['g_inputs'] + 1, values[1])
        mem.w8(sym['vbl_pending'], 1)
        resume()
        step = args.profile and f >= args.first
        l1, r1 = run_to(done, step, f >= args.first)
        ready = mem.r8(sym['frame_ready'])                # (a VBL shows the frame)
        if ready:
            mem.w16(sym['prev_idx'], mem.r16(sym['shown_idx']))
            mem.w16(sym['shown_idx'], ready - 1)
            mem.w8(sym['frame_ready'], 0)
        resume()
        l2, r2 = run_to(wait, step, f >= args.first)
        if f == args.first:
            by_name.clear()                           # (the first measured tick starts in the middle of the hook)
        elif f > args.first:
            if l1 + l2 > 2_000_000:
                print(f'tick {f}: logic {l1 + l2}')
            logic.append(l1 + l2)
            frames.append(r1 + r2)
    n = len(logic)
    print(f'{n} ticks: logic mean {sum(logic)//n} max {max(logic)}; frame (CPU + Blitter) mean {sum(frames)//n} max {max(frames)}')
    print(f'at 8 MHz: {8e6/(sum(logic)/n+sum(frames)/n):.1f} ticks+frames a second (Musashi cycles)')
    if args.profile:
        tot = sum(by_name.values())
        for k, v in by_name.most_common(30):
            print(f'{k:24s} {v//n:8d} {100*v/tot:5.1f}%')


if __name__ == '__main__':
    main()
