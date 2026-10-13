"""NEC V30 instruction decoder for the translator (engine/v30x.py): the structure of an instruction, not its text
(the text is engine/v30dis.py's, MAME's necdasm).

    decode(rd, cs, ip) -> Ins       rd(linear address) -> byte

Ins fields: cs ip lin length text; op (the opcode after the prefixes; $0F: op $0F, sub the second byte); seg (a segment
override: 0 DS1, 1 PS, 2 SS, 3 DS0, else None); rep (repnc repc repne rep or None); mn (the canonical name below); w (1
or 2: the operand size); ops (operands, destination first); flow (seq jmp jcc call ret ijmp icall int iret halt jmpf
callf retf ijmpf icallf); target ((cs, ip) of a direct jump / call / branch); cond (0-15: the condition of a jcc, the
low nibble of $70-$7F); loop (dbnzne dbnze dbnz bcwz: E0-E3).

Operands: ("r", i, w) a register (w 1: AL CL DL BL AH CH DH BH = 0-7; w 2: AW CW DW BW SP BP IX IY = 0-7),
("s", i) a segment register (DS1 PS SS DS0 = 0-3), ("i", value) an immediate (unsigned, the operand's size; an
8-bit one sign-extended by $83 / $6B / $6A already), ("m", regs, disp, seg) memory: regs a tuple of BW BP IX IY
indexes (3 5 6 7), disp 0-$FFFF, seg the segment register used (the override or the default: SS with BP).

Canonical names: add or addc subc and sub xor cmp (k 0-7 of the ALU block), test mov xch lea ldp (LES / LDS: ops
reg, mem, seg in sreg) inc dec not neg mulu mul divu div imul (3 operands) rol ror rolc rorc shl shr shra (ops dst,
count: ("i", n) or ("r", 1, 1) CL) push pop pusha popa pushf popf sahf lahf cvtbw cvtwl adj4a adj4s adjba adjbs cvtbd
cvtdb trans movbk cmpbk stm ldm cmpm inm outm in out (ops: data register, port ("i", p) or ("r", 2, 2) DW) jcc loop
br call ret retf reti int into halt nop clr1cy set1cy not1cy di ei cld std poll chkind prepare dispose salc test1 clr1
set1 not1 (ops: dst, bit) add4s sub4s cmp4s rol4 ror4 ins ext buslock brkem invalid.
"""
from collections import namedtuple

import v30dis

Ins = namedtuple("Ins", "cs ip lin length text op sub seg rep mn w ops flow target cond loop")

ALU = ("add", "or", "addc", "subc", "and", "sub", "xor", "cmp")
SHIFTS = ("rol", "ror", "rolc", "rorc", "shl", "shr", None, "shra")
EA_REGS = ((3, 6), (3, 7), (5, 6), (5, 7), (6,), (7,), (5,), (3,))
DS1, PS, SS, DS0 = range(4)
SEG_PREFIX = {0x26: DS1, 0x2E: PS, 0x36: SS, 0x3E: DS0}
REP_PREFIX = {0x64: "repnc", 0x65: "repc", 0xF2: "repne", 0xF3: "rep"}
STRING = {0xA4: "movbk", 0xA5: "movbk", 0xA6: "cmpbk", 0xA7: "cmpbk", 0xAA: "stm", 0xAB: "stm", 0xAC: "ldm",
          0xAD: "ldm", 0xAE: "cmpm", 0xAF: "cmpm", 0x6C: "inm", 0x6D: "inm", 0x6E: "outm", 0x6F: "outm"}
SIMPLE = {0x27: "adj4a", 0x2F: "adj4s", 0x37: "adjba", 0x3F: "adjbs", 0x60: "pusha", 0x61: "popa", 0x90: "nop",
          0x98: "cvtbw", 0x99: "cvtwl", 0x9B: "poll", 0x9C: "pushf", 0x9D: "popf", 0x9E: "sahf", 0x9F: "lahf",
          0xC9: "dispose", 0xCE: "into", 0xD6: "salc", 0xD7: "trans", 0xF0: "buslock", 0xF4: "halt", 0xF5: "not1cy",
          0xF8: "clr1cy", 0xF9: "set1cy", 0xFA: "di", 0xFB: "ei", 0xFC: "cld", 0xFD: "std"}


