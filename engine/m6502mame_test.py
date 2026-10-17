"""Tests of engine/m6502mame.py (MAME's NMOS 6502, generated from om6502.lst by engine/m6502mame_gen.py).

    venv/bin/python engine/m6502mame_test.py [--regen]

1. instruction tests (a flat 64 KB bus): cycle counts (the documented NMOS counts, page crossings, taken branches),
   the bus accesses of the addressing modes with their cycles (dummy reads at the unfixed address, the
   read-modify-write instructions' dummy write of the old value, JSR/RTS/RTI's dummy reads, zero page wrap, JMP
   ($xxFF)), the reset sequence, slices ending after an access and the instruction going on in the next run,
   abort_timeslice from a write, BRK/RTI, IRQ (pushed B clear, the CLI/SEI/PLP delay, RTI's none), NMI (edge only,
   not at total cycle 0, taking over a BRK whose vector is not fetched yet), ADC/SBC in binary and decimal mode
   (values worked out by hand from m6502.cpp's do_adc_d / do_sbc_d), KIL.
2. MAME comparisons: MAME 0.289's gauntlet, the sound CPU (audiocpu) traced by the debugger (totalcycles, PC A X Y P
   S before every instruction, the "(interrupted at ...)" notes) and every bus access logged by Lua read/write taps
   on its program space (address, data, machine time -> cycles; the debugger's own reads, done with side effects
   disabled, are left out).  The core runs in random slices and must reproduce every access (same cycle, address
   and data; the I/O reads and the RAM's power-on contents come from the log) and every trace line; the interrupts
   are replayed from the notes (the line is held for the instruction before the interrupted one: only its last
   prefetch samples it).
   a. gauntlet's own sound program from its release from reset (the first 2,000,000 accesses, ~1.1 s);
   b. a test program patched into the audiocpu ROM region (reset/IRQ/NMI vectors too): every opcode but KIL in
      three register/flag set-ups (page crossings, zero page wrap, decimal mode), branches taken / not / across
      pages both ways, JSR/RTS, JMP abs / ($xxFF), BRK, RTI, and IRQs where a PLP happens to clear I;
   c. another patched program: ADC and SBC in decimal mode for every A, operand and carry (918k instructions,
      trace only).
   Fixtures in build/m6502mame/*.npz (made when missing and mame + the ROMs are there; --regen forces it).
3. speed: cycles per second of the core on (2c)'s program with a plain bytearray bus.
"""
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import ROOT, EXTRACTED
from m6502mame import M6502Mame
from m6502mame_ops import OPS

FAIL = []
FIX = ROOT / "build" / "m6502mame"
MAME_ROMS = ROOT / "build" / "gauntlet" / "mame_roms"
ASPC = 10 ** 18 // 1789772                   # HZ_TO_ATTOSECONDS(14.318181 MHz / 8 as MAME's u32 clock)


def check(cond, what):
    if not cond:
        FAIL.append(what)
        print("FAIL:", what)


# ---- 1. instruction tests ----------------------------------------------------------------------------------------
class Bus:
    def __init__(self, code, at=0x0200):
        self.m = bytearray(0x10000)
        self.m[at:at + len(code)] = code
        self.m[0xFFFC], self.m[0xFFFD] = at & 0xFF, at >> 8
        self.log = []
        self.cpu = None
        self.on_wr = None

    def rd(self, a):
        self.log.append(("r", a, self.cpu.total_cycles()))
        return self.m[a]

    def wr(self, a, v):
        self.log.append(("w", a, v, self.cpu.total_cycles()))
        self.m[a] = v
        if self.on_wr:
            self.on_wr(a, v)


def make(code, at=0x0200, **regs):
    bus = Bus(bytes.fromhex(code.replace(" ", "")), at)
    acks = []
    c = M6502Mame(bus.rd, bus.wr, acks.append)
    bus.cpu = c
    starts = []

    def hook():
        if not starts:                                   # the registers once the reset sequence has set I and S
            for k, v in regs.items():
                setattr(c, k, v)
        starts.append((c.total_cycles(), c.NPC))
    c.hook = hook
    c.starts, c.acks = starts, acks
    return c, bus


def steps(c, k):
    """run until k more instructions have started (the run that starts the last one also does its first access)"""
    want = len(c.starts) + k
    while len(c.starts) < want:
        c.run(1)


def between(bus, t, t1):
    """the accesses in [t, t1) with their cycles relative to t"""
    return [e[:-1] + (e[-1] - t,) for e in bus.log if t <= e[-1] < t1]


