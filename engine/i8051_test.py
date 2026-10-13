"""Tests of the MCS-51 interpreter (engine/i8051.py) and disassembler (engine/i8051dis.py).

    venv/bin/python engine/i8051_test.py [--regen] [--seconds N]

1. instruction tests: flags (ADD/ADDC/SUBB/DA/MUL/DIV), parity, bit addressing, PUSH/POP of SP, DJNZ, CJNE, MOVX
   addressing, timers (modes 0-3, the mode 2 reload, GATE), interrupt entry (+2 cycles, the vector runs in the same
   iteration), priorities and RETI, level and edge triggered INT0/INT1, cycle counts.
2. MAME comparison: MAME 0.289's mrheli (Irem M72, i8751 MCU at 8 MHz) from power on through the attract mode with
   its sample playback, the MCU traced by the debugger (registers, TCON/TMOD, the timers, P3 with the INT0/INT1 pins,
   totalcycles before every instruction) plus a bus log (Lua taps on the MCU's xdata space: every MOVX read and write,
   and on its sfr space: port reads and writes).  The interpreter replays it independently of the board: MOVX reads
   come from the log, every MOVX and port write is checked against it, INT0/INT1 change where the trace's P3 pins
   change (MAME applies line changes between instructions), the timer interrupts must come by themselves; PC, A, B,
   PSW, SP, DPTR, R0-R7, IE, IP, TCON, TMOD, TL0/TH0/TL1/TH1 and the cycle count are compared at every instruction.
   The disassembler is checked against MAME's disassembly of every executed address.  Fixtures in build/i8051/
   (generated when missing and mame is installed, ~10 minutes for the default 50 seconds; --regen forces it).
   ROM content is never written to the repo.
"""
import gzip
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import ROOT
from i8051 import I8051, CYCLES, PARITY

FAIL = []


def check(cond, what):
    if not cond:
        FAIL.append(what)
        print("FAIL:", what)


# ---- 1. instruction tests ----------------------------------------------------------------------------------------

def make(code, at=0, vectors=None, **kw):
    rom = bytearray(0x1000)
    rom[at:at + len(code)] = bytes(code)
    if at:
        rom[0:3] = bytes([0x02, at >> 8, at & 0xFF])         # ljmp
    for a, bs in (vectors or {}).items():
        rom[a:a + len(bs)] = bytes(bs)
    xram = bytearray(0x10000)
    outs = []

    def rd(a): return xram[a]

    def wr(a, v): xram[a] = v
    cpu = I8051(rom, rd, wr, port_out=lambda n, v: outs.append((n, v)), **kw)
    cpu.xram, cpu.outs = xram, outs
    return cpu


def steps(cpu, n):
    return [cpu.step() for _ in range(n)]