def s8(v):
    return v - 256 if v & 0x80 else v


class _R:
    def __init__(self, rd, cs, ip):
        self.rd, self.cs, self.ip0, self.ip = rd, cs, ip, ip

    def byte(self):
        v = self.rd(((self.cs << 4) + self.ip) & 0xFFFFF)
        self.ip = (self.ip + 1) & 0xFFFF
        return v

    def word(self):
        lo = self.byte()
        return lo | (self.byte() << 8)


def decode(rd, cs, ip):
    r = _R(rd, cs, ip)
    seg = rep = None
    op = r.byte()
    while True:
        if op in SEG_PREFIX:
            seg = SEG_PREFIX[op]
        elif op in REP_PREFIX:
            rep = REP_PREFIX[op]
        else:
            break
        op = r.byte()
    f = dict(op=op, sub=None, seg=seg, rep=rep, mn="invalid", w=1, ops=(), flow="seq", target=None, cond=None,
             loop=None)

    def modrm(w):
        m = r.byte()
        mod, reg, rm = m >> 6, (m >> 3) & 7, m & 7
        if mod == 3:
            return m, reg, ("r", rm, w)
        sg = DS0
        if mod == 0 and rm == 6:
            regs, disp = (), r.word()
        else:
            regs = EA_REGS[rm]
            if 5 in regs:
                sg = SS
            disp = 0
            if mod == 1:
                disp = s8(r.byte()) & 0xFFFF
            elif mod == 2:
                disp = r.word()
        return m, reg, ("m", regs, disp, seg if seg is not None else sg)

    def imm(w):
        return ("i", r.byte() if w == 1 else r.word())

    if op < 0x40 and (op & 7) < 6:
        k, j = op >> 3, op & 7
        f["mn"] = ALU[k]
        if j < 4:
            w = 1 + (j & 1)
            m, reg, rm = modrm(w)
            f["ops"] = (rm, ("r", reg, w)) if j < 2 else (("r", reg, w), rm)
        else:
            w = 1 + (j & 1)
            f["ops"] = (("r", 0, w), imm(w))
        f["w"] = w
    elif op in (0x06, 0x0E, 0x16, 0x1E):
        f.update(mn="push", w=2, ops=(("s", op >> 3),))
    elif op in (0x07, 0x17, 0x1F):
        f.update(mn="pop", w=2, ops=(("s", op >> 3),))
    elif op == 0x0F:
        sub = r.byte()
        f["sub"] = sub
        if 0x10 <= sub <= 0x1F:
            w = 1 + (sub & 1)
            m, reg, rm = modrm(w)
            bit = ("r", 1, 1) if sub < 0x18 else ("i", r.byte() & (15 if w == 2 else 7))
            f.update(mn=("test1", "clr1", "set1", "not1")[(sub >> 1) & 3], w=w, ops=(rm, bit))
        elif sub in (0x20, 0x22, 0x26):
            f["mn"] = {0x20: "add4s", 0x22: "sub4s", 0x26: "cmp4s"}[sub]
        elif sub in (0x28, 0x2A):
            m, reg, rm = modrm(1)
            f.update(mn="rol4" if sub == 0x28 else "ror4", ops=(rm,))
        elif sub in (0x31, 0x33, 0x39, 0x3B):
            m, reg, rm = modrm(1)
            extra = ("i", r.byte() & 15) if sub >= 0x39 else ("r", reg, 1)
            f.update(mn="ins" if sub in (0x31, 0x39) else "ext", ops=(rm, extra))
        elif sub == 0xFF:
            r.byte()
            f["mn"] = "brkem"
    elif op in SIMPLE:
        f["mn"] = SIMPLE[op]
        if op in (0x9C, 0x9D, 0x60, 0x61):
            f["w"] = 2
        if op == 0xF4:
            f["flow"] = "halt"
    elif 0x40 <= op < 0x50:
        f.update(mn="inc" if op < 0x48 else "dec", w=2, ops=(("r", op & 7, 2),))
    elif 0x50 <= op < 0x60:
        f.update(mn="push" if op < 0x58 else "pop", w=2, ops=(("r", op & 7, 2),))
    elif op == 0x62:
        m, reg, rm = modrm(2)
        f.update(mn="chkind", w=2, ops=(("r", reg, 2), rm))
    elif op in (0x68, 0x6A):
        v = r.word() if op == 0x68 else s8(r.byte()) & 0xFFFF
        f.update(mn="push", w=2, ops=(("i", v),))
    elif op in (0x69, 0x6B):
        m, reg, rm = modrm(2)
        v = r.word() if op == 0x69 else s8(r.byte()) & 0xFFFF
        f.update(mn="imul", w=2, ops=(("r", reg, 2), rm, ("i", v)))
    elif op in STRING:
        f.update(mn=STRING[op], w=1 + (op & 1))
    elif 0x70 <= op < 0x80:
        d = s8(r.byte())
        f.update(mn="jcc", cond=op & 15, flow="jcc", target=(cs, (r.ip + d) & 0xFFFF))
    elif 0x80 <= op <= 0x83:
        w = 1 if op in (0x80, 0x82) else 2
        m, reg, rm = modrm(w)
        if op == 0x83:
            v = s8(r.byte()) & 0xFFFF
        else:
            v = r.byte() if w == 1 else r.word()
        f.update(mn=ALU[reg], w=w, ops=(rm, ("i", v)))
    elif op in (0x84, 0x85, 0x86, 0x87, 0x88, 0x89, 0x8A, 0x8B):
        w = 1 + (op & 1)
        m, reg, rm = modrm(w)
        mn = {0x84: "test", 0x86: "xch", 0x88: "mov", 0x8A: "mov"}[op & ~1]
        f.update(mn=mn, w=w, ops=(("r", reg, w), rm) if op >= 0x8A else (rm, ("r", reg, w)))
    elif op == 0x8C:
        if (rd(((cs << 4) + r.ip) & 0xFFFFF) >> 3) & 7 >= 4:
            r.byte()                                   # (MAME: no operand fetched for registers 4-7)
            f.update(mn="nop")
        else:
            m, reg, rm = modrm(2)
            f.update(mn="mov", w=2, ops=(rm, ("s", reg)))
    elif op == 0x8D:
        m, reg, rm = modrm(2)
        f.update(mn="lea", w=2, ops=(("r", reg, 2), rm))
    elif op == 0x8E:
        m, reg, rm = modrm(2)
        f.update(mn="mov" if reg < 4 else "nop", w=2, ops=(("s", reg), rm) if reg < 4 else ())
    elif op == 0x8F:
        m, reg, rm = modrm(2)
        f.update(mn="pop", w=2, ops=(rm,))
    elif 0x91 <= op <= 0x97:
        f.update(mn="xch", w=2, ops=(("r", 0, 2), ("r", op & 7, 2)))
    elif op in (0x9A, 0xEA):
        off = r.word()
        sg = r.word()
        f.update(mn="call" if op == 0x9A else "br", flow="callf" if op == 0x9A else "jmpf", target=(sg, off))
    elif 0xA0 <= op <= 0xA3:
        w = 1 + (op & 1)
        mem = ("m", (), r.word(), seg if seg is not None else DS0)
        f.update(mn="mov", w=w, ops=(("r", 0, w), mem) if op < 0xA2 else (mem, ("r", 0, w)))
    elif op in (0xA8, 0xA9):
        w = 1 + (op & 1)
        f.update(mn="test", w=w, ops=(("r", 0, w), imm(w)))
    elif 0xB0 <= op < 0xC0:
        w = 1 if op < 0xB8 else 2
        f.update(mn="mov", w=w, ops=(("r", op & 7, w), imm(w)))
    elif op in (0xC0, 0xC1, 0xD0, 0xD1, 0xD2, 0xD3):
        w = 1 + (op & 1)
        m, reg, rm = modrm(w)
        if op in (0xC0, 0xC1):
            cnt = ("i", r.byte())
        elif op in (0xD0, 0xD1):
            cnt = ("i", 1)
        else:
            cnt = ("r", 1, 1)
        f.update(mn=SHIFTS[reg] or "invalid", w=w, ops=(rm, cnt))
    elif op in (0xC2, 0xC3):
        f.update(mn="ret", flow="ret", ops=(("i", r.word()),) if op == 0xC2 else ())
    elif op in (0xC4, 0xC5):
        m, reg, rm = modrm(2)
        f.update(mn="ldp", w=2, ops=(("r", reg, 2), rm, ("s", DS1 if op == 0xC4 else DS0)))
    elif op in (0xC6, 0xC7):
        w = 1 + (op & 1)
        m, reg, rm = modrm(w)
        f.update(mn="mov", w=w, ops=(rm, imm(w)))
    elif op == 0xC8:
        n = r.word()
        lv = r.byte()
        f.update(mn="prepare", ops=(("i", n), ("i", lv)))
    elif op in (0xCA, 0xCB):
        f.update(mn="retf", flow="retf", ops=(("i", r.word()),) if op == 0xCA else ())
    elif op in (0xCC, 0xCD):
        n = 3 if op == 0xCC else r.byte()
        f.update(mn="int", flow="int", ops=(("i", n),))
    elif op == 0xCF:
        f.update(mn="reti", flow="iret")
    elif op in (0xD4, 0xD5):
        f.update(mn="cvtbd" if op == 0xD4 else "cvtdb", ops=(("i", r.byte()),))
    elif 0xD8 <= op <= 0xDF:
        modrm(1)
        f["mn"] = "nop"
    elif 0xE0 <= op <= 0xE3:
        d = s8(r.byte())
        f.update(mn="loop", loop=("dbnzne", "dbnze", "dbnz", "bcwz")[op & 3], flow="jcc",
                 target=(cs, (r.ip + d) & 0xFFFF))
    elif op in (0xE4, 0xE5, 0xE6, 0xE7, 0xEC, 0xED, 0xEE, 0xEF):
        w = 1 + (op & 1)
        port = ("i", r.byte()) if op < 0xE8 else ("r", 2, 2)
        f.update(mn="in" if not op & 2 else "out", w=w, ops=(("r", 0, w), port))
    elif op in (0xE8, 0xE9):
        d = r.word()
        f.update(mn="call" if op == 0xE8 else "br", flow="call" if op == 0xE8 else "jmp",
                 target=(cs, (r.ip + d) & 0xFFFF))
    elif op == 0xEB:
        d = s8(r.byte())
        f.update(mn="br", flow="jmp", target=(cs, (r.ip + d) & 0xFFFF))
    elif op in (0xF6, 0xF7):
        w = 1 + (op & 1)
        m, reg, rm = modrm(w)
        if reg == 0:
            f.update(mn="test", w=w, ops=(rm, imm(w)))
        elif reg >= 2:
            f.update(mn=("not", "neg", "mulu", "mul", "divu", "div")[reg - 2], w=w, ops=(rm,))
    elif op in (0xFE, 0xFF):
        w = 1 + (op & 1)
        m, reg, rm = modrm(w)
        if reg < 2:
            f.update(mn=("inc", "dec")[reg], w=w, ops=(rm,))
        elif op == 0xFF and reg < 7:
            f.update(mn=(None, None, "call", "call", "br", "br", "push")[reg], w=2, ops=(rm,),
                     flow=(None, None, "icall", "icallf", "ijmp", "ijmpf", "seq")[reg])
    elif op in (0x63, 0x64, 0x65, 0x66, 0x67, 0xF1):
        if op in (0x66, 0x67):
            modrm(1)
            f["mn"] = "nop"
    length = (r.ip - ip) & 0xFFFF
    text = v30dis.decode(lambda a: rd(a), (cs << 4) + ip).text
    return Ins(cs, ip, ((cs << 4) + ip) & 0xFFFFF, length, text, **f)
