"""The natives (src/natives.s, gen.py NATIVES) against the 6809 running the ROM's routines (machine.HyperSports, the
reference CPU), outside the game: random states and the edge cases the play never reaches.

    python games/hyperspt/tools/native_test.py [N]

* nat_div_A62B: N random states (D, X over every range: 0, below $1000, $1000-$7FFF, bit 15 set; the entry's C; Y and
  U), plus X = 0, 1, $0FFF, $1000, $7FFF, $8000, $FFFF; the 6809 runs from $A62B to its RTS's return, the 68000 from
  the native's label to the RTS's translation (patched to stop there).  Compared: A, B, X, Y, U, N Z V C, <$5B-$5F.
* nat_copy_4FBD / nat_copy_4FD2: random RAM; compared: the RAM $1000-$10FF, A, B, X, U, N Z V C.
The play's coverage gives the division small divisors only (below $1000), so its other paths are checked here.
"""
from pathlib import Path
import random
import sys

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from sim import Sim, TRAP1
from machine68k import Register as R
from machine import HyperSportsPort
from paths import ROOT, build_dir

RET = 0x7F00                        # (a return address pushed for the 6809: the reference stops when it gets there)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    run = ROOT / 'run' / 'hyperspt_sim'
    sim = Sim(str(run / 'HYPERSPT.PRG'), ram_kib=16384, run_dir=run)
    sim.mem.set_trace_mode(False)
    sym = {k: v + sim.base for k, v in sim.symbols(build_dir('hyperspt') / 'hyperspt_sim.map').items()}
    mem, cpu = sim.mem, sim.cpu
    base = sym['hs_mem']
    stops = {}
    for lab in ('M00A67A', 'M00A67D', 'M004FD1', 'M004FE6'):
        stops[sym[lab]] = lab
        mem.w16(sym[lab], 0x60FE)                   # bra.s * (the RTS not run: the test reads the state there)
    ref = HyperSportsPort()
    rnd = random.Random(5)
    bad = 0

    def run68(label, regs, c_in, ram):
        mem.w_block(base, bytes(ram))
        for r, v in zip((R.D0, R.D1, R.D2, R.D3, R.D4), regs):
            cpu.w_reg(r, v)
        cpu.w_reg(R.A6, sym['main_ctx'])
        cpu.w_reg(R.A3, base)
        cpu.w_reg(R.A4, base)
        cpu.w_reg(R.A2, base + 0xE000)
        cpu.w_reg(R.A5, base + 0x3700)
        cpu.w_sr(0x2700 | (0x11 if c_in else 0))      # (C and X: the native reads C)
        cpu.w_pc(sym[label])
        for _ in range(10000):
            cpu.execute(400)
            pc = cpu.r_pc()
            if pc in stops:
                break
            if pc == TRAP1 or sim.terminated:
                raise RuntimeError('stopped at %06x' % (pc - sim.base))
        else:
            raise RuntimeError('%s: no end' % label)
        out = [cpu.r_reg(r) for r in (R.D0, R.D1, R.D2, R.D3, R.D4)]
        return (out[0] & 255, out[1] & 255, out[2] & 0xFFFF, out[3] & 0xFFFF, out[4] & 0xFFFF,
                cpu.r_sr() & 0x0F, bytes(mem.r_block(base, 0x10000)), stops[pc])

    def run6809(pc, a, b, x, y, u, c_in, ram):
        m = ref
        m.mem[:] = ram
        m.mem[0x4000:] = m.rom[0x4000:]
        c = m.cpu
        c.a, c.b, c.x, c.y, c.u, c.dp = a, b, x, y, u, 0x30
        c.cc = 0x50 | (1 if c_in else 0)
        c.s = 0x3700 - 2
        m.mem[0x36FE], m.mem[0x36FF] = RET >> 8, RET & 255
        c.pc = pc
        for _ in range(200000):
            c.step()
            if c.pc == RET:
                return c.a, c.b, c.x, c.y, c.u, c.cc & 0x0F, bytes(m.mem)
        raise RuntimeError('6809: no return from %04X' % pc)

    # the division
    xs = [0, 1, 0x0FFF, 0x1000, 0x7FFF, 0x8000, 0xFFFF]
    cases = [(rnd.randrange(65536), x, rnd.randrange(2)) for x in xs for _ in range(6)]
    for _ in range(n):
        x = rnd.choice((0, rnd.randrange(1, 0x1000), rnd.randrange(0x1000, 0x8000), rnd.randrange(0x8000, 0x10000),
                        rnd.randrange(1, 64)))
        cases.append((rnd.randrange(65536), x, rnd.randrange(2)))
    for d, x, c_in in cases:
        y, u = rnd.randrange(65536), rnd.randrange(65536)
        ram = bytearray(rnd.randrange(256) for _ in range(0x10000))
        want = run6809(0xA62B, d >> 8, d & 255, x, y, u, c_in, ram)
        ram[0x36FE], ram[0x36FF] = RET >> 8, RET & 255      # (the same RAM: the reference's pushed return address)
        got = run68('nat_div_A62B', (d >> 8, d & 255, x, y, u), c_in, ram)
        wr, gr = want[6][0x305B:0x3060], got[6][0x305B:0x3060]
        if want[:6] != got[:6] or wr != gr:
            bad += 1
            if bad <= 8:
                print('div D=%04X X=%04X C=%d: 6809 A B X Y U NZVC %s <$5B> %s; native %s %s (%s)' % (
                    d, x, c_in, [hex(v) for v in want[:6]], wr.hex(), [hex(v) for v in got[:6]], gr.hex(), got[7]))
    print('division: %d states (X = 0: %d, X >= $1000: %d)' % (len(cases), sum(1 for c in cases if c[1] == 0),
                                                            sum(1 for c in cases if c[1] >= 0x1000)))
    # the copies
    for pc, label in ((0x4FBD, 'nat_copy_4FBD'), (0x4FD2, 'nat_copy_4FD2')):
        for _ in range(40):
            regs = [rnd.randrange(256), rnd.randrange(256)] + [rnd.randrange(65536) for _ in range(3)]
            c_in = rnd.randrange(2)
            ram = bytearray(rnd.randrange(256) for _ in range(0x10000))
            want = run6809(pc, *regs, c_in, ram)
            ram[0x36FE], ram[0x36FF] = RET >> 8, RET & 255
            got = run68(label, regs, c_in, ram)
            if want[:6] != got[:6] or want[6][0x1000:0x1100] != got[6][0x1000:0x1100]:
                bad += 1
                if bad <= 8:
                    print('%s: 6809 %s native %s' % (label, [hex(v) for v in want[:6]], [hex(v) for v in got[:6]]))
    print('copies: 80 states')
    print('%s: %d differ' % ('PASS' if not bad else 'FAIL', bad))
    return int(bad != 0)


if __name__ == '__main__':
    sys.exit(main())