def unit_tests():
    # ADD / ADDC / SUBB flags, parity
    cpu = make([0x74, 0x7F, 0x24, 0x01,          # mov a,#$7F; add a,#1 -> $80 OV AC
                0x74, 0xFF, 0x34, 0x01,          # mov a,#$FF; addc a,#1 -> 0 CY AC (C was 0)
                0x74, 0x10, 0x94, 0x20,          # mov a,#$10; subb a,#$20 (C=1) -> $EF CY AC
                0x74, 0x80, 0x94, 0x01])         # mov a,#$80; subb a,#1 -> $7F OV AC
    steps(cpu, 2)
    check(cpu.acc == 0x80 and cpu.get_psw() == 0x44 | PARITY[0x80], "add #$7F+1 psw %02x" % cpu.get_psw())
    steps(cpu, 2)
    check(cpu.acc == 0 and cpu.get_psw() == 0xC0, "addc $FF+1 psw %02x" % cpu.get_psw())
    steps(cpu, 2)
    check(cpu.acc == 0xEF and cpu.psw & 0xC4 == 0xC0, "subb $10-$20-1 psw %02x" % cpu.get_psw())
    cpu.psw &= 0x7F
    steps(cpu, 2)
    check(cpu.acc == 0x7F and cpu.psw & 0xC4 == 0x44, "subb $80-1 psw %02x" % cpu.get_psw())

    # DA A (MAME: C is never cleared), MUL (OV = bit 8 of the product), DIV (by 0: OV, A and B kept)
    cpu = make([0x74, 0x99, 0x24, 0x01, 0xD4,    # $99+1 = $9A, da -> $00 C
                0x74, 0x40, 0x75, 0xF0, 0x05, 0xA4,  # $40*5 = $140: A=$40 B=1 OV
                0x74, 0x20, 0x75, 0xF0, 0x00, 0x84,  # div by 0
                0x74, 0xFB, 0x75, 0xF0, 0x0A, 0x84])  # 251/10
    steps(cpu, 3)
    check(cpu.acc == 0 and cpu.psw & 0x80, "da a %02x %02x" % (cpu.acc, cpu.psw))
    steps(cpu, 3)
    check((cpu.acc, cpu.b) == (0x40, 1) and cpu.psw & 0x84 == 0x04, "mul %02x %02x %02x" % (cpu.acc, cpu.b, cpu.psw))
    c = steps(cpu, 3)
    check((cpu.acc, cpu.b) == (0x20, 0) and cpu.psw & 0x84 == 0x04 and c[2] == 4, "div by 0")
    steps(cpu, 3)
    check((cpu.acc, cpu.b) == (25, 1) and not cpu.psw & 0x84, "div 251/10")

    # PSW writes keep the parity bit; register banks
    cpu = make([0x74, 0x01, 0x75, 0xD0, 0x18, 0x78, 0x55, 0x75, 0xD0, 0x00, 0xE5, 0x18])
    steps(cpu, 2)
    check(cpu.get_psw() == 0x19, "psw write keeps P %02x" % cpu.get_psw())
    steps(cpu, 3)
    check(cpu.ram[0x18] == 0x55 and cpu.acc == 0x55, "bank 3 r0")

    # bit addressing, JBC, CPL/MOV bit,C; PUSH SP / POP SP
    cpu = make([0xD2, 0x0B, 0x10, 0x0B, 0x00, 0x00, 0xB2, 0xE7, 0xA2, 0xE7, 0x92, 0x00,
                0xC0, 0x81, 0xD0, 0x81])
    steps(cpu, 1)
    check(cpu.ram[0x21] == 0x08, "setb $21.3")
    steps(cpu, 1)
    check(cpu.ram[0x21] == 0 and cpu.pc == 5, "jbc clears and jumps (pc %x)" % cpu.pc)
    steps(cpu, 4)
    check(cpu.acc == 0x80 and cpu.psw & 0x80 and cpu.ram[0x20] & 1, "cpl acc.7, mov c,acc.7, mov $20.0,c")
    steps(cpu, 1)
    check(cpu.sp == 8 and cpu.ram[8] == 8, "push sp pushes the incremented sp")
    steps(cpu, 1)
    check(cpu.sp == 7, "pop sp: popped value - 1 (%02x)" % cpu.sp)

    # DJNZ, CJNE carry, MOVX @Ri with P2, MOVC
    cpu = make([0x7A, 0x03, 0xDA, 0xFE, 0xB4, 0x10, 0x00, 0x75, 0xA0, 0x12, 0x78, 0x34, 0xE2, 0x74, 0x00,
                0x83, 0x77])
    cpu.xram[0x1234] = 0x5A
    c = steps(cpu, 4)
    check(cpu.ram[2] == 0 and c == [1, 2, 2, 2], "djnz r2 cycles %s" % c)
    cpu.acc = 5
    steps(cpu, 1)
    check(cpu.psw & 0x80, "cjne a<data sets C")
    steps(cpu, 3)
    check(cpu.acc == 0x5A, "movx a,@r0 with P2")
    c = steps(cpu, 2)
    check(cpu.acc == 0x77 and c == [1, 2], "movc a,@a+pc")

    # timer 1 mode 2: reload cycle by cycle, TF1; timer 0 mode 1 overflow -> interrupt, +2 cycles, vector runs
    cpu = make([0x75, 0x89, 0x21, 0x75, 0x8D, 0xFE, 0x75, 0x8B, 0xFE, 0xD2, 0x8E])
    steps(cpu, 4)                                # tmod, th1, tl1 = $FE, setb tr1 (1 cycle burnt)
    check(cpu.tl1 == 0xFF and not cpu.tcon & 0x80, "t1 counts after setb tr1 %02x" % cpu.tl1)
    steps(cpu, 1)                                # nop: overflow -> reload $FE
    check(cpu.tl1 == 0xFE and cpu.tcon & 0x80, "t1 mode 2 reload %02x" % cpu.tl1)
    cpu = make([0x75, 0x89, 0x01, 0x75, 0x8C, 0xFF, 0x75, 0x8A, 0xFD, 0x75, 0xA8, 0x82, 0xD2, 0x8C, 0x00, 0x00, 0x00],
               at=0x40, vectors={0x0B: [0x04]})       # inc a at the timer 0 vector
    steps(cpu, 6)
    c = steps(cpu, 3)
    check(cpu.pc == 0x0C and cpu.acc == 1 and c == [1, 1, 3] and cpu.sp == 9 and not cpu.tcon & 0x20,
          "TF0 interrupt: %s pc %x" % (c, cpu.pc))
    check(cpu.ram[8] == 0x50 and cpu.ram[9] == 0, "pushed return address %02x%02x" % (cpu.ram[9], cpu.ram[8]))

    # INT0 level: IE0 follows the line, not cleared by the entry; edge: set on the transition, cleared on entry
    cpu = make([0x75, 0xA8, 0x81, 0x00, 0x00, 0x00], at=0x40)
    steps(cpu, 2)
    cpu.set_input_line(I8051.INT0_LINE, True)
    check(cpu.tcon & 2, "level INT0 sets IE0")
    entered = []
    cpu.irq_hook = lambda c, line: entered.append(line)
    steps(cpu, 1)
    check(entered == [0] and cpu.tcon & 2 and cpu.irq_active == 1, "level: IE0 kept on entry")
    cpu.set_input_line(I8051.INT0_LINE, False)
    check(not cpu.tcon & 2, "level: clear clears IE0")
    cpu = make([0x75, 0x88, 0x01, 0x75, 0xA8, 0x81, 0x00, 0x00], at=0x40)
    steps(cpu, 3)
    cpu.set_input_line(I8051.INT0_LINE, True)
    check(cpu.tcon & 2, "edge INT0 sets IE0")
    steps(cpu, 1)
    check(not cpu.tcon & 2 and cpu.sp == 9, "edge: IE0 cleared on entry")
    cpu.set_input_line(I8051.INT0_LINE, True)
    check(not cpu.tcon & 2, "edge: no new IE0 without a transition")

    # priorities: a high level interrupts a low one, not the reverse; RETI ends the level
    cpu = make([0x75, 0xB8, 0x04, 0x75, 0xA8, 0x85, 0x00, 0x00, 0x00], at=0x40,
               vectors={0x03: [0x00, 0x00], 0x13: [0x32]})   # INT0 (low): nops; INT1 (high): reti
    steps(cpu, 3)
    cpu.set_input_line(I8051.INT0_LINE, True)
    steps(cpu, 1)
    check(cpu.pc == 4 and cpu.cur_irq_prio == 0, "INT0 low taken")
    cpu.set_input_line(I8051.INT1_LINE, True)
    steps(cpu, 1)
    check(cpu.pc == 4 and cpu.cur_irq_prio == 0 and cpu.irq_active == 1, "INT1 high nests, reti back (%x)" % cpu.pc)
    cpu.set_input_line(I8051.INT0_LINE, False)
    cpu.tcon &= ~8                               # (the program would clear IE1; the line stays: level, no new edge)
    steps(cpu, 1)
    check(cpu.pc == 5, "no new INT0 while it is in service")

    # run(): MAME's do/while overshoot
    cpu = make([0x02, 0x00, 0x00])               # ljmp 0 (2 cycles)
    n = cpu.run(3)
    check(n == 4 and cpu.icount == -1, "run overshoot %d %d" % (n, cpu.icount))
    n = cpu.run(3)
    check(n == 2 and cpu.icount == 0, "overshoot carried %d" % n)

    for op, n in ((0x00, 1), (0x02, 2), (0x12, 2), (0x84, 4), (0xA4, 4), (0xA5, 1), (0x85, 2), (0x75, 2),
                  (0xE0, 2), (0xF0, 2), (0x93, 2), (0x22, 2), (0x32, 2), (0xB4, 2), (0xD5, 2), (0x10, 2)):
        check(CYCLES[op] == n, "cycles %02x" % op)