def unit_tests():
    n0 = len(FAIL)
    # the reset sequence: PC, PC, three stack reads (S $0100 -> $01FD), the vector, the prefetch: 8 cycles
    c, bus = make("EA EA")
    steps(c, 1)
    check(between(bus, 0, 8) == [("r", 0, 0), ("r", 0, 1), ("r", 0x100, 2), ("r", 0x1FF, 3), ("r", 0x1FE, 4),
                      ("r", 0xFFFC, 5), ("r", 0xFFFD, 6), ("r", 0x200, 7)] and c.starts == [(8, 0x200)]
          and c.SP == 0x1FD and c.P == 0x36 | 4, "reset: %s SP %X P %X" % (bus.log, c.SP, c.P))
    # cycle counts (from one instruction start to the next)
    timings = [("EA", 2), ("A9 12", 2), ("A5 12", 3), ("B5 12", 4), ("AD 34 12", 4), ("BD 34 12", 4),
               ("BD FF 12", 5), ("B9 FF 12", 5), ("A1 12", 6), ("B1 10", 5), ("B1 20", 6), ("85 12", 3), ("95 12", 4),
               ("8D 34 12", 4), ("9D 34 12", 5), ("99 34 12", 5), ("81 12", 6), ("91 10", 6), ("E6 12", 5),
               ("F6 12", 6), ("EE 34 12", 6), ("FE 34 12", 7), ("0A", 2), ("48", 3), ("08", 3), ("68", 4),
               ("28", 4), ("20 00 03", 6), ("4C 00 03", 3), ("6C 34 12", 5), ("00 00", 7), ("D0 00", 2),
               ("F0 00", 3), ("F0 FD", 4), ("18", 2), ("AA", 2), ("9A", 2), ("C9 12", 2), ("24 12", 3),
               ("2C 34 12", 4), ("E8", 2), ("1A", 2), ("04 12", 3), ("0C 34 12", 4), ("1C 34 12", 4),
               ("1C FF 12", 5), ("80 12", 2), ("07 12", 5), ("03 12", 8), ("13 10", 8), ("1B 34 12", 7),
               ("9B 34 12", 5), ("9C 34 12", 5), ("BB 34 12", 4), ("BB FF 12", 5), ("A7 12", 3), ("B3 10", 5),
               ("B3 20", 6), ("87 12", 3), ("CB 12", 2), ("0B 12", 2), ("6B 12", 2), ("E9 12", 2), ("F8", 2)]
    for code, exp in timings:
        c, bus = make(code + " EA EA EA", X=1, Y=1, P=0x36)
        bus.m[0x10], bus.m[0x11] = 0x34, 0x12              # ($10),Y: $1235, no crossing
        bus.m[0x20], bus.m[0x21] = 0xFF, 0x12              # ($20),Y: $1300, crossing
        bus.m[0x300] = 0xEA                                # JSR / JMP target
        steps(c, 2)
        got = c.starts[1][0] - c.starts[0][0]
        check(got == exp, "cycles %s: %d (expected %d)" % (code, got, exp))
    # the accesses of the addressing modes (t = the instruction's start; its opcode was fetched at t-1)
    cases = [
        # INC abs: the old value written back, then the new one
        ("EE 34 12", {}, {0x1234: 0x41},
         [("r", 0x201, 0), ("r", 0x202, 1), ("r", 0x1234, 2), ("w", 0x1234, 0x41, 3), ("w", 0x1234, 0x42, 4),
          ("r", 0x203, 5)]),
        # LDA abs,X across a page: the dummy read at the unfixed address
        ("BD FF 12", {"X": 1}, {}, [("r", 0x201, 0), ("r", 0x202, 1), ("r", 0x1200, 2), ("r", 0x1300, 3),
                                    ("r", 0x203, 4)]),
        # STA abs,X: always the dummy read
        ("9D 00 12", {"X": 1, "A": 0x77}, {}, [("r", 0x201, 0), ("r", 0x202, 1), ("r", 0x1201, 2),
                                               ("w", 0x1201, 0x77, 3), ("r", 0x203, 4)]),
        # INC abs,X: dummy read, read, two writes
        ("FE FF 12", {"X": 1}, {0x1300: 7}, [("r", 0x201, 0), ("r", 0x202, 1), ("r", 0x1200, 2), ("r", 0x1300, 3),
                                              ("w", 0x1300, 7, 4), ("w", 0x1300, 8, 5), ("r", 0x203, 6)]),
        # LDA (zp),Y across a page
        ("B1 10", {"Y": 1}, {0x10: 0xFF, 0x11: 0x12}, [("r", 0x201, 0), ("r", 0x10, 1), ("r", 0x11, 2),
                                                       ("r", 0x1200, 3), ("r", 0x1300, 4), ("r", 0x202, 5)]),
        # LDA (zp,X) with the pointer wrapping in zero page
        ("A1 FE", {"X": 1}, {0xFF: 0x34, 0x00: 0x12}, [("r", 0x201, 0), ("r", 0xFE, 1), ("r", 0xFF, 2),
                                                       ("r", 0x00, 3), ("r", 0x1234, 4), ("r", 0x202, 5)]),
        # LDA zp,X wraps in zero page, the dummy read at the base
        ("B5 F0", {"X": 0x20}, {}, [("r", 0x201, 0), ("r", 0xF0, 1), ("r", 0x10, 2), ("r", 0x202, 3)]),
        # JMP ($12FF): the high byte from $1200
        ("6C FF 12", {}, {0x12FF: 0x00, 0x1200: 0x05, 0x1300: 0x09},
         [("r", 0x201, 0), ("r", 0x202, 1), ("r", 0x12FF, 2), ("r", 0x1200, 3), ("r", 0x500, 4)]),
        # JSR: dummy stack read, push PC (of the high operand byte), read the high byte, the prefetch
        ("20 00 05", {}, {}, [("r", 0x201, 0), ("r", 0x1FD, 1), ("w", 0x1FD, 0x02, 2), ("w", 0x1FC, 0x02, 3),
                              ("r", 0x202, 4), ("r", 0x500, 5)]),
        # RTS: dummy reads at PC and the stack, the pulls, the dummy read at the pulled address
        ("60", {"SP": 0x1FB}, {0x1FC: 0x10, 0x1FD: 0x05},
         [("r", 0x201, 0), ("r", 0x1FB, 1), ("r", 0x1FC, 2), ("r", 0x1FD, 3), ("r", 0x510, 4), ("r", 0x511, 5)]),
        # PHA, PLA
        ("48", {"A": 0x99}, {}, [("r", 0x201, 0), ("w", 0x1FD, 0x99, 1), ("r", 0x201, 2)]),
        ("68", {"SP": 0x1F0}, {0x1F1: 0x80}, [("r", 0x201, 0), ("r", 0x1F0, 1), ("r", 0x1F1, 2), ("r", 0x201, 3)]),
        # ASL A: the dummy read at PC
        ("0A", {}, {}, [("r", 0x201, 0), ("r", 0x201, 1)]),
        # SLO (zp),Y: undocumented RMW, always the dummy read
        ("13 10", {"Y": 1}, {0x10: 0x00, 0x11: 0x12, 0x1201: 0x81},
         [("r", 0x201, 0), ("r", 0x10, 1), ("r", 0x11, 2), ("r", 0x1201, 3), ("r", 0x1201, 4),
          ("w", 0x1201, 0x81, 5), ("w", 0x1201, 0x02, 6), ("r", 0x202, 7)]),
    ]
    for code, regs, mem, exp in cases:
        c, bus = make(code + " EA EA", **regs)
        for a, v in mem.items():
            bus.m[a] = v
        steps(c, 2)
        got = between(bus, c.starts[0][0], c.starts[1][0])
        check(got == exp, "accesses %s: %s" % (code, got))
    # a taken branch across a page: operand, dummy read at PC, dummy read at the unfixed target, prefetch
    c, bus = make("D0 20", at=0x2F0, P=0x34)
    steps(c, 2)
    got = between(bus, c.starts[0][0], c.starts[1][0])
    check(got == [("r", 0x2F1, 0), ("r", 0x2F2, 1), ("r", 0x212, 2), ("r", 0x312, 3)] and c.starts[1][1] == 0x312,
          "branch across a page: %s" % got)
    c, bus = make("D0 FB", at=0x300, P=0x34)                # backwards across a page: $0302 - 5 = $02FD
    steps(c, 2)
    got = between(bus, c.starts[0][0], c.starts[1][0])
    check(got == [("r", 0x301, 0), ("r", 0x302, 1), ("r", 0x3FD, 2), ("r", 0x2FD, 3)], "branch back: %s" % got)

    # slices end after an access; the instruction goes on in the next run (steps() leaves the INC at $0200 after
    # its first operand read, at cycle 8)
    c, bus = make("EE 34 12 EA")
    steps(c, 1)
    bus.log.clear()
    ran = c.run(3)                                        # the second operand, the read of $1234, the old value back
    check(ran == 3 and len(c.starts) == 1 and bus.log == [("r", 0x202, 9), ("r", 0x1234, 10), ("w", 0x1234, 0, 11)],
          "slice 1: %s" % bus.log)
    bus.log.clear()
    ran = c.run(2)                                        # the new value, the prefetch; prefetch_end waits
    check(ran == 2 and bus.log == [("w", 0x1234, 1, 12), ("r", 0x203, 13)] and c.PC == 0x203 and len(c.starts) == 1,
          "slice 2: %s PC %X" % (bus.log, c.PC))
    c.run(1)
    check(c.PC == 0x204 and c.starts[1] == (14, 0x203), "slice 3: %s PC %X" % (c.starts, c.PC))
    # an IRQ raised between the prefetch and prefetch_end (in the next slice) is taken there
    c, bus = make("EA EA EA", P=0x30)
    bus.m[0xFFFE], bus.m[0xFFFF] = 0x00, 0x05
    steps(c, 1)                                           # NOP's dummy read done
    c.run(1)                                              # the prefetch of $0201 -> stop before prefetch_end
    c.set_input("irq", 1)
    steps(c, 2)
    check([p for _, p in c.starts] == [0x200, 0x201, 0x500] and c.acks == ["irq"], "IRQ at the slice edge: %s" %
          c.starts)
    # abort_timeslice from a write: the run ends after that access (MAME counts it: cycles_running - icount)
    c, bus = make("8D 00 10 EA EA", A=5)
    steps(c, 1)                                           # STA's first operand read done
    bus.on_wr = lambda a, v: c.abort()
    ran = c.run(100)                                      # the second operand, the write
    check(ran == 2 and c.executed() == 2 and len(c.starts) == 1 and bus.m[0x1000] == 5, "abort at a write: ran %d" % ran)
    bus.on_wr = None
    c.run(1)
    check(c.NPC == 0x203 and len(c.starts) == 1, "after abort: NPC %X" % c.NPC)
    # BRK / RTI: pushes PC+2 and P (B set), I set, vector $FFFE; RTI back to PC+2
    c, bus = make("00 EA EA EA", P=0x31 | 0x08, SP=0x1FF)
    bus.m[0xFFFE], bus.m[0xFFFF] = 0x00, 0x05
    bus.m[0x500] = 0x40
    steps(c, 3)
    check([p for _, p in c.starts] == [0x200, 0x500, 0x202] and bus.m[0x1FF] == 0x02 and bus.m[0x1FE] == 0x02
          and bus.m[0x1FD] == 0x39 and c.P == 0x39 and c.SP == 0x1FF and c.acks == [],
          "BRK/RTI: %s stack %02X %02X %02X P %X" % (c.starts, bus.m[0x1FF], bus.m[0x1FE], bus.m[0x1FD], c.P))
    # IRQ: taken when the line is held and I clear; B clear in the pushed P; RTI comes back to the instruction
    c, bus = make("EA EA EA EA", P=0x30, SP=0x1FF)
    bus.m[0xFFFE], bus.m[0xFFFF] = 0x00, 0x05
    bus.m[0x500] = 0x40
    steps(c, 1)
    c.set_input("irq", 1)
    steps(c, 1)                                           # the NOP at $0200 ends sampling the line: IRQ at $0201
    c.set_input("irq", 0)
    steps(c, 2)
    check([p for _, p in c.starts] == [0x200, 0x201, 0x500, 0x201] and c.starts[2][0] - c.starts[1][0] == 7
          and bus.m[0x1FD] == 0x20 and bus.m[0x1FE] == 0x01 and c.acks == ["irq"],
          "IRQ: %s pushed P %02X" % (c.starts, bus.m[0x1FD]))
    # CLI: the instruction after it still runs before the IRQ; SEI: the IRQ is taken after it; PLP likewise
    for code, p0, exp in [("58 EA EA EA", 0x34, [0x200, 0x201, 0x202, 0x500]),
                          ("78 EA EA EA", 0x30, [0x200, 0x201, 0x500]),
                          ("28 EA EA EA", 0x34, [0x200, 0x201, 0x202, 0x500]),
                          ("40 EA", 0x34, [0x200, 0x300, 0x500])]:
        c, bus = make(code, P=p0, SP=0x1F0)
        bus.m[0x1F1], bus.m[0x1F2], bus.m[0x1F3] = 0x30, 0x00, 0x03   # P, PC for PLP / RTI
        bus.m[0xFFFE], bus.m[0xFFFF] = 0x00, 0x05
        c.set_input("irq", 1)
        steps(c, len(exp))
        check([p for _, p in c.starts] == exp, "I delay %s: %s" % (code, [hex(p) for _, p in c.starts]))
    # NMI: an edge; not at total cycle 0; vector $FFFA; level held: no second NMI
    c, bus = make("EA EA EA EA EA EA", P=0x34)
    bus.m[0xFFFA], bus.m[0xFFFB] = 0x00, 0x06
    bus.m[0x600:0x604] = b"\xEA\xEA\xEA\xEA"
    c.set_input("nmi", 1, total_cycles=0)
    steps(c, 3)
    check(all(p != 0x600 for _, p in c.starts), "NMI at total 0: %s" % c.starts)
    c.set_input("nmi", 0)
    c.set_input("nmi", 1, total_cycles=c.total_cycles())
    steps(c, 4)
    check([p for _, p in c.starts[3:]] == [0x203, 0x600, 0x601, 0x602] and c.acks == ["nmi"], "NMI: %s" % c.starts)
    # NMI during a BRK's pushes: the BRK takes the NMI vector (B set in the pushed P: a BRK)
    c, bus = make("00 EA EA", P=0x30, SP=0x1FF)
    bus.m[0xFFFA], bus.m[0xFFFB] = 0x00, 0x06
    bus.m[0xFFFE], bus.m[0xFFFF] = 0x00, 0x05
    bus.on_wr = lambda a, v: c.set_input("nmi", 1, 100) if a == 0x1FE else None
    steps(c, 2)
    check(c.starts[1][1] == 0x600 and bus.m[0x1FD] == 0x30 and c.acks == ["nmi"] and c.nmi_pending == 0,
          "NMI over BRK: %s P %02X" % (c.starts, bus.m[0x1FD]))
    # ADC / SBC: (A, operand, P in) -> (A, P out); P = $30 | flags
    adc = [(0x50, 0x50, 0x30, 0xA0, 0xF0), (0x01, 0xFF, 0x30, 0x00, 0x33), (0xFF, 0x01, 0x31, 0x01, 0x31),
           (0x80, 0x80, 0x30, 0x00, 0x73),
           (0x12, 0x34, 0x38, 0x46, 0x38), (0x58, 0x46, 0x39, 0x05, 0xF9), (0x15, 0x26, 0x38, 0x41, 0x38),
           (0x81, 0x92, 0x38, 0x73, 0x79), (0x99, 0x01, 0x38, 0x00, 0xB9), (0x09, 0x01, 0x38, 0x10, 0x38),
           (0x99, 0x00, 0x39, 0x00, 0xB9), (0x0F, 0x0F, 0x38, 0x14, 0x38), (0x79, 0x00, 0x39, 0x80, 0xF8),
           (0x00, 0x00, 0x38, 0x00, 0x3A)]
    sbc = [(0x50, 0xB0, 0x31, 0xA0, 0xF0), (0x00, 0x01, 0x31, 0xFF, 0xB0), (0x05, 0x05, 0x31, 0x00, 0x33),
           (0x46, 0x12, 0x39, 0x34, 0x39), (0x40, 0x13, 0x39, 0x27, 0x39), (0x32, 0x02, 0x38, 0x29, 0x39),
           (0x00, 0x01, 0x39, 0x99, 0xB8), (0x21, 0x34, 0x39, 0x87, 0xB8), (0x80, 0x01, 0x39, 0x79, 0x79)]
    for name, op, cases in (("ADC", "69", adc), ("SBC", "E9", sbc)):
        for a, v, p, ea, ep in cases:
            c, bus = make("%s %02X EA" % (op, v), A=a, P=p)
            steps(c, 2)
            check((c.A, c.P) == (ea, ep), "%s A=%02X #%02X P=%02X: A=%02X P=%02X (expected %02X %02X)" % (
                name, a, v, p, c.A, c.P, ea, ep))
    # KIL: reads $FFFF forever, no next instruction
    c, bus = make("02 EA")
    steps(c, 1)
    c.run(50)
    check(len(c.starts) == 1 and bus.log[-1][:2] == ("r", 0xFFFF), "KIL: %s" % bus.log[-3:])
    print("instruction tests: %d failures" % (len(FAIL) - n0))


