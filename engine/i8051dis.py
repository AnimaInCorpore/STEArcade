"""MCS-51 (8051/8751) disassembler / decoder (the instruction set of i8051.py).

decode(rom, pc, base=0) -> Ins(pc, op, length, mn, flow, target, text)
  flow: seq, jmp, jcc (conditional branch: target or fall through), call, ret (RET/RETI), ijmp (JMP @A+DPTR),
        ill (A5)
  text: MAME's mcs51 disassembler syntax and symbol names (i8051_disassembler: "mov   a,#$12", "jb    int0,$0123",
        "setb  $21.3", ...), so that it can be compared with a MAME trace (spaces collapsed).
discover(rom, roots, base=0) -> {pc: Ins} by recursive descent (jump tables are not followed).
"""
from collections import namedtuple

Ins = namedtuple("Ins", "pc op length mn flow target text")

NAMES = {0x80: "p0", 0x81: "sp", 0x82: "dpl", 0x83: "dph", 0x87: "pcon", 0x88: "tcon", 0x89: "tmod", 0x8A: "tl0",
         0x8B: "tl1", 0x8C: "th0", 0x8D: "th1", 0x90: "p1", 0x98: "scon", 0x99: "sbuf", 0xA0: "p2", 0xA8: "ie",
         0xB0: "p3", 0xB8: "ip", 0xD0: "psw", 0xE0: "acc", 0xF0: "b"}
NAMES.update({r + 8 * b: "rb%dr%d" % (b, r) for b in range(4) for r in range(8)})
BITS = dict(zip(range(0x88, 0x90), "it0 ie0 it1 ie1 tr0 tf0 tr1 tf1".split()))
BITS.update(zip(range(0x98, 0xA0), "ri ti rb8 tb8 ren sm2 sm1 sm0".split()))
BITS.update(zip(range(0xA8, 0xB0), "ex0 et0 ex1 et1 es ie.5 ie.6 ea".split()))
BITS.update(zip(range(0xB0, 0xB8), "rxd txd int0 int1 t0 t1 wr rd".split()))
BITS.update(zip(range(0xB8, 0xC0), "px0 pt0 px1 pt1 ps ip.5 ip.6 ip.7".split()))
BITS.update(zip(range(0xD0, 0xD8), "p psw.1 ov rs0 rs1 f0 ac cy".split()))

ALU = {0x2: "add", 0x3: "addc", 0x4: "orl", 0x5: "anl", 0x6: "xrl", 0x9: "subb"}


def dname(a):
    return NAMES.get(a, "$%02X" % a)


def bname(a):
    if a < 0x80:
        return "$%02X.%d" % ((a >> 3) | 0x20, a & 7)
    if a in BITS:
        return BITS[a]
    return "%s.%d" % (NAMES.get(a & 0xF8, "$%02X" % (a & 0xF8)), a & 7)


