"""Z80 instruction decoder producing structured instructions.

decode(rom, pc) -> Ins(pc, length, mn, ops, text, flow)
  mn   : lower-case mnemonic ('ld', 'add', 'jp', ...)
  ops  : list of operand tuples
         ('r8', 'a'|'b'|...|'ixh'|'ixl'...)    8-bit register
         ('r16', 'bc'|'de'|'hl'|'sp'|'af'|'ix'|'iy')
         ('imm', value)                         immediate
         ('ind16', addr)                        (nn)
         ('ind', 'hl'|'bc'|'de'|'sp'|'ix'|'iy', disp)  (hl), (ix+d)
         ('cc', 'nz'...)                         condition
         ('addr', target)                        jump/call target
         ('port', n) ...
  flow : 'seq' | 'jmp' | 'jcc' | 'call' | 'ccall' | 'ret' | 'cret' | 'ijmp' | 'halt' | 'rst'
"""
from collections import namedtuple

Ins = namedtuple("Ins", "pc length mn ops text flow target")

R8 = ["b", "c", "d", "e", "h", "l", "(hl)", "a"]
RP = ["bc", "de", "hl", "sp"]
RP2 = ["bc", "de", "hl", "af"]
CC = ["nz", "z", "nc", "c", "po", "pe", "p", "m"]
ALU = ["add", "adc", "sub", "sbc", "and", "xor", "or", "cp"]
ROT = ["rlc", "rrc", "rl", "rr", "sla", "sra", "sll", "srl"]


def s8(v):
    return v - 256 if v >= 128 else v