# ---- 2a. a synthetic program: every MCS-51 opcode with random operands, the timers, the serial port, priorities ---
#
# Run by MAME's i8751 in place of mrheli's MCU program (the ROM region patched from Lua before the first instruction)
# and replayed like the game trace.  A loop of blocks "lcall SETUP; <instruction>": SETUP loads random values (a
# table-driven generator in the program) into $20-$3F (the bit area and the operands), a random register bank with
# R0/R1 pointing into $20-$3F, B, DPTR (into the random tables, for MOVC), A and PSW.  Branches skip a NOP; direct
# operands are RAM or ACC/B/PSW/DPL/DPH/P1, bits RAM, ACC/B/PSW/P1/TCON/SCON bits; MOVX goes to the dual-port RAM.
# Then the timers in every mode with their interrupts, nested priorities, GATE, the serial port in modes 0-3.

class Asm:
    def __init__(self):
        self.mem = bytearray(0x1000)
        self.pc = 0
        self.labels = {}
        self.fix = []                            # (at, kind, label, pc_after)

    def org(self, a):
        self.pc = a

    def label(self, name):
        self.labels[name] = self.pc

    def db(self, *bs):
        for b in bs:
            self.mem[self.pc] = b & 0xFF
            self.pc += 1

    def lab16(self, op, name):                   # ljmp / lcall / mov dptr,#label
        self.db(op)
        self.fix.append((self.pc, "abs", name, 0))
        self.db(0, 0)

    def rel(self, ops, name):                    # an instruction whose last byte is a relative offset to name
        self.db(*ops)
        self.fix.append((self.pc, "rel", name, self.pc + 1))
        self.db(0)

    def link(self):
        for at, kind, name, after in self.fix:
            t = self.labels[name]
            if kind == "abs":
                self.mem[at], self.mem[at + 1] = t >> 8, t & 0xFF
            else:
                d = t - after
                assert -128 <= d < 128, (name, d)
                self.mem[at] = d & 0xFF
        return bytes(self.mem)


