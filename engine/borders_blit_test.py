"""Exercise the shared short-HOG dispatcher without game ROMs.

Compare split copies with one unsplit Blitter operation, including masked pixels,
register endpoints, reverse increments and 64 KB crossings. Print CPU+bus costs.
Use --include DIR to test a saved borders.s for before/after comparisons.
"""
import argparse
from pathlib import Path
import random
import subprocess
import tempfile

from machine68k import Register as R
from paths import VASM, VLINK, RT_INCLUDE
from sim import Sim

STOP = 0x700
SRC = 0x30ff80
DST = 0x32ff80
SIZE = 0x10000


def build(folder, include):
    source = folder / 'test.s'
    source.write_text('''
        include "borders.s"
        section text,code
start:  rts
        borders_blit_go
        section bss,bss
        borders_vars
''')
    obj, prg, symbols = (folder / n for n in ('test.o', 'test.prg', 'test.map'))
    subprocess.run([VASM, '-Fvobj', '-quiet', '-I', str(include), '-o', str(obj), str(source)], check=True)
    subprocess.run([VLINK, '-b', 'ataritos', '-s', '-o', str(prg), '-M' + str(symbols), str(obj)], check=True)
    return prg, symbols


def run(prg, symbols, entry_name, copies_only, fills_only, allow_long):
    sim = Sim(str(prg), ram_kib=16384)
    mem, cpu = sim.mem, sim.cpu
    entry = sim.base + sim.symbols(symbols)[entry_name]
    rng = random.Random(68000)
    data = rng.randbytes(SIZE)
    background = rng.randbytes(SIZE)
    total = cpu_total = bus_total = longest = count = 0
    cases = []
    for x in (1, 2, 3, 4, 8, 16, 17, 20, 28, 32, 33, 40, 56, 64, 84):
        for y in (1, 2, 4, 8, 16, 31):
            for op in (0, 3, 6, 15):
                for masked in (False, True):
                    cases.append((x, y, op, masked, 0, 2))
    for shift in range(16):
        for flags in (0, 0x40, 0x80, 0xc0):
            for x in (1, 2, 4):
                for step in (2, -2):
                    for y in (4, 16):
                        for masked in (False, True):
                            cases.append((x, y, 3, masked, flags | shift, step))
    if copies_only:
        cases = [c for c in cases if not c[3] and c[2] in (0, 3, 15) and not c[4]]
    if fills_only:
        cases = [c for c in cases if not c[4]]
    # Track actual passes, independently of the dispatcher's choice of piece.
    original = sim.blitter.run
    passes = []

    def tracked():
        before = sim.blitter.cycles
        assert sim.io[0xa3c] & 0x40, 'non-HOG pass'
        original()
        passes.append(sim.blitter.cycles - before)

    sim.blitter.run = tracked
    for x, y, op, masked, skew, step in cases:
        source = SRC + (0x4000 if step < 0 else 0)
        dest = DST + (0x4000 if step < 0 else 0)
        registers = {0x20: step, 0x22: 256 - (x - 1) * step,
                     0x24: source, 0x28: 0x5aa5 if masked else 0xffff,
                     0x2a: 0x3c3c if masked and x > 2 else 0xffff,
                     0x2c: 0xa55a if masked else 0xffff,
                     0x2e: step, 0x30: 256 - (x - 1) * step,
                     0x32: dest, 0x36: x, 0x38: y, 0x3a: (0 if fills_only else 0x0200) | op,
                     0x3c: 0, 0x3d: skew}

        def setup():
            mem.set_trace_mode(False)
            mem.w_block(SRC, data)
            mem.w_block(DST, background)
            for off, value in registers.items():
                size = 4 if off in (0x24, 0x32) else 1 if off >= 0x3c else 2
                value &= (1 << (8 * size)) - 1
                sim.io[0xa00 + off:0xa00 + off + size] = value.to_bytes(size, 'big')
            mem.w_block(0xff8000, bytes(sim.io))
            sim.blitter.cycles = 0
            sim.blitter.upper = sim.blitter.lower = 0

        setup()
        original()
        expected = bytes(mem.r_block(DST, SIZE))
        endpoints = bytes(sim.io[0xa20:0xa3c])
        setup()
        cpu.w_sr(0x2700)
        cpu.w_reg(R.A7, 0x8000)
        mem.w32(0x8000, STOP)
        cpu.w_pc(entry)
        preserved = [(reg, rng.randrange(0x100000000)) for reg in
                     (R.D0, R.D1, R.D2, R.D3, R.D4, R.D5, R.D6, R.D7,
                      R.A0, R.A1, R.A2, R.A3, R.A4, R.A5, R.A6)]
        for reg, value in preserved:
            cpu.w_reg(reg, value)
        mem.set_trace_mode(True)
        used = 0
        passes.clear()
        for _ in range(100000):
            if cpu.r_pc() == STOP:
                break
            used += cpu.execute(1).cycles
        else:
            raise AssertionError(('did not return', cases[count]))
        actual = bytes(mem.r_block(DST, SIZE))
        assert actual == expected, ('pixels', cases[count])
        assert bytes(sim.io[0xa20:0xa3c]) == endpoints, ('registers', cases[count])
        for reg, value in preserved:
            assert cpu.r_reg(reg) == value, ('CPU register', reg, cases[count])
        assert cpu.r_reg(R.A7) == 0x8004, ('stack', cases[count])
        longest = max(longest, max(passes, default=0))
        bus = sim.blitter.cycles
        total += used + bus
        cpu_total += used
        bus_total += bus
        count += 1
    sim.m.cleanup()
    print(f'{count} split/unsplit pixel, endpoint and register checks passed; '
          f'CPU {cpu_total}, bus {bus_total}, total {total}; longest HOG pass {longest}')
    assert allow_long or longest <= 256, ('HOG limit', longest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--include', type=Path, default=RT_INCLUDE)
    parser.add_argument('--entry', help='one entry point; default tests all current dispatch paths')
    parser.add_argument('--copies-only', action='store_true')
    parser.add_argument('--fills-only', action='store_true')
    parser.add_argument('--allow-long', action='store_true', help='report historical oversized passes without failing')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='border-blit-') as directory:
        prg, symbols = build(Path(directory), args.include)
        run(prg, symbols, args.entry or 'blit_go', args.copies_only, args.fills_only, args.allow_long)
        if not args.entry and not args.copies_only and not args.fills_only and args.include.resolve() == RT_INCLUDE.resolve():
            run(prg, symbols, 'blit_go_copy', True, False, args.allow_long)
            run(prg, symbols, 'blit_go_fill', False, True, args.allow_long)


if __name__ == '__main__':
    main()
