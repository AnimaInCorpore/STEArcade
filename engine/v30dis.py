"""NEC V30 disassembler: MAME's necdasm text (the debugger's trace format), native mode.

    decode(rd, pc) -> Ins(text, length, op, flow)   rd(addr20) -> byte, pc the linear address (as MAME's trace shows it)

The tables are necdasm.cpp's (mnemonic|flags|params).  The FPU escapes D8-DF are shown as "escape" (MAME decodes
8087 forms; the V30 has no FPU interface in the M72).  flow: seq, jmp, jcc, call, ret, ijmp, icall, int, iret, halt.
"""
from collections import namedtuple

Ins = namedtuple("Ins", "text length op flow")


def _t(s):
    out = []
    for e in s.strip().replace("\n", "\t").split("\t"):
        mn, fl, ps = e.split("|")
        out.append((mn, fl or None, tuple(p for p in ps.split(",") if p)))
    return out


T1 = _t("""
add|MODRM|RM8,REG8	add|MODRM|RM16,REG16	add|MODRM|REG8,RM8	add|MODRM|REG16,RM16
add||AL,UI8	add||AW,IMM	push    ds1||	pop     ds1||
or|MODRM|RM8,REG8	or|MODRM|RM16,REG16	or|MODRM|REG8,RM8	or|MODRM|REG16,RM16
or||AL,UI8	or||AW,IMM	push    ps||	two_byte|TWO_BYTE|
addc|MODRM|RM8,REG8	addc|MODRM|RM16,REG16	addc|MODRM|REG8,RM8	addc|MODRM|REG16,RM16
addc||AL,UI8	addc||AW,IMM	push    ss||	pop     ss||
subc|MODRM|RM8,REG8	subc|MODRM|RM16,REG16	subc|MODRM|REG8,RM8	subc|MODRM|REG16,RM16
subc||AL,UI8	subc||AW,IMM	push    ds0||	pop     ds0||
and|MODRM|RM8,REG8	and|MODRM|RM16,REG16	and|MODRM|REG8,RM8	and|MODRM|REG16,RM16
and||AL,UI8	and||AW,IMM	ds1:|SEG_DS1|	adj4a||
sub|MODRM|RM8,REG8	sub|MODRM|RM16,REG16	sub|MODRM|REG8,RM8	sub|MODRM|REG16,RM16
sub||AL,UI8	sub||AW,IMM	ps:|SEG_PS|	adj4s||
xor|MODRM|RM8,REG8	xor|MODRM|RM16,REG16	xor|MODRM|REG8,RM8	xor|MODRM|REG16,RM16
xor||AL,UI8	xor||AW,IMM	ss:|SEG_SS|	adjba||
cmp|MODRM|RM8,REG8	cmp|MODRM|RM16,REG16	cmp|MODRM|REG8,RM8	cmp|MODRM|REG16,RM16
cmp||AL,UI8	cmp||AW,IMM	ds0:|SEG_DS0|	adjbs||
inc||AW	inc||CW	inc||DW	inc||BW
inc||SP	inc||BP	inc||IX	inc||IY
dec||AW	dec||CW	dec||DW	dec||BW
dec||SP	dec||BP	dec||IX	dec||IY
push||AW	push||CW	push||DW	push||BW
push||SP	push||BP	push||IX	push||IY
pop||AW	pop||CW	pop||DW	pop||BW
pop||SP	pop||BP	pop||IX	pop||IY
push    r||	pop     r||	chkind|MODRM|REG16,RM16	brkn||UI8
repnc|PREFIX|	repc|PREFIX|	fpo2    0||	fpo2    1||
push||IMM	mul|MODRM|REG16,RM16,IMM	push||I8	mul|MODRM|REG16,RM16,I8
inmb||	inmw||	outmb||	outmw||
bv||REL8	bnv||REL8	bc||REL8	bnc||REL8
be||REL8	bne||REL8	bnh||REL8	bh||REL8
bn||REL8	bp||REL8	bpe||REL8	bpo||REL8
blt||REL8	bge||REL8	ble||REL8	bgt||REL8
immb|GROUP|	immw|GROUP|	immb|GROUP|	immws|GROUP|
test|MODRM|RM8,REG8	test|MODRM|RM16,REG16	xch|MODRM|REG8,RM8	xch|MODRM|REG16,RM16
mov|MODRM|RM8,REG8	mov|MODRM|RM16,REG16	mov|MODRM|REG8,RM8	mov|MODRM|REG16,RM16
mov|MODRM|RM16,SREG	ldea|MODRM|REG16,RM16	mov|MODRM|SREG,RM16	pop|MODRM|RM16
nop||	xch||AW,CW	xch||AW,DW	xch||AW,BW
xch||AW,SP	xch||AW,BP	xch||AW,IX	xch||AW,IY
cvtbw||	cvtwl||	call||ADDR	poll||
push    psw||	pop     psw||	mov     psw,ah||	mov     ah,psw||
mov||AL,MEM_OFFS	mov||AW,MEM_OFFS	mov||MEM_OFFS,AL	mov||MEM_OFFS,AW
movbkb||	movbkw||	cmpbkb||	cmpbkw||
test||AL,UI8	test||AW,IMM	stmb||	stmw||
ldmb||	ldmw||	cmpmb||	cmpmw||
mov||AL,UI8	mov||CL,UI8	mov||DL,UI8	mov||BL,UI8
mov||AH,UI8	mov||CH,UI8	mov||DH,UI8	mov||BH,UI8
mov||AW,IMM	mov||CW,IMM	mov||DW,IMM	mov||BW,IMM
mov||SP,IMM	mov||BP,IMM	mov||IX,IMM	mov||IY,IMM
shiftbi|GROUP|	shiftwi|GROUP|	ret||I16	ret||
mov     ds1,|MODRM|REG16,RM16	mov     ds0,|MODRM|REG16,RM16	mov|MODRM|RMPTR8,UI8	mov|MODRM|RMPTR16,IMM
prepare||I16,UI8	dispose||	retf||I16	retf||
brk     3||	brk||UI8	brkv||	reti||
shiftb|GROUP|	shiftw|GROUP|	shiftbv|GROUP|	shiftwv|GROUP|
cvtbd||I8	cvtdb||I8	???||	trans||
escape|FPU|	escape|FPU|	escape|FPU|	escape|FPU|
escape|FPU|	escape|FPU|	escape|FPU|	escape|FPU|
dbnzne||REL8	dbnze||REL8	dbnz||REL8	bcwz||REL8
in||AL,UI8	in||AW,UI8	out||UI8,AL	out||UI8,AW
call||REL16	br||REL16	br||ADDR	br||REL8
in||AL,DW	in||AW,DW	out||DW,AL	out||DW,AW
buslock|PREFIX|	brks||UI8	repne|PREFIX|	rep|PREFIX|
halt||	not1    cy||	group1b|GROUP|	group1w|GROUP|
clr1    cy||	set1    cy||	di||	ei||
clr1    dir||	set1    dir||	group2b|GROUP|	group2w|GROUP|
""")
T2 = _t("""
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
test1|MODRM|RMPTR8,CL	test1|MODRM|RMPTR16,CL	clr1|MODRM|RMPTR8,CL	clr1|MODRM|RMPTR16,CL
set1|MODRM|RMPTR8,CL	set1|MODRM|RMPTR16,CL	not1|MODRM|RMPTR8,CL	not1|MODRM|RMPTR16,CL
test1|MODRM|RMPTR8,I3	test1|MODRM|RMPTR16,I4	clr1|MODRM|RMPTR8,I3	clr1|MODRM|RMPTR16,I4
set1|MODRM|RMPTR8,I3	set1|MODRM|RMPTR16,I4	not1|MODRM|RMPTR8,I3	not1|MODRM|RMPTR16,I4
add4s||	???||	sub4s||	???||
???||	movspa||	cmp4s||	???||
rol4|MODRM|RMPTR8	???||	ror4|MODRM|RMPTR8	???||
???||	brkcs|MODRM|REG2_16	???||	???||
???||	ins|MODRM|REG2_8,REG8	???||	ext|MODRM|REG2_8,REG8
???||	???||	???||	???||
???||	ins|MODRM|REG2_8,I4	???||	ext|MODRM|REG2_8,I4
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	retrbi||	fint||	???||
tsksw|MODRM|REG2_16	movspb|MODRM|REG2_16	???||	???||
???||	???||	???||	???||
btclr||SFREG,I3,REL8	???||	stop||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
brkxa||UI8	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
retxa||UI8	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	???||
???||	???||	???||	brkem||UI8
""")
GROUPS = {
    'immb': _t('add||RMPTR8,UI8\tor||RMPTR8,UI8\taddc||RMPTR8,UI8\tsubc||RMPTR8,UI8\tand||RMPTR8,UI8\tsub||RMPTR8,UI8\txor||RMPTR8,UI8\tcmp||RMPTR8,UI8'),
    'immw': _t('add||RMPTR16,IMM\tor||RMPTR16,IMM\taddc||RMPTR16,IMM\tsubc||RMPTR16,IMM\tand||RMPTR16,IMM\tsub||RMPTR16,IMM\txor||RMPTR16,IMM\tcmp||RMPTR16,IMM'),
    'immws': _t('add||RMPTR16,I8\tor||RMPTR16,I8\taddc||RMPTR16,I8\tsubc||RMPTR16,I8\tand||RMPTR16,I8\tsub||RMPTR16,I8\txor||RMPTR16,I8\tcmp||RMPTR16,I8'),
    'shiftbi': _t('rol||RMPTR8,I8\tror||RMPTR8,I8\trolc||RMPTR8,I8\trorc||RMPTR8,I8\tshl||RMPTR8,I8\tshr||RMPTR8,I8\t???||RMPTR8,I8\tshra||RMPTR8,I8'),
    'shiftwi': _t('rol||RMPTR16,I8\tror||RMPTR16,I8\trolc||RMPTR16,I8\trorc||RMPTR16,I8\tshl||RMPTR16,I8\tshr||RMPTR16,I8\t???||RMPTR16,I8\tshra||RMPTR16,I8'),
    'shiftb': _t('rol||RMPTR8,1\tror||RMPTR8,1\trolc||RMPTR8,1\trorc||RMPTR8,1\tshl||RMPTR8,1\tshr||RMPTR8,1\t???||RMPTR8,1\tshra||RMPTR8,1'),
    'shiftw': _t('rol||RMPTR16,1\tror||RMPTR16,1\trolc||RMPTR16,1\trorc||RMPTR16,1\tshl||RMPTR16,1\tshr||RMPTR16,1\t???||RMPTR16,1\tshra||RMPTR16,1'),
    'shiftbv': _t('rol||RMPTR8,CL\tror||RMPTR8,CL\trolc||RMPTR8,CL\trorc||RMPTR8,CL\tshl||RMPTR8,CL\tshr||RMPTR8,CL\t???||RMPTR8,CL\tshra||RMPTR8,CL'),
    'shiftwv': _t('rol||RMPTR16,CL\tror||RMPTR16,CL\trolc||RMPTR16,CL\trorc||RMPTR16,CL\tshl||RMPTR16,CL\tshr||RMPTR16,CL\t???||RMPTR16,CL\tshra||RMPTR16,CL'),
    'group1b': _t('test||RMPTR8,UI8\t???||\tnot||RMPTR8\tneg||RMPTR8\tmulu||RMPTR8\tmul||RMPTR8\tdivu||RMPTR8\tdiv||RMPTR8'),
    'group1w': _t('test||RMPTR16,IMM\t???||\tnot||RMPTR16\tneg||RMPTR16\tmulu||RMPTR16\tmul||RMPTR16\tdivu||RMPTR16\tdiv||RMPTR16'),
    'group2b': _t('inc||RMPTR8\tdec||RMPTR8\t???||\t???||\t???||\t???||\t???||\t???||'),
    'group2w': _t('inc||RMPTR16\tdec||RMPTR16\tcall||RMPTR16\tcall    far ptr ||RM16\tbr||RMPTR16\tbr      far ptr ||RM16\tpush||RMPTR16\t???||'),
}

