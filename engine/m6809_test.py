"""Tests of the MC6809 interpreter (m6809.py) and disassembler (m6809dis.py).

    python engine/m6809_test.py [--regen] [--only <game>_<cpu> or probe]

(a) hand-written instruction tests (flags, results, cycles, interrupts, CWAI/SYNC);
(b) MAME traces of Pac-Mania, Galaga '88 and Splatterhouse (main, sub and sound CPU; the boot and some seconds of
    the attract mode) with every bus read and write: the disassembler's text must equal MAME's for every distinct
    instruction, and the interpreter must reproduce each step (registers, writes, cycles) from the state before it,
    its reads answered from the trace;
(c) a probe program run on Pac-Mania's main CPU in MAME (all opcodes, all 256 indexed postbytes, TFR/EXG pairs,
    random operands) checked the same way.
The traces are made once into build/m6809/ (not in git; they hold ROM bytes) when MAME and the ROMs are there,
else (b) and (c) are skipped.
"""
import os
import random
import shutil
import subprocess
import sys
import time
import zipfile
from collections import Counter, defaultdict, deque

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m6809
from m6809 import M6809
import m6809dis
from paths import ROOT, ROMS

OUT = ROOT / "build" / "m6809"
GAMES = ["pacmania", "galaga88", "splatter"]
CPUS = ["maincpu", "subcpu", "audiocpu"]
WINDOWS = [(0, 60), (900, 1020)]             # traced frames: the boot (1 s), and 2 s from 15 s on (attract mode)
FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("FAIL", msg)


# ---- (a) instruction tests ---------------------------------------------------------------------------------
class Mem:
    def __init__(self):
        self.m = bytearray(65536)
        self.writes = []

    def rd(self, a):
        return self.m[a]

    def wr(self, a, v):
        self.m[a] = v
        self.writes.append((a, v))


def cpu_with(code, at=0x1000, **regs):
    mem = Mem()
    mem.m[at:at + len(code)] = code
    mem.m[0xFFFE], mem.m[0xFFFF] = at >> 8, at & 0xFF
    c = M6809(mem.rd, mem.wr)
    c.reset()
    c.cycles = 0
    for k, v in regs.items():
        setattr(c, k, v)
    return c, mem


def run1(code, **regs):
    c, mem = cpu_with(bytes.fromhex(code), **regs)
    n = c.step()
    return c, mem, n


def flags(c):
    return "".join(ch if c.cc & bit else "." for ch, bit in zip("EFHINZVC", (0x80, 0x40, 0x20, 0x10, 8, 4, 2, 1)))


