"""MC6809 disassembler / decoder (the instruction set of m6809.py; text in MAME's syntax).

decode(rd, pc, dp=None) -> Ins(pc, op, length, mn, mode, arg, flow, target, text)
  rd(addr) -> byte; op includes the page ($10xx, $11xx); mn lowercase (MAME's name); length as the CPU executes it
  mode: inh, imm8, imm16, dir, ext, idx, rel8, rel16, stack (PSH/PUL postbyte), regs (TFR/EXG postbyte)
  arg:  the value / address / signed offset; for idx an Idx(post, reg, kind, offset, indirect, inc, addr):
        reg x y u s, 'pc' (pcr8/pcr16) or None (abs = extended indirect [n] or the undocumented $8F);
        kind off5 off8 off16 zero acc_a acc_b acc_d inc1 inc2 dec1 dec2 pcr8 pcr16 abs illegal ($x7 $xA $xE: address 0);
        offset signed (abs: the address); inc +1 +2 -1 -2 or 0; addr the absolute address of pcr8/pcr16/abs
  flow: seq, jmp, jcc, call, ret (RTS, PULS/PULU with PC), ijmp (JMP indexed, TFR/EXG to PC), icall (JSR indexed),
        swi (SWI SWI2 SWI3 XSWI2 XFIRQ XRES), rti, wait (CWAI SYNC), halt (the free-run opcodes $14 $15 $CD)
        JMP/JSR direct are jmp/call with a target when dp is given, else ijmp/icall
  text: as MAME's 6x09dasm prints it (uppercase, `$` hex, `<` direct, `>` extended below $100, `,PCR` absolute)
"""
from collections import namedtuple

Ins = namedtuple("Ins", "pc op length mn mode arg flow target text")
Idx = namedtuple("Idx", "post reg kind offset indirect inc addr")

INH, DIR, EXT, IND, IMM, REL, LREL, PSHS, PULS, PSHU, PULU, RR, PG2, PG3 = range(14)
OPS = {}                                   # (page << 8) | op -> (NAME, mode, operand length)


def _row(base, names, mode, ln):
    for i, n in enumerate(names):
        if n:
            OPS[base + i] = (n, mode, ln)


_RMW = ["NEG", "NEG", "XNC", "COM", "LSR", "LSR", "ROR", "ASR", "ASL", "ROL", "DEC", "XDEC", "INC", "TST", "JMP", "CLR"]
_row(0x00, _RMW, DIR, 1)
_row(0x60, _RMW, IND, 1)
_row(0x70, _RMW, EXT, 2)
_row(0x40, [n + "A" for n in _RMW[:14]] + ["XCLRA", "CLRA"], INH, 0)
_row(0x50, [n + "B" for n in _RMW[:14]] + ["XCLRB", "CLRB"], INH, 0)
OPS.update({0x10: ("PAGE2", PG2, 0), 0x11: ("PAGE3", PG3, 0), 0x12: ("NOP", INH, 0), 0x13: ("SYNC", INH, 0),
            0x14: ("XHCF", INH, 0), 0x15: ("XHCF", INH, 0), 0x16: ("LBRA", LREL, 2), 0x17: ("LBSR", LREL, 2),
            0x18: ("X18", INH, 0), 0x19: ("DAA", INH, 0), 0x1A: ("ORCC", IMM, 1), 0x1B: ("NOP", INH, 0),
            0x1C: ("ANDCC", IMM, 1), 0x1D: ("SEX", INH, 0), 0x1E: ("EXG", RR, 1), 0x1F: ("TFR", RR, 1),
            0x30: ("LEAX", IND, 1), 0x31: ("LEAY", IND, 1), 0x32: ("LEAS", IND, 1), 0x33: ("LEAU", IND, 1),
            0x34: ("PSHS", PSHS, 1), 0x35: ("PULS", PULS, 1), 0x36: ("PSHU", PSHU, 1), 0x37: ("PULU", PULU, 1),
            0x38: ("XANDCC", IMM, 1), 0x39: ("RTS", INH, 0), 0x3A: ("ABX", INH, 0), 0x3B: ("RTI", INH, 0),
            0x3C: ("CWAI", IMM, 1), 0x3D: ("MUL", INH, 0), 0x3E: ("XRES", INH, 0), 0x3F: ("SWI", INH, 0),
            0x8D: ("BSR", REL, 1), 0xCD: ("XHCF", INH, 0)})
