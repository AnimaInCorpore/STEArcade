"""Tests of the HD63701 interpreter (engine/hd63701.py).

    venv/bin/python engine/hd63701_test.py [--regen]

1. instruction tests: the 6301 extras (AIM OIM EIM TIM, XGDX, SLP, TRAP, $12/$13), WAI/TAP/CLI interrupt timing,
   the timer (OCI, TOI, counter writes), HD6301 cycle counts.
2. MAME comparison: MAME 0.289's HD63701V0 (in pacmania, galaga88, splatter) traced: registers, total cycles, free
   running counter and TCSR before every instruction, plus a bus log (reads of the external bus and the port
   registers, all non-RAM writes, from address space taps).  The interpreter replays it: bus reads come from the log
   (the voice ROM from the ROM set), every write is checked against the log, IRQ1 is raised where MAME's trace marks
   it, the timer interrupts must come by themselves.  Programs: a synthetic one with every opcode (in place of the
   CUS64 ROM, see synthetic_program) and the real CUS64 program of the three games, with voice requests poked into
   the shared RAM.  The hd6301 mode of m6801dis.decode is checked against MAME's disassembly on the way.
   Fixtures in build/hd63701/ (generated when missing and mame is installed, ~4 minutes; --regen forces it).  ROM
   content is never written to the repo.
"""
import gzip
import os
import re
import shutil
import subprocess
import sys
import zipfile
import zlib
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import ROOT, ROMS
from hd63701 import HD63701, CYCLES, I, N, Z, V, C

FAIL = []


def check(cond, what):
    if not cond:
        FAIL.append(what)
        print("FAIL:", what)


# ---- 1. instruction tests ----------------------------------------------------------------------------------------

def make(code, vectors=None, at=0xF000, **kw):
    rom = bytearray(0x1000)
    rom[at - 0xF000:at - 0xF000 + len(code)] = bytes(code)
    vec = {0xFFFE: 0xF000}
    vec.update(vectors or {})
    for v, a in vec.items():
        rom[v - 0xF000] = a >> 8
        rom[v - 0xF000 + 1] = a & 0xFF
    ext = bytearray(0x10000)

    def rd(a): return ext[a]

    def wr(a, v): ext[a] = v
    cpu = HD63701(rom, rd, wr, **kw)
    cpu.ext = ext
    return cpu


def steps(cpu, n):
    return [cpu.step() for _ in range(n)]


