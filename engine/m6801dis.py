"""MC6801 disassembler / decoder (the instruction set of m6801.py).

decode(rom, pc, base=0xF000, hd6301=False) -> Ins(pc, op, length, mn, mode, arg, flow, target)
  mode: inh, imm8, imm16, dir, idx, ext, rel; HD6301 only: imdir, imidx (arg = (imm, address/offset))
  flow: seq, jmp, jcc, call, ret, ijmp (JMP indexed), wai
hd6301=True decodes the HD6301/63701 set of hd63701.py: + XGDX, SLP (flow wai), AIM OIM EIM TIM, MAME's $12/$13
(asx1/asx2: X += (S+1)); STAA/STAB/STD/STS/STX immediate are TRAPs there and raise like the other undefined opcodes.
"""
from collections import namedtuple

Ins = namedtuple("Ins", "pc op length mn mode arg flow target text")

INH = {0x01: "nop", 0x04: "lsrd", 0x05: "asld", 0x06: "tap", 0x07: "tpa", 0x08: "inx", 0x09: "dex",
       0x0A: "clv", 0x0B: "sev", 0x0C: "clc", 0x0D: "sec", 0x0E: "cli", 0x0F: "sei", 0x10: "sba",
       0x11: "cba", 0x16: "tab", 0x17: "tba", 0x19: "daa", 0x1B: "aba", 0x30: "tsx", 0x31: "ins",
       0x32: "pula", 0x33: "pulb", 0x34: "des", 0x35: "txs", 0x36: "psha", 0x37: "pshb", 0x38: "pulx",
       0x39: "rts", 0x3A: "abx", 0x3B: "rti", 0x3C: "pshx", 0x3D: "mul", 0x3E: "wai"}
BRANCH = ["bra", "brn", "bhi", "bls", "bcc", "bcs", "bne", "beq", "bvc", "bvs", "bpl", "bmi", "bge", "blt", "bgt", "ble"]
UNARY = {0: "neg", 3: "com", 4: "lsr", 6: "ror", 7: "asr", 8: "asl", 9: "rol", 10: "dec", 12: "inc", 13: "tst", 15: "clr"}
ALU = {0: "sub", 1: "cmp", 2: "sbc", 4: "and", 5: "bit", 6: "ld", 7: "st", 8: "eor", 9: "adc", 10: "ora", 11: "add"}


HD6301_INH = {0x18: "xgdx", 0x1A: "slp", 0x12: "asx1", 0x13: "asx2", 0x3F: "swi"}   # asx: MAME's names
HD6301_IMM = {1: "aim", 2: "oim", 5: "eim", 11: "tim"}