def synthetic_program(seed=8051):
    import random
    rnd = random.Random(seed)
    r8 = lambda: rnd.randrange(256)
    a = Asm()
    for vec, name in ((0, "MAIN"), (3, "X0H"), (0x0B, "T0H"), (0x13, "X1H"), (0x1B, "T1H"), (0x23, "SERH")):
        a.org(vec)
        a.lab16(0x02, name)
    a.org(0x30)
    a.label("X0H")
    a.db(0x05, 0x44, 0xC2, 0x89, 0x32)           # inc $44; clr ie0 (level: still set); reti
    a.label("X1H")
    a.db(0x05, 0x45, 0xC2, 0x8B, 0x32)
    a.label("T0H")
    a.db(0xC0, 0xD0, 0x05, 0x41, 0xE5, 0x46)     # push psw; inc $41; mov a,$46 (nesting test: spin in T0)
    a.rel([0x60], "T0X")                         # jz T0X
    a.db(0x7E, 0x30)                             # mov r6,#$30
    a.rel([0xDE], "T0SPIN")                      # T0SPIN: djnz r6,T0SPIN
    a.labels["T0SPIN"] = a.pc - 2
    a.label("T0X")
    a.db(0xD0, 0xD0, 0x32)                       # pop psw; reti
    a.label("T1H")
    a.db(0x05, 0x42, 0x32)
    a.label("SERH")
    a.db(0xC2, 0x99, 0xC2, 0x98, 0x05, 0x43, 0x32)   # clr ti; clr ri; inc $43; reti
    a.label("SUBRET")
    a.db(0x22)
    a.label("SUBRETI")
    a.db(0x32)
    # RND: A = T1[$7F] ^ T2[$7E]; $7F += 1 (carry into $7E)
    a.label("RND")
    a.lab16(0x90, "TAB1")                        # mov dptr,#TAB1
    a.db(0xE5, 0x7F, 0x93, 0xF5, 0x7D,           # mov a,$7F; movc; mov $7D,a
         0xE5, 0x7E, 0x05, 0x83, 0x93, 0x65, 0x7D,  # mov a,$7E; inc dph; movc; xrl a,$7D
         0x05, 0x7F, 0xC0, 0xE0, 0xE5, 0x7F, 0x70, 0x02, 0x05, 0x7E, 0xD0, 0xE0, 0x22)
    # SETUP
    a.label("SETUP")
    a.db(0x75, 0xD0, 0x00, 0x78, 0x20)           # mov psw,#0; mov r0,#$20
    a.label("SETUP1")
    a.lab16(0x12, "RND")
    a.db(0xF6, 0x08)                             # mov @r0,a; inc r0
    a.rel([0xB8, 0x40], "SETUP1")                # cjne r0,#$40,SETUP1
    a.lab16(0x12, "RND")
    a.db(0x54, 0x18, 0xF5, 0x7C, 0x85, 0x7C, 0xD0)   # anl a,#$18; mov $7C,a; mov psw,$7C
    for r in range(2, 8):
        a.lab16(0x12, "RND")
        a.db(0xF8 | r)                           # mov rN,a
    for r in range(2):
        a.lab16(0x12, "RND")
        a.db(0x54, 0x1F, 0x44, 0x20, 0xF8 | r)   # anl a,#$1F; orl a,#$20; mov rN,a
    a.lab16(0x12, "RND")
    a.db(0xF5, 0xF0, 0x75, 0xA0, 0xC0)           # mov b,a; mov p2,#$C0
    a.lab16(0x12, "RND")
    a.db(0xC0, 0xE0)                             # push acc (dpl)
    a.lab16(0x12, "RND")
    a.db(0x54, 0xE7, 0x45, 0x7C, 0xC0, 0xE0)     # anl a,#$E7; orl a,$7C; push acc (psw)
    a.lab16(0x12, "RND")
    a.db(0xF5, 0x7A, 0xD0, 0xD0, 0xD0, 0x82, 0x75, 0x83, 0x0E, 0xE5, 0x7A, 0x22)
    # pop psw; pop dpl; mov dph,#$0E; mov a,$7A; ret

    a.label("MAIN")
    a.db(0x75, 0x81, 0x5F, 0x75, 0x7E, 0x00, 0x75, 0x7F, 0x00)   # mov sp,#$5F; seed
    a.label("LOOP")
    dirs = [lambda: 0x20 + rnd.randrange(32)] * 6 + [lambda: rnd.choice([0xE0, 0xF0, 0xD0, 0x82, 0x83, 0x90])]
    bits = [lambda: rnd.randrange(0x80)] * 5 + [lambda: rnd.choice([0xE0, 0xF0, 0xD0, 0x90, 0x88, 0x98]) |
                                                  rnd.randrange(8)]
    d = lambda: rnd.choice(dirs)()
    bt = lambda: rnd.choice(bits)()
    n = [0]

    def block(*body, setup=True):
        if setup:
            a.lab16(0x12, "SETUP")
        a.db(*body)

    def branch(ops):                             # ops + rel over a nop
        a.lab16(0x12, "SETUP")
        a.db(*ops, 0x01, 0x00)

    def ajmp_acall():                            # within the 2 KB page (padded off a page boundary)
        while (a.pc + 8) & 0xF800 != a.pc & 0xF800:
            a.db(0x00)
        a.lab16(0x12, "SETUP")
        t = a.pc + 3
        a.db(0x01 | ((t >> 3) & 0xE0), t & 0xFF, 0x00)      # ajmp t; nop
        t = a.pc + 4
        a.db(0x11 | ((t >> 3) & 0xE0), t & 0xFF, 0x80, 0x01, 0x22)  # acall t; sjmp +1; ret

    for op in range(256):
        hi, lo = op >> 4, op & 15
        if op % 8 == 0:                          # (spread over the program: every page bit combination)
            ajmp_acall()
        if op in (0x02, 0x12, 0x22, 0x32, 0x73, 0x80) or lo == 1:
            continue                              # jumps and calls: below
        if op in (0x10, 0x20, 0x30):
            for _ in range(3):
                branch([op, bt()])
        elif op in (0x40, 0x50, 0x60, 0x70):
            branch([op])
        elif op == 0xB4 or op >= 0xB6 and op <= 0xBF:
            for _ in range(2):
                branch([op, r8()])
        elif op == 0xB5:
            branch([op, d()])
        elif op == 0xD5:
            branch([op, d()])
        elif hi == 0xD and lo >= 8:
            branch([op])
        elif op in (0x72, 0x82, 0x92, 0xA0, 0xA2, 0xB0, 0xB2, 0xC2, 0xD2):
            for _ in range(3):
                block(op, bt())
        elif op in (0x05, 0x15, 0x25, 0x35, 0x42, 0x45, 0x52, 0x55, 0x62, 0x65, 0x95, 0xC5, 0xE5, 0xF5) or \
                (hi == 8 and lo >= 6) or (hi == 0xA and lo >= 6):
            for _ in range(2):
                block(op, d())
        elif op in (0x24, 0x34, 0x44, 0x54, 0x64, 0x74, 0x94) or (hi == 7 and lo >= 6):
            block(op, r8())
        elif op in (0x43, 0x53, 0x63, 0x75):
            for _ in range(2):
                block(op, d(), r8())
        elif op == 0x85:
            for _ in range(2):
                block(op, d(), d())
        elif op == 0x90:
            block(op, 0x0E, r8())
        elif op == 0xC0:                         # push / pop pairs, push sp / pop sp
            block(0xC0, d(), 0xD0, d())
            block(0xC0, 0x81, 0xD0, 0x81)
        elif op == 0xD0:
            block(0xC0, 0xE0, 0xD0, 0xD0)        # push acc; pop psw
        elif op in (0xE0, 0xF0):
            block(0x90, 0xC0, r8(), op)          # mov dptr,#$C0xx; movx
        elif op in (0xD4,):
            for _ in range(3):
                block(0x24, r8(), 0xD4)          # add a,#n; da a
                block(0x34, r8(), 0xD4)
        else:
            block(op)
            if op in (0x84, 0xA4, 0x13, 0x33, 0x03, 0x23):
                block(op)
    # jumps and calls
    for k in range(4):
        a.lab16(0x12, "SETUP")
        a.lab16(0x02, "J%d" % k)                 # ljmp
        a.db(0x00)
        a.label("J%d" % k)
    a.lab16(0x12, "SETUP")
    a.lab16(0x12, "SUBRET")                      # lcall + ret
    a.lab16(0x12, "SETUP")
    a.lab16(0x12, "SUBRETI")                     # lcall + reti (no interrupt in service)
    a.lab16(0x12, "SETUP")
    a.rel([0x80], "S1")                          # sjmp
    a.db(0x00)
    a.label("S1")
    for k in range(3):                           # jmp @a+dptr with a random A
        a.lab16(0x12, "SETUP")
        kk = rnd.randrange(1, 40)
        a.db(0x74, kk)                           # mov a,#kk
        tgt = a.pc + 4
        a.db(0x90, (tgt - kk) >> 8 & 0xFF, (tgt - kk) & 0xFF, 0x73)
    # timers and interrupts (deterministic)
    def wait(r7):
        a.db(0x7F, r7)
        a.db(0xDF, 0xFE)                         # djnz r7,$
    a.db(0x75, 0xD0, 0x00, 0xE4, 0xF5, 0x41, 0xF5, 0x42, 0xF5, 0x43, 0xF5, 0x46)  # psw 0; clear counters, $46
    for tmod, th0, tl0, th1, tl1, ie, ip in (
            (0x22, 0xC0, 0xF0, 0xD0, 0xFA, 0x8A, 0x08), (0x22, 0xE0, 0xFE, 0xC0, 0x00, 0x8A, 0x00),
            (0x22, 0xFF, 0xFE, 0xFF, 0xFD, 0x80, 0x00), (0x00, 0xFF, 0x1C, 0xFF, 0x10, 0x8A, 0x02),
            (0x11, 0xFF, 0xD0, 0xFF, 0xC0, 0x8A, 0x08), (0x03, 0xF8, 0xF0, 0x12, 0x34, 0x8A, 0x00),
            (0x13, 0xE0, 0xFC, 0xFF, 0xF0, 0x8A, 0x02), (0x23, 0xE0, 0xFC, 0xFF, 0xF0, 0x8A, 0x00),
            (0x09, 0xFF, 0x80, 0x00, 0x00, 0x82, 0x00), (0x90, 0x00, 0x00, 0xFF, 0xA0, 0x88, 0x00),
            (0x55, 0xFF, 0xF0, 0xFF, 0xF0, 0x8A, 0x00)):
        a.db(0x75, 0x89, tmod, 0x75, 0x8C, th0, 0x75, 0x8A, tl0, 0x75, 0x8D, th1, 0x75, 0x8B, tl1,
             0x75, 0xB8, ip, 0x75, 0xA8, ie, 0xD2, 0x8C, 0xD2, 0x8E)          # ... setb tr0; setb tr1
        wait(60)
        a.db(0xD2, 0x89)                         # setb ie0 (GATE counts with IE0; EX0 off)
        a.db(0xD2, 0x8B)                         # setb ie1
        wait(60)
        a.db(0x75, 0xA8, 0x00, 0x75, 0x88, 0x00)    # mov ie,#0; mov tcon,#0 (timers stopped, flags cleared)
    # nesting: T0 (high) spins while T1 (low) ... and the reverse: T0 low spins, T1 high interrupts it
    for ip in (0x02, 0x08):
        a.db(0x75, 0x46, 0x01, 0x75, 0x89, 0x21, 0x75, 0x8C, 0xFF, 0x75, 0x8A, 0xC0, 0x75, 0x8D, 0xF0, 0x75, 0x8B, 0xF0,
             0x75, 0xB8, ip, 0x75, 0xA8, 0x8A, 0xD2, 0x8C, 0xD2, 0x8E)
        wait(200)
        a.db(0x75, 0x46, 0x00, 0x75, 0xA8, 0x00, 0x75, 0x88, 0x00)
    a.db(0x75, 0xA8, 0x00, 0xC2, 0x8C, 0xC2, 0x8E, 0x75, 0x88, 0x00)    # ie 0; timers off; tcon 0
    # IE0/IE1 by software: level/edge flags, priorities
    a.db(0x75, 0xB8, 0x04, 0x75, 0xA8, 0x85, 0xD2, 0x89, 0x00, 0xD2, 0x8B, 0x00, 0xD2, 0x88, 0xD2, 0x89, 0x00,
         0xD2, 0x8A, 0xD2, 0x8B, 0x00, 0x75, 0xA8, 0x00, 0x75, 0x88, 0x00)
    # the serial port: mode 0 (shifts P3), modes 1/3 with timer 1 as the baud clock, mode 2, SMOD, REN, ES
    a.db(0x75, 0x89, 0x20, 0x75, 0x8D, 0xFF, 0x75, 0x8B, 0xFF, 0xD2, 0x8E, 0x75, 0xA8, 0x90)
    for scon, pcon in ((0x00, 0x00), (0x40, 0x00), (0x40, 0x80), (0xC8, 0x00), (0x80, 0x00), (0x80, 0x80),
                       (0x50, 0x00), (0xD0, 0x80), (0x10, 0x00)):
        a.db(0x75, 0x87, pcon, 0x75, 0x98, scon, 0x75, 0x99, r8())   # pcon; scon; mov sbuf,#n
        wait(250)
        wait(250)
    a.db(0x75, 0xA8, 0x00, 0x75, 0x98, 0x00, 0x75, 0x87, 0x01, 0x00, 0x00, 0x75, 0x87, 0x00)  # (IDL: no effect)
    a.db(0xC2, 0x8E, 0x75, 0x88, 0x00, 0x75, 0xB8, 0x00, 0x75, 0x89, 0x00)
    a.lab16(0x02, "LOOP")
    assert a.pc <= 0x0E00, hex(a.pc)
    a.org(0x0E00)
    a.label("TAB1")
    a.db(*[r8() for _ in range(512)])
    return a.link()