def unit_tests():
    # AIM/OIM/EIM/TIM direct (internal RAM) and indexed (external), flags and cycles
    cpu = make([0x8E, 0x00, 0xFF,              # lds #$00FF          3
                0x86, 0xF0, 0x97, 0x90,        # lda #$F0; sta $90   2 3
                0x71, 0x3C, 0x90,              # aim #$3C,$90 -> $30 6
                0x72, 0x81, 0x90,              # oim #$81,$90 -> $B1 6
                0x75, 0xFF, 0x90,              # eim #$FF,$90 -> $4E 6
                0x7B, 0x01, 0x90,              # tim #$01,$90 -> Z   4
                0xCE, 0x20, 0x00,              # ldx #$2000          3
                0x61, 0x0F, 0x05,              # aim #$0F,$05,x      7
                0x62, 0x80, 0x05,              # oim #$80,$05,x      7
                0x65, 0x01, 0x05,              # eim #$01,$05,x      7
                0x6B, 0x80, 0x05,              # tim #$80,$05,x  N   5
                ])
    cpu.ext[0x2005] = 0x5A
    cyc = steps(cpu, 4)
    check(cpu.ram[0x10] == 0x30 and cyc == [3, 2, 3, 6], "aim direct %02x %s" % (cpu.ram[0x10], cyc))
    check(cpu.cc & (N | Z | V) == 0, "aim flags %02x" % cpu.cc)
    cpu.cc |= C
    steps(cpu, 1)
    check(cpu.ram[0x10] == 0xB1 and cpu.cc & N and cpu.cc & C, "oim direct, C kept")
    steps(cpu, 1)
    check(cpu.ram[0x10] == 0x4E and not cpu.cc & N, "eim direct")
    c = steps(cpu, 1)
    check(cpu.ram[0x10] == 0x4E and cpu.cc & Z and c == [4], "tim direct: Z, no write, 4 cycles")
    c = steps(cpu, 5)
    check(cpu.ext[0x2005] == 0x8B and c == [3, 7, 7, 7, 5] and cpu.cc & N, "aim/oim/eim/tim indexed %02x %s"
          % (cpu.ext[0x2005], c))

    # XGDX, $12 (X += (S+1)), MUL, ABX
    cpu = make([0x8E, 0x00, 0xEF, 0xCC, 0x12, 0x34, 0xCE, 0xAB, 0xCD, 0x18,   # lds ldd ldx xgdx
                0x86, 0x07, 0x36, 0x12, 0x13])                                 # lda #7; psha: (S+1)=7; $12 $13
    c = steps(cpu, 4)
    check(cpu.x == 0x1234 and (cpu.a, cpu.b) == (0xAB, 0xCD) and c[3] == 2, "xgdx")
    steps(cpu, 2)
    c = steps(cpu, 2)
    check(cpu.x == 0x1234 + 14 and c == [4, 4], "$12/$13 X += (S+1): %04x %s" % (cpu.x, c))

    # TRAP: undefined opcode -> $FFEE, pushed PC = the opcode's address, 12 + 4 cycles
    cpu = make([0x8E, 0x00, 0xFF, 0x01, 0x00], {0xFFEE: 0xF100})
    steps(cpu, 2)
    c = cpu.step()
    check(cpu.pc == 0xF100 and c == 16 and cpu.cc & I, "trap vector/cycles %04x %d" % (cpu.pc, c))
    check((cpu.ram[0xFE - 0x80] << 8) | cpu.ram[0xFF - 0x80] == 0xF004, "trap pushes the opcode address")
    for op in (0x87, 0x8F, 0xC7, 0xCD, 0xCF, 0x41, 0x1C):
        cpu = make([0x8E, 0x00, 0xFF, op], {0xFFEE: 0xF100})
        steps(cpu, 2)
        check(cpu.pc == 0xF100, "trap on %02x" % op)

    # SLP: sleeps until IRQ1, the interrupt costs 12 (SLP did not stack)
    cpu = make([0x8E, 0x00, 0xFF, 0x0E, 0x01, 0x1A, 0x01], {0xFFF8: 0xF200})
    steps(cpu, 2)                               # lds, cli(+nop)
    c0 = cpu.cycles
    cpu.step(wait=0)                            # slp
    check(cpu.wai_state == 2 and cpu.cycles - c0 == 4, "slp cycles %d" % (cpu.cycles - c0))
    cpu.step(wait=100)
    check(cpu.wai_state == 2 and cpu.cycles - c0 == 104, "slp waits")
    cpu.set_irq1(True)
    c = cpu.step(wait=10)
    check(cpu.pc == 0xF200 and cpu.wai_state == 0 and c == 22 and cpu.sp == 0xF8, "slp -> irq1 %04x %d" % (cpu.pc, c))

    # WAI: stacks at once, the interrupt then costs 4
    cpu = make([0x8E, 0x00, 0xFF, 0x0E, 0x01, 0x3E, 0x01], {0xFFF8: 0xF200})
    steps(cpu, 2)
    c = cpu.step(wait=0)
    check(cpu.wai_state == 1 and cpu.sp == 0xF8 and c == 9, "wai stacks, 9 cycles")
    cpu.set_irq1(True)
    c = cpu.step(wait=0)
    check(cpu.pc == 0xF200 and c == 4 and cpu.sp == 0xF8, "wai -> irq1 in 4 cycles")

    # CLI / TAP: the next instruction runs before a pending IRQ1 is taken
    for code in ([0x0E, 0x4C, 0x4C], [0x4F, 0x06, 0x4C, 0x4C]):
        cpu = make([0x8E, 0x00, 0xFF] + code, {0xFFF8: 0xF200})
        cpu.step()
        cpu.set_irq1(True)
        if code[0] == 0x4F:
            cpu.step()
        cpu.step()
        check(cpu.pc == 0xF200 and cpu.a == 1, "%s: one instruction then IRQ1 (a=%d)" % (
            "cli" if code[0] == 0x0E else "tap", cpu.a))

    # timer: OCI fires when the counter reaches OCR, TOF at $FFFF, a write to $09 loads $FFF8
    cpu = make([0x8E, 0x00, 0xFF,
                0xCC, 0x00, 0x40, 0xDD, 0x0B,  # ldd #$0040; std $0B (OCR)
                0x86, 0x08, 0x97, 0x08,        # lda #EOCI; sta $08
                0x0E, 0x01,                    # cli; nop
                0x20, 0xFE], {0xFFF4: 0xF300})  # bra *
    cpu.rom = bytes(cpu.rom[:0x300]) + bytes([0x96, 0x08, 0xDD, 0x0B, 0x3B]) + bytes(cpu.rom[0x305:])
    for _ in range(40):
        cpu.step()
        if cpu.pc == 0xF300:
            break
    check(cpu.pc == 0xF300 and cpu.tcsr & 0x40, "OCI taken pc=%04x tcsr=%02x" % (cpu.pc, cpu.tcsr))
    check(0x40 <= (cpu.ctd & 0xFFFF) - 12 < 0x43, "OCI at counter $40 (+12 stacking) %04x" % (cpu.ctd & 0xFFFF))
    steps(cpu, 3)                               # lda tcsr; std ocr: clears OCF; rti
    check(not cpu.tcsr & 0x40, "OCF cleared by TCSR read + OCR write")

    cpu = make([0xC6, 0x12, 0xD7, 0x09, 0x96, 0x08, 0x96, 0x08, 0x96, 0x08, 0xD6, 0x09])
    c = steps(cpu, 2)
    check(cpu.ctd & 0xFFFF == 0xFFF8 + 3, "write $09 -> $FFF8 (%04x)" % (cpu.ctd & 0xFFFF))
    steps(cpu, 2)
    check(cpu.tcsr & 0x20, "TOF at $FFFF")
    steps(cpu, 2)
    check(not cpu.tcsr & 0x20, "TOF cleared by TCSR read + counter high read")

    # cycle table spot checks against MAME's cycles_63701
    for op, n in ((0x3D, 7), (0x3B, 10), (0x3F, 12), (0x8D, 5), (0xBD, 6), (0x6E, 3), (0x7E, 3), (0x39, 5),
                  (0x08, 1), (0x36, 4), (0x32, 3), (0xDD, 4), (0x93, 4), (0x18, 2), (0x1A, 4)):
        check(CYCLES[op] == n, "cycles %02x" % op)

    # ports: P1 out with DDR, P2 out only bits 0-4 after a data write, P1 in mixed with the output latch
    got = []
    cpu = make([0x86, 0x0F, 0x97, 0x00, 0x86, 0xA5, 0x97, 0x02, 0x96, 0x02, 0x86, 0xFF, 0x97, 0x01,
                0x86, 0x35, 0x97, 0x03],
               in_p1=lambda: 0x3C, out_p1=lambda v, d: got.append(("p1", v, d)),
               out_p2=lambda v, d: got.append(("p2", v, d)))
    steps(cpu, 5)
    check(got == [("p1", 0xF0, 0x0F), ("p1", 0xF5, 0x0F)] and cpu.a == 0x35, "port 1 %s %02x" % (got, cpu.a))
    del got[:]
    steps(cpu, 4)
    check(got == [("p2", 0x15, 0xFF & 0x1F)], "port 2 %s" % got)