_row(0x20, ["BRA", "BRN", "BHI", "BLS", "BCC", "BCS", "BNE", "BEQ", "BVC", "BVS", "BPL", "BMI", "BGE", "BLT", "BGT", "BLE"], REL, 1)
for _m, _mode in enumerate((IMM, DIR, IND, EXT)):
    for _side, _names, _w16 in ((0x80, ["SUBA", "CMPA", "SBCA", "SUBD", "ANDA", "BITA", "LDA", "STA", "EORA", "ADCA", "ORA",
                                        "ADDA", "CMPX", "JSR", "LDX", "STX"], (3, 12, 14, 15)),
                                (0xC0, ["SUBB", "CMPB", "SBCB", "ADDD", "ANDB", "BITB", "LDB", "STB", "EORB", "ADCB", "ORB",
                                        "ADDB", "LDD", "STD", "LDU", "STU"], (3, 12, 13, 14, 15))):
        for _k, _n in enumerate(_names):
            _op = _side + _m * 16 + _k
            if _op in OPS:
                continue
            if _mode == IMM:
                if _k in (7, 15):
                    _n = "X" + _n
                elif _k == 13:
                    continue
            ln = (2 if _k in _w16 else 1) if _mode == IMM else (2 if _mode == EXT else 1)
            OPS[_op] = (_n, _mode, ln)
OPS.update({0x1010: ("PAGE2", PG2, 0), 0x1011: ("PAGE3", PG3, 0), 0x1020: ("XLBRA", LREL, 2),
            0x103E: ("XSWI2", INH, 0), 0x103F: ("SWI2", INH, 0), 0x1087: ("XSTA", IMM, 1), 0x108F: ("XSTY", IMM, 2),
            0x10C3: ("XADDD", IMM, 2), 0x10C7: ("XSTB", IMM, 1), 0x10CF: ("XSTS", IMM, 2),
            0x1110: ("PAGE2", PG2, 0), 0x1111: ("PAGE3", PG3, 0), 0x113E: ("XFIRQ", INH, 0), 0x113F: ("SWI3", INH, 0),
            0x1187: ("XSTA", IMM, 1), 0x118F: ("XSTX", IMM, 2), 0x11C3: ("XADDU", IMM, 2), 0x11C7: ("XSTB", IMM, 1),
            0x11CF: ("XSTU", IMM, 2)})
_row(0x1021, ["LBRN", "LBHI", "LBLS", "LBCC", "LBCS", "LBNE", "LBEQ", "LBVC", "LBVS", "LBPL", "LBMI", "LBGE", "LBLT",
              "LBGT", "LBLE"], LREL, 2)
for _m, _mode in enumerate((IMM, DIR, IND, EXT)):
    _ln = 2 if _mode in (IMM, EXT) else 1
    _l8 = 2 if _mode == EXT else 1
    for _op, _n in ((0x83, "CMPD"), (0x8C, "CMPY"), (0x8E, "LDY"), (0xCE, "LDS")):
        OPS[0x1000 + _op + _m * 16] = (_n, _mode, _ln)
    for _op, _n in ((0x83, "CMPU"), (0x8C, "CMPS")):
        OPS[0x1100 + _op + _m * 16] = (_n, _mode, _ln)
    if _mode != IMM:
        for _op, _n in ((0x8F, "STY"), (0xCF, "STS"), (0xC3, "XADDD")):
            OPS[0x1000 + _op + _m * 16] = (_n, _mode, _l8)
        OPS[0x1100 + 0xC3 + _m * 16] = ("XADDU", _mode, _l8)

REGS = ["X", "Y", "U", "S", "PC"]
TEREGS = ["D", "X", "Y", "U", "S", "PC", "inv", "inv", "A", "B", "CC", "DP", "inv", "inv", "inv", "inv"]


