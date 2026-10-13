"""Tests of engine/z80mame.py (MAME's Z80, generated from z80.lst by engine/z80mame_gen.py) and of the M72 board's
sound CPU (engine/m72board.py).

    venv/bin/python engine/z80m72_test.py [--regen]

1. instruction tests: cycle counts (the documented T-states), the M-cycle steps (an access happens before its
   cycles come off icount; a slice ends after any step with icount <= 0 and the instruction goes on in the next
   run), abort_timeslice from an access, IM 0 with an RST from the data bus (13 cycles), IM 1/2, the EI delay, HALT,
   NMI (11 cycles, not at total cycle 0), and the flags against engine/z80.py (S Z H P/V N C) on random operands.
2. MAME comparison: MAME 0.289's rtype, the sound CPU traced by the debugger (totalcycles and all registers before
   every instruction) from its release from reset (frame 298, main CPU port 02 bit 4) to frame 400; the board runs
   from power on (main V30, scheduler, latch, RST buffer, YM2151 timers) and its Z80 must reproduce every step.
   Fixture build/z80m72/rtype_soundcpu.npz (made when missing and mame + the ROMs are there; --regen forces it).
"""
import os
import random
import shutil
import subprocess
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import ROOT
from z80mame import Z80Mame
from z80 import Z80

FAIL = []
FIX = ROOT / "build" / "z80m72"
MAME_ROMS = ROOT / "build" / "rtype" / "mame_roms"
TRACE_FROM, TRACE_TO = 290, 400


def check(cond, what):
    if not cond:
        FAIL.append(what)
        print("FAIL:", what)


class Bus:
    def __init__(self, code, at=0):
        self.m = bytearray(0x10000)
        self.m[at:at + len(code)] = code
        self.log = []
        self.cpu = None

    def rd(self, a):
        self.log.append(("r", a, self.cpu.executed()))
        return self.m[a]

    def wr(self, a, v):
        self.log.append(("w", a, self.cpu.executed()))
        self.m[a] = v

    def io_in(self, p):
        self.log.append(("i", p, self.cpu.executed()))
        return 0x5A

    def io_out(self, p, v):
        self.log.append(("o", p, self.cpu.executed()))
        if self.on_out:
            self.on_out(p, v)

    on_out = None


def make(code, vector=0xFF, **regs):
    bus = Bus(bytes.fromhex(code.replace(" ", "")))
    c = Z80Mame(bus.rd, bus.wr, bus.io_in, bus.io_out, lambda: vector)
    bus.cpu = c
    for k, v in regs.items():
        setattr(c, k, v)
    starts = []
    c.hook = lambda: starts.append((c.total + c.executed(), c.PC))
    c.starts = starts
    return c, bus


def run(c, n):
    ran = c.run(n)
    c.total += ran
    return ran