def decode(rom, pc):
    """rom: indexable bytes (len >= 0x10000 not required, wrapped)."""
    start = pc
    n = len(rom)

    def b(i):
        return rom[(start + i) % n] if (start + i) < n else 0

    def opcode(i):
        bus = getattr(rom, "opcodes", rom)
        return bus[(start + i) % n] if (start + i) < n else 0

    op = opcode(0)
    ix = None
    i = 0
    if op in (0xDD, 0xFD):
        ix = "ix" if op == 0xDD else "iy"
        i = 1
        op = opcode(1)
        if op in (0xDD, 0xFD, 0xED):  # prefix chain: treat as NOP-like
            return Ins(start, 1, "nop", [], "nop*", "seq", None)

    def r8(idx, allow_ix=True):
        if idx == 6:
            return None
        name = R8[idx]
        if ix and allow_ix and idx in (4, 5):
            name = ix + ("h" if idx == 4 else "l")
        return ("r8", name)

    def mem_operand(disp_pos):
        if ix:
            d = s8(b(disp_pos))
            return ("ind", ix, d), disp_pos + 1
        return ("ind", "hl", 0), disp_pos

    def fmt(o):
        k = o[0]
        if k == "r8" or k == "r16" or k == "cc":
            return o[1]
        if k == "imm":
            return "$%02X" % o[1] if o[1] < 256 else "$%04X" % o[1]
        if k == "ind16":
            return "($%04X)" % o[1]
        if k == "ind":
            if o[1] in ("ix", "iy"):
                return "(%s%+d)" % (o[1], o[2])
            return "(%s)" % o[1]
        if k == "addr":
            return "$%04X" % o[1]
        if k == "port":
            return "($%02X)" % o[1]
        return str(o)

    def mk(length, mn, ops, flow="seq", target=None):
        text = mn + (" " + ",".join(fmt(o) for o in ops) if ops else "")
        return Ins(start, length, mn, ops, text, flow, target)

    x = op >> 6
    y = (op >> 3) & 7
    z = op & 7
    p = y >> 1
    q = y & 1
    base = 1 + i  # index of first operand byte for simple opcodes

    if op == 0xCB and not ix:
        op2 = opcode(1)
        x2 = op2 >> 6
        y2 = (op2 >> 3) & 7
        z2 = op2 & 7
        tgt = ("ind", "hl", 0) if z2 == 6 else ("r8", R8[z2])
        if x2 == 0:
            return mk(2, ROT[y2], [tgt])
        return mk(2, ("bit", "res", "set")[x2 - 1], [("imm", y2), tgt])
    if op == 0xCB and ix:
        # DD CB d op   (op was b(1) -> here i==1 so op==0xCB at b(1))
        d = s8(b(2))
        op2 = b(3)
        x2 = op2 >> 6
        y2 = (op2 >> 3) & 7
        z2 = op2 & 7
        tgt = ("ind", ix, d)
        extra = [] if z2 == 6 else [("r8", R8[z2])]
        if x2 == 0:
            return mk(4, ROT[y2], [tgt] + extra)
        return mk(4, ("bit", "res", "set")[x2 - 1], [("imm", y2), tgt] + extra)
    if op == 0xED and not ix:
        op2 = opcode(1)
        x2 = op2 >> 6
        y2 = (op2 >> 3) & 7
        z2 = op2 & 7
        p2 = y2 >> 1
        q2 = y2 & 1
        if x2 == 1:
            if z2 == 0:
                return mk(2, "in", [("r8", R8[y2]) if y2 != 6 else ("imm", 0), ("ind", "bc", 0)])
            if z2 == 1:
                return mk(2, "out", [("ind", "bc", 0), ("r8", R8[y2]) if y2 != 6 else ("imm", 0)])
            if z2 == 2:
                return mk(2, "sbc" if q2 == 0 else "adc", [("r16", "hl"), ("r16", RP[p2])])
            if z2 == 3:
                nn = b(2) | (b(3) << 8)
                if q2 == 0:
                    return mk(4, "ld", [("ind16", nn), ("r16", RP[p2])])
                return mk(4, "ld", [("r16", RP[p2]), ("ind16", nn)])
            if z2 == 4:
                return mk(2, "neg", [])
            if z2 == 5:
                return mk(2, "reti" if y2 == 1 else "retn", [], "ret")
            if z2 == 6:
                return mk(2, "im", [("imm", (0, 0, 1, 2)[y2 & 3])])
            if z2 == 7:
                names = ["ld i,a", "ld r,a", "ld a,i", "ld a,r", "rrd", "rld", "nop", "nop"]
                return mk(2, names[y2], [])
        if x2 == 2 and z2 <= 3 and y2 >= 4:
            names = [["ldi", "cpi", "ini", "outi"], ["ldd", "cpd", "ind", "outd"],
                     ["ldir", "cpir", "inir", "otir"], ["lddr", "cpdr", "indr", "otdr"]]
            return mk(2, names[y2 - 4][z2], [])
        return mk(2, "nop", [])

    # --- main table -------------------------------------------------------
    if x == 1:
        if op == 0x76:
            return mk(1 + i, "halt", [], "halt")
        if z == 6:
            m, nb = mem_operand(base)
            return mk(nb, "ld", [r8(y, False), m])
        if y == 6:
            m, nb = mem_operand(base)
            return mk(nb, "ld", [m, r8(z, False)])
        return mk(1 + i, "ld", [r8(y), r8(z)])
    if x == 2:
        if z == 6:
            m, nb = mem_operand(base)
            return mk(nb, ALU[y], [("r8", "a"), m])
        return mk(1 + i, ALU[y], [("r8", "a"), r8(z)])
    if x == 0:
        if z == 0:
            if y == 0:
                return mk(1, "nop", [])
            if y == 1:
                return mk(1, "ex af,af'", [])
            d = s8(b(1))
            tgt = (start + 2 + d) & 0xFFFF
            if y == 2:
                return mk(2, "djnz", [("addr", tgt)], "jcc", tgt)
            if y == 3:
                return mk(2, "jr", [("addr", tgt)], "jmp", tgt)
            return mk(2, "jr", [("cc", CC[y - 4]), ("addr", tgt)], "jcc", tgt)
        if z == 1:
            if q == 0:
                rp = ("r16", ix if (ix and p == 2) else RP[p])
                return mk(3 + i, "ld", [rp, ("imm", b(base) | (b(base + 1) << 8))])
            rp = ("r16", ix if (ix and p == 2) else RP[p])
            return mk(1 + i, "add", [("r16", ix or "hl"), rp])
        if z == 2:
            if p == 0 or p == 1:
                m = ("ind", "bc" if p == 0 else "de", 0)
                return mk(1, "ld", [m, ("r8", "a")] if q == 0 else [("r8", "a"), m])
            nn = b(base) | (b(base + 1) << 8)
            if p == 2:
                hl = ("r16", ix or "hl")
                return mk(3 + i, "ld", [("ind16", nn), hl] if q == 0 else [hl, ("ind16", nn)])
            return mk(3 + i, "ld", [("ind16", nn), ("r8", "a")] if q == 0 else [("r8", "a"), ("ind16", nn)])
        if z == 3:
            rp = ("r16", ix if (ix and p == 2) else RP[p])
            return mk(1 + i, "inc" if q == 0 else "dec", [rp])
        if z == 4 or z == 5:
            mn = "inc" if z == 4 else "dec"
            if y == 6:
                m, nb = mem_operand(base)
                return mk(nb, mn, [m])
            return mk(1 + i, mn, [r8(y)])
        if z == 6:
            if y == 6:
                m, nb = mem_operand(base)
                return mk(nb + 1, "ld", [m, ("imm", b(nb))])
            return mk(2 + i, "ld", [r8(y), ("imm", b(base))])
        names = ["rlca", "rrca", "rla", "rra", "daa", "cpl", "scf", "ccf"]
        return mk(1, names[y], [])
    # x == 3
    if z == 0:
        return mk(1, "ret", [("cc", CC[y])], "cret")
    if z == 1:
        if q == 0:
            return mk(1 + i, "pop", [("r16", ix if (ix and p == 2) else RP2[p])])
        if p == 0:
            return mk(1, "ret", [], "ret")
        if p == 1:
            return mk(1, "exx", [])
        if p == 2:
            return mk(1 + i, "jp", [("ind", ix or "hl", 0)], "ijmp")
        return mk(1 + i, "ld", [("r16", "sp"), ("r16", ix or "hl")])
    if z == 2:
        nn = b(1) | (b(2) << 8)
        return mk(3, "jp", [("cc", CC[y]), ("addr", nn)], "jcc", nn)
    if z == 3:
        if y == 0:
            nn = b(1) | (b(2) << 8)
            return mk(3, "jp", [("addr", nn)], "jmp", nn)
        if y == 2:
            return mk(2, "out", [("port", b(1)), ("r8", "a")])
        if y == 3:
            return mk(2, "in", [("r8", "a"), ("port", b(1))])
        if y == 4:
            return mk(1 + i, "ex", [("ind", "sp", 0), ("r16", ix or "hl")])
        if y == 5:
            return mk(1, "ex", [("r16", "de"), ("r16", "hl")])
        if y == 6:
            return mk(1, "di", [])
        return mk(1, "ei", [])
    if z == 4:
        nn = b(1) | (b(2) << 8)
        return mk(3, "call", [("cc", CC[y]), ("addr", nn)], "ccall", nn)
    if z == 5:
        if q == 0:
            return mk(1 + i, "push", [("r16", ix if (ix and p == 2) else RP2[p])])
        nn = b(1) | (b(2) << 8)
        return mk(3, "call", [("addr", nn)], "call", nn)
    if z == 6:
        return mk(2, ALU[y], [("r8", "a"), ("imm", b(1))])
    return mk(1, "rst", [("imm", y * 8)], "rst", y * 8)