def unit_tests():
    n0 = len(FAILS)
    # ADC / SBC: half carry, overflow, carry
    c, _, n = run1("8901", a=0x0F, cc=0x01)            # ADCA #1 with C: $0F+1+1
    check(c.a == 0x11 and flags(c) == "..H.....", "adca half carry: %02X %s" % (c.a, flags(c)))
    c, _, n = run1("897F", a=0x01, cc=0)               # $01+$7F: V N H
    check(c.a == 0x80 and flags(c) == "..H.N.V.", "adca overflow: %02X %s" % (c.a, flags(c)))
    c, _, n = run1("8B80", a=0x80, cc=0)               # ADDA: $80+$80 = 0 V C Z
    check(c.a == 0 and flags(c) == ".....ZVC" and n == 2, "adda: %02X %s %d" % (c.a, flags(c), n))
    c, _, n = run1("8201", a=0x00, cc=0x01)            # SBCA #1 with C: 0-1-1 = $FE N C
    check(c.a == 0xFE and flags(c) == "....N..C", "sbca: %02X %s" % (c.a, flags(c)))
    c, _, n = run1("8201", a=0x80, cc=0x00)            # $80-1 = $7F V
    check(c.a == 0x7F and flags(c) == "......V.", "sbca overflow: %02X %s" % (c.a, flags(c)))
    c, _, n = run1("8000", a=0x80, cc=0x20)            # SUBA leaves H
    check(flags(c) == "..H.N...", "suba keeps H: %s" % flags(c))
    # DAA
    for a, cc, ra, rf in ((0x0A, 0, 0x10, "........"), (0x9A, 0, 0x00, ".....Z.C"), (0x12, 0x20, 0x18, "..H....."),
                          (0x45, 0x01, 0xA5, "....N..C"), (0xA0, 0, 0x00, ".....Z.C")):
        c, _, n = run1("19", a=a, cc=cc)
        check(c.a == ra and flags(c) == rf and n == 2, "daa %02X/%02X: %02X %s" % (a, cc, c.a, flags(c)))
    # NEG
    for v, r, f in ((0x00, 0x00, ".....Z.."), (0x80, 0x80, "....N.VC"), (0x01, 0xFF, "....N..C")):
        c, _, n = run1("40", a=v, cc=0)
        check(c.a == r and flags(c) == f and n == 2, "nega %02X: %02X %s" % (v, c.a, flags(c)))
    # 16-bit compares
    c, _, n = run1("1083 8000", a=0x7F, b=0xFF, cc=0)  # CMPD #$8000: $7FFF-$8000 = $FFFF, N V C
    check(flags(c) == "....N.VC" and n == 5, "cmpd: %s %d" % (flags(c), n))
    c, _, n = run1("8C 1234", x=0x1234, cc=0x0F)
    check(flags(c) == ".....Z.." and n == 4, "cmpx eq: %s" % flags(c))
    c, _, n = run1("11 8C 0001", s=0x0000, cc=0)       # CMPS: 0-1
    check(flags(c) == "....N..C", "cmps: %s" % flags(c))
    # shifts and rotates
    c, _, n = run1("47", a=0x81, cc=0x02)               # ASRA keeps V
    check(c.a == 0xC0 and flags(c) == "....N.VC", "asra: %02X %s" % (c.a, flags(c)))
    c, _, n = run1("44", a=0x01, cc=0x0A)               # LSRA: N cleared, V kept, Z C
    check(c.a == 0 and flags(c) == ".....ZVC", "lsra: %02X %s" % (c.a, flags(c)))
    c, _, n = run1("49", a=0x40, cc=0x01)               # ROLA: $81, V (b7^b6), C 0
    check(c.a == 0x81 and flags(c) == "....N.V.", "rola: %02X %s" % (c.a, flags(c)))
    c, _, n = run1("46", a=0x01, cc=0x01)               # RORA: $80 C
    check(c.a == 0x80 and flags(c) == "....N..C", "rora: %02X %s" % (c.a, flags(c)))
    c, _, n = run1("48", a=0xC0, cc=0)                  # ASLA: $80, C, no V
    check(c.a == 0x80 and flags(c) == "....N..C", "asla: %02X %s" % (c.a, flags(c)))
    c, mem, n = run1("6884", x=0x2000, cc=0)            # ASL ,X
    check(n == 6, "asl ,x cycles %d" % n)
    # MUL, SEX
    c, _, n = run1("3D", a=0xFF, b=0xFF, cc=0x0F)
    check(c.d == 0xFE01 and flags(c) == "....N.V." and n == 11, "mul: %04X %s %d" % (c.d, flags(c), n))
    c, _, n = run1("3D", a=0x00, b=0x80, cc=0)
    check(c.d == 0 and flags(c) == ".....Z..", "mul 0: %s" % flags(c))
    c, _, n = run1("3D", a=0x01, b=0x80, cc=0)
    check(c.d == 0x80 and flags(c) == ".......C", "mul C: %s" % flags(c))
    c, _, n = run1("1D", b=0x80, cc=0x02)
    check(c.d == 0xFF80 and flags(c) == "....N.V.", "sex: %04X %s" % (c.d, flags(c)))
    # TFR / EXG, MAME's mixed sizes
    c, _, n = run1("1F 81", a=0x12)                     # TFR A,X: $FF12
    check(c.x == 0xFF12 and n == 6, "tfr a,x: %04X" % c.x)
    c, _, n = run1("1F 18", x=0x1234)                   # TFR X,A: low byte
    check(c.a == 0x34, "tfr x,a: %02X" % c.a)
    c, _, n = run1("1F A1", cc=0x5A)                    # TFR CC,X: $5A5A
    check(c.x == 0x5A5A, "tfr cc,x: %04X" % c.x)
    c, _, n = run1("1E 81", a=0x12, x=0x3456)           # EXG A,X: X=$FF12, A=$56
    check(c.x == 0xFF12 and c.a == 0x56 and n == 8, "exg a,x: %04X %02X" % (c.x, c.a))
    c, _, n = run1("1E 1A", x=0x3456, cc=0x50)          # EXG X,CC: X=$FF50, CC=$56
    check(c.x == 0xFF50 and c.cc == 0x56, "exg x,cc: %04X %02X" % (c.x, c.cc))
    c, _, n = run1("1F 86")                              # TFR A,inv: nothing
    c, _, n = run1("1F 61", x=0x1234)                   # TFR inv,X: $FFFF
    check(c.x == 0xFFFF, "tfr inv,x: %04X" % c.x)
    c, _, n = run1("1F 14", x=0x8000)
    check(c.s == 0x8000 and c.lds, "tfr x,s arms NMI")
    # indexed modes
    c, mem, n = run1("A6 1F", x=0x2001)                 # LDA -1,X (5-bit)
    check(n == 5, "lda -1,x cycles %d" % n)
    c, mem = cpu_with(bytes.fromhex("A6 9F 3000"), x=0)  # LDA [$3000]
    mem.m[0x3000:0x3002] = b"\x40\x00"
    mem.m[0x4000] = 0x77
    n = c.step()
    check(c.a == 0x77 and n == 9, "lda [$3000]: %02X %d" % (c.a, n))
    c, mem = cpu_with(bytes.fromhex("A6 8C 10"))       # LDA $10,PCR
    mem.m[0x1013] = 0x55
    n = c.step()
    check(c.a == 0x55 and n == 5, "lda pcr8: %02X %d" % (c.a, n))
    c, mem = cpu_with(bytes.fromhex("EC 9D 0100"))     # LDD [$0100,PCR]
    mem.m[0x1104:0x1106] = b"\x50\x00"
    mem.m[0x5000:0x5002] = b"\xBE\xEF"
    n = c.step()
    check(c.d == 0xBEEF and n == 13, "ldd [pcr16]: %04X %d" % (c.d, n))
    c, mem, n = run1("A6 A1", y=0x2000)                 # LDA ,Y++
    check(c.y == 0x2002 and n == 7, "lda ,y++: %04X %d" % (c.y, n))
    c, mem, n = run1("A6 C2", u=0x2000)                 # LDA ,-U
    check(c.u == 0x1FFF and n == 6, "lda ,-u: %04X %d" % (c.u, n))
    c, mem, n = run1("A6 F3", s=0x2000)                 # LDA [,--S]
    check(c.s == 0x1FFE and n == 10, "lda [,--s]: %04X %d" % (c.s, n))
    c, mem, n = run1("30 85", x=0x1000, b=0xFF)         # LEAX B,X: B signed
    check(c.x == 0x0FFF and n == 5, "leax b,x: %04X %d" % (c.x, n))
    c, mem, n = run1("30 8B", x=0x1000, a=0xF0, b=0x00)  # LEAX D,X: $F000+$1000 = 0, Z
    check(c.x == 0 and c.cc & 4 and n == 8, "leax d,x: %04X %d" % (c.x, n))
    c, mem, n = run1("32 E9 FF00", s=0x1000, cc=0)      # LEAS -$100,S: no flags, arms NMI
    check(c.s == 0x0F00 and c.cc == 0 and c.lds and n == 8, "leas: %04X %d" % (c.s, n))
    c, mem, n = run1("A6 87", x=0x1000)                 # illegal postbyte $87: address 0
    check(n == 3, "lda illegal postbyte cycles %d" % n)
    # push / pull order
    c, mem, n = run1("34 FF", a=1, b=2, dp=3, x=0x0405, y=0x0607, u=0x0809, s=0x2000, cc=0x0A)
    check(bytes(mem.m[0x1FF4:0x2000]) == bytes([0x0A, 1, 2, 3, 4, 5, 6, 7, 8, 9, 0x10, 0x02]) and n == 17 and c.s == 0x1FF4,
          "pshs all: %s %d" % (bytes(mem.m[0x1FF4:0x2000]).hex(), n))
    check([a for a, v in mem.writes] == list(range(0x1FFF, 0x1FF3, -1)), "pshs write order")
    c, mem = cpu_with(bytes.fromhex("37 FF"), u=0x3000)
    mem.m[0x3000:0x300C] = bytes([0x0A, 1, 2, 3, 4, 5, 6, 7, 8, 9, 0x12, 0x34])
    n = c.step()
    check((c.cc, c.a, c.b, c.dp, c.x, c.y, c.s, c.pc, c.u) == (0x0A, 1, 2, 3, 0x0405, 0x0607, 0x0809, 0x1234, 0x300C) and n == 17,
          "pulu all")
    c, mem, n = run1("36 40", u=0x3000, s=0xABCD)       # PSHU S
    check(bytes(mem.m[0x2FFE:0x3000]) == b"\xAB\xCD", "pshu s")
    # interrupts
    def irq_setup():
        c, mem = cpu_with(bytes.fromhex("12 12 12"), s=0x2000, cc=0x00, a=0x11, b=0x22, dp=0x33, x=0x4444, y=0x5555, u=0x6666)
        mem.m[0xFFF8:0xFFFA] = b"\x80\x00"
        mem.m[0xFFF6:0xFFF8] = b"\x90\x00"
        mem.m[0xFFFC:0xFFFE] = b"\xA0\x00"
        return c, mem
    c, mem = irq_setup()
    c.set_irq(True)
    n = c.step()
    check(n == 19 and c.pc == 0x8000 and c.s == 0x1FF4 and c.cc == 0x90 and mem.m[0x1FF4] == 0x80, "irq entry %d %04X %02X" % (n, c.s, c.cc))
    n = c.step()
    check(c.s == 0x1FF4 and c.pc != 0x8000, "irq masked after entry")
    c, mem = irq_setup()
    c.set_firq(True)
    n = c.step()
    check(n == 10 and c.pc == 0x9000 and c.s == 0x1FFD and c.cc == 0x50 and mem.m[0x1FFD] == 0x00, "firq entry %d %04X %02X" % (n, c.s, c.cc))
    mem.m[0x9000] = 0x3B                                # RTI with E clear: pc and cc only
    c.set_firq(False)
    n = c.step()
    check(n == 6 and c.pc == 0x1000 and c.s == 0x2000 and c.cc == 0, "firq rti %d %04X" % (n, c.pc))
    c, mem = irq_setup()
    c.nmi()                                             # not armed: S never loaded
    c.step()
    check(c.pc == 0x1001, "nmi ignored before lds")
    c.lds = True
    c.nmi()
    n = c.step()
    check(n == 19 and c.pc == 0xA000 and c.cc == 0xD0, "nmi entry %d %02X" % (n, c.cc))
    mem.m[0xA000] = 0x3B                                # RTI with E: everything back
    n = c.step()
    check(n == 15 and c.pc == 0x1001 and (c.a, c.b, c.dp, c.x, c.y, c.u, c.s, c.cc) == (0x11, 0x22, 0x33, 0x4444, 0x5555, 0x6666, 0x2000, 0x80),
          "nmi rti %d" % n)
    # CWAI: pushes everything, waits, FIRQ then also sets F; SYNC waits for a masked line too
    c, mem = cpu_with(bytes.fromhex("3C AF 12"), s=0x2000, cc=0x50)
    mem.m[0xFFF6:0xFFF8] = b"\x90\x00"
    n = c.step()
    check(n == 16 and c.s == 0x1FF4 and mem.m[0x1FF4] == 0x80 and c.wait, "cwai %d %02X" % (n, mem.m[0x1FF4]))
    check(c.step() == 1 and c.run(100) == 100, "cwai waits")
    c.set_firq(True)
    n = c.step()
    check(n == 4 and c.pc == 0x9000 and c.cc == 0xD0 and c.s == 0x1FF4, "cwai firq %d %02X %04X" % (n, c.cc, c.s))
    c, mem = cpu_with(bytes.fromhex("13 12"), s=0x2000, cc=0x50)
    n = c.step()
    check(n == 2 and c.wait, "sync")
    check(c.run(50) == 50, "sync waits")
    c.set_irq(True)                                     # masked: wakes, continues
    check(c.step() == 1 and c.step() == 2 and c.pc == 0x1002, "sync wake on masked irq")
    # SWI family, RTS, branches, cycles
    c, mem = cpu_with(bytes.fromhex("3F"), s=0x2000, cc=0)
    mem.m[0xFFFA:0xFFFC] = b"\x70\x00"
    n = c.step()
    check(n == 19 and c.pc == 0x7000 and c.cc == 0xD0, "swi")
    c, mem = cpu_with(bytes.fromhex("10 3F"), s=0x2000, cc=0)
    mem.m[0xFFF4:0xFFF6] = b"\x70\x00"
    n = c.step()
    check(n == 20 and c.pc == 0x7000 and c.cc == 0x80, "swi2 %02X" % c.cc)
    for code, taken, n_exp in (("2000", True, 3), ("2100", False, 3), ("1021 0000", False, 5), ("1020 0010", True, 6),
                               ("1600 10", True, 5), ("17 0010", True, 9), ("8D 10", True, 7)):
        c, _, n = run1(code, s=0x2000)
        check(n == n_exp, "branch %s: %d" % (code, n))
    for code, n_exp in (("12", 2), ("3A", 3), ("1A 00", 3), ("1C FF", 3), ("39", 5), ("35 FF", 17), ("96 00", 4), ("B6 0000", 5),
                        ("DC 00", 5), ("FC 0000", 6), ("10 DE 00", 6), ("D3 00", 6), ("10 B3 0000", 8), ("0F 00", 6),
                        ("7F 0000", 7), ("6F 84", 6), ("0D 00", 6), ("4D", 2), ("9D 00", 7), ("BD 0000", 8), ("AD 84", 7),
                        ("0E 00", 3), ("7E 0000", 4), ("6E 84", 3), ("97 00", 4), ("ED 84", 5), ("A6 89 0000", 8),
                        ("A6 8B", 8), ("A6 86", 5), ("A6 88 00", 5), ("A6 8D 0000", 9), ("A6 94", 7), ("1E 01", 8),
                        ("10 8E 0000", 4), ("10 CE 0000", 4), ("CC 0000", 3), ("C3 0000", 4)):
        c, _, n = run1(code, s=0x2000, x=0x3000)
        check(n == n_exp, "cycles %s: %d (MAME %d)" % (code, n, n_exp))
    # undocumented ones MAME implements
    c, _, n = run1("4B", a=0x00, cc=0)                  # XDECA: C = (A != 0)
    check(c.a == 0xFF and flags(c) == "....N...", "xdeca: %s" % flags(c))
    c, _, n = run1("42", a=0x01, cc=1)                  # XNCA with C: COM
    check(c.a == 0xFE and flags(c) == "....N..C", "xnca: %s" % flags(c))
    c, _, n = run1("5E", b=0x12, cc=0x0F)               # XCLRB keeps C
    check(c.b == 0 and flags(c) == ".....Z.C", "xclrb: %s" % flags(c))
    c, _, n = run1("10 C3 0001", a=0xFF, b=0xFF, cc=0)  # XADDD: flags only
    check(c.d == 0xFFFF and flags(c) == ".....Z.C" and n == 5, "xaddd: %s" % flags(c))
    try:
        run1("14")
        check(False, "xhcf raises")
    except m6809.M6809Error:
        pass
    # disassembler
    for code, text, mode, flow in (("CC03F8", "LDD    #$03F8", "imm16", "seq"), ("FDEC00", "STD    $EC00", "ext", "seq"),
                                   ("7EC000", "JMP    $C000", "ext", "jmp"), ("9700", "STA    <$00", "dir", "seq"),
                                   ("B60012", "LDA    >$0012", "ext", "seq"), ("300D", "LEAX   $D,X", "idx", "seq"),
                                   ("3016", "LEAX   -$A,X", "idx", "seq"), ("A69F1234", "LDA    [$1234]", "idx", "seq"),
                                   ("6E9F1234", "JMP    [$1234]", "idx", "ijmp"), ("AD84", "JSR    ,X", "idx", "icall"),
                                   ("3510", "PULS   X", "stack", "seq"), ("35F6", "PULS   D,X,Y,U,PC", "stack", "ret"),
                                   ("3476", "PSHS   U,Y,X,D", "stack", "seq"), ("1F8B", "TFR    A,DP", "regs", "seq"),
                                   ("1F15", "TFR    X,PC", "regs", "ijmp"), ("10CE03F8", "LDS    #$03F8", "imm16", "seq"),
                                   ("1026002B", "LBNE   $102F", "rel16", "jcc"), ("26F6", "BNE    $0FF8", "rel8", "jcc"),
                                   ("A68C10", "LDA    $1013,PCR", "idx", "seq"), ("E6A8F0", "LDB    -$10,Y", "idx", "seq"),
                                   ("ED81", "STD    ,X++", "idx", "seq"), ("3B", "RTI", "inh", "rti"),
                                   ("103F", "SWI2", "inh", "swi"), ("13", "SYNC", "inh", "wait"), ("3CEF", "CWAI   #$EF", "imm8", "wait"),
                                   ("A6D3", "LDA    [,--U]", "idx", "seq")):
        mem = bytearray(65536)
        b = bytes.fromhex(code)
        mem[0x1000:0x1000 + len(b)] = b
        ins = m6809dis.decode(mem.__getitem__, 0x1000)
        check((ins.text, ins.mode, ins.flow) == (text, mode, flow), "decode %s: %s %s %s" % (code, ins.text, ins.mode, ins.flow))
        check(ins.length == len(b), "decode %s length %d" % (code, ins.length))
    print("unit tests: %d failures" % (len(FAILS) - n0))