def _fetch(rd, pc):
    """MAME's fetch_opcode: (entry, opcode, pointer after it) or (None, None, pointer) for FCB."""
    page, count, p = 0, 0, pc
    while True:
        opcode = page | rd(p & 0xFFFF)
        p += 1
        e = OPS.get(opcode)
        if e is None:
            if page:
                p -= 1                       # a 6809 falls through to page 1
                page = 0
                continue
            return None, None, p
        if e[1] in (PG2, PG3):
            if page == 0:
                count += 1
                page = opcode << 8
            else:
                count += 1
                p -= 1
                return None, None, p
            continue
        return e, opcode, p


def _sx8(v):
    return v - 256 if v & 0x80 else v


def _sx16(v):
    return v - 65536 if v & 0x8000 else v


def _r16(rd, a):
    return (rd(a & 0xFFFF) << 8) | rd((a + 1) & 0xFFFF)


def _idx_text(rd, pb, p):
    """MAME's indexed(): (text, pointer after the operand bytes it consumed)."""
    reg = (pb >> 5) & 3
    pbm = pb & 0x8F
    ind = (pb & 0x90) == 0x90
    t = ""

    def signed(off, width):
        return ("-" if off < 0 else "") + ("$%0*X" % (width, -off if off < 0 else off))
    if pbm == 0x80:
        if ind:
            if reg == 0: t = ",W"
            elif reg == 1:
                t = signed(_sx16(_r16(rd, p)), 4) + ",W"; p += 2
            elif reg == 2: t = ",W++"
            else: t = ",--W"
        else:
            t = ",%s+" % REGS[reg]
    elif pbm == 0x81: t = ",%s++" % REGS[reg]
    elif pbm == 0x82: t = "Illegal Postbyte" if ind else ",-%s" % REGS[reg]
    elif pbm == 0x83: t = ",--%s" % REGS[reg]
    elif pbm == 0x84: t = ",%s" % REGS[reg]
    elif pbm == 0x85: t = "B,%s" % REGS[reg]
    elif pbm == 0x86: t = "A,%s" % REGS[reg]
    elif pbm == 0x87: t = "E,%s" % REGS[reg]
    elif pbm == 0x88:
        t = signed(_sx8(rd(p & 0xFFFF)), 2) + "," + REGS[reg]; p += 1
    elif pbm == 0x89:
        t = signed(_sx16(_r16(rd, p)), 4) + "," + REGS[reg]; p += 2
    elif pbm == 0x8A: t = "F,%s" % REGS[reg]
    elif pbm == 0x8B: t = "D,%s" % REGS[reg]
    elif pbm == 0x8C:
        off = _sx8(rd(p & 0xFFFF)); p += 1
        t = "$%04X,PCR" % ((p + off) & 0xFFFF)
    elif pbm == 0x8D:
        off = _sx16(_r16(rd, p)); p += 2
        t = "$%04X,PCR" % ((p + off) & 0xFFFF)
    elif pbm == 0x8E: t = "W,%s" % REGS[reg]
    elif pbm == 0x8F:
        if ind:
            t = "$%04X" % _r16(rd, p); p += 2
        elif reg == 0: t = ",W"
        elif reg == 1:
            t = signed(_sx16(_r16(rd, p)), 4) + ",W"; p += 2
        elif reg == 2: t = ",W++"
        else: t = ",--W"
    else:
        off = pb & 0x1F
        if off > 15:
            off -= 32
        t = ("-" if off < 0 else "") + "$%X," % abs(off) + REGS[reg]
    if ind and pbm != 0x82:
        t = "[" + t + "]"
    return t, p