# ---- 2a. a synthetic program: every HD6301 opcode with pseudo-random operands, flags and CC ---------------------
#
# Run by MAME's HD63701V0 in place of the CUS64 ROM (pacmania, ROM region patched from Lua) and replayed like the
# game traces.  A loop of blocks "jsr SETUP; <instruction>": SETUP loads new random D, X, CC (I kept set) and memory
# operands ($80/$81 internal, $C100/$C101 external).  Branches skip a NOP, traps return past the opcode, WAI/SLP
# wake on OCI, TAP/CLI let one instruction run before a pending OCI, IRQ1 (vblank) acked by the handler.

RND, SETUP, SETUPX, SUB = 0xFE00, 0xFE30, 0xFE50, 0xFE70
IRQH, RTIH, TRAPH, OCIH = 0xFE78, 0xFE7F, 0xFE80, 0xFE90


def synthetic_program(seed=6301):
    import random
    rnd = random.Random(seed)
    rom = bytearray([0x01] * 0x1000)

    def put(a, bs):
        rom[a - 0xF000:a - 0xF000 + len(bs)] = bytes(bs)

    def w(v):
        return [v >> 8, v & 0xFF]
    put(RND, [0xDC, 0x90, 0x05, 0x05, 0xD3, 0x90, 0xC3, 0x36, 0x19, 0xDD, 0x90, 0x36,          # s1 = s1*5 + $3619
              0xDC, 0x92, 0x05, 0x05, 0x05, 0xD3, 0x92, 0xC3, 0x5A, 0x5B, 0xDD, 0x92,          # s2 = s2*9 + $5A5B
              0x16, 0x32, 0x39])                                                               # D = hi1:hi2
    setup = [0xBD] + w(RND) + [0xDD, 0x80, 0xFD, 0xC1, 0x00]                                   # operands
    tail = [0xBD] + w(RND) + [0x37, 0x36, 0xBD] + w(RND) + [0x8A, 0x10, 0x06, 0x32, 0x33, 0x39]  # D, CC (I set)
    put(SETUP, setup + [0xBD] + w(RND) + [0x18] + tail)                                        # X random
    put(SETUPX, setup + [0xCE, 0xC0, 0xF8] + tail)                                             # X = $C100 - 8
    put(SUB, [0x39])
    put(IRQH, [0xB7, 0xF0, 0x00, 0x3B])                                                        # ack, rti
    put(RTIH, [0x3B])
    put(TRAPH, [0x30, 0xEC, 0x05, 0xC3, 0x00, 0x01, 0xED, 0x05, 0x3B])                         # stacked PC += 1
    put(OCIH, [0x96, 0x08, 0xDC, 0x0B, 0xDD, 0x0B, 0x7F, 0x00, 0x08, 0x3B])                    # clear OCF, EOCI off
    for v, a in ((0xFFF0, RTIH), (0xFFF2, RTIH), (0xFFF4, OCIH), (0xFFF6, RTIH), (0xFFF8, IRQH), (0xFFFA, RTIH),
                 (0xFFFC, RTIH), (0xFFFE, 0xF000), (0xFFEE, TRAPH), (0xFFEC, RTIH), (0xFFEA, RTIH)):
        put(v, w(a))

    blocks = []
    S, SX = [0xBD] + w(SETUP), [0xBD] + w(SETUPX)
    r8 = lambda: rnd.randrange(256)
    traps = [0x00, 0x02, 0x03, 0x14, 0x15, 0x1C, 0x1D, 0x1E, 0x1F, 0x41, 0x42, 0x45, 0x4B, 0x4E, 0x51, 0x52, 0x55,
             0x5B, 0x5E, 0x87, 0x8F, 0xC7, 0xCD, 0xCF]
    for op in [0x01, 0x04, 0x05, 0x07, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0F, 0x10, 0x11, 0x12, 0x13, 0x16,
               0x17, 0x18, 0x19, 0x1B, 0x3A, 0x3D] + [h | k for h in (0x40, 0x50)
                                                      for k in (0, 3, 4, 6, 7, 8, 9, 0xA, 0xC, 0xD, 0xF)]:
        blocks.append(S + [op])
    blocks.append(S + [0x19, 0x19])                              # DAA after DAA (H/C from the first)
    blocks.append(S + [0x1B, 0x19])                              # ABA; DAA
    for k in range(16):                                          # branches over a NOP
        blocks.append(S + [0x20 | k, 0x01, 0x01])
    for k in (0, 3, 4, 6, 7, 8, 9, 0xA, 0xC, 0xD, 0xF):         # memory read-modify-write
        blocks.append(SX + [0x60 | k, 0x08])
        blocks.append(S + [0x70 | k, 0xC1, 0x00])
    for k in (1, 2, 5, 0xB):                                     # AIM OIM EIM TIM
        for _ in range(2):
            blocks.append(SX + [0x60 | k, r8(), 0x08])
            blocks.append(S + [0x70 | k, r8(), 0x80, 0xDC, 0x80])
    for hi in (0x80, 0xC0):                                      # accumulator and 16 bit ops, all modes
        for k in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 0xA, 0xB, 0xC, 0xD, 0xE, 0xF):
            op = hi | k
            if op in (0x8D, 0x8E):
                continue
            wide = k in (3, 0xC, 0xE) or (hi == 0xC0 and k in (0xD, 0xF)) or (hi == 0x80 and k == 0xF)
            if op not in traps:
                for _ in range(2):
                    blocks.append(S + [op] + ([r8(), r8()] if wide else [r8()]))
            if (hi | 0x10 | k) in (0x9D, 0x9E):
                continue
            store = k in (7, 0xD, 0xF) and not (hi == 0x80 and k == 0xD)
            blocks.append(S + [hi | 0x10 | k, 0x80] + ([0xDC, 0x80] if store else []))
            blocks.append(SX + [hi | 0x20 | k, 0x08])
            blocks.append(S + [hi | 0x30 | k, 0xC1, 0x00])
    def here():
        return 0xF007 + sum(len(b) for b in blocks)
    blocks.append(S + [0x8D, 0x02, 0x20, 0x01, 0x39])            # BSR to an RTS
    blocks.append(S + [0x9D, 0xA0])                              # JSR direct (RTS in RAM)
    blocks.append(S + [0xCE] + w(SUB) + [0xAD, 0x00])            # JSR indexed
    blocks.append(S + [0xBD] + w(SUB))                           # JSR extended
    a = here() + 3 + 3 + 2
    blocks.append(S + [0xCE] + w(a) + [0x6E, 0x00])              # JMP indexed to the next block
    a = here() + 3 + 3
    blocks.append(S + [0x7E] + w(a))                             # JMP extended
    blocks.append(S + [0x3F])                                    # SWI
    for op in traps:
        blocks.append(S + [op])                                  # TRAP
    blocks.append(S + [0x36, 0x32, 0x37, 0x33, 0x3C, 0x38, 0x30, 0x35, 0x34, 0x31])   # stack ops
    blocks.append(S + [0x9F, 0x82, 0x8E, r8(), r8(), 0x9F, 0x84, 0x9E, 0x80, 0x9F, 0x86, 0x9E, 0x82])  # LDS/STS
    blocks.append(SX + [0x9F, 0x82, 0xAE, 0x08, 0xAF, 0x08, 0x9E, 0x82])
    blocks.append(S + [0x9F, 0x82, 0xBE, 0xC1, 0x00, 0xBF, 0xC1, 0x02, 0x9E, 0x82])
    blocks.append(S + [0x06])                                    # TAP with a random I: IRQ1 may come
    blocks.append(S + [0x0E, 0x01, 0x0F])                        # CLI
    oci = [0x0F, 0x96, 0x08, 0xDC, 0x09, 0xC3, 0x00, 0x30, 0xDD, 0x0B, 0x86, 0x08, 0x97, 0x08]  # OCI in 48 clocks
    blocks.append(oci + [0x0E, 0x01, 0x3E, 0x0F])                # CLI; WAI (OCI or IRQ1 wakes it)
    blocks.append(oci + [0x0E, 0x01, 0x1A, 0x0F])                # CLI; SLP
    pend = oci + [0x7B, 0x40, 0x08, 0x27, 0xFB]                  # ... wait for OCF with I set
    blocks.append(pend + [0x4F, 0x06, 0x4C, 0x4C, 0x0F])         # CLRA; TAP: one INCA, then OCI
    blocks.append(pend + [0x0E, 0x4C, 0x4C, 0x0F])               # CLI: one INCA, then OCI
    blocks.append(S + [0xD7, 0x09, 0x96, 0x08, 0xDC, 0x09, 0xDC, 0x0D, 0x96, 0x14])     # counter -> $FFF8, reads
    blocks.append(S + [0xDD, 0x09, 0x96, 0x08, 0x96, 0x09, 0x96, 0x0A])                 # counter := latch:low
    blocks.append(S + [0x97, 0x02, 0xD7, 0x00, 0x96, 0x02, 0x84, 0xFC, 0x97, 0x03, 0xD7, 0x01, 0x96, 0x03,
                       0x96, 0x06, 0x96, 0x07, 0x96, 0x0F, 0x96, 0x10, 0x96, 0x11, 0x96, 0x12])  # ports
    code = [0x8E, 0x00, 0xFF, 0x86, 0x39, 0x97, 0xA0]            # lds #$FF; RTS at $A0
    body = sum(blocks, [])
    put(0xF000, code[:7] + body + [0x7E, 0xF0, 0x07])            # ...; jmp loop
    assert 0xF007 + len(body) + 3 <= RND, hex(len(body))
    return bytes(rom)