REG16 = ("aw", "cw", "dw", "bw", "sp", "bp", "ix", "iy")
REG8 = ("al", "cl", "dl", "bl", "ah", "ch", "dh", "bh")
SREG = ("ds1", "ps", "ss", "ds0", "???", "???", "???", "???")
EA = ("bw+ix", "bw+iy", "bp+ix", "bp+iy", "ix", "iy", "bp", "bw")
MAX_LENGTH = 8


def hexstring(v, digits=0):
    s = "%0*Xh" % (digits, v) if digits else "%Xh" % v
    return "0" + s if s[0] > "9" else s


def shexstring(v, always):
    if v < 0:
        return "-" + hexstring(-v)
    return ("+" if always else "") + hexstring(v)


class _D:
    def __init__(self, rd, pc):
        self.rd, self.base, self.pc = rd, pc, pc
        self.segment = None
        self.modrm = 0
        self.mstr = ""

    def fetch(self):
        if self.pc - self.base + 1 > MAX_LENGTH:
            return 0xFF
        v = self.rd(self.pc & 0xFFFFF)
        self.pc += 1
        return v

    def fetch16(self):
        if self.pc - self.base + 1 > MAX_LENGTH:
            return 0xFF
        v = self.rd(self.pc & 0xFFFFF) | (self.rd((self.pc + 1) & 0xFFFFF) << 8)
        self.pc += 2
        return v

    def handle_modrm(self):
        m = self.modrm = self.fetch()
        self.mstr = ""
        if m >= 0xC0:
            return
        mod, rm = m >> 6, m & 7
        s = (self.segment[:-1] + ":") if self.segment else ""
        s += "["
        if rm == 6:
            s += hexstring(self.fetch16()) if mod == 0 else "bp"
        else:
            s += EA[rm]
        if mod == 1:
            d = self.fetch()
            s += shexstring(d - 256 if d & 0x80 else d, True)
        elif mod == 2:
            d = self.fetch16()
            s += shexstring(d - 0x10000 if d & 0x8000 else d, True)
        self.mstr = s + "]"

    def param(self, p):
        m = self.modrm
        if p == "REG8":
            return REG8[(m >> 3) & 7]
        if p == "REG16":
            return REG16[(m >> 3) & 7]
        if p == "REG2_8":
            return REG8[m & 7]
        if p == "REG2_16":
            return REG16[m & 7]
        if p in ("RM8", "RMPTR8"):
            if m >= 0xC0:
                return REG8[m & 7]
            return ("byte ptr " if p == "RMPTR8" else "") + self.mstr
        if p in ("RM16", "RMPTR16"):
            if m >= 0xC0:
                return REG16[m & 7]
            return ("word ptr " if p == "RMPTR16" else "") + self.mstr
        if p == "I3":
            return "%d" % (self.fetch() & 7)
        if p == "I4":
            return "%d" % (self.fetch() & 15)
        if p == "I8":
            v = self.fetch()
            return shexstring(v - 256 if v & 0x80 else v, False)
        if p == "I16":
            v = self.fetch16()
            return shexstring(v - 0x10000 if v & 0x8000 else v, False)
        if p == "UI8":
            return hexstring(self.fetch())
        if p == "IMM":
            return hexstring(self.fetch16())
        if p == "ADDR":
            a = self.fetch16()
            s = self.fetch16()
            return "%s:%s" % (hexstring(s, 4), hexstring(a))
        if p == "REL16":
            d = self.fetch16()
            d = d - 0x10000 if d & 0x8000 else d
            return hexstring((self.pc & 0xFFFF0000) | ((self.pc + d) & 0xFFFF))
        if p == "REL8":
            d = self.fetch()
            return hexstring(self.pc + (d - 256 if d & 0x80 else d))
        if p == "MEM_OFFS":
            s = (self.segment[:-1] + ":") if self.segment else ""
            return s + "[%s]" % hexstring(self.fetch16())
        if p == "SREG":
            return SREG[(m >> 3) & 7]
        if p == "SFREG":
            return "%02X" % self.fetch()
        if p == "1":
            return "1"
        return p.lower()

    def decode(self, e, out):
        mn, fl, ps = e
        if fl == "TWO_BYTE":
            return self.decode(T2[self.fetch()], out)
        if fl and fl.startswith("SEG_"):
            self.segment = mn
            return self.decode(T1[self.fetch()], out)
        if fl == "PREFIX":
            out.append("%-8s" % mn)
            return self.decode(T1[self.fetch()], out)
        if fl == "GROUP":
            self.handle_modrm()
            return self.decode(GROUPS[mn][(self.modrm >> 3) & 7], out)
        if fl == "FPU":
            self.fetch()
            out.append("escape")
            return
        if fl == "MODRM":
            self.handle_modrm()
        out.append("%-8s" % mn)
        out.append(",".join(self.param(p) for p in ps))


JMPS = {0xE9: "jmp", 0xEA: "jmp", 0xEB: "jmp", 0xE8: "call", 0x9A: "call", 0xC2: "ret", 0xC3: "ret", 0xCA: "ret",
        0xCB: "ret", 0xCF: "iret", 0xCC: "int", 0xCD: "int", 0xCE: "int", 0xF4: "halt"}


def decode(rd, pc):
    d = _D(rd, pc)
    out = []
    op = d.fetch()
    d.decode(T1[op], out)
    text = "".join(out)
    flow = JMPS.get(op, "seq")
    if 0x70 <= op <= 0x7F or 0xE0 <= op <= 0xE3:
        flow = "jcc"
    elif op == 0xFF and (d.modrm >> 3) & 7 in (2, 3):
        flow = "icall"
    elif op == 0xFF and (d.modrm >> 3) & 7 in (4, 5):
        flow = "ijmp"
    return Ins(text, d.pc - pc, op, flow)