def unit_tests():
    n0 = len(FAIL)
    timings = [("00", 4), ("3E 12", 7), ("DD 21 12 34", 14), ("DD 34 05", 23), ("CB 46", 12), ("CB 40", 8),
               ("DD CB 05 46", 20), ("DD CB 05 06", 23), ("ED B0", 21), ("10 FE", 13), ("18 00", 12), ("20 00", 7),
               ("C9", 10), ("C0", 5), ("CD 00 00", 17), ("C4 00 00", 10), ("E3", 19), ("ED 57", 9), ("D3 10", 11),
               ("DB 10", 11), ("ED A3", 16), ("ED B3", 21), ("F5", 11), ("C1", 10), ("09", 11), ("ED 42", 15),
               ("ED 67", 18), ("36 12", 10), ("DD 36 01 12", 19), ("2A 00 00", 16), ("22 00 00", 16), ("D9", 4),
               ("F9", 6), ("03", 6), ("34", 11), ("ED 4D", 14), ("ED 45", 14), ("E9", 4), ("FF", 11), ("ED 46", 8),
               ("ED 78", 12), ("ED 79", 12), ("DD DD 00", 12), ("DD 00", 8), ("ED 00", 8), ("08", 4)]
    for code, exp in timings:
        c, _ = make(code + " 00 00 00 00", B=2, C=2)
        run(c, 200)
        got = c.starts[1][0] - c.starts[0][0]
        check(got == exp, "cycles %s: %d (expected %d)" % (code, got, exp))
    # an access happens before its M-cycle's cycles come off icount: LD A,(nn) reads (nn) at 10
    c, bus = make("3A 34 12 00")
    run(c, 100)
    check(("r", 0x1234, 10) in bus.log, "LD A,(nn) read time: %s" % bus.log[:4])
    # slices end after a step with icount <= 0 and the instruction goes on in the next run
    c, bus = make("3A 34 12 00")
    ran = run(c, 5)                                     # opcode fetch 4, then the first operand read (3): 7
    check(ran == 7 and c.PC == 1 and not any(a == 0x1234 for _, a, _ in bus.log), "suspend: ran %d PC %X" % (ran, c.PC))
    bus.log.clear()
    ran = run(c, 4)                                     # the second operand (3), then (nn) (3): 6, done
    check(ran == 6 and bus.log == [("r", 2, 0), ("r", 0x1234, 3)] and c.A == 0,
          "resume: ran %d %s" % (ran, bus.log))
    check(len(c.starts) == 1, "no new instruction yet")
    run(c, 1)
    check(len(c.starts) == 2 and c.starts[1] == (13, 3), "next instruction %s" % c.starts)
    # abort_timeslice from an OUT: the run ends after the I/O step, the rest is stolen
    c, bus = make("D3 10 00 00")
    bus.on_out = lambda p, v: c.abort()
    ran = run(c, 100)
    check(ran == 11 and c.PC == 2, "abort at OUT: ran %d PC %X" % (ran, c.PC))
    # IM 0: the RST on the data bus, 13 cycles; the EI delay
    c, bus = make("FB 00 00 00", vector=0xEF, SP=0x8000)
    c.set_input("irq", 1)
    run(c, 30)
    check([p for _, p in c.starts[:3]] == [0, 1, 0x28] and c.starts[2][0] == 4 + 4 + 13,
          "IM0 RST 28 after EI; NOP: %s" % c.starts[:3])
    check(bus.m[0x7FFE] == 2 and bus.m[0x7FFF] == 0 and c.iff1 == 0, "IM0 pushed %02X%02X" % (bus.m[0x7FFF], bus.m[0x7FFE]))
    # IM 1 and IM 2
    c, bus = make("ED 56 FB 00 00", SP=0x8000)
    c.set_input("irq", 1)
    run(c, 40)
    check(c.starts[3] == (8 + 4 + 4 + 13, 0x38), "IM1: %s" % c.starts[:4])
    c, bus = make("ED 5E FB 00 00", vector=0x10, SP=0x8000, I=0x40)
    bus.m[0x4010:0x4012] = b"\x00\x30"
    c.set_input("irq", 1)
    run(c, 50)
    check(c.starts[3] == (8 + 4 + 4 + 19, 0x3000), "IM2: %s" % c.starts[:4])
    # HALT: the PC after it is pushed; 4 cycles per halted fetch
    c, bus = make("FB 76 00 00", vector=0xFF, SP=0x8000)
    run(c, 30)
    check(c.halt_ == 1 and c.PC == 2, "halted at %X" % c.PC)
    c.set_input("irq", 1)
    t = c.total
    run(c, 30)
    t += -t % 4                                        # (the run may have stopped inside a halted fetch)
    check(c.halt_ == 0 and (t + 13, 0x38) in c.starts and bus.m[0x7FFE] == 2,
          "HALT left by IRQ: %s" % c.starts)
    # NMI: 11 cycles to $66, IFF1 off, IFF2 kept; an edge at total cycle 0 (RESET's moment) is not taken
    c, bus = make("FB 00 00 00", SP=0x8000)
    c.set_input("nmi", 1, total_cycles=0)
    run(c, 8)
    check(all(p != 0x66 for _, p in c.starts), "NMI at total 0")
    c.set_input("nmi", 0)
    c.set_input("nmi", 1, total_cycles=8)
    run(c, 20)
    check(c.starts[2] == (8 + 11, 0x66) and c.iff1 == 0 and c.iff2 == 1, "NMI: %s iff %d%d" % (c.starts[:3], c.iff1, c.iff2))
    # flags against engine/z80.py (documented flags)
    rnd = random.Random(1)
    ops = ["80", "88", "90", "98", "A0", "A8", "B0", "B8", "04", "05", "27", "ED 44", "CB 00", "CB 08", "CB 10",
           "CB 18", "CB 20", "CB 28", "CB 38", "17", "1F", "07", "0F", "2F", "37", "3F", "09", "ED 4A", "ED 42"]
    bad = 0
    for _ in range(3000):
        op = rnd.choice(ops)
        a, f, b, h, l, cc = (rnd.randrange(256) for _ in range(6))
        code = bytes.fromhex(op.replace(" ", "")) + b"\x00"
        ref = Z80(lambda x: code[x] if x < len(code) else 0, lambda x, v: None)
        ref.a, ref.f, ref.b, ref.c, ref.h, ref.l = a, f, b, cc, h, l
        ref.step()
        m, _ = make(op + " 00", A=a, B=b, C=cc, H=h, L=l)
        m.set_f(f)
        while len(m.starts) < 2:
            run(m, 1)
        mf = m.get_f()
        if (m.A, mf & 0xD7, m.H, m.L) != (ref.a, ref.f & 0xD7, ref.h, ref.l):
            bad += 1
            if bad < 5:
                print("  flags %s A=%02X F=%02X B=%02X: mame-core A=%02X F=%02X, z80.py A=%02X F=%02X" % (
                    op, a, f, b, m.A, mf, ref.a, ref.f))
    check(bad == 0, "flags differ from z80.py in %d of 3000 cases" % bad)
    print("instruction tests: %d failures" % (len(FAIL) - n0))