# ---- 2. MAME comparisons -----------------------------------------------------------------------------------------
LUA = r'''
local LIMIT = %(limit)d
local END_PC = %(end_pc)d
local TAPS = %(taps)s
local PATCH = {%(patch)s}
local dbg = manager.machine.debugger
local mach = manager.machine
local cpu = mach.devices[":audiocpu"]
local space = cpu.spaces["program"]
local region = mach.memory.regions[":audiocpu"]
for i = 1, #PATCH, 2 do region:write_u8(PATCH[i], PATCH[i + 1]) end
local f = io.open("acc.txt", "w")
local buf, n, total, done = {}, 0, 0, false
local function finish()
  if done then return end
  done = true
  dbg:command('trace off,audiocpu')
  f:write(table.concat(buf, "\n"), "\n")
  f:close()
  mach:exit()
end
local function log(kind, off, data)
  if done or mach:side_effects_disabled() then return end
  local tm = mach.time
  n = n + 1
  buf[n] = string.format("%%s %%x %%x %%d %%d", kind, off, data, tm.seconds, tm.attoseconds)
  if n >= 20000 then f:write(table.concat(buf, "\n"), "\n"); buf = {}; n = 0 end
  total = total + 1
  if total >= LIMIT then finish() end
end
if TAPS then
  rtap = space:install_read_tap(0, 0xffff, "rt", function(off, data, mask) log("r", off, data) end)
  wtap = space:install_write_tap(0, 0xffff, "wt", function(off, data, mask) log("w", off, data) end)
end
dbg:command('trace trace.txt,audiocpu,noloop,{tracelog "%%d %%04X %%02X %%02X %%02X %%02X %%04X ",totalcycles,pc,a,x,y,p,sp}')
sub = emu.register_frame_done(function()
  dbg.visible_cpu = cpu
  if END_PC >= 0 and cpu.state["PC"].value == END_PC then finish() end
end)
dbg:command('go')
'''


