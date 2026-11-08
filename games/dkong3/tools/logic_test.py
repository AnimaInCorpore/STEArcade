"""Whole-program lock-step test: translated 68000 code (Musashi) vs the Z80 reference.

Both run the same instruction sequences: the NMI is injected at the Nth visit of the
idle-loop head ($0249) on both sides, so RAM and registers must match exactly.

    python logic_test.py [frames] [--visits N]
"""
import argparse, os, random, re, subprocess, sys
from pathlib import Path
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import gen, z80x
from machine import DK3
from machine68k import CPUType, Machine, Register as R

from paths import ROOT, EXTRACTED, RT_INCLUDE, VASM, VLINK, build_dir
BUILD = build_dir("dkong3")
CODE = 0x10000
BLOCK = 0x110000        # (the code and the 256 KB table of the program lie below: test.bin is about 0x80000 bytes)
DISPATCH = 0x140000     # the swapped dispatch table, 256 KB
STACK = 0x0F000


def build(hooks=(gen.IDLE,), extra_roots=()):
    text, rep, em = gen.generate(hooks, extra_roots=extra_roots)
    BUILD.mkdir(exist_ok=True)
    (BUILD / "dkong3_code.s").write_text(text)
    (BUILD / "test_rt.s").write_text("""
	section text
z80_hook:	bra.s	z80_hook
z80_badpc:	bra.s	z80_badpc
z80_badjump:	bra.s	z80_badjump
z80_unsupported:	bra.s	z80_unsupported
z80_nmi_ret:	bra.s	z80_nmi_ret
	include "rtlib.s"
	include "natives.s"
	include "dkong3_code.s"
""")
    r = subprocess.run([str(VASM), "-Fvobj", "-quiet", "-nowarn=2047", "-I", str(RT_INCLUDE), "-I", str(Path(__file__).resolve().parents[1] / "src"), "-o", "test.o", "test_rt.s"], cwd=BUILD,
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
    def __init__(self, hooks=(gen.IDLE,)):
        self.binary, self.sym, self.rep = build(hooks)
        self.m = Machine(CPUType.M68000, 2048)
        self.cpu, self.mem = self.m.cpu, self.m.mem
        self.mem.w_block(CODE, self.binary)
        rom = gen.load_rom()
        self.mem.w_block(BLOCK, rom[:0x6000])
        self.mem.w_block(BLOCK - 0x8000, rom[0x8000:0xA000])      # $8000-$9FFF lie below the block (signed word index)
        self.ref = DK3()
        self.lastw = {}                      # address -> the pc of the reference's last store (printed at a mismatch)
        _wr = self.ref.cpu.wr8
        def wr(a, v):
            self.lastw[a] = self.ref.cpu.pc
            _wr(a, v)
        self.ref.cpu.wr8 = wr
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

    def set_inputs(self, in0, in1, dsw0, dsw1):
        for off, v in ((0x7A00, in0), (0x7A80, in1), (0x7B00, dsw0), (0x7B80, dsw1)):      # gen.IO_REDIRECT
            self.mem.w8(BLOCK + off, v)
        self.ref.in0, self.ref.in1, self.ref.dsw0, self.ref.dsw1 = in0, in1, dsw0, dsw1

    def ref_to_idle(self, cap=20_000_000):
        cpu = self.ref.cpu
        n = 0
        while True:
            cpu.step()
            n += 1
            if cpu.pc == gen.IDLE:
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
        if want["ix"] == 0x7C80 and got["ix"] == 0x7A80:        # (gen.PATCH_WORDS: the boot test's pointer to IN1)
            want["ix"] = 0x7A80
        errs = ["%s: got %X expected %X" % (k, got[k], want[k]) for k in want if got[k] != want[k]]
        mem68 = self.mem.r_block(BLOCK, 0x8000)
        n = 0
        dead = range(max(0, c.sp - 0x80), c.sp)      # popped stack bytes: not state
        for lo, hi in ((0x6000, 0x7000), (0x7400, 0x7800)):
            for a in range(lo, hi):
                if a in dead:
                    continue
                if mem68[a] != self.ref.rd8(a):
                    errs.append("mem[%04X]: got %02X expected %02X (the reference's last store: pc %04X)" % (a, mem68[a], self.ref.rd8(a), self.lastw.get(a, -1)))
                    n += 1
                    if n > 12:
                        break
        ref = self.ref
        rom = self.ref.rom
        bad = [a for a in range(0x6000) if mem68[a] != rom[a]]
        if bad:
            errs.append("the ROM was written at %s ..." % " ".join("%04X" % a for a in bad[:8]))
        for what, got, want in tuple(("latch $7E8%d" % i, mem68[0x7E80 + i] & 1, ref.latch[0x7E80 + i]) for i in range(1, 8)) + tuple(("sound latch $%04X" % a, mem68[a], ref.snd[a]) for a in (0x7C00, 0x7C80, 0x7D00)):
            if got != want:
                errs.append("%s: got %02X expected %02X" % (what, got, want))
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
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--cheat", action="store_true", help="MAME's cheats on both sides: credits, lives, and the stage poked while a game starts")
    ap.add_argument("--dsw0", type=lambda x: int(x, 0), default=0, help="DSW0: coinage, service, cabinet")
    ap.add_argument("--dsw1", type=lambda x: int(x, 0), default=0, help="DSW1: lives, bonus, difficulty")
    a = ap.parse_args()
    L = Lock()
    print("code instructions:", L.rep["instructions"], "unsupported:", len(L.rep["unsupported"]))
    rnd = random.Random(a.seed)
    L.set_inputs(0, 0, a.dsw0, a.dsw1)
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
        L.cpu.w_pc(L.sym["Z%04X_r" % gen.IDLE])
        if visits % a.visits == 0 and L.ref.nmi_mask:
            frame += 1
            if frame % 7 == 0:
                joy = rnd.choice([0, 0, 1, 2, 4, 8, 16, 17, 18, 5, 9])
            in0 = joy | (0x20 if (40 <= frame < 44 or (a.cheat and frame % 500 in (60, 61, 62))) else 0)
            in1 = 0x20 if (20 <= frame < 24 or (a.cheat and frame % 500 in (30, 31))) else 0                    # coin
            if a.cheat:
                pokes = {0x6BF1: 0x63, 0x601A: 6}
                if frame % 500 in range(63, 200):
                    pokes[0x601B] = (a.seed + frame // 500) % 3
                for ad, v in pokes.items():
                    L.ref.ram[ad - 0x6000] = v
                    L.mem.w8(BLOCK + ad, v)
            L.set_inputs(in0, in1, a.dsw0, a.dsw1)
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
            L.mem.w8(a5, gen.TOKEN & 255)
            L.mem.w8(a5 + 1, gen.TOKEN >> 8)
            L.cpu.w_reg(R.A5, a5)
            L.cpu.w_pc(L.sym["Z0066"])
            why = L.run68()
            if why != "z80_nmi_ret":
                print("68k NMI stopped:", why, "d7=%X" % (L.cpu.r_reg(R.D7) & 0xFFFF))
                return 1
            L.cpu.w_pc(L.sym["Z%04X_r" % gen.IDLE])            # the ret token jumps here: nothing pushed on a7
            if not L.compare("after NMI %d" % frame):
                return 1
            if frame % 20 == 0:
                print("frame", frame, "ok  ref pc/sp", hex(cpu.pc), hex(cpu.sp))
    print("lock-step OK:", frame, "frames")
    return 0


if __name__ == "__main__":
    sys.exit(main())