# ---- 2. MAME comparison --------------------------------------------------------------------------------------------

GAME = "mrheli"
MCU_ROM = ROOT / "assets" / "roms" / "extracted" / "mrheli" / "mh_c-pr-.ic1"
MAME_ROMS = ROOT / "build" / "mrheli" / "mame_roms"
SECONDS = 50                # the first sample plays at ~30 s (frame 1637), three more by 50 s
FIX = ROOT / "build" / "i8051"

SYNTH_SECONDS = 2          # two passes of the synthetic program
LUA = r'''
local dbg = manager.machine.debugger
local pf = io.open("program.bin", "rb")
if pf then  -- the synthetic test: our program in place of the MCU's (before its first instruction)
  local prog = pf:read("a")
  local r = manager.machine.memory.regions[":mcu"]
  for i = 1, #prog do r:write_u8(i - 1, prog:byte(i)) end
end
local mcu = manager.machine.devices[":mcu"]
local xd = mcu.spaces["xdata"]
local sfr = mcu.spaces["sfr"]
local f = io.open("bus.txt", "w")
local function port(o) return o == 0x80 or o == 0x90 or o == 0xa0 or o == 0xb0 end
rt = xd:install_read_tap(0x0000, 0xffff, "rlog", function(o, d, m) f:write(string.format("R %04X %02X\n", o, d)) end)
wt = xd:install_write_tap(0x0000, 0xffff, "wlog", function(o, d, m) f:write(string.format("W %04X %02X\n", o, d)) end)
pr = sfr:install_read_tap(0x80, 0xb0, "prlog", function(o, d, m)
  if port(o) then f:write(string.format("r %04X %02X\n", o, d)) end end)
pw = sfr:install_write_tap(0x80, 0xb0, "pwlog", function(o, d, m)
  if port(o) then f:write(string.format("w %04X %02X\n", o, d)) end end)
dbg:command("trace trace.txt,mcu,noloop,{tracelog \"%02X%02X%02X%02X%04X %02X%02X%02X%02X%02X%02X%02X%02X %02X%02X%02X%02X%02X%02X%02X%02X%02X %d \",a,b,psw,sp,dptr,r0,r1,r2,r3,r4,r5,r6,r7,ie,ip,tcon,tmod,tl0,th0,tl1,th1,p3,totalcycles}")
dbg:command("go")
-- tracelog prints for the debugger's visible CPU, which "go" sets back to the main CPU
dbg.visible_cpu = mcu
sub = emu.add_machine_frame_notifier(function() dbg.visible_cpu = mcu end)
'''