def run_mame(name, limit=10 ** 12, patches=(), end_pc=-1, taps=True, seconds=40):
    """MAME's gauntlet with the Lua above -> build/m6502mame/<name>.npz: trace (totalcycles, pc a x y p sp),
    irqs (trace index of each interrupt sequence, line: 0 IRQ, else NMI), acc (kind 0 read / 1 write, addr, data,
    cycle)"""
    out = FIX / (name + ".npz")
    FIX.mkdir(parents=True, exist_ok=True)
    pl = ",".join("%d,%d" % (at + i, b) for at, data in patches for i, b in enumerate(data))
    print("  running mame gauntlet for %s (~%s)" % (name, "a minute" if taps else "half a minute"))
    with tempfile.TemporaryDirectory(dir=FIX) as tmp:       # a fresh directory: MAME writes cfg/ nvram/ there
        with open(os.path.join(tmp, "t.lua"), "w") as f:
            f.write(LUA % {"limit": limit, "end_pc": end_pc, "taps": "true" if taps else "false", "patch": pl})
        subprocess.run(["mame", "gauntlet", "-rompath", str(MAME_ROMS), "-debug", "-debugger", "none",
                        "-autoboot_script", "t.lua", "-window", "-video", "none", "-sound", "none", "-nothrottle",
                        "-skip_gameinfo", "-seconds_to_run", str(seconds)],
                       cwd=tmp, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        tr, irqs = [], []
        with open(os.path.join(tmp, "trace.txt")) as f:
            for ln in f:
                if ln.startswith("   (interrupted at"):
                    irqs.append((len(tr) - 1, int(ln.rsplit(" ", 1)[1].rstrip(")\n"))))
                    continue
                p = ln.split(" ", 7)
                if len(p) < 8 or not p[0].isdigit():
                    continue
                tr.append([int(p[0])] + [int(x, 16) for x in p[1:7]])
        acc = []
        t0 = None
        with open(os.path.join(tmp, "acc.txt")) as f:
            for ln in f:
                p = ln.split()
                if len(p) != 5:
                    continue
                t = int(p[3]) * 10 ** 18 + int(p[4])
                if t0 is None:
                    t0 = t
                cyc, rem = divmod(t - t0, ASPC)
                assert rem == 0, ln
                acc.append((0 if p[0] == "r" else 1, int(p[1], 16), int(p[2], 16), cyc))
    np.savez_compressed(out, trace=np.array(tr, np.int64), irqs=np.array(irqs, np.int64).reshape(-1, 2),
                        acc=np.array(acc, np.int64).reshape(-1, 4))
    return out


def gauntlet_rom():
    rom = bytearray(0x10000)
    rom[0x4000:0x8000] = (EXTRACTED / "gauntlet" / "136037-120.16r").read_bytes()
    rom[0x8000:0x10000] = (EXTRACTED / "gauntlet" / "136037-119.16s").read_bytes()
    return rom


class Mismatch(Exception):
    pass


class Done(Exception):
    pass


class Replay:
    """the sound CPU's memory map (RAM $0000-$0FFF mirrored at $2000, ROM $4000-$FFFF, the rest I/O) checking each
    access against MAME's log (when there is one) and each instruction against its trace"""

    def __init__(self, rom, trace, irqs, acc):
        self.rom = rom
        self.ram = bytearray(0x1000)
        self.known = bytearray(0x1000)              # RAM bytes written (or seen in MAME's log) so far
        self.trace = trace.tolist()
        self.irqs = {int(i): int(line) for i, line in irqs}
        self.acc = acc.tolist() if acc is not None and len(acc) else None
        self.k = 0
        self.i = 0
        self.cpu = M6502Mame(self.rd, self.wr)
        self.cpu.hook = self.hook

    def access(self, kind, a, v):
        if self.k == len(self.acc):
            raise Done
        e = self.acc[self.k]
        t = self.cpu.total_cycles()
        if e[0] != kind or e[1] != a or e[3] != t or (v is not None and e[2] != v):
            raise Mismatch("access %d: %s %04X %s at %d; MAME %s %04X %02X at %d" % (
                self.k, "rw"[kind], a, "--" if v is None else "%02X" % v, t, "rw"[e[0]], e[1], e[2], e[3]))
        self.k += 1
        return e[2]

    def rd(self, a):
        if not a & 0xD000:
            r = a & 0xFFF
            if self.acc is not None:
                if not self.known[r]:                       # power-on contents: as MAME had them
                    self.ram[r] = self.acc[self.k][2] if self.k < len(self.acc) else 0
                    self.known[r] = 1
                self.access(0, a, self.ram[r])
            return self.ram[r]
        if a >= 0x4000:
            if self.acc is not None:
                self.access(0, a, self.rom[a])
            return self.rom[a]
        return self.access(0, a, None) if self.acc is not None else 0xFF

    def wr(self, a, v):
        if self.acc is not None:
            self.access(1, a, v)
        if not a & 0xD000:
            self.ram[a & 0xFFF] = v
            self.known[a & 0xFFF] = 1

    def hook(self):
        c = self.cpu
        i = self.i
        if i == len(self.trace):
            raise Done
        got = [c.total_cycles(), c.NPC, c.A, c.X, c.Y, c.P, c.SP]
        if got != self.trace[i]:
            names = "totalcycles pc a x y p sp".split()
            raise Mismatch("instruction %d: %s; MAME %s" % (i, " ".join(
                "%s=%X" % kv for kv in zip(names, got)), " ".join("%s=%X" % kv for kv in zip(names, self.trace[i]))))
        if i in self.irqs:                                  # this one is the interrupt sequence: lines down again
            c.set_input("irq", 0)
            c.set_input("nmi", 0)
        if i + 1 in self.irqs:                              # held while this instruction's prefetch samples it
            c.set_input("irq" if self.irqs[i + 1] == 0 else "nmi", 1, c.total_cycles())
        self.i = i + 1

    def run(self, seed=1):
        rnd = random.Random(seed)
        try:
            while True:
                self.cpu.run(rnd.choice((1, 2, 3, 7, 50, 300, 5000)))
        except Done:
            return None
        except Mismatch as e:
            return str(e)


class Prog:
    """a tiny assembler for the patched test programs"""

    def __init__(self, org):
        self.org = org
        self.code = bytearray()
        self.labels = {}
        self.fix = []

    @property
    def pc(self):
        return self.org + len(self.code)

    def b(self, *bs):
        self.code += bytes(bs)

    def label(self, name):
        self.labels[name] = self.pc

    def abs_(self, opc, name):                      # JMP / JSR to a label
        self.b(opc, 0, 0)
        self.fix.append(("abs", len(self.code) - 2, name))

    def rel(self, opc, name):
        self.b(opc, 0)
        self.fix.append(("rel", len(self.code) - 1, name))

    def align(self, low):                            # NOPs up to the next address with this low byte
        while self.pc & 0xFF != low:
            self.b(0xEA)

    def done(self):
        for kind, at, name in self.fix:
            t = self.labels[name]
            if kind == "abs":
                self.code[at], self.code[at + 1] = t & 0xFF, t >> 8
            else:
                d = t - (self.org + at + 1)
                assert -128 <= d < 128, (name, d)
                self.code[at] = d & 0xFF
        return bytes(self.code)


def vectors(p, nmi, reset, irq):
    return bytes([p.labels[nmi] & 0xFF, p.labels[nmi] >> 8, p.labels[reset] & 0xFF, p.labels[reset] >> 8,
                  p.labels[irq] & 0xFF, p.labels[irq] >> 8])


def common_start(p):
    p.label("nmi")
    p.b(0x40)                                        # NMI (the main CPU's sound commands): RTI (the line stays up)
    p.label("irq")
    p.b(0x48, 0xAD, 0x30, 0x18, 0x68, 0x40)          # IRQ / BRK: PHA, LDA $1830 (acknowledge), PLA, RTI
    p.label("reset")
    p.b(0x78, 0xD8, 0xA2, 0xFF, 0x9A)                # SEI CLD LDX #$FF TXS


OPERANDS = {"imm": [0xC3], "zpg": [0xF0], "zpx": [0xF0], "zpy": [0xF0], "aba": [0xF0, 0x02], "abx": [0xF0, 0x02],
            "aby": [0xF0, 0x02], "idx": [0x40], "idy": [0x50], "imp": [], "acc": []}
SETUPS = [(0x5A, 0x01, 0x01, 0x24), (0xA5, 0xFF, 0xFF, 0xE5), (0x99, 0x10, 0x10, 0x2D)]   # A X Y P (I always set)


def opcodes_program():
    p = Prog(0x8000)
    common_start(p)
    # RAM: a pattern in $0200-$03FF; pointers ($3F,$40)=$02F8 ($41,$42)=$0280 ($50,$51)=$02F0
    p.b(0xA2, 0x00)                                  # LDX #0
    p.label("fill")
    p.b(0x8A, 0x49, 0x5C, 0x9D, 0x00, 0x02, 0x0A, 0x9D, 0x00, 0x03, 0xE8)   # TXA EOR #$5C STA $200,X ASL STA $300,X INX
    p.rel(0xD0, "fill")
    for a, v in ((0x3F, 0xF8), (0x40, 0x02), (0x41, 0x80), (0x42, 0x02), (0x50, 0xF0), (0x51, 0x02)):
        p.b(0xA9, v, 0x85, a)
    for a, x, y, flags in SETUPS:
        for opc in range(256):
            name = OPS[opc].__name__[3:]
            mnem, mode = name.split("_")
            if mode in ("rel", "non", "adr", "ind") or mnem in ("brk", "rti", "rts"):
                continue
            p.b(0xA9, flags | 0x04, 0x48, 0xA9, a, 0xA2, x, 0xA0, y, 0x28)    # LDA #P PHA LDA #a LDX #x LDY #y PLP
            p.b(opc, *OPERANDS[mode])
    # branches: not taken, taken in the page, taken forward across a page, taken backward across a page
    for k, opc in enumerate((0x10, 0x30, 0x50, 0x70, 0x90, 0xB0, 0xD0, 0xF0)):
        bit = {0: 0x80, 1: 0x40, 2: 0x01, 3: 0x02}[k >> 1]
        taken_p = 0x24 | (bit if k & 1 else 0)
        not_p = 0x24 | (0 if k & 1 else bit)
        p.b(0xA9, not_p, 0x48, 0x28)
        p.b(opc, 0x00)                                  # not taken
        p.b(0xA9, taken_p, 0x48, 0x28)
        p.rel(opc, "s%d" % k)                           # taken, same page (or across: wherever it falls)
        p.b(0xEA)
        p.label("s%d" % k)
        p.align(0xF0)
        p.b(0xA9, taken_p, 0x48, 0x28)                  # $xxF0..F3
        p.rel(opc, "f%d" % k)                           # $xxF4: forward across the page
        p.b(0x00, 0xEA)
        p.align(0x10)
        p.label("f%d" % k)
        p.abs_(0x4C, "b%d" % k)
        p.align(0xF0)
        p.label("t%d" % k)
        p.abs_(0x4C, "c%d" % k)
        p.align(0x00)
        p.label("b%d" % k)
        p.b(0xA9, taken_p, 0x48, 0x28)
        p.rel(opc, "t%d" % k)                           # backward across the page
        p.label("c%d" % k)
    # JSR / RTS, JMP abs, JMP ($02FF) (high byte from $0200), BRK, RTI with a pushed P and PC
    p.abs_(0x20, "sub")
    p.abs_(0x4C, "j1")
    p.label("sub")
    p.b(0x60)
    p.label("j1")
    p.b(0xA9, 0, 0x8D, 0xFF, 0x02, 0xA9, 0, 0x8D, 0x00, 0x02)     # patched below: ($02FF) = j2
    at_lo, at_hi = len(p.code) - 9, len(p.code) - 4
    p.b(0x6C, 0xFF, 0x02)
    p.b(0x00)                                        # never reached
    p.label("j2")
    p.b(0x00, 0xEA)                                  # BRK (returns behind its signature byte)
    p.b(0xA9, 0, 0x48, 0xA9, 0, 0x48, 0xA9, 0xE7, 0x48, 0x40)     # push PC = r1, P = $E7; RTI
    at_r1 = len(p.code) - 10
    p.label("r1")
    p.label("end")
    p.abs_(0x4C, "end")
    code = bytearray(p.done())
    j2, r1 = p.labels["j2"], p.labels["r1"]
    code[at_lo], code[at_hi] = j2 & 0xFF, j2 >> 8
    code[at_r1 + 1], code[at_r1 + 4] = r1 >> 8, r1 & 0xFF
    return p, bytes(code)


def decimal_program():
    p = Prog(0x8000)
    common_start(p)
    p.b(0xA9, 0x00, 0x85, 0x00, 0xF8)                # LDA #0 STA $00 SED
    p.label("outer")
    p.b(0xA2, 0x00)
    p.label("inner")
    p.b(0x8A, 0x18, 0x65, 0x00, 0x8A, 0x38, 0x65, 0x00,     # TXA CLC ADC $00  TXA SEC ADC $00
        0x8A, 0x18, 0xE5, 0x00, 0x8A, 0x38, 0xE5, 0x00, 0xE8)   # TXA CLC SBC $00  TXA SEC SBC $00  INX
    p.rel(0xD0, "inner")
    p.b(0xE6, 0x00)
    p.rel(0xD0, "outer")
    p.b(0xD8)
    p.label("end")
    p.abs_(0x4C, "end")
    return p, p.done()


def patched(code, p):
    """the patch for the audiocpu region (program at $8000, the vectors) and the ROM image it makes"""
    rom = gauntlet_rom()
    rom[0x8000:0x8000 + len(code)] = code
    vec = vectors(p, "nmi", "reset", "irq")
    rom[0xFFFA:0x10000] = vec
    return rom, [(0x8000, code), (0xFFFA, vec)]


def fixture(name, regen, **kw):
    out = FIX / (name + ".npz")
    if out.exists() and not regen:
        return out
    if not shutil.which("mame") or not (MAME_ROMS / "gauntlet").is_dir():
        return None
    return run_mame(name, **kw)


def mame_tests(regen):
    if not (EXTRACTED / "gauntlet" / "136037-119.16s").exists():
        print("MAME comparisons skipped (no ROMs: venv/bin/python games/gauntlet/tools/prepare.py)")
        return
    # a. gauntlet's sound program
    path = fixture("gauntlet_boot", regen, limit=2000000)
    if path is None:
        print("MAME comparisons skipped (no mame or no ROMs in %s)" % MAME_ROMS)
        return
    z = np.load(path)
    rp = Replay(gauntlet_rom(), z["trace"], z["irqs"], z["acc"])
    err = rp.run()
    check(err is None, "gauntlet boot: %s" % err)
    nirq = sum(1 for v in rp.irqs.values() if v == 0)
    print("MAME gauntlet sound CPU: %d of %d instructions and %d of %d accesses equal (%d IRQs, %d NMIs replayed)" % (
        rp.i, len(z["trace"]), rp.k, len(z["acc"]), nirq, len(rp.irqs) - nirq))
    check(rp.k >= len(z["acc"]) - 1 and rp.i >= len(z["trace"]) - 2, "gauntlet boot: stopped early")
    # b. every opcode
    p, code = opcodes_program()
    rom, patches = patched(code, p)
    path = fixture("opcodes", regen, patches=patches, end_pc=p.labels["end"], seconds=30)
    z = np.load(path)
    rp = Replay(rom, z["trace"], z["irqs"], z["acc"])
    err = rp.run(2)
    check(err is None, "opcode program: %s" % err)
    reached = rp.trace[rp.i - 1][1] == p.labels["end"] if rp.i else False
    check(reached, "opcode program: the end not reached in MAME's trace")
    print("MAME opcode program: %d of %d instructions and %d of %d accesses equal (%d interrupts)" % (
        rp.i, len(z["trace"]), rp.k, len(z["acc"]), len(rp.irqs)))
    # c. decimal mode ADC / SBC, all operands
    p, code = decimal_program()
    rom, patches = patched(code, p)
    path = fixture("decimal", regen, patches=patches, end_pc=p.labels["end"], taps=False, seconds=30)
    z = np.load(path)
    rp = Replay(rom, z["trace"], z["irqs"], None)
    err = rp.run(3)
    check(err is None, "decimal program: %s" % err)
    n_ops = sum(1 for r in rp.trace[:rp.i] if r[1] in (p.labels["inner"] + 2, p.labels["inner"] + 6,
                                                       p.labels["inner"] + 10, p.labels["inner"] + 14))
    check(n_ops == 4 * 65536, "decimal program: %d ADC/SBC traced" % n_ops)
    print("MAME decimal ADC/SBC program: %d of %d instructions equal (%d ADC/SBC)" % (rp.i, len(z["trace"]), n_ops))
    return rom, p


# ---- 3. speed ----------------------------------------------------------------------------------------------------
def speed():
    p, code = decimal_program()
    m = bytearray(0x10000)
    m[0x8000:0x8000 + len(code)] = code
    m[0xFFFA:0x10000] = vectors(p, "nmi", "reset", "irq")

    def wr(a, v):
        m[a] = v

    c = M6502Mame(m.__getitem__, wr)
    n = 1000000
    t = time.perf_counter()
    k = 0
    while k < n:
        k += c.run(30000)
    dt = time.perf_counter() - t
    print("speed: %.0f cycles/s (%d cycles in %.2f s, ADC/SBC loop, slices of 30000)" % (k / dt, k, dt))


def main():
    unit_tests()
    mame_tests("--regen" in sys.argv)
    speed()
    print("FAILURES: %d" % len(FAIL) if FAIL else "all tests passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