def mame_text(rd, pc):
    """The text MAME's 6809 disassembler prints for the instruction at pc (trailing blanks stripped)."""
    e, opcode, p = _fetch(rd, pc)
    if e is None:
        return ",".join(["FCB    $%02X" % rd(pc & 0xFFFF)] + ["$%02X" % rd(q & 0xFFFF) for q in range(pc + 1, p)])
    name, mode, ln = e
    ppc = p
    p += ln
    if mode == INH:
        return name
    t = "%-7s" % name
    if mode in (PSHS, PSHU):
        pb = rd(ppc & 0xFFFF)
        l = []
        if pb & 0x80: l.append("PC")
        if pb & 0x40: l.append("U" if mode == PSHS else "S")
        if pb & 0x20: l.append("Y")
        if pb & 0x10: l.append("X")
        if pb & 0x08: l.append("DP")
        if pb & 0x04: l.append("D" if pb & 0x02 else "B")
        elif pb & 0x02: l.append("A")
        if pb & 0x01: l.append("CC")
        t += ",".join(l)
    elif mode in (PULS, PULU):
        pb = rd(ppc & 0xFFFF)
        l = []
        if pb & 0x01: l.append("CC")
        if pb & 0x02: l.append("D" if pb & 0x04 else "A")
        elif pb & 0x04: l.append("B")
        if pb & 0x08: l.append("DP")
        if pb & 0x10: l.append("X")
        if pb & 0x20: l.append("Y")
        if pb & 0x40: l.append("U" if mode == PULS else "S")
        if pb & 0x80: l.append("PC")
        t += ",".join(l)
    elif mode == DIR:
        t += "<$%02X" % rd(ppc & 0xFFFF)
    elif mode == REL:
        t += "$%04X" % ((p + _sx8(rd(ppc & 0xFFFF))) & 0xFFFF)
    elif mode == LREL:
        t += "$%04X" % ((p + _sx16(_r16(rd, ppc))) & 0xFFFF)
    elif mode == EXT:
        ea = _r16(rd, ppc)
        t += (">" if ea < 0x100 else "") + "$%04X" % ea
    elif mode == IND:
        t += _idx_text(rd, rd(ppc & 0xFFFF), p)[0]
    elif mode == IMM:
        t += "#$%04X" % _r16(rd, ppc) if ln == 2 else "#$%02X" % rd(ppc & 0xFFFF)
    elif mode == RR:
        pb = rd(ppc & 0xFFFF)
        t += "%s,%s" % (TEREGS[pb >> 4], TEREGS[pb & 15])
    return t.rstrip()


def _idx(rd, pb, p):
    """The indexed operand as the CPU executes it: (Idx, pointer after the operand bytes); addr filled in later."""
    reg = "xyus"[(pb >> 5) & 3]
    if not pb & 0x80:
        off = pb & 0x1F
        return Idx(pb, reg, "off5", off - 32 if off & 0x10 else off, False, 0, None), p
    ind = bool(pb & 0x10)
    k = pb & 0x0F
    if k == 0: return Idx(pb, reg, "inc1", 0, ind, 1, None), p
    if k == 1: return Idx(pb, reg, "inc2", 0, ind, 2, None), p
    if k == 2: return Idx(pb, reg, "dec1", 0, ind, -1, None), p
    if k == 3: return Idx(pb, reg, "dec2", 0, ind, -2, None), p
    if k == 4: return Idx(pb, reg, "zero", 0, ind, 0, None), p
    if k == 5: return Idx(pb, reg, "acc_b", 0, ind, 0, None), p
    if k == 6: return Idx(pb, reg, "acc_a", 0, ind, 0, None), p
    if k == 8: return Idx(pb, reg, "off8", _sx8(rd(p & 0xFFFF)), ind, 0, None), p + 1
    if k == 9: return Idx(pb, reg, "off16", _sx16(_r16(rd, p)), ind, 0, None), p + 2
    if k == 11: return Idx(pb, reg, "acc_d", 0, ind, 0, None), p
    if k == 12:
        off = _sx8(rd(p & 0xFFFF))
        return Idx(pb, "pc", "pcr8", off, ind, 0, (p + 1 + off) & 0xFFFF), p + 1
    if k == 13:
        off = _sx16(_r16(rd, p))
        return Idx(pb, "pc", "pcr16", off, ind, 0, (p + 2 + off) & 0xFFFF), p + 2
    if k == 15:
        a = _r16(rd, p)
        return Idx(pb, None, "abs", a, ind, 0, a), p + 2
    return Idx(pb, reg, "illegal", 0, ind, 0, 0), p


