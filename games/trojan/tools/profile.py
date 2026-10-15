"""Where the 68000's time goes (run/trojan_sim on Musashi, the port schedule): the program counter sampled every
SAMPLE cycles between arcade frames FIRST and LAST, charged to the nearest label (the translated code: "Z80"),
the cycles a frame split into the logic (to the idle point) and the picture (render_frame).

    python games/trojan/tools/profile.py [FIRST] [LAST] [--seed N | --auto]
"""
from pathlib import Path
import argparse
import bisect
import collections
import re
import sys

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine'),
                str(Path(__file__).resolve().parents[1] / 'ref')]
from sim import Sim, TRAP1
from machine68k import Register as R
from paths import ROOT, build_dir
from logic_test import auto_inputs
import cover

SAMPLE = 64


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('first', nargs='?', type=int, default=1100)
    ap.add_argument('last', nargs='?', type=int, default=1300)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--auto', action='store_true')
    ap.add_argument('--z80', type=int, default=0, help='1: the translated code by Z80 instruction (the nearest label '
                    'the map has), 2: by 256 bytes')
    args = ap.parse_args()
    run = ROOT / 'run' / 'trojan_sim'
    sim = Sim(str(run / 'TROJAN.PRG'), ram_kib=16384, run_dir=run)
    raw = sim.symbols(build_dir('trojan') / 'trojan_sim.map')
    sym = {k: v + sim.base for k, v in raw.items()}
    labels = sorted((v, k) for k, v in sym.items() if not k.startswith('.') and not (re.fullmatch(r'[A-Z_0-9]+', k) and not re.fullmatch(r'(Z|BK)[0-9A-F]{4,5}', k)))
    addrs = [v for v, _ in labels]
    mem, cpu = sim.mem, sim.cpu
    level, cheats, inputs = cover.schedule(args.seed)
    if args.auto:
        level, cheats = None, False
    if level:
        mem.w8(sym['tr_dsw'], 0x1C | cover.LEVEL_DSW[level])
    block = sym['g_block']
    stops = {sym['sim_wait']: 'wait', sym['sim_frame_done']: 'done'}
    hist = collections.Counter()
    render = [0, 0]                             # cycles in render_frame, total
    rf, rf_end = sym['render_frame'], sym['pal_update']

    def run_to(profile):
        while True:
            r = cpu.execute(SAMPLE)
            pc = cpu.r_pc()
            if profile:
                render[1] += r.cycles
                i = bisect.bisect_right(addrs, pc) - 1
                name = labels[i][1] if i >= 0 else '?'
                if re.fullmatch(r'Z[0-9A-F]{4,5}(_r)?|BK[0-9A-F]{4}|tr_base_\w+|tr_bad_\w+|L\w+', name):
                    if args.z80:
                        j = i
                        while j > 0 and not re.fullmatch(r'Z[0-9A-F]{4,5}', labels[j][1]):
                            j -= 1
                        name = 'Z80 %s.. ' % labels[j][1][1:-2] if args.z80 == 2 else labels[j][1]
                    else:
                        name = 'Z80'
                hist[name] += r.cycles
            if pc in stops:
                return stops[pc]
            if pc == TRAP1:
                sim.gemdos()

    def resume():
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp))
        cpu.w_reg(R.A7, sp + 4)
    run_to(False)
    for f in range(args.last):
        if args.auto:
            s, p, lives = auto_inputs(f)
        else:
            s, p = inputs(f)
            lives = cheats and f >= 1000
        mem.w8(sym['tr_inputs'], s)
        mem.w8(sym['tr_inputs'] + 1, p)
        if lives:
            mem.w8(block + 0x8000 + 0xCDA0 - 0x10000, 3)
        mem.w8(sym['vbl_pending'], 1)
        resume()
        on = f >= args.first
        if f == args.first:
            c0 = {k: mem.r32(sym[k]) for k in ('cnt_cells', 'cnt_cells_bg2', 'cnt_sprites')}
            b0 = sim.blitter.cycles
        run_to(on)
        resume()
        run_to(on)
    n = args.last - args.first
    print('cells drawn %.1f (bg2 behind %.1f), sprites %.1f a frame' % tuple(
        (mem.r32(sym[k]) - c0[k]) / n for k in ('cnt_cells', 'cnt_cells_bg2', 'cnt_sprites')))
    total = render[1]
    print('frames %d-%d: %.0f CPU cycles a frame, Blitter %.0f' % (args.first, args.last, total / n,
                                                                  (sim.blitter.cycles - b0) / n))
    for name, c in hist.most_common(40):
        print('%8.0f %5.1f%%  %s' % (c / n, 100 * c / total, name))


if __name__ == '__main__':
    main()