# ---- 2. MAME comparison --------------------------------------------------------------------------------------------

GAMES = {   # voice ROM region (0xC0000): (crc, offset, size); 64 KB parts are mirrored (ROM_LOAD_HS)
    "pacmania": [(0x1ad5788f, 0x00000, 0x10000)],
    "galaga88": [(0x86921dd4, 0x00000, 0x10000), (0x9c300e16, 0x20000, 0x10000), (0x5316b4b0, 0x40000, 0x10000),
                 (0xdc077af4, 0x60000, 0x10000), (0xac0279a7, 0x80000, 0x10000), (0x014ddba1, 0xa0000, 0x10000)],
    "splatter": [(0x2199cb66, 0x00000, 0x20000), (0x9b6472af, 0x20000, 0x20000), (0x25ea75b6, 0x40000, 0x20000),
                 (0x5eebcdb4, 0x60000, 0x20000)],
}
MCU_CRC = 0xffb5c0bd
SECONDS = 4
FIX = ROOT / "build" / "hd63701"

LUA = r'''
local dbg = manager.machine.debugger
local pf = io.open("program.bin", "rb")
if pf then  -- the synthetic test: our program in place of the CUS64 ROM (the MCU starts when the main CPU releases it)
  local prog = pf:read("a")
  local r = manager.machine.memory.regions[":mcu"]
  for i = 1, #prog do r:write_u8(i - 1, prog:byte(i)) end
end
local mcu = manager.machine.devices[":mcu"]
local sp = mcu.spaces["program"]
local f = io.open("bus.txt", "w")
local function rkeep(a)
  if a < 0x20 then return a == 2 or a == 3 or a == 6 or a == 7 or a == 0x13 or a >= 0x15 end
  return (a >= 0x20 and a < 0x80) or (a >= 0x100 and a < 0x4000) or (a >= 0xc000 and a < 0xf000)
end
rt = sp:install_read_tap(0x0000, 0xffff, "rlog", function(offset, data, mask)
  if rkeep(offset) then f:write(string.format("R %04X %02X\n", offset, data)) end
end)
wt = sp:install_write_tap(0x0000, 0xffff, "wlog", function(offset, data, mask)
  if offset < 0x80 or offset >= 0x100 then f:write(string.format("W %04X %02X\n", offset, data)) end
end)
dbg:command("trace trace.txt,mcu,noloop,{tracelog \"A=%02X B=%02X X=%04X S=%04X CC=%02X T=%d C=%04X F=%02X \",a,b,x,s,cc,totalcycles,(b@$9<<8)|b@$a,b@$8}")
dbg:command("go")
-- tracelog prints for the debugger's visible CPU, which "go" sets back to the main CPU
dbg.visible_cpu = mcu
-- voice requests as the main CPU makes them (shared RAM $C02B-$C02E: sample, start|ROM), written into the share so
-- that the MCU's bus taps do not see them
local tri = manager.machine.memory.shares[":triram"]
local frame = 0
local pokes = {[150] = {0x2b, 1, 0x2c, 0x40}, [165] = {0x2d, 2, 0x2e, 0x40}, [185] = {0x2b, 3, 0x2c, 0x40},
               [190] = {0x2b, 4, 0x2c, 0x40}, [200] = {0x2d, 0, 0x2e, 0x40}}
sub = emu.add_machine_frame_notifier(function()
  dbg.visible_cpu = mcu
  frame = frame + 1
  local p = pokes[frame]
  if p then tri:write_u8(p[1], p[2]); tri:write_u8(p[3], p[4]) end
end)
'''


