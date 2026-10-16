"""Where the 68000's time goes (run/trojan_sim on Musashi, the port schedule): the program counter sampled every
SAMPLE cycles between arcade frames FIRST and LAST, charged to the nearest label of the program; the translated code
("Z80") apart.  --z80: the translated code by Z80 function (the nearest call / rst target before the instruction)
and by instruction, its addresses from a vasm listing of the sim build (every Zxxxx label, the merged ones too).

    python games/trojan/tools/profile.py [FIRST] [LAST] [--seed N | --auto] [--z80] [--top N]
"""
from pathlib import Path
import argparse
import bisect
import collections
import re
import subprocess
import sys

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine'),
                str(Path(__file__).resolve().parents[1] / 'ref')]
from sim import Sim, TRAP1
from machine68k import Register as R
from paths import ROOT, build_dir, VASM, RT_INCLUDE, src_dir
from logic_test import auto_inputs
import cover

SAMPLE = 64


def z80_labels():
    """[(text offset, Z80 virtual pc)] of every translated instruction, from a listing of the sim build"""
    lst = build_dir('trojan') / 'trojan_sim.lst'
    obj = build_dir('trojan') / 'prof_tmp.o'
    subprocess.run([VASM, '-Fvobj', '-quiet', '-nowarn=2047', '-I', str(build_dir('trojan')), '-I', str(RT_INCLUDE),
                    '-DSIM=1', '-L', str(lst), '-o', str(obj), 'trojan.s'], cwd=src_dir('trojan'), check=True,
                   capture_output=True)
    pending, out = [], []
    for line in open(lst, errors='replace'):
        m = re.match(r'^01:([0-9A-F]{8}) ', line)
        if m:
            off = int(m[1], 16)
            out += [(off, pc) for pc in pending]
            pending = []
            continue
        if line[:3].isdigit() and line[2] == ':':
            pending = []
            continue
        m = re.match(r'^\s+\d+: Z([0-9A-F]{4,5}):', line)
        if m:
            pending.append(int(m[1], 16))
    out.sort()
    return out


def listing_lines():
    """[(text offset, source text)] of every line with code in section 01 of the listing (z80_labels made it)"""
    out = []
    for line in open(build_dir('trojan') / 'trojan_sim.lst', errors='replace'):
        m = re.match(r'^01:([0-9A-F]{8}) \S+\s+\d+: (.*)', line)
        if m:
            out.append((int(m[1], 16), m[2].strip()))
    return out