def fixture(name, regen, seconds, program=None):
    d = FIX / name
    fresh = (d / "trace.txt.gz").exists() and (d / "bus.txt.gz").exists() and \
        (d / "seconds").exists() and (d / "seconds").read_text() == str(seconds)
    if program is not None and fresh:
        fresh = (d / "program.bin").exists() and (d / "program.bin").read_bytes() == program
    if fresh and not regen:
        return d
    if not shutil.which("mame") or not MAME_ROMS.is_dir():
        return None
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    print("  running mame %s for %d s (MCU trace of %s, takes ~%d minutes)" % (GAME, seconds, name,
                                                                             seconds * 12 // 60 + 1))
    with tempfile.TemporaryDirectory() as tmp:          # a fresh directory: MAME writes cfg/ and nvram/ there
        with open(os.path.join(tmp, "t.lua"), "w") as f:
            f.write(LUA)
        if program is not None:
            with open(os.path.join(tmp, "program.bin"), "wb") as f:
                f.write(program)
        subprocess.run(["mame", GAME, "-rompath", str(MAME_ROMS), "-debug", "-debugger", "none",
                        "-autoboot_script", "t.lua", "-window", "-video", "none", "-sound", "none", "-nothrottle",
                        "-skip_gameinfo", "-seconds_to_run", str(seconds)],
                       cwd=tmp, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for n in ("trace.txt", "bus.txt"):
            with open(os.path.join(tmp, n), "rb") as src, gzip.open(d / (n + ".gz"), "wb", compresslevel=1) as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
    if program is not None:
        (d / "program.bin").write_bytes(program)
    (d / "seconds").write_text(str(seconds))
    return d


def load_bus(d):
    out = []
    with gzip.open(d / "bus.txt.gz", "rt") as f:
        for line in f:
            out.append((line[0], int(line[2:6], 16), int(line[7:9], 16)))
    return out


def records(d):
    """(state tuple, totalcycles, pc, irq_marker, text) for each traced instruction"""
    irq = None
    with gzip.open(d / "trace.txt.gz", "rt") as f:
        for line in f:
            if len(line) < 60:
                m = re.search(r"interrupted at ([0-9A-F]+), IRQ (\d)", line)
                if m:
                    irq = int(m.group(2))
                continue
            regs, rs, sf, t, rest = line.split(" ", 4)
            pc, text = rest.split(": ", 1)
            yield regs, rs, sf, int(t), int(pc, 16), irq, text.strip()
            irq = None


class Desync(Exception):
    pass


class Replay(I8051):
    """I8051 whose xdata and port bus is the MAME log"""

    def __init__(self, rom, bus):
        self.bus, self.bp, self.live = bus, 0, False
        super().__init__(rom, self.bus_rd, self.bus_wr)
        self.live = True

    def pop(self, kind, a):
        if self.bp >= len(self.bus):
            raise Desync("bus log exhausted")
        k, la, v = self.bus[self.bp]
        if (k, la) != (kind, a):
            raise Desync("bus #%d: model %s %04X, MAME %s %04X %02X" % (self.bp, kind, a, k, la, v))
        self.bp += 1
        return v

    def bus_rd(self, a):
        return self.pop("R", a)

    def bus_wr(self, a, v):
        lv = self.pop("W", a)
        if lv != v:
            raise Desync("xdata write %04X: model %02X, MAME %02X" % (a, v, lv))

    def port_rd(self, n):
        v = super().port_rd(n)
        lv = self.pop("r", 0x80 + 16 * n)
        if lv != v:
            raise Desync("port %d read: model %02X, MAME %02X" % (n, v, lv))
        return v

    def port_wr(self, n, v):
        super().port_wr(n, v)
        if self.live:                            # (not the writes of device_reset: they bypass the sfr space)
            lv = self.pop("w", 0x80 + 16 * n)
            if lv != v:
                raise Desync("port %d write: model %02X, MAME %02X" % (n, v, lv))


def state_strings(c):
    regs = "%02X%02X%02X%02X%04X" % (c.acc, c.b, c.get_psw(), c.sp, c.dptr)
    bank = c.psw & 0x18
    rs = c.ram[bank:bank + 8].hex().upper()
    sf = "%02X%02X%02X%02X%02X%02X%02X%02X%02X" % (c.ie, c.ip, c.tcon, c.tmod, c.tl0, c.th0, c.tl1, c.th1,
                                                     c.p[3] & ~((c.last_line_state & 3) << 2))
    return regs, rs, sf


def replay(d, rom, limit=None):
    cpu = Replay(rom, load_bus(d))
    st = {"irqs": []}
    cpu.irq_hook = lambda c, line: st["irqs"].append(line)
    cpu.hook = snapshot
    ops = Counter()
    texts = {}
    n = 0
    lines = 0
    names = ["A B PSW SP DPTR".split(), ["R%d" % i for i in range(8)], "IE IP TCON TMOD TL0 TH0 TL1 TH1 P3".split()]
    widths = [[2, 2, 2, 2, 4], [2] * 8, [2] * 9]
    try:
        for regs, rs, sf, t, pc, irq, text in records(d):
            lines += 1
            if limit and n >= limit:
                break
            pins = ((cpu.p[3] & ~int(sf[16:18], 16)) >> 2) & 3      # (P3 = latch & ~pins; port_in(3) = $FF)
            for line in (0, 1):                  # MAME applies line changes between instructions
                if (pins ^ cpu.last_line_state) & (1 << line):
                    cpu.set_input_line(line, (pins >> line) & 1)
            st["irqs"] = []
            cpu.step()                           # (the hook saved the state before the instruction, as MAME's trace)
            if irq is not None and st["irqs"] != [irq] or irq is None and st["irqs"]:
                raise Desync("trace line %d (%04X %s): IRQ entry model %s, MAME %s" % (lines, pc, text, st["irqs"],
                                                                                     irq))
            n += 1
            texts.setdefault(cpu.ppc, text)
            ops[cpu.rom[cpu.ppc]] += 1
            if cpu.ppc != pc or cpu.pre != (regs, rs, sf) or cpu.pre_cycles != t:
                mine = cpu.pre
                diff = ["PC model %04X MAME %04X" % (cpu.ppc, pc)] if cpu.ppc != pc else []
                if cpu.pre_cycles != t:
                    diff.append("T model %d MAME %d" % (cpu.pre_cycles, t))
                for g, w, nm, wd in zip(mine, (regs, rs, sf), names, widths):
                    i = 0
                    for name, k in zip(nm, wd):
                        if g[i:i + k] != w[i:i + k]:
                            diff.append("%s model %s MAME %s" % (name, g[i:i + k], w[i:i + k]))
                        i += k
                raise Desync("trace line %d (%04X %s): %s" % (lines, pc, text, ", ".join(diff)))
    except Desync as e:
        return n, str(e), ops, texts, cpu
    return n, None, ops, texts, cpu


def snapshot(c):
    """the hook: the state before each instruction (after the interrupt check), as MAME's trace prints it"""
    c.pre = state_strings(c)
    c.pre_cycles = c.cycles


def decoder_test(rom, texts):
    from i8051dis import decode
    bad = []
    for pc, text in sorted(texts.items()):
        mine = decode(rom, pc).text
        if mine.split() != text.split():
            bad.append("%04X %s / MAME %s" % (pc, mine, text))
    return bad


def mame_tests(regen, seconds):
    if not MCU_ROM.exists():
        print("MAME comparison skipped (no %s: port.py prepare mrheli)" % MCU_ROM.relative_to(ROOT))
        return
    allops = Counter()
    for name, secs, rom in (("synthetic", SYNTH_SECONDS, synthetic_program()),
                            (GAME, seconds, MCU_ROM.read_bytes())):
        d = fixture(name, regen, secs, rom if name == "synthetic" else None)
        if d is None:
            print("%s: MAME comparison skipped (no mame or no %s, no fixture in %s)" % (name, MAME_ROMS, FIX / name))
            continue
        n, err, ops, texts, cpu = replay(d, rom)
        allops.update(ops)
        print("%s: %d instructions checked against MAME (%d machine cycles, %.1f s; bus log %d/%d), %s" % (
            name, n, cpu.cycles, cpu.cycles / (8e6 / 12), cpu.bp, len(cpu.bus), "0 mismatches" if not err
            else "MISMATCH: " + err))
        check(err is None, "%s replay" % name)
        check(err or cpu.bp >= len(cpu.bus) - 2, "%s: whole bus log consumed (%d/%d)" % (name, cpu.bp, len(cpu.bus)))
        bad = decoder_test(rom, texts)
        print("%s: i8051dis vs MAME disassembly: %d addresses, %d differences %s" % (name, len(texts), len(bad),
                                                                                   bad[:5]))
        check(not bad, "%s decoder" % name)
        print("%s: %d distinct opcodes executed" % (name, len(ops)))
    if allops:
        print("opcode coverage: %d of 256" % len(allops))


if __name__ == "__main__":
    unit_tests()
    print("instruction tests: %s" % ("ok" if not FAIL else "%d failures" % len(FAIL)))
    secs = SECONDS
    if "--seconds" in sys.argv:
        secs = int(sys.argv[sys.argv.index("--seconds") + 1])
    mame_tests("--regen" in sys.argv, secs)
    if FAIL:
        print("%d failures" % len(FAIL))
        sys.exit(1)
    print("all ok")