BRANCH = {"bra", "lbra", "xlbra"}
SWIS = {"swi", "swi2", "swi3", "xswi2", "xfirq", "xres"}


def decode(rd, pc, dp=None):
    # the CPU's view of the prefixes: repeated $10/$11 keep the first page; an unknown page 2/3 opcode
    # skips that byte and runs the next one as a page 1 opcode (MAME's m6809 core)
    p, page = pc, 0
    while True:
        b = rd(p & 0xFFFF)
        p += 1
        if page == 0:
            if b in (0x10, 0x11):
                page = b
                continue
            opcode = b
            break
        if b in (0x10, 0x11):
            continue
        if (page << 8) | b in OPS:
            opcode = (page << 8) | b
            break
        page = 0
    name, mode, ln = OPS[opcode]
    mn = name.lower()
    ppc = p
    p += ln
    arg = target = None
    flow = "seq"
    m = None
    if mode == INH:
        m = "inh"
        if mn in ("rts",): flow = "ret"
        elif mn == "rti": flow = "rti"
        elif mn in SWIS: flow = "swi"
        elif mn in ("cwai", "sync"): flow = "wait"
        elif mn == "xhcf": flow = "halt"
    elif mode == IMM:
        m = "imm16" if ln == 2 else "imm8"
        arg = _r16(rd, ppc) if ln == 2 else rd(ppc & 0xFFFF)
        if mn == "cwai": flow = "wait"
    elif mode == DIR:
        m, arg = "dir", rd(ppc & 0xFFFF)
        if mn in ("jmp", "jsr"):
            if dp is None:
                flow = "ijmp" if mn == "jmp" else "icall"
            else:
                flow, target = ("jmp" if mn == "jmp" else "call"), (dp << 8) | arg
    elif mode == EXT:
        m, arg = "ext", _r16(rd, ppc)
        if mn == "jmp": flow, target = "jmp", arg
        elif mn == "jsr": flow, target = "call", arg
    elif mode == IND:
        m = "idx"
        arg, p = _idx(rd, rd(ppc & 0xFFFF), p)
        if arg.kind in ("pcr8", "pcr16"):
            arg = arg._replace(addr=(p + arg.offset) & 0xFFFF)
        if mn == "jmp": flow = "ijmp"
        elif mn == "jsr": flow = "icall"
    elif mode in (REL, LREL):
        m = "rel8" if mode == REL else "rel16"
        arg = _sx8(rd(ppc & 0xFFFF)) if mode == REL else _sx16(_r16(rd, ppc))
        target = (p + arg) & 0xFFFF
        if mn in BRANCH: flow = "jmp"
        elif mn in ("brn", "lbrn"): flow = "seq"
        elif mn in ("bsr", "lbsr"): flow = "call"
        else: flow = "jcc"
    elif mode in (PSHS, PULS, PSHU, PULU):
        m, arg = "stack", rd(ppc & 0xFFFF)
        if mode in (PULS, PULU) and arg & 0x80:
            flow = "ret"
    elif mode == RR:
        m, arg = "regs", rd(ppc & 0xFFFF)
        if (arg & 15) == 5 or (mn == "exg" and (arg >> 4) == 5):
            flow = "ijmp"
    return Ins(pc, opcode, p - pc, mn, m, arg, flow, target, mame_text(rd, pc))


if __name__ == "__main__":
    import sys
    data = bytes.fromhex(sys.argv[1]) if len(sys.argv) > 1 else bytes.fromhex("10CE03F8A69F1234ECA4")
    mem = bytearray(65536)
    mem[:len(data)] = data
    pc = 0
    while pc < len(data):
        i = decode(mem.__getitem__, pc)
        print("%04X  %-10s %-24s %s %s %s" % (pc, data[pc:pc + i.length].hex(), i.text, i.mode, i.arg, i.flow))
        pc += i.length