def decode(rom, pc, base=0):
    def b(i):
        return rom[(pc + i - base) & 0xFFFF] if 0 <= pc + i - base < len(rom) else 0

    op = b(0)
    hi, lo = op >> 4, op & 15

    def rel(n):     # target of a relative branch whose offset is the last of n bytes
        d = b(n - 1)
        return (pc + n + (d - 256 if d & 0x80 else d)) & 0xFFFF

    def mk(n, mn, args="", flow="seq", target=None):
        return Ins(pc, op, n, mn, flow, target, ("%-5s %s" % (mn, args)) if args else mn)

    if lo == 1:                                                   # AJMP / ACALL
        t = ((pc + 2) & 0xF800) | ((op & 0xE0) << 3) | b(1)
        return mk(2, "acall" if op & 0x10 else "ajmp", "$%04X" % t, "call" if op & 0x10 else "jmp", t)
    if lo >= 8 or lo in (6, 7):                                   # register / @Ri forms
        r = "r%d" % (op & 7) if lo >= 8 else "@r%d" % (op & 1)
        if hi in ALU:
            return mk(1, ALU[hi], "a," + r)
        simple = {0x0: ("inc", r), 0x1: ("dec", r), 0xC: ("xch", "a," + r), 0xE: ("mov", "a," + r),
                  0xF: ("mov", r + ",a")}
        if hi in simple:
            return mk(1, *simple[hi])
        if hi == 0x7:
            return mk(2, "mov", "%s,#$%02X" % (r, b(1)))
        if hi == 0x8:
            return mk(2, "mov", "%s,%s" % (dname(b(1)), r))
        if hi == 0xA:
            return mk(2, "mov", "%s,%s" % (r, dname(b(1))))
        if hi == 0xB:
            return mk(3, "cjne", "%s,#$%02X,$%04X" % (r, b(1), rel(3)), "jcc", rel(3))
        if hi == 0xD:
            if lo >= 8:
                return mk(2, "djnz", "%s,$%04X" % (r, rel(2)), "jcc", rel(2))
            return mk(1, "xchd", "a," + r)
        raise AssertionError(hex(op))
    if hi in ALU and lo in (4, 5):
        return mk(2, ALU[hi], "a,#$%02X" % b(1) if lo == 4 else "a," + dname(b(1)))
    if hi in (4, 5, 6) and lo in (2, 3):
        mn = ALU[hi]
        return mk(2, mn, dname(b(1)) + ",a") if lo == 2 else mk(3, mn, "%s,#$%02X" % (dname(b(1)), b(2)))
    T = {
        0x00: (1, "nop", ""), 0x03: (1, "rr", "a"), 0x04: (1, "inc", "a"), 0x13: (1, "rrc", "a"),
        0x14: (1, "dec", "a"), 0x23: (1, "rl", "a"), 0x33: (1, "rlc", "a"), 0x73: (1, "jmp", "@a+dptr"),
        0x83: (1, "movc", "a,@a+pc"), 0x84: (1, "div", "ab"), 0x93: (1, "movc", "a,@a+dptr"),
        0xA3: (1, "inc", "dptr"), 0xA4: (1, "mul", "ab"), 0xA5: (1, "ill/rsv", ""), 0xB3: (1, "cpl", "c"),
        0xC3: (1, "clr", "c"), 0xC4: (1, "swap", "a"), 0xD3: (1, "setb", "c"), 0xD4: (1, "da", "a"),
        0xE0: (1, "movx", "a,@dptr"), 0xE2: (1, "movx", "a,@r0"), 0xE3: (1, "movx", "a,@r1"),
        0xE4: (1, "clr", "a"), 0xF0: (1, "movx", "@dptr,a"), 0xF2: (1, "movx", "@r0,a"),
        0xF3: (1, "movx", "@r1,a"), 0xF4: (1, "cpl", "a"), 0x22: (1, "ret", ""), 0x32: (1, "reti", ""),
    }
    if op in T:
        n, mn, a = T[op]
        flow = {0x22: "ret", 0x32: "ret", 0x73: "ijmp", 0xA5: "ill"}.get(op, "seq")
        return mk(n, mn, a, flow)
    d1 = dname(b(1))
    if op == 0x02 or op == 0x12:
        t = (b(1) << 8) | b(2)
        return mk(3, "ljmp" if op == 2 else "lcall", "$%04X" % t, "jmp" if op == 2 else "call", t)
    if op in (0x10, 0x20, 0x30):
        mn = {0x10: "jbc", 0x20: "jb", 0x30: "jnb"}[op]
        return mk(3, mn, "%s,$%04X" % (bname(b(1)), rel(3)), "jcc", rel(3))
    if op in (0x40, 0x50, 0x60, 0x70):
        mn = {0x40: "jc", 0x50: "jnc", 0x60: "jz", 0x70: "jnz"}[op]
        return mk(2, mn, "$%04X" % rel(2), "jcc", rel(2))
    if op == 0x80:
        return mk(2, "sjmp", "$%04X" % rel(2), "jmp", rel(2))
    if op == 0x05 or op == 0x15:
        return mk(2, "inc" if op == 5 else "dec", d1)
    BIT1 = {0x72: ("orl", "c,%s"), 0x82: ("anl", "c,%s"), 0x92: ("mov", "%s,c"), 0xA0: ("orl", "c,/%s"),
            0xA2: ("mov", "c,%s"), 0xB0: ("anl", "c,/%s"), 0xB2: ("cpl", "%s"), 0xC2: ("clr", "%s"),
            0xD2: ("setb", "%s")}
    if op in BIT1:
        mn, f = BIT1[op]
        return mk(2, mn, f % bname(b(1)))
    if op == 0x74:
        return mk(2, "mov", "a,#$%02X" % b(1))
    if op == 0x75:
        return mk(3, "mov", "%s,#$%02X" % (d1, b(2)))
    if op == 0x85:
        return mk(3, "mov", "%s,%s" % (dname(b(2)), d1))
    if op == 0x90:
        return mk(3, "mov", "dptr,#$%04X" % ((b(1) << 8) | b(2)))
    if op == 0xB4:
        return mk(3, "cjne", "a,#$%02X,$%04X" % (b(1), rel(3)), "jcc", rel(3))
    if op == 0xB5:
        return mk(3, "cjne", "a,%s,$%04X" % (d1, rel(3)), "jcc", rel(3))
    if op == 0xC0 or op == 0xD0:
        return mk(2, "push" if op == 0xC0 else "pop", d1)
    if op == 0xC5:
        return mk(2, "xch", "a," + d1)
    if op == 0xD5:
        return mk(3, "djnz", "%s,$%04X" % (d1, rel(3)), "jcc", rel(3))
    if op == 0xE5:
        return mk(2, "mov", "a," + d1)
    if op == 0xF5:
        return mk(2, "mov", d1 + ",a")
    raise AssertionError(hex(op))


def discover(rom, roots, base=0):
    """recursive descent from roots; returns {pc: Ins}"""
    seen, todo = {}, list(roots)
    while todo:
        pc = todo.pop()
        while pc not in seen and 0 <= pc - base < len(rom):
            ins = decode(rom, pc, base)
            seen[pc] = ins
            if ins.flow in ("jmp", "jcc", "call"):
                todo.append(ins.target)
            if ins.flow in ("jmp", "ret", "ijmp", "ill"):
                break
            pc = (pc + ins.length) & 0xFFFF
    return seen


if __name__ == "__main__":
    import sys
    data = open(sys.argv[1], "rb").read()
    code = discover(data, [0, 3, 0xB, 0x13, 0x1B, 0x23])
    for pc in sorted(code):
        ins = code[pc]
        print("%04X  %-9s %s" % (pc, " ".join("%02X" % data[pc + i] for i in range(ins.length) if pc + i < len(data)),
                                 ins.text))
