"""digdug.s's natives against the Z80 reference: nat_y0e4c (the sub CPU's sprite position copy, $0E4C) on random memory in
all its paths ($87F0 bit 3 set; plain; the flipped cabinet): the 8 KB of shared RAM (but the call's return word), A, B, DE and HL afterwards equal the
Z80 code's.   python native_test.py [cases]   (needs the --sim build)"""
import os, random, sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from machine68k import Register as R
from sim import Sim
from paths import ROOT, build_dir
from machine import load, DigDug
from z80 import Z80

cases = int(sys.argv[1]) if len(sys.argv) > 1 else 300
RUN = ROOT / "run" / "digdug_sim"
s = Sim(str(RUN / "DIGDUG.PRG"), ram_kib=16384, run_dir=RUN)
sym = {k: v + s.base for k, v in s.symbols(build_dir("digdug") / "digdug.map").items()}
cpu, mem = s.cpu, s.mem
rom = b"".join(load(f) for f in ("dd1a.5", "dd1a.6"))
rnd = random.Random(7)
STOP = sym["Y0E73"]


def z80(ram, a0, b0, c0):
    mem8 = bytearray(0x10000)
    mem8[:len(rom)] = rom
    mem8[0x8000:0xA000] = ram
    def rd(a): return mem8[a & 0xFFFF]
    def wr(a, v):
        if a >= 0x8000: mem8[a & 0xFFFF] = v
    c = Z80(rd, wr)
    c.pc, c.sp = 0x0E4C, 0x8F00
    c.b, c.c, c.a = b0, c0, a0
    c.sp -= 2; mem8[c.sp] = 0x34; mem8[c.sp + 1] = 0x12          # return to $1234
    while c.pc != 0x1234:
        c.step()
    return bytes(mem8[0x8000:0xA000]), c.a, c.b, (c.d << 8) | c.e, (c.h << 8) | c.l


def native(ram, a0, b0, c0):
    mem.w_block(sym["g_ram"], bytes(ram))
    cpu.w_sr(0x2700)
    for r in (R.D0, R.D1, R.D2, R.D3, R.D4, R.D5, R.D7):
        cpu.w_reg(r, 0)
    cpu.w_reg(R.D0, a0)
    cpu.w_reg(R.D1, (0x5500 | c0) if False else (c0 << 8) | b0)      # (BC byte swapped: B in the low byte)
    cpu.w_reg(R.A6, sym["g_block"])
    cpu.w_reg(R.A7, 0x8000)
    for r in (R.A0, R.A1, R.A2):
        cpu.w_reg(r, 0x1111111 * (1 + r - R.A0))
    cpu.w_pc(sym["nat_y0e4c"])
    for _ in range(100000):
        if cpu.r_pc() == STOP:
            break
        cpu.execute(1)
    else:
        raise AssertionError("nat_y0e4c did not reach the ret")
    for r, v in ((R.A0, 0x1111111), (R.A1, 0x2222222), (R.A2, 0x3333333)):
        assert cpu.r_reg(r) == v, "a%d changed" % (r - R.A0)
    return (bytes(mem.r_block(sym["g_ram"], 0x2000)), cpu.r_reg(R.D0) & 0xFF, cpu.r_reg(R.D1) & 0xFF,
            cpu.r_reg(R.D2) & 0xFFFF, cpu.r_reg(R.D3) & 0xFFFF, cpu.r_reg(R.D1) >> 8 & 0xFF)


bad = 0
for n in range(cases):
    ram = bytearray(rnd.randrange(256) for _ in range(0x2000))
    ram[0x07F0] = rnd.choice((0, 8, 0xFF, rnd.randrange(256)))
    ram[0x0400] = rnd.choice((0, 2, 4, 6, 0xFF, rnd.randrange(256)))
    a0, b0, c0 = rnd.randrange(256), rnd.choice((0x40, 1, 0)), rnd.randrange(256)
    want = z80(bytes(ram), a0, b0, c0)
    got = native(ram, a0, b0, c0)
    same = lambda x, y: x[:0xEF0] == y[:0xEF0] and x[0xF00:] == y[0xF00:]      # (the call's return word at $8EFE is the Z80's only)
    ok = same(want[0], got[0]) and want[1] == got[1] and want[2] == got[2] and want[3] == got[3] and want[4] == got[4] and got[5] == c0
    if not ok:
        bad += 1
        print("case %d: RAM %s, A %02X/%02X, B %02X/%02X, DE %04X/%04X, HL %04X/%04X, C %02X/%02X" % (
            n, same(want[0], got[0]), want[1], got[1], want[2], got[2], want[3], got[3], want[4], got[4], c0, got[5]))
        if bad > 5:
            break
print("nat_y0e4c: %d cases, %d differ" % (cases, bad))
sys.exit(1 if bad else 0)