def rom_by_crc(game, crc):
    with zipfile.ZipFile(ROMS / (game + ".zip")) as z:
        for n in z.namelist():
            d = z.read(n)
            if zlib.crc32(d) == crc:
                return d
    raise FileNotFoundError("%s.zip: no ROM with crc %08x" % (game, crc))


def fixture(game, regen, name=None, program=None):
    d = FIX / (name or game)
    fresh = (d / "trace.txt.gz").exists() and (d / "bus.txt.gz").exists()
    if program is not None and fresh:
        fresh = (d / "program.bin").exists() and (d / "program.bin").read_bytes() == program
    if fresh and not regen:
        return d
    if not shutil.which("mame"):
        return None
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    (d / "t.lua").write_text(LUA)
    if program is not None:
        (d / "program.bin").write_bytes(program)
    print("  running mame %s for %d s (MCU trace, takes a minute)" % (name or game, SECONDS))
    subprocess.run(["mame", game, "-rompath", str(ROMS), "-debug", "-debugger", "none", "-autoboot_script", "t.lua",
                    "-window", "-video", "none", "-sound", "none", "-nothrottle", "-seconds_to_run", str(SECONDS)],
                   cwd=d, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for n in ("trace.txt", "bus.txt"):
        with open(d / n, "rb") as src, gzip.open(d / (n + ".gz"), "wb") as dst:
            shutil.copyfileobj(src, dst)
        (d / n).unlink()
    return d


REC = re.compile(r"A=(..) B=(..) X=(....) S=(....) CC=(..) T=(\d+) C=(....) F=(..) (....): (.*)$")


def load_trace(d):
    recs, irq = [], False
    with gzip.open(d / "trace.txt.gz", "rt") as f:
        for line in f:
            m = REC.match(line)
            if m:
                a, b, x, s, cc, t, ct, tf, pc, mn = m.groups()
                recs.append((int(a, 16), int(b, 16), int(x, 16), int(s, 16), int(cc, 16), int(t), int(ct, 16),
                             int(tf, 16), int(pc, 16), irq, mn.strip()))
                irq = False
            elif "interrupted at" in line:
                irq = True
    return recs


def load_bus(d):
    out = []
    with gzip.open(d / "bus.txt.gz", "rt") as f:
        for line in f:
            k, a, v = line.split()
            out.append((k, int(a, 16), int(v, 16)))
    return out


class Desync(Exception):
    pass


class Replay(HD63701):
    """HD63701 whose bus is the MAME log"""

    def __init__(self, rom, voice, bus):
        self.voice, self.bus, self.bp, self.bank = voice, bus, 0, 0
        super().__init__(rom, self.bus_rd, self.bus_wr)

    def pop(self, kind, a):
        if self.bp >= len(self.bus):
            raise Desync("bus log exhausted")
        k, la, v = self.bus[self.bp]
        if (k, la) != (kind, a):
            raise Desync("bus #%d: model %s %04X, MAME %s %04X %02X" % (self.bp, kind, a, k, la, v))
        self.bp += 1
        return v

    def bus_rd(self, a):
        if 0x4000 <= a < 0xC000:
            return self.voice[self.bank * 0x8000 + a - 0x4000]
        return self.pop("R", a)

    def bus_wr(self, a, v):
        lv = self.pop("W", a)
        if lv != v:
            raise Desync("write %04X: model %02X, MAME %02X" % (a, v, lv))
        if a == 0xD800:                          # MAME mcu_bankswitch_w
            sel = {0xF8: 0, 0xF4: 4, 0xEC: 8, 0xDC: 12, 0xBC: 16, 0x7C: 20}.get(v & 0xFC, 0)
            if v & 0xFC == 0xF8:
                v ^= 2
            self.bank = sel + (v & 3)
        elif a == 0xF000:                        # MAME mcu_irq_ack_w
            self.irq1 = False

    def rd_reg(self, a):
        if a in (2, 3, 6, 7):
            return self.pop("R", a)
        return super().rd_reg(a)

    def wr_reg(self, a, v):
        lv = self.pop("W", a)
        if lv != v:
            raise Desync("write %04X: model %02X, MAME %02X" % (a, v, lv))
        super().wr_reg(a, v)


def voice_rom(game):
    voice = bytearray(0xC0000)
    for crc, off, size in GAMES[game]:
        data = rom_by_crc(game, crc)
        voice[off:off + size] = data
        if size == 0x10000:
            voice[off + size:off + 2 * size] = data
    return voice


DIS_ALIAS = {"cpx": "cmpx", "oraa": "ora", "orab": "orb"}     # m6801dis.py's names that MAME's disassembler spells differently


def decoder_test(game, recs, rom=None):
    """m6801dis.decode(hd6301=True) of every executed instruction against MAME's disassembly in the trace"""
    from m6801dis import decode
    mem = bytearray(0x10000)
    mem[0x4000:0xC000] = voice_rom(game)[0x8000:0x10000]    # bank $FB: the program part of the voice ROM
    mem[0xF000:] = rom or rom_by_crc(game, MCU_CRC)
    seen = {r[8]: r[10] for r in recs}
    bad = []
    seen = {pc: t for pc, t in seen.items() if pc >= 0x4000}     # not the RTS the synthetic test puts in RAM
    for pc, text in sorted(seen.items()):
        try:
            mine = decode(mem, pc, 0, hd6301=True).text.split()
        except ValueError:                       # the decoder rejects the undefined opcodes (TRAP); MAME's
            mine = ["illegal"]                   # disassembler shows the store-immediates as 6801 instructions
            if mem[pc] in (0x87, 0x8F, 0xC7, 0xCD, 0xCF):
                continue
        mine[0] = DIS_ALIAS.get(mine[0], mine[0])
        if mine != text.split():
            bad.append("%04X %s / MAME %s" % (pc, " ".join(mine), text))
    return len(seen), bad


def replay(game, d, recs, rom=None):
    rom = rom or rom_by_crc(game, MCU_CRC)
    voice = voice_rom(game)
    cpu = Replay(rom, voice, load_bus(d))
    st = {"j": 0, "irqs": 0, "ops": Counter(), "base": 0}

    def hook(c):
        j = st["j"]
        if j >= len(recs):
            raise StopIteration
        a, b, x, s, cc, t, ct, tf, pc, irq, mn = recs[j]
        if irq != (st["irqs"] > 0):
            raise Desync("IRQ1 entry: model %d, MAME %s" % (st["irqs"], irq))
        st["irqs"] = 0
        got = (c.a, c.b, c.x, c.sp, c.cc, c.cycles - st["base"], c.ctd & 0xFFFF, c.tcsr, c.pc)
        want = (a, b, x, s, cc, t, ct, tf, pc)
        if got != want:
            names = "A B X S CC T counter TCSR PC".split()
            diff = ", ".join("%s model %X MAME %X" % (n, g, w) for n, g, w in zip(names, got, want) if g != w)
            raise Desync("trace line %d (%04X %s): %s" % (j, pc, mn, diff))
        st["ops"][c.rd(c.pc) if c.pc < 0xF000 else c.rom[c.pc - 0xF000]] += 1
        st["j"] = j + 1

    def irq_hook(c, line):
        if line == 0:
            st["irqs"] += 1
    cpu.hook, cpu.irq_hook = hook, irq_hook
    resets = 0
    try:
        while st["j"] < len(recs):
            j = st["j"]
            a, b, x, s, cc, t, ct, tf, pc, irq, mn = recs[j]
            if j and t == 0 and pc == cpu.rd16(0xFFFE) and cpu.pc != pc:   # the main CPU reset the MCU
                cpu.reset()
                st["base"] = cpu.cycles
                resets += 1
            if cpu.wai_state:                    # sleeping: let the time pass up to MAME's next instruction
                due = t + st["base"] - (12 if irq and cpu.wai_state & 2 else 4)
                cpu.icount = due - cpu.cycles
                while cpu.wai_state and cpu.icount > 0:
                    cpu.eat_cycles()
            if irq and st["irqs"] == 0:          # MAME took IRQ1 here (asserted at a slice boundary)
                cpu.irq1 = True
                cpu.check_irq_lines()
                if cpu.wai_state:
                    raise Desync("IRQ1 not taken at trace line %d" % j)
            cpu.icount = 0
            op = cpu.rd(cpu.pc) if cpu.pc < 0xF000 else cpu.rom[cpu.pc - 0xF000]
            if op in (0x3E, 0x1A) and j + 1 < len(recs) and not recs[j + 1][9]:
                # WAI/SLP woken by a timer interrupt: MAME takes it inside the instruction (its cycles counted after
                # the interrupt entry) when the event falls in the same scheduler slice, else in a later slice
                ev = cpu.timer_next
                if (recs[j + 1][6] - ev) & 0xFFFF == (4 if op == 0x3E else 12) + CYCLES[op]:
                    cpu.icount = ev - cpu.ctd + 1
            cpu.execute_one()
    except StopIteration:
        pass
    except Desync as e:
        return st["j"], str(e), st["ops"], resets, cpu
    return st["j"], None, st["ops"], resets, cpu


def mame_tests(regen):
    allops = Counter()
    for name in ["synthetic"] + list(GAMES):
        game, prog = (name, None) if name in GAMES else ("pacmania", synthetic_program())
        if not (ROMS / (game + ".zip")).exists():
            print("%s: skipped (no %s.zip)" % (name, game))
            continue
        d = fixture(game, regen, name, prog)
        if d is None:
            print("%s: skipped (no mame, no fixture in %s)" % (name, FIX / name))
            continue
        recs = load_trace(d)
        n, err, ops, resets, cpu = replay(game, d, recs, prog)
        allops.update(ops)
        print("%s: %d instructions checked against MAME (%d E clocks, %d MCU resets, bus log %d/%d), %s" % (
            name, n, cpu.cycles, resets, cpu.bp, len(cpu.bus), "0 mismatches" if not err else "MISMATCH: " + err))
        check(err is None, "%s replay" % name)
        check(cpu.bp == len(cpu.bus) or err, "%s: whole bus log consumed" % name)
        n, bad = decoder_test(game, recs, prog)
        print("%s: m6801dis hd6301 decoder vs MAME disassembly: %d addresses, %d differences %s" % (
            name, n, len(bad), bad[:5]))
        check(not bad, "%s decoder" % name)
    if allops:
        print("opcode coverage: %d distinct opcodes executed: %s" % (
            len(allops), " ".join("%02X" % o for o in sorted(allops))))


if __name__ == "__main__":
    unit_tests()
    print("instruction tests: %s" % ("ok" if not FAIL else "%d failures" % len(FAIL)))
    mame_tests("--regen" in sys.argv)
    if FAIL:
        print("%d failures" % len(FAIL))
        sys.exit(1)
    print("all ok")