# ---- (b) MAME traces ------------------------------------------------------------------------------------------
TRACELOG = ('{tracelog "%d %02X%02X%02X%02X%02X A=%02X B=%02X X=%04X Y=%04X U=%04X S=%04X DP=%02X CC=%02X ",'
            'totalcycles,b@pc,b@(pc+1),b@(pc+2),b@(pc+3),b@(pc+4),a,b,x,y,u,s,dp,cc}')
WPS = ['wpset 0,10000,r,1,{tracelog "R %04X %02X\\n",wpaddr,wpdata; g}',
       'wpset 0,10000,w,1,{tracelog "W %04X %02X\\n",wpaddr,wpdata; g}']


def lua_quote(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def trace_script(tag, windows):
    """Lua: trace the CPU `tag` with its reads and writes during the frame windows (file w<i>.txt each)."""
    lines = ["local dbg = manager.machine.debugger", "local frame = 0", "local function on(i)",
             "  dbg:command('focus %s')" % tag,
             "  dbg.visible_cpu = manager.machine.devices[':%s']" % tag,     # (tracelog and wpset use the visible CPU)
             "  dbg:command(" + lua_quote("trace w") + " .. i .. " + lua_quote(".txt,%s,noloop,%s" % (tag, TRACELOG)) + ")"]
    lines += ["  dbg:command(%s)" % lua_quote(w) for w in WPS]
    lines += ["end", "local function off()", "  dbg:command('wpclear')", "  dbg:command('trace off,%s')" % tag, "end"]
    lines += ["sub = emu.register_frame_done(function()", "  frame = frame + 1"]
    for i, (a, b) in enumerate(windows):
        if a > 0:
            lines.append("  if frame == %d then on(%d) end" % (a, i))
        lines.append("  if frame == %d then off() end" % b)
    lines += ["end)"]
    if windows[0][0] == 0:
        lines.append("on(0)")
    lines.append("dbg:command('go')")
    return "\n".join(lines) + "\n"


def mame_cmd(game, script, seconds):
    return ["mame", game, "-rompath", str(ROMS), "-debug", "-debugger", "none", "-autoboot_script", script, "-window",
            "-video", "none", "-sound", "none", "-nothrottle", "-seconds_to_run", str(seconds), "-skip_gameinfo"]


def parse_trace(path):
    """MAME trace text -> arrays: cyc, regs (a b x y u s dp cc pc), opb (5 bytes at pc), text index, accesses."""
    cyc, regs, opb, tix, acc, off = [], [], [], [], [], []
    texts = {}
    with open(path) as f:
        for line in f:
            if line[0] in "RW" and line[1] == " ":
                acc.append(((line[0] == "W") << 24) | (int(line[2:6], 16) << 8) | int(line[7:9], 16))
                continue
            if not line.strip() or line.startswith("   ("):
                continue                     # (MAME's notes: interrupts, loops)
            p = line.split(" ", 11)
            if len(p) < 12 or not p[0].isdigit() or not p[2].startswith("A="):
                raise ValueError("%s: not a trace line: %r" % (path, line))
            cyc.append(int(p[0]))
            opb.append(bytes.fromhex(p[1]))
            r = [int(q.split("=")[1], 16) for q in p[2:10]]
            pc, text = p[10].rstrip(":"), p[11]
            r.append(int(pc, 16))
            regs.append(r)
            off.append(len(acc))
            text = text.rstrip()
            tix.append(texts.setdefault(text, len(texts)))
    off.append(len(acc))
    return dict(cyc=np.array(cyc, np.int64), regs=np.array(regs, np.int32), opb=np.frombuffer(b"".join(opb), np.uint8).reshape(-1, 5),
                tix=np.array(tix, np.int32), acc=np.array(acc, np.uint32), off=np.array(off, np.int64),
                texts=np.array(sorted(texts, key=texts.get), dtype=object))


def have_mame():
    return shutil.which("mame") is not None and all((ROMS / (g + ".zip")).exists() for g in GAMES)


NAMES = ["%s_%s" % (g, c) for g in GAMES for c in CPUS] + ["probe"]


def make_traces(names):
    """Runs MAME for the named fixtures (in parallel; about 3 minutes) and packs them into OUT/<name>.npz."""
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = []
    seconds = WINDOWS[-1][1] // 60 + 2
    for g in GAMES:
        for cpu in CPUS:
            name = "%s_%s" % (g, cpu)
            if name not in names:
                continue
            d = OUT / ("run_" + name)
            shutil.rmtree(d, ignore_errors=True)
            d.mkdir()
            (d / "t.lua").write_text(trace_script(cpu, WINDOWS))
            log = open(d / "mame.log", "w")
            jobs.append((name, d, subprocess.Popen(mame_cmd(g, "t.lua", seconds), cwd=d, stdout=log, stderr=subprocess.STDOUT)))
    if "probe" in names:
        jobs.append(make_probe_job())
    for name, d, p in jobs:
        p.wait()
        pack(name, d)


def pack(name, d):
    """The trace text of a run directory -> OUT/<name>.npz (the directory is removed)."""
    files = [d / "probe.txt"] if name == "probe" else [d / ("w%d.txt" % i) for i in range(len(WINDOWS))]
    parts = [parse_trace(f) for f in files if f.exists()]
    parts = [p for p in parts if len(p["cyc"])]
    if not parts:
        print("no trace for", name, "(see %s)" % (d / "mame.log"))
        return
    extra = {"skip_pcs": np.array(probe_vector_targets())} if name == "probe" else {}
    np.savez_compressed(OUT / (name + ".npz"), **extra, **{"%s_%d" % (k, i): v for i, part in enumerate(parts) for k, v in part.items()})
    shutil.rmtree(d)
    print("trace", name, sum(len(p["cyc"]) for p in parts), "instructions")


def load_trace(path):
    z = np.load(path, allow_pickle=True)
    parts = []
    i = 0
    while "cyc_%d" % i in z:
        parts.append({k: z["%s_%d" % (k, i)] for k in ("cyc", "regs", "opb", "tix", "acc", "off", "texts")})
        i += 1
    return parts, set(z["skip_pcs"].tolist()) if "skip_pcs" in z else set()


VECS = {0xFFF8: "irq", 0xFFF6: "firq", 0xFFFC: "nmi"}


def replay(part, stats, opcount, name, skip_pcs=(), strict=False):
    """Each trace step from the logged state before it: registers, writes and cycles must match the next line."""
    cyc, regs, opb, acc, off, tix, texts = part["cyc"], part["regs"], part["opb"], part["acc"], part["off"], part["tix"], part["texts"]
    reads = defaultdict(deque)
    mine = []
    missing = []

    def rd(a):
        q = reads.get(a)
        if q:
            return q.popleft()
        missing.append(a)
        return 0

    def wr(a, v):
        mine.append((a, v))
    c = M6809(rd, wr)
    seen = {}
    bad = 0
    prev_text = None
    regsl = regs.tolist()
    accl = acc.tolist()
    offl = off.tolist()
    cycl = cyc.tolist()
    for i in range(len(regsl) - 1):
        r = regsl[i]
        c.a, c.b, c.x, c.y, c.u, c.s, c.dp, c.cc, c.pc = r
        c.wait = 0
        c.irq_line = c.firq_line = c.nmi_asserted = False
        c._upd()
        reads.clear()
        del mine[:]
        del missing[:]
        logw = []
        vecs = []
        for v in accl[offl[i]:offl[i + 1]]:
            a, d = (v >> 8) & 0xFFFF, v & 0xFF
            if v >> 24:
                logw.append((a, d))
            else:
                reads[a].append(d)
                if a in VECS:
                    vecs.append(a)
        pcb = bytes(opb[i])
        key = (r[8], pcb)
        mtext = texts[tix[i]]
        after_fcb = prev_text is not None and prev_text.startswith("FCB")
        if r[8] in skip_pcs:                         # (the probe: a breakpoint there returned to the probe)
            prev_text = mtext
            stats["skipped"] += 1
            continue
        if after_fcb:                                # (MAME's disassembler keeps the page of an FCB'd prefix)
            stats["dis_after_fcb"] += 1
        elif key not in seen:
            mem = bytearray(65536)
            for k in range(5):
                mem[(r[8] + k) & 0xFFFF] = pcb[k]
            try:
                ins = m6809dis.decode(mem.__getitem__, r[8])
                t = ins.text
                opcount[ins.op] += 1
            except Exception as e:
                t = "<%s>" % e
            seen[key] = t
            stats["dis"] += 1
            if t != mtext:
                stats["dis_bad"] += 1
                if stats["dis_bad"] <= 10:
                    print("  dis %s %04X %s: %r, MAME %r" % (name, r[8], pcb.hex(), t, texts[tix[i]]))
        prev_text = mtext
        n = 0
        waited = False
        try:
            n = c.step()
            for _ in range(4):                       # a wait, or an interrupt taken after it (its vector was read)
                if c.wait and not waited:
                    waited = True
                    stats["waits"] += 1
                vec = vecs[0] if vecs and reads.get(vecs[0]) else None
                if vec is None:
                    if c.wait != m6809.SYNC:
                        break
                    c.set_irq(True)                  # (a masked line ended the SYNC)
                    n += c.step()
                    c.set_irq(False)
                    continue
                kind = VECS[vec]
                if kind == "irq":
                    c.set_irq(True)
                elif kind == "firq":
                    c.set_firq(True)
                else:
                    c.lds = True
                    c.nmi()
                n += c.step()
                c.set_irq(False)
                c.set_firq(False)
                if not reads.get(vec):
                    stats["ints"] += 1
                    vecs.pop(0)
        except m6809.M6809Error as e:
            print("  ", name, e)
        nr = regsl[i + 1]
        ok = list(c.state()) == nr and mine == logw and not missing
        if ok and (strict or not waited) and n != cycl[i + 1] - cycl[i]:
            ok = False
        stats["steps"] += 1
        if not ok:
            bad += 1
            stats["bad"] += 1
            if bad <= 10:
                print("  step %s #%d %04X %s: mine %s cyc %d writes %s missing %s; MAME %s cyc %d writes %s" % (
                    name, i, r[8], texts[tix[i]], " ".join("%X" % v for v in c.state()), n, mine[:6],
                    ["%04X" % a for a in missing[:4]], " ".join("%X" % v for v in nr), cycl[i + 1] - cycl[i], logw[:6]))
    return bad


def trace_tests(names):
    opcount = {"games": Counter(), "probe": Counter()}
    for name in names:
        f = OUT / (name + ".npz")
        if not f.exists():
            continue
        t = time.time()
        stats = Counter()
        probe = name == "probe"
        parts, skip = load_trace(f)
        for part in parts:
            replay(part, stats, opcount["probe" if probe else "games"], name, skip, probe)
        dt = time.time() - t
        print("%-18s %8d steps checked, %d mismatches, %4d interrupts, %3d waits; %5d distinct instructions, %d text mismatches"
              " (%.1f s, %.0f steps/s)" % (name, stats["steps"], stats["bad"], stats["ints"], stats["waits"], stats["dis"],
                                           stats["dis_bad"], dt, stats["steps"] / dt))
        check(stats["bad"] == 0 and stats["dis_bad"] == 0, "trace %s" % name)
    all_ops = set(m6809dis.OPS) - {0x10, 0x11, 0x1010, 0x1011, 0x1110, 0x1111}
    for k, c in opcount.items():
        if c:
            ops = set(c) & all_ops
            print("opcode coverage, %-5s %d of %d opcodes (%d page 1, %d page 2, %d page 3); not seen: %s" % (
                k, len(ops), len(all_ops), sum(1 for o in ops if o < 0x100), sum(1 for o in ops if o >> 8 == 0x10),
                sum(1 for o in ops if o >> 8 == 0x11),
                " ".join("%X" % o for o in sorted(all_ops - ops)) if len(all_ops - ops) < 40 else "%d" % len(all_ops - ops)))
    return opcount


# ---- (c) the probe program ----------------------------------------------------------------------------------
# Pac-Mania's main CPU after its RAM clear ($C2DE): $4000-$BFFF is work RAM (banks $180-$183), interrupts are off.
# The probe is loaded at $4000 (code), data at $AC00-$AFFF (bytes $AC-$AF, so any word read there points into
# it), stacks in $B400-$BC00.  Every case sets CC (I and F kept) and some registers, then runs one instruction;
# cases are simulated with m6809.py first and kept only when all their accesses stay inside these areas.
PROBE_AT, PROBE_BP, DATA, STACK = 0x4000, 0xC2DE, (0xAC00, 0xB000), (0xB000, 0xC000)
CODE_END = 0xAB00


class ProbeGen:
    def __init__(self, seed=6809):
        self.rng = random.Random(seed)
        self.mem = bytearray(65536)
        for a in range(*DATA):
            self.mem[a] = self.rng.randrange(0xAC, 0xB0)
        self.at = PROBE_AT
        self.cpu = M6809(self._rd, self._wr)
        self.cpu.pc = PROBE_AT
        self.cpu.cc = 0xD0
        self.cpu.s = 0xB800
        self.cpu.set_irq(True)                       # (MAME: the vblank IRQ is asserted and never acknowledged)
        self.case_lo = self.case_hi = 0
        self.low_ok = False
        self.cases = 0
        self.mem[0xFFF2:0x10000] = bytes([0xFF, 0x00] * 7)    # the SWI family lands here: back to the probe (a bp in MAME)
        self.failed = []
        self.full = False

    def _rd(self, a):
        if not (PROBE_AT <= a < self.case_hi or DATA[0] <= a < STACK[1] or (self.low_ok and a < 2) or a >= 0xFFF2):
            raise ValueError("read %04X" % a)
        return self.mem[a]

    def _wr(self, a, v):
        if not (DATA[0] <= a < STACK[1] or self.case_lo <= a < self.case_hi or (self.low_ok and a < 2)):
            raise ValueError("write %04X" % a)
        self.mem[a] = v

    def rnd_data(self):
        return self.rng.randrange(DATA[0] + 0x80, DATA[1] - 0x80)

    def setup(self, need=(), force=None):
        """Code that loads S, CC and a random choice of the other registers (force: {reg: value})."""
        r = self.rng
        force = dict(force or {})
        v = {"s": r.randrange(0xB400, 0xBC00)}
        for k in ("dp", "d", "x", "y", "u"):
            if k in need or r.random() < 0.25:
                if k == "dp":
                    v[k] = r.randrange(DATA[0] >> 8, DATA[1] >> 8)
                elif k == "d":
                    v[k] = r.randrange(0x10000) if r.random() < 0.6 else r.randrange(0, 0x200)
                else:
                    v[k] = self.rnd_data() if r.random() < 0.8 else r.randrange(0x10000)
        v.update(force)
        code = []
        if "dp" in v:
            code += [0x86, v["dp"], 0x1F, 0x8B]
        if "d" in v:
            code += [0xCC, v["d"] >> 8, v["d"] & 0xFF]
        if "a" in v:
            code += [0x86, v["a"]]
        if "b" in v:
            code += [0xC6, v["b"]]
        for k, pre in (("x", [0x8E]), ("y", [0x10, 0x8E]), ("u", [0xCE]), ("s", [0x10, 0xCE])):
            if k in v:
                code += pre + [v[k] >> 8, v[k] & 0xFF]
        cc = v.get("cc", r.randrange(256)) | 0x50
        code += [0x1A, 0xFF, 0x1C, cc]
        return code

    def try_case(self, build):
        """build(at) -> bytes of one case (setup + instruction(s)); simulated, kept if it behaves."""
        for _ in range(300):
            snap = (bytes(self.mem), self.cpu.state(), self.cpu.lds)
            code = bytes(build(self.at))
            end = self.at + len(code)
            if end > CODE_END:
                self.full = True
                return False
            self.mem[self.at:end] = code
            self.case_lo, self.case_hi = self.at, end
            c = self.cpu
            ok = True
            try:
                for _ in range(64):
                    if c.pc == end and not c.wait:
                        break
                    c.step()
                    if c.pc == 0xFF00:                     # what the breakpoint on the vector's target does
                        c.pc = (self.mem[(c.s + 10) & 0xFFFF] << 8) | self.mem[(c.s + 11) & 0xFFFF]
                        c.s = (c.s + 12) & 0xFFFF
                    if not PROBE_AT <= c.pc <= end:
                        raise ValueError("pc")
                else:
                    raise ValueError("no end")
                if c.cc & 0x50 != 0x50 or c.wait:
                    raise ValueError("cc")
            except (ValueError, m6809.M6809Error) as e:
                ok = False
                self.why = str(e)
            if ok:
                self.at = end
                self.cases += 1
                return True
            self.mem[:] = snap[0]
            c.a, c.b, c.x, c.y, c.u, c.s, c.dp, c.cc, c.pc = snap[1]
            c.lds = snap[2]
            c.wait = 0
            c._upd()
        self.failed.append((code[-6:].hex(), self.why))
        return False

    def operand(self, mode, ln, at_end=None):
        r = self.rng
        if mode == m6809dis.IMM:
            return [r.randrange(256) for _ in range(ln)]
        if mode == m6809dis.DIR:
            return [r.randrange(256)]
        if mode == m6809dis.EXT:
            a = self.rnd_data()
            return [a >> 8, a & 0xFF]
        return self.idx_bytes(r.randrange(256))

    def idx_bytes(self, pb):
        r = self.rng
        if not pb & 0x80:
            return [pb]
        k = pb & 15
        if k == 8:
            return [pb, r.randrange(256)]
        if k == 9:
            o = r.randrange(-0x400, 0x400) & 0xFFFF
            return [pb, o >> 8, o & 0xFF]
        if k == 12:
            return [pb, r.randrange(0x80, 0xF8)]          # backwards: code already there
        if k == 13:
            return [pb, None, None]                         # filled by the caller: a data address
        if k == 15:
            a = self.rnd_data()
            return [pb, a >> 8, a & 0xFF]
        return [pb]

    def instr(self, prefix, op, mode, ln, pb=None):
        """Builder for one ordinary instruction with random operands."""
        def build(at):
            need = ("dp",) if mode == m6809dis.DIR else ()
            if mode == m6809dis.IND:
                ob = self.idx_bytes(self.rng.randrange(256) if pb is None else pb)
                self.low_ok = ob[0] & 0x80 and ob[0] & 15 in (7, 10, 14)
            else:
                ob = self.operand(mode, ln)
                self.low_ok = False
            code = self.setup(need) + prefix + [op]
            if None in ob:                                  # 16-bit PC-relative: aim into the data
                end = at + len(code) + 3
                o = (self.rnd_data() - end) & 0xFFFF
                ob = [ob[0], o >> 8, o & 0xFF]
            return code + ob
        return build

    def generate(self):
        r = self.rng
        D = m6809dis
        skip = {0x10, 0x11, 0x13, 0x14, 0x15, 0xCD, 0x3C, 0x3E, 0x3F, 0x103E, 0x103F, 0x113E, 0x113F, 0x1010, 0x1011,
                0x1110, 0x1111, 0x39, 0x3B, 0x0E, 0x6E, 0x7E, 0x9D, 0xAD, 0xBD, 0x1E, 0x1F, 0x35, 0x37}
        plain = [o for o in sorted(D.OPS) if o not in skip and D.OPS[o][1] not in (D.REL, D.LREL)]
        # branches (taken or not, over NOPs), BSR/LBSR
        for o in [o for o in sorted(D.OPS) if D.OPS[o][1] in (D.REL, D.LREL)]:
            for rep in range(3):
                def build(at, o=o):
                    k = r.randrange(4)
                    pre = [o >> 8] if o > 0xFF else []
                    off = [k >> 8, k] if D.OPS[o][1] == D.LREL else [k]
                    return self.setup() + pre + [o & 0xFF] + off + [0x12] * k
                self.try_case(build)
        # TFR / EXG: every postbyte (PC as a destination only from a 16-bit register holding the next address)
        for op in (0x1F, 0x1E):
            for pb in range(256):
                src, dst = pb >> 4, pb & 15
                if op == 0x1F and dst == 5 or op == 0x1E and 5 in (src, dst):
                    other = src if dst == 5 else dst
                    if other > 4 or (op == 0x1E and src == dst):
                        continue
                    def build(at, op=op, pb=pb, other=other):
                        base = self.setup()
                        nxt = at + len(base) + 5 + 2   # (+ the register load below, 3 or 4 bytes)
                        ld = {0: [0xCC], 1: [0x8E], 2: [0x10, 0x8E], 3: [0xCE], 4: [0x10, 0xCE]}[other]
                        nxt = at + len(base) + len(ld) + 2 + 2
                        return base + ld + [nxt >> 8, nxt & 0xFF] + [op, pb]
                    self.try_case(build)
                    continue
                self.try_case(lambda at, op=op, pb=pb: self.setup() + [op, pb])
        # PSH/PUL with random masks; PUL with PC from a frame pushed first
        for op in (0x34, 0x36, 0x35, 0x37):
            for rep in range(24):
                m = r.randrange(256)
                if op in (0x35, 0x37):
                    m &= 0xBF if r.random() < 0.5 else 0xFF
                def build(at, op=op, m=m):
                    base = self.setup()
                    if op in (0x35, 0x37) and m & 0x80:
                        push = 0x34 if op == 0x35 else 0x36
                        nxt = at + len(base) + 3 + 2 + 2 + 2
                        return base + [0xCC, nxt >> 8, nxt & 0xFF, push, 0x06, push, m & 0x7F, op, m]
                    return base + [op, m]
                self.try_case(build)
        # RTS, RTI (E set / clear), JMP/JSR in their modes, all aimed at the next instruction
        for rep in range(6):
            def rts(at):
                base = self.setup()
                nxt = at + len(base) + 3 + 2 + 1
                return base + [0xCC, nxt >> 8, nxt & 0xFF, 0x34, 0x06, 0x39]
            self.try_case(rts)
            for e in (0x80, 0x00):
                def rti(at, e=e):
                    base = self.setup()
                    nxt = at + len(base) + 3 + 2 + 2 + 2 + 1
                    cc_op = [0x1A, 0x80] if e else [0x1C, 0x7F]
                    return base + [0xCC, nxt >> 8, nxt & 0xFF, 0x34, 0x06] + cc_op + [0x34, 0x7F if e else 0x01] + [0x3B]
                self.try_case(rti)
            for op in (0x0E, 0x9D):
                def jdir(at, op=op):
                    base = self.setup()
                    nxt = at + len(base) + 4 + 2
                    return base + [0x86, nxt >> 8, 0x1F, 0x8B, op, nxt & 0xFF]
                self.try_case(jdir)
            for op in (0x7E, 0xBD):
                def jext(at, op=op):
                    base = self.setup()
                    nxt = at + len(base) + 3
                    return base + [op, nxt >> 8, nxt & 0xFF]
                self.try_case(jext)
            for op in (0x6E, 0xAD):
                def jx(at, op=op):
                    base = self.setup()
                    nxt = at + len(base) + 3 + 2
                    return base + [0x8E, nxt >> 8, nxt & 0xFF, op, 0x84]
                self.try_case(jx)

                def jpcr(at, op=op):
                    return self.setup() + [op, 0x8C, 0x00]
                self.try_case(jpcr)

                def jind(at, op=op):
                    base = self.setup()
                    p = self.rnd_data()
                    nxt = at + len(base) + 3 + 3 + 4
                    return base + [0xCC, nxt >> 8, nxt & 0xFF, 0xFD, p >> 8, p & 0xFF, op, 0x9F, p >> 8, p & 0xFF]
                self.try_case(jind)
        # SYNC (the IRQ line is up: it ends at once), CWAI and ANDCC clearing I (the IRQ is taken)
        for rep in range(4):
            self.try_case(lambda at: self.setup() + [0x13])
            self.try_case(lambda at: self.setup() + [0x3C, r.randrange(256) & 0xEF | 0x40])
            self.try_case(lambda at: self.setup() + [0x1C, r.randrange(256) & 0xEF | 0x40, 0x12])
        # the SWI family (MAME: a breakpoint on the vector's target pulls the frame and returns)
        for seq in ([0x3F], [0x10, 0x3F], [0x11, 0x3F], [0x3E], [0x10, 0x3E], [0x11, 0x3E]):
            for rep in range(3):
                self.try_case(lambda at, seq=seq: self.setup() + list(seq))
        # prefixes: repeated, and page 2/3 bytes that are no page 2/3 opcode
        for seq in ([0x10, 0x10, 0x8E, 0x12, 0x34], [0x10, 0x11, 0x8E, 0x12, 0x34], [0x11, 0x10, 0x83, 0x12, 0x34],
                    [0x11, 0x11, 0x8C, 0x12, 0x34], [0x10, 0x86, 0x4C], [0x11, 0x86, 0x5C], [0x10, 0x12, 0x4C],
                    [0x10, 0x30, 0x4C], [0x11, 0x8E, 0x5C]):
            for rep in range(2):
                self.try_case(lambda at, seq=seq: self.setup() + list(seq))
        idx_ops = [o for o in plain if D.OPS[o][1] == D.IND]
        for rep in range(5):
            if rep == 1 or rep == 2:             # every postbyte twice, on random indexed instructions
                for pb in range(256):
                    o = r.choice(idx_ops)
                    self.try_case(self.instr([o >> 8] if o > 0xFF else [], o & 0xFF, D.IND, 1, pb))
            order = list(plain)
            r.shuffle(order)
            for o in order:                      # every plain opcode, until the code area is full
                n, mode, ln = D.OPS[o]
                self.try_case(self.instr([o >> 8] if o > 0xFF else [], o & 0xFF, mode, ln))
        self.mem[self.at:self.at + 2] = b"\x20\xFE"         # BRA *
        return self.at


def probe_vector_targets():
    """Pac-Mania's main CPU vectors $FFF2-$FFFF (bank 7 = the top of pn2_p7.bin)."""
    rom = zipfile.ZipFile(ROMS / "pacmania.zip").read("pn2_p7.bin")
    return sorted({(rom[a] << 8) | rom[a + 1] for a in range(0xFFF2, 0xFFFE, 2)})


def probe_script(end):
    t = TRACELOG
    back = "".join("bpset %X,(s>=B000 && s<C000),{do pc=w@(s+0A); do s=s+0C; g}; " % v for v in probe_vector_targets())
    inner = "bpdisable; load probe.bin,%X; do pc=%X; trace probe.txt,maincpu,noloop,%s; %s; %s; %sbpset %X,1,{bpdisable; wpclear; trace off,maincpu; g}; g" % (
        PROBE_AT, PROBE_AT, t, WPS[0], WPS[1], back, end)
    return "\n".join(["local dbg = manager.machine.debugger", "dbg:command('focus maincpu')",
                      "dbg:command(%s)" % lua_quote("bpset %X,1,{%s}" % (PROBE_BP, inner)), "dbg:command('go')"]) + "\n"


def make_probe_job():
    d = OUT / "run_probe"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    g = ProbeGen()
    end = g.generate()
    print("probe: %d cases, %d bytes" % (g.cases, end - PROBE_AT))
    (d / "probe.bin").write_bytes(bytes(g.mem[PROBE_AT:DATA[1]]))
    (d / "t.lua").write_text(probe_script(end))
    log = open(d / "mame.log", "w")
    return ("probe", d, subprocess.Popen(mame_cmd("pacmania", "t.lua", 3), cwd=d, stdout=log, stderr=subprocess.STDOUT))


def main():
    args = sys.argv[1:]
    names = [args[args.index("--only") + 1]] if "--only" in args else NAMES
    unit_tests()
    missing = [n for n in names if "--regen" in args or not (OUT / (n + ".npz")).exists()]
    if missing:
        if have_mame():
            make_traces(missing)
        else:
            print("MAME traces: skipped (no mame or ROMs)")
    trace_tests(names)
    print("m6809: %s" % ("OK" if not FAILS else "%d FAILED" % len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
