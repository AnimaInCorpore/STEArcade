"""Tests of the MB88 core (engine/mb88.py) on hand-made programs; the expected values follow MAME 0.289's mb88xx.cpp.
The whole-chip check is games/galaga/ref/mame_cmp_51xx.py (the 51XX / 54XX programs against MAME).

    python engine/mb88_test.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mb88 import MB88
from mb88dis import listing


def cpu(code, **kw):
    rom = bytearray(1024)
    rom[:len(code)] = bytes(code)
    return MB88(rom, **kw)


def run(c, n):
    for _ in range(n):
        c.step()
    return c


def test_arith():
    # li 9, lxi 0, lyi 3, st (M=9), li 4, setc, adc: 9 + 4 + 1 = 14, no carry
    c = run(cpu([0x99, 0x58, 0x83, 0x1D, 0x94, 0x21, 0x0E]), 7)
    assert (c.a, c.cf, c.st, c.zf) == (14, 0, 1, 0)
    # sbc: M - A - C with M = 9, A = 12, C = 0 -> 13, borrow (C = 1, ST = 0)
    c = run(cpu([0x99, 0x58, 0x83, 0x1D, 0x9C, 0x23, 0x1E]), 7)
    assert (c.a, c.cf, c.st) == (13, 1, 0)
    # daa after 9 + 9 = 18: A = 2, C = 0 -> daa (A > 9? no; C? no): unchanged; with the carry set: A + 6
    c = run(cpu([0x99, 0x58, 0x80, 0x1D, 0x21, 0x0E, 0x10]), 7)     # 9 + 9 + 1 = 19 -> A 3, C 1; daa -> 9, C 0
    assert (c.a, c.cf) == (9, 0), (c.a, c.cf)
    # neg 3 -> 13; ci / cyi compare: ST = 0 when equal
    c = run(cpu([0x93, 0x2D, 0xBD]), 3)
    assert (c.a, c.st, c.zf) == (13, 0, 1)
    # dcy from 0: Y 15, ST 0 (borrow), Z unchanged
    c = run(cpu([0x80, 0x18]), 2)
    assert (c.y, c.st, c.zf) == (15, 0, 1)


def test_rotate():
    c = run(cpu([0x99, 0x21, 0x0C]), 3)          # rol 1001 with C 1 -> 0011, C 1
    assert (c.a, c.cf, c.st) == (3, 1, 0)
    c = run(cpu([0x98, 0x23, 0x1C]), 3)          # ror 1000 with C 0 -> 0100, C 0
    assert (c.a, c.cf, c.st) == (4, 0, 1)
    c = run(cpu([0x91, 0x21, 0x1C]), 3)          # ror 0001 with C 1 -> 1000, C 1
    assert (c.a, c.cf, c.st) == (8, 1, 0)


def test_jumps():
    # jmp is taken only with ST = 1: ci #5 with A = 5 clears ST, so the jmp at 2 falls through
    c = run(cpu([0x95, 0xB5, 0xCA, 0x00]), 3)
    assert c.addr == 3
    # call $105 / rts; the stack has four levels and wraps
    code = [0x61, 0x05]
    c = cpu(code)
    c.rom = bytearray(c.rom)
    c.rom[0x105] = 0x2C
    c.rom = bytes(c.rom)
    run(c, 1)
    assert c.addr == 0x105 and c.si == 1
    run(c, 1)
    assert c.addr == 0x002 and c.si == 0
    # jpa: PA from the operand, PC = A * 4
    c = run(cpu([0x93, 0x3D, 0x05]), 2)
    assert c.addr == (5 << 6) | 12
    # the 6-bit PC wraps into the next page
    rom = bytearray(1024)
    rom[0x3F] = 0x00
    c = MB88(rom)
    c.pc = 0x3F
    c.step()
    assert c.addr == 0x40


def test_interrupts():
    # en #$04 (external), then the /IRQ rising edge: vector 2 after the instruction, flags saved and restored by rti
    rom = bytearray(1024)
    rom[0:2] = bytes([0x3E, 0x04])
    rom[2] = 0x3C                                # rti at the vector
    rom[3:6] = bytes([0x21, 0x00, 0x00])         # setc, nop, nop
    c = MB88(rom)
    c.pc = 0
    run(c, 1)                                    # en
    c.pc = 3
    run(c, 1)                                    # setc
    c.set_irq(1)
    run(c, 1)                                    # nop, then the interrupt
    assert c.addr == 2 and c.in_irq and c.cycles == 2 + 1 + 1 + 3
    c.cf = 0
    run(c, 1)                                    # rti
    assert c.addr == 5 and c.cf == 1 and not c.in_irq
    c.set_irq(1)                                 # still high: no new edge
    run(c, 1)
    assert not c.in_irq
    # the timer pin: counts on the falling edge when enabled (pio $40); 256 counts overflow into VF
    c = cpu([0x3E, 0x40])
    run(c, 1)
    for _ in range(256):
        c.set_tc(1)
        c.set_tc(0)
    assert (c.th, c.tl, c.vf) == (0, 0, 1)
    # the serial port (pio $20): SF after four bits
    c = cpu([0x3E, 0x20, 0x00, 0x00, 0x00, 0x00])
    run(c, 1)
    assert c.sf == 0
    run(c, 2)
    assert c.sf == 1


def test_ports():
    # outO writes the nibble the carry selects (PLA of 8 bits)
    got = []
    c = cpu([0x95, 0x23, 0x01, 0x9A, 0x21, 0x01], write_o=lambda v, mask: got.append((v, mask)))
    run(c, 6)
    assert got == [(0x05, 0x0F), (0xA5, 0xF0)]
    # unconnected inputs read 0
    c = run(cpu([0x9F, 0x12]), 2)
    assert c.a == 0 and c.zf == 1


def test_disassembler():
    text = listing(bytes([0x61, 0x05, 0x3D, 0x06, 0xC9, 0x5A]) + bytes(58) + bytes([0xC3]), 0, 0x41)
    assert "CALL  $105" in text and "JPA   #$06" in text and "JMP   $009" in text and "LXI   #$2" in text
    assert "JMP   $043" in text                 # the jump at $040 stays in its page


if __name__ == "__main__":
    for name, f in sorted(globals().items()):
        if name.startswith("test_"):
            f()
            print("ok", name)