def functions():
    """the Z80 call / rst targets (virtual pcs) of the translation"""
    out = set()
    for line in (build_dir('trojan') / 'code_trojan.s').read_text().splitlines():
        m = re.match(r'^Z([0-9A-F]{4,5}):\t\t; (call|rst)', line)
        if m:
            t = re.search(r'\$([0-9A-F]+)', line)
            if t:
                out.add(int(t[1], 16))
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('first', nargs='?', type=int, default=1100)
    ap.add_argument('last', nargs='?', type=int, default=1300)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--auto', action='store_true')
    ap.add_argument('--z80', action='store_true')
    ap.add_argument('--top', type=int, default=40)
    ap.add_argument('--lines', default=None, help='a label: the samples inside it by source line')
    args = ap.parse_args()
    run = ROOT / 'run' / 'trojan_sim'
    sim = Sim(str(run / 'TROJAN.PRG'), ram_kib=16384, run_dir=run)
    raw = sim.symbols(build_dir('trojan') / 'trojan_sim.map')
    sym = {k: v + sim.base for k, v in raw.items()}
    labels = sorted((v, k) for k, v in sym.items() if not k.startswith('.') and
                    not (re.fullmatch(r'[A-Z_0-9]+', k) and not re.fullmatch(r'(Z|BK)[0-9A-F]{4,5}', k)))
    addrs = [v for v, _ in labels]
    zl = z80_labels() if args.z80 or args.lines else []
    src = listing_lines() if args.lines else []
    src_addr = [sim.base + o for o, _ in src]
    lhist = collections.Counter()
    zaddr = [sim.base + o for o, _ in zl]
    funcs = functions() if args.z80 else []
    mem, cpu = sim.mem, sim.cpu
    level, cheats, inputs = cover.schedule(args.seed)
    if args.auto:
        level, cheats = None, False
    if level:
        mem.w8(sym['tr_dsw'], 0x1C | cover.LEVEL_DSW[level])
    block = sym['g_block']
    stops = {sym['sim_wait']: 'wait', sym['sim_frame_done']: 'done'}
    hist = collections.Counter()
    zins = collections.Counter()
    zfun = collections.Counter()
    total = [0]
    zcode = re.compile(r'Z[0-9A-F]{4,5}(_r)?|BK[0-9A-F]{4}|tr_base_\w+|tr_bad_\w+|L\w+')
    zfirst, zlast = (zaddr[0], sym['tr_fixed_dispatch']) if zaddr else (0, 0)

    def run_to(profile, part):
        while True:
            r = cpu.execute(SAMPLE)
            pc = cpu.r_pc()
            if profile:
                total[0] += r.cycles
                i = bisect.bisect_right(addrs, pc) - 1
                name = labels[i][1] if i >= 0 else '?'
                if zcode.fullmatch(name) or (zaddr and zfirst <= pc < zlast and not name.startswith('tr_')):
                    name = 'Z80'
                    if zaddr:
                        j = bisect.bisect_right(zaddr, pc) - 1
                        if j >= 0:
                            zpc = zl[j][1]
                            zins[zpc] += r.cycles
                            k = bisect.bisect_right(funcs, zpc) - 1
                            zfun[funcs[k] if k >= 0 else 0] += r.cycles
                hist[name] += r.cycles
                if args.lines and name == args.lines:
                    j = bisect.bisect_right(src_addr, pc) - 1
                    lhist[(src_addr[j] - sim.base, src[j][1]) if j >= 0 else (0, '?')] += r.cycles
                part[0] += r.cycles
            if pc in stops:
                return stops[pc]
            if pc == TRAP1:
                sim.gemdos()

    def resume():
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp))
        cpu.w_reg(R.A7, sp + 4)
    logic, picture = [0], [0]
    run_to(False, logic)
    c0 = {}
    b0 = 0
    for f in range(args.last):
        if args.auto:
            s, p, lives = auto_inputs(f)
        else:
            s, p = inputs(f)
            lives = cheats and f >= 1000
        mem.w8(sym['tr_inputs'], s)
        mem.w8(sym['tr_inputs'] + 1, p)
        if lives:
            for a, v in ((0xCDA0, 3), (0xC078, 0), (0xC079, 0x99)) if cheats else ((0xCDA0, 3),):
                mem.w8(block + 0x8000 + a - 0x10000, v)
        mem.w8(sym['vbl_pending'], 1)
        on = f >= args.first
        if f == args.first:
            c0 = {k: mem.r32(sym[k]) for k in ('cnt_cells', 'cnt_cells_bg2', 'cnt_sprites', 'cnt_cells_bad', 'cnt_full', 'cnt_part', 'cnt_tpass', 'cnt_chars', 'cnt_tdmg')}
            b0 = sim.blitter.cycles
        resume()
        run_to(on, logic)              # (the NMI and the foreground: to sim_frame_done, the picture inside)
        resume()
        run_to(on, logic)
    n = args.last - args.first
    print('cells drawn %.1f (bg2 behind %.1f, keys lost %.1f), sprites %.1f, full passes %.2f, column passes %.2f a '
          'frame' % tuple((mem.r32(sym[k]) - c0[k]) / n for k in ('cnt_cells', 'cnt_cells_bg2', 'cnt_cells_bad',
                                                                   'cnt_sprites', 'cnt_full', 'cnt_part')))
    print('text passes %.2f, characters %.1f, text cells damaged %.1f a frame' % tuple(
        (mem.r32(sym[k]) - c0[k]) / n for k in ('cnt_tpass', 'cnt_chars', 'cnt_tdmg')))
    print('frames %d-%d: %.0f CPU cycles a frame, Blitter %.0f' % (args.first, args.last, total[0] / n,
                                                                  (sim.blitter.cycles - b0) / n))
    for name, c in hist.most_common(args.top):
        print('%8.0f %5.1f%%  %s' % (c / n, 100 * c / total[0], name))
    if args.lines:
        print('inside %s (the sample after the instruction):' % args.lines)
        for (o, t), c in sorted(lhist.items()):
            print('%8.0f  %06X  %s' % (c / n, o, t))
    if args.z80:
        print('the translated code by function (call / rst target):')
        for pc, c in zfun.most_common(args.top):
            print('%8.0f %5.1f%%  %05X' % (c / n, 100 * c / total[0], pc))
        print('by instruction:')
        for pc, c in zins.most_common(args.top):
            print('%8.0f %5.1f%%  %05X' % (c / n, 100 * c / total[0], pc))


if __name__ == '__main__':
    main()
