"""Whole-program lock-step test: translated 68000 code (Musashi) vs the Z80 reference.

Both run the same instruction sequences: the NMI is injected at the Nth visit of the
idle-loop head ($02BD) on both sides, so RAM and registers must match exactly.

    python fullrun.py [frames] [--visits N]
"""
import argparse, os, random, re, subprocess, sys
from pathlib import Path
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import gen, bench, z80x
from machine import DKong
from machine68k import CPUType, Machine, Register as R

from paths import ROOT, EXTRACTED, RT_INCLUDE, VASM, VLINK, build_dir
BUILD = build_dir("dkong")
CODE = 0x10000
BLOCK = 0x40000
DISPATCH = 0x80000      # the swapped dispatch table, 256 KB
STACK = 0x0F000


def build(hooks=(0x2BD,), extra_roots=()):
    text, rep, em = gen.generate(hooks, extra_roots=extra_roots)
    BUILD.mkdir(exist_ok=True)
    (BUILD / "dk_code.s").write_text(text)
    (BUILD / "test_rt.s").write_text("""
	section text
z80_hook:	bra.s	z80_hook
z80_badpc:	bra.s	z80_badpc
z80_badjump:	bra.s	z80_badjump
z80_unsupported:	bra.s	z80_unsupported
z80_nmi_ret:	bra.s	z80_nmi_ret
	include "rtlib.s"
	include "dk_code.s"
""")
    r = subprocess.run([str(VASM), "-Fvobj", "-quiet", "-nowarn=2047", "-I", str(RT_INCLUDE), "-o", "test.o", "test_rt.s"], cwd=BUILD,
                       capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(r.stdout + r.stderr)
    r = subprocess.run([str(VLINK), "-brawbin1", "-Ttext", hex(CODE), "-Mtest.map", "-o", "test.bin", "test.o"],
                       cwd=BUILD, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(r.stdout + r.stderr)
    syms = {}
    for line in (BUILD / "test.map").read_text().splitlines():
        m = re.match(r"\s+0x([0-9a-f]{8})\s+(\S+?):", line)
        if m:
            syms[m.group(2)] = int(m.group(1), 16)
    return (BUILD / "test.bin").read_bytes(), syms, rep


class Lock:
    def __init__(self, hooks=(0x2BD,)):
        self.binary, self.sym, self.rep = build(hooks)
        self.m = Machine(CPUType.M68000, 2048)
        self.cpu, self.mem = self.m.cpu, self.m.mem
        self.mem.w_block(CODE, self.binary)
        rom = open(EXTRACTED / "dkong" / "cpu.rom", "rb").read()
        self.mem.w_block(BLOCK, rom)
        self.ref = DKong()
        self.stops = {self.sym[k]: k for k in ("z80_hook", "z80_badpc", "z80_badjump", "z80_unsupported", "z80_nmi_ret")}
        # the swapped dispatch table (256 KB), built by the runtime's routine
        w = self.cpu.w_reg
        w(R.A0, self.sym["z80_dispatch"])
        w(R.A1, DISPATCH)
        w(R.D0, gen.TABLE_ENTRIES)
        w(R.A7, STACK - 4)
        self.mem.w32(STACK - 4, self.sym["z80_hook"])
        self.cpu.w_sr(0x2700)
        self.cpu.w_pc(self.sym["z80_init_dispatch"])
        assert self.run68() == "z80_hook"
        self.reset68()

    def reset68(self):
        w = self.cpu.w_reg
        for r in (R.D0, R.D1, R.D2, R.D3, R.D4, R.D5, R.D6, R.D7, R.A0, R.A1, R.A2, R.A3):
            w(r, 0)
        w(R.A4, DISPATCH)
        w(R.A5, BLOCK + 0x6C00)
        w(R.A6, BLOCK)
        w(R.A7, STACK)
        w(R.ISP, STACK)
        self.cpu.w_sr(0x2700)
        self.cpu.w_pc(self.sym["Z0000"])
        self.mem.w16(BLOCK + 0x7FF0, 0)
        self.mem.w16(BLOCK + 0x7FF2, 0)

    def run68(self, budget=50_000_000):
        used = 0
        while used < budget:
            r = self.cpu.execute(20000)
            used += r.cycles if hasattr(r, "cycles") else 20000
            pc = self.cpu.r_pc()
            if pc in self.stops:
                return self.stops[pc]
        return "budget"

    def set_inputs(self, in0, in1, in2, dsw):
        for off, v in ((0x7E00, in0), (0x7E80, in1), (0x7F00, in2), (0x7F80, dsw)):
            self.mem.w8(BLOCK + off, v)
        self.ref.in0, self.ref.in1, self.ref.in2, self.ref.dsw0 = in0, in1, in2, dsw

    def ref_to_idle(self, cap=20_000_000):
        cpu = self.ref.cpu
        n = 0
        while True:
            cpu.step()
            n += 1
            if cpu.pc == 0x2BD:
                return n
            if n > cap:
                raise RuntimeError("reference did not reach the idle loop")

    def regs68(self):
        r = self.cpu.r_reg
        return {"a": r(R.D0) & 0xFF, "bc": z80x.swap16(r(R.D1)), "de": r(R.D2) & 0xFFFF, "hl": r(R.D3) & 0xFFFF,
                "ix": r(R.D4) & 0xFFFF, "iy": r(R.A2) & 0xFFFF,          # (z80x.FAST: IY in a2)
                "sp": (r(R.A5) - BLOCK) & 0xFFFF}

    def compare(self, tag):
        c = self.ref.cpu
        want = {"a": c.a, "bc": c.bc, "de": c.de, "hl": c.hl, "ix": c.ix, "iy": c.iy, "sp": c.sp}
        got = self.regs68()
        errs = ["%s: got %X expected %X" % (k, got[k], want[k]) for k in want if got[k] != want[k]]
        mem68 = self.mem.r_block(BLOCK, 0x8000)
        n = 0
        dead = range(max(0, c.sp - 0x80), c.sp)      # popped stack bytes: not state
        for lo, hi in ((0x6000, 0x7000), (0x7400, 0x7800)):
            for a in range(lo, hi):
                if a in dead:
                    continue
                if mem68[a] != self.ref.mem[a]:
                    errs.append("mem[%04X]: got %02X expected %02X" % (a, mem68[a], self.ref.mem[a]))
                    n += 1
                    if n > 12:
                        break
        if errs:
            print("MISMATCH", tag)
            for e in errs[:20]:
                print("   ", e)
            return False
        return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frames", nargs="?", type=int, default=100)
    ap.add_argument("--visits", type=int, default=3)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    L = Lock()
    print("code instructions:", L.rep["instructions"], "unsupported:", len(L.rep["unsupported"]))
    rnd = random.Random(a.seed)
    L.set_inputs(0, 0, 0, 0x80)
    visits = 0
    frame = 0
    joy = 0
    while frame < a.frames:
        L.ref_to_idle()
        why = L.run68()
        if why != "z80_hook":
            print("68k stopped:", why, "d7=%X" % (L.cpu.r_reg(R.D7) & 0xFFFF), "pc=%X" % L.cpu.r_pc())
            return 1
        visits += 1
        if not L.compare("visit %d (frame %d)" % (visits, frame)):
            return 1
        L.cpu.w_reg(R.A7, L.cpu.r_reg(R.A7) + 4)   # the hook pushed its resume label
        L.cpu.w_pc(L.sym["Z02BD_r"])
        if visits % a.visits == 0 and L.ref.nmi_mask:
            frame += 1
            if frame % 7 == 0:
                joy = rnd.choice([0, 0, 1, 2, 4, 8, 16, 17, 18])
            in2 = 0
            if 20 <= frame < 24: in2 |= 0x80
            if 40 <= frame < 44: in2 |= 0x04
            L.set_inputs(joy, 0, in2, 0x80)
            # reference NMI
            cpu = L.ref.cpu
            sp0, pc0 = cpu.sp, cpu.pc
            cpu.nmi()
            n = 0
            while not (cpu.sp == sp0 and cpu.pc == pc0):
                cpu.step()
                n += 1
                if n > 5_000_000:
                    raise RuntimeError("reference NMI did not return")
            # 68k NMI: token on the Z80 stack
            a5 = L.cpu.r_reg(R.A5) - 2
            L.mem.w8(a5, 0x01)
            L.mem.w8(a5 + 1, 0x40)
            L.cpu.w_reg(R.A5, a5)
            L.cpu.w_pc(L.sym["Z0066"])
            why = L.run68()
            if why != "z80_nmi_ret":
                print("68k NMI stopped:", why, "d7=%X" % (L.cpu.r_reg(R.D7) & 0xFFFF))
                return 1
            L.cpu.w_reg(R.A7, L.cpu.r_reg(R.A7) + 4)   # the hook pushed its resume label
            L.cpu.w_pc(L.sym["Z02BD_r"])
            if not L.compare("after NMI %d" % frame):
                return 1
            if frame % 20 == 0:
                print("frame", frame, "ok  ref pc/sp", hex(cpu.pc), hex(cpu.sp))
    print("lock-step OK:", frame, "frames")
    return 0


if __name__ == "__main__":
    sys.exit(main())


def fine_trace(L, max_instr=200000, stop_pc=0x2BD):
    """From a synced state: step the reference and the 68k one Z80 instruction at a
    time and report the first register divergence (instruction-level lock-step)."""
    import bisect
    from z80dis import decode
    labs = {v: int(k[1:5], 16) for k, v in L.sym.items() if re.fullmatch(r"Z[0-9A-F]{4}", k)}
    rom = L.ref.mem[:0x4000]
    c = L.ref.cpu
    prev = []
    for n in range(max_instr):
        pc = c.pc
        ins = decode(bytes(L.ref.mem[:0x4000]), pc) if pc < 0x4000 else None
        c.step()
        if ins and ins.mn in ("ldir", "lddr", "cpir", "cpdr"):
            while c.pc == pc:               # the reference repeats the instruction
                c.step()
        # run the 68k to the next instruction label
        steps = 0
        while True:
            L.cpu.execute(1)
            steps += 1
            p = L.cpu.r_pc()
            if p in labs or p in L.stops:
                break
            if steps > 100000:
                print("68k runaway after", ins.text if ins else pc)
                return False
        if p in L.stops:
            if L.stops[p] == "z80_nmi_ret" and c.pc == stop_pc:
                return True                 # the NMI returned on both sides
            print("68k stopped at", L.stops[p], "after", ins.text if ins else hex(pc))
            return False
        if labs[p] != c.pc:
            print("PC diverged after %04X %s: 68k at %04X, ref at %04X" % (pc, ins.text if ins else "?", labs[p], c.pc))
            for pp in prev[-6:]:
                print("   ", pp)
            return False
        want = {"a": c.a, "bc": c.bc, "de": c.de, "hl": c.hl, "ix": c.ix, "iy": c.iy, "sp": c.sp}
        got = L.regs68()
        bad = [k for k in want if want[k] != got[k]]
        prev.append("%04X %-20s a=%02X bc=%04X de=%04X hl=%04X f=%02X" % (pc, ins.text if ins else "?", c.a, c.bc, c.de, c.hl, c.f))
        if bad:
            print("REG diverged after %04X %s: %s" % (pc, ins.text if ins else "?",
                  ", ".join("%s got %X expected %X" % (k, got[k], want[k]) for k in bad)))
            for pp in prev[-8:]:
                print("   ", pp)
            return False
        if c.pc == stop_pc:
            return True
    return True