# ---- 2. MAME comparison ----------------------------------------------------------------------------------------------
LUA = r'''
local dbg = manager.machine.debugger
local snd = manager.machine.devices[":soundcpu"]
local frame = 0
local on = false
sub = emu.register_frame_done(function()
  frame = frame + 1
  if frame == %d then
    dbg:command('trace trace.txt,soundcpu,noloop,{tracelog "%%d %%04X %%04X %%04X %%04X %%04X %%04X %%04X %%04X %%04X %%04X %%04X %%04X %%02X %%02X %%X %%X %%X %%X ",totalcycles,pc,af,bc,de,hl,ix,iy,sp,af2,bc2,de2,hl2,r,i,im,iff1,iff2,halt}')
    on = true
  elseif frame == %d then
    dbg:command('trace off,soundcpu')
    on = false
  end
  if on then dbg.visible_cpu = snd end
end)
dbg:command('go')
'''


def fixture(regen):
    out = FIX / "rtype_soundcpu.npz"
    if out.exists() and not regen:
        return out
    if not shutil.which("mame") or not (MAME_ROMS / "rtype").is_dir():
        return None
    FIX.mkdir(parents=True, exist_ok=True)
    print("  running mame rtype to frame %d (sound CPU trace, ~1 minute)" % TRACE_TO)
    with tempfile.TemporaryDirectory(dir=FIX) as tmp:       # a fresh directory: MAME writes cfg/ there
        with open(os.path.join(tmp, "t.lua"), "w") as f:
            f.write(LUA % (TRACE_FROM, TRACE_TO))
        subprocess.run(["mame", "rtype", "-rompath", str(MAME_ROMS), "-debug", "-debugger", "none",
                        "-autoboot_script", "t.lua", "-window", "-video", "none", "-sound", "none", "-nothrottle",
                        "-skip_gameinfo", "-seconds_to_run", str(TRACE_TO // 55 + 2)],
                       cwd=tmp, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cyc, regs = [], []
        with open(os.path.join(tmp, "trace.txt")) as f:
            for ln in f:
                if not ln.strip() or ln.startswith("   ("):
                    continue
                p = ln.split(" ", 19)
                cyc.append(int(p[0]))
                regs.append([int(x, 16) for x in p[1:19]])
    np.savez_compressed(out, cyc=np.array(cyc, np.int64), regs=np.array(regs, np.uint16))
    return out


def mame_test(regen):
    path = fixture(regen)
    if path is None:
        print("MAME comparison skipped (no mame or no ROMs in %s)" % MAME_ROMS)
        return
    import m72board
    z = np.load(path)
    cyc, regs = z["cyc"].tolist(), [tuple(r) for r in z["regs"].tolist()]
    b = m72board.M72("rtype")
    ex = b.sound.core
    cpu = ex.cpu
    rec = []
    cpu.hook = lambda: rec.append((ex.total + cpu.executed(), cpu.regs()))
    names = "pc af bc de hl ix iy sp af2 bc2 de2 hl2 r i im iff1 iff2 halt".split()
    k = 0
    while k < len(cyc) and b.frame < TRACE_TO + 5:
        b.run_frame()
        for c, r in rec:
            if k == len(cyc):
                break
            if (c, r) != (cyc[k], regs[k]):
                diff = ["%s %X/%X" % (n, x, y) for n, x, y in zip(names, r, regs[k]) if x != y]
                check(False, "sound CPU step %d (frame %d): totalcycles %d, MAME %d; %s" % (
                    k, b.frame, c, cyc[k], " ".join(diff)))
                return
            k += 1
        rec.clear()
    check(k == len(cyc), "board stopped after %d of %d steps" % (k, len(cyc)))
    print("MAME comparison: %d sound CPU steps equal (totalcycles and registers), frames %d-%d" % (
        k, TRACE_FROM, TRACE_TO))


def main():
    unit_tests()
    mame_test("--regen" in sys.argv)
    print("FAILURES: %d" % len(FAIL) if FAIL else "all tests passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