def decode(rom, pc, base=0xF000, hd6301=False):
    def b(i):
        return rom[pc - base + i]
    op = b(0)
    hi, k = op >> 4, op & 15
    if hd6301:
        if op in HD6301_INH:
            t = HD6301_INH[op]
            return Ins(pc, op, 1, t, "inh", None, {0x1A: "wai", 0x3F: "call"}.get(op, "seq"), None,
                       t + " 1,s" if op in (0x12, 0x13) else t)
        if hi in (6, 7) and k in HD6301_IMM:
            mn, imm, a = HD6301_IMM[k], b(1), b(2)
            if hi == 6:
                return Ins(pc, op, 3, mn, "imidx", (imm, a), "seq", None, "%s #$%02X,$%02X,x" % (mn, imm, a))
            return Ins(pc, op, 3, mn, "imdir", (imm, a), "seq", None, "%s #$%02X,$%02X" % (mn, imm, a))
        if op in (0xCD, 0xCF):
            raise ValueError("bad opcode %02X at %04X" % (op, pc))

    def mk(length, mn, mode, arg=None, flow="seq", target=None):
        if mode == "inh": t = mn
        elif mode == "imm8": t = "%s #$%02X" % (mn, arg)
        elif mode == "imm16": t = "%s #$%04X" % (mn, arg)
        elif mode == "dir": t = "%s $%02X" % (mn, arg)
        elif mode == "idx": t = "%s $%02X,x" % (mn, arg)
        elif mode == "ext": t = "%s $%04X" % (mn, arg)
        else: t = "%s $%04X" % (mn, target)
        return Ins(pc, op, length, mn, mode, arg, flow, target, t)

    if op in INH:
        flow = "ret" if op in (0x39, 0x3B) else ("wai" if op == 0x3E else "seq")
        return mk(1, INH[op], "inh", flow=flow)
    if hi == 2:
        d = b(1)
        tgt = (pc + 2 + (d - 256 if d & 0x80 else d)) & 0xFFFF
        flow = "jmp" if k == 0 else ("seq" if k == 1 else "jcc")
        return mk(2, BRANCH[k], "rel", flow=flow, target=tgt)
    if hi in (4, 5):
        if k in UNARY:
            return mk(1, UNARY[k] + "ab"[hi - 4], "inh")
    if hi in (6, 7) and k in UNARY or (hi in (6, 7) and k == 14):
        mode = "idx" if hi == 6 else "ext"
        arg = b(1) if hi == 6 else (b(1) << 8) | b(2)
        ln = 2 if hi == 6 else 3
        if k == 14:
            return mk(ln, "jmp", mode, arg, "ijmp" if hi == 6 else "jmp", arg if hi == 7 else None)
        return mk(ln, UNARY[k], mode, arg)
    if hi >= 8:
        bsel = "b" if hi >= 12 else "a"
        mode = ["imm", "dir", "idx", "ext"][(hi - 8) & 3]
        if op == 0x8D:
            d = b(1)
            tgt = (pc + 2 + (d - 256 if d & 0x80 else d)) & 0xFFFF
            return mk(2, "bsr", "rel", flow="call", target=tgt)

        def operand(size16):
            if mode == "imm":
                return (("imm16", (b(1) << 8) | b(2), 3) if size16 else ("imm8", b(1), 2))
            if mode == "dir": return ("dir", b(1), 2)
            if mode == "idx": return ("idx", b(1), 2)
            return ("ext", (b(1) << 8) | b(2), 3)
        if k in (0, 1, 2, 4, 5, 6, 8, 9, 10, 11) or (k == 7 and mode != "imm"):
            m, a, ln = operand(False)
            return mk(ln, ALU[k] + bsel, m, a)
        if k == 3:
            m, a, ln = operand(True)
            return mk(ln, "subd" if hi < 12 else "addd", m, a)
        if k == 12:
            m, a, ln = operand(True)
            return mk(ln, "cpx" if hi < 12 else "ldd", m, a)
        if k == 13:
            if hi < 12:
                m, a, ln = operand(False)
                if mode == "imm":
                    raise ValueError("bad opcode")
                flow = "call"
                tgt = a if mode == "ext" else None
                return mk(ln, "jsr", m, a, flow, tgt)
            m, a, ln = operand(False)
            return mk(ln, "std", m, a)
        if k == 14:
            m, a, ln = operand(True)
            return mk(ln, "lds" if hi < 12 else "ldx", m, a)
        if k == 15 and hi >= 9:
            m, a, ln = operand(False)
            return mk(ln, "sts" if hi < 12 else "stx", m, a)
    raise ValueError("bad opcode %02X at %04X" % (op, pc))


def discover(rom, roots, base=0xF000, stop=(), hd6301=False):
    """Recursive descent from the roots; JMP indexed / unknown flow reported."""
    code, work = {}, list(roots)
    ijmps = []
    while work:
        pc = work.pop()
        while base <= pc < base + len(rom):
            if pc in code:
                break
            ins = decode(rom, pc, base, hd6301)
            code[pc] = ins
            nxt = pc + ins.length
            if ins.flow == "seq":
                pc = nxt
            elif ins.flow == "jmp":
                if ins.target is not None and ins.target not in stop:
                    work.append(ins.target)
                break
            elif ins.flow == "jcc":
                work.append(ins.target)
                pc = nxt
            elif ins.flow == "call":
                if ins.target is not None:
                    work.append(ins.target)
                else:
                    ijmps.append(pc)
                pc = nxt
            else:
                if ins.flow == "ijmp":
                    ijmps.append(pc)
                break
    return code, ijmps


if __name__ == "__main__":
    import os, sys
    from paths import EXTRACTED
    rom = open(EXTRACTED / "bublbobl" / "a78-01.17", "rb").read()
    code, ij = discover(rom, [0xF000, 0xF046, 0xF092])
    print("; %d instructions, indexed jumps/calls at %s" % (len(code), ["%04X" % p for p in ij]))
    for pc in sorted(code):
        i = code[pc]
        print("%04X  %-8s %s" % (pc, rom[pc - 0xF000:pc - 0xF000 + i.length].hex(), i.text))
