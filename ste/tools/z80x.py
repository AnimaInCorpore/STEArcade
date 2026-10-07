"""Z80 -> 68000 static translator (STE port of arcade Z80 programs).

Pipeline (same shape as F030CT's tools/smkx):
  1. discovery (discover.py): reachable instructions from entries/dispatch seeds
  2. flag liveness over the instruction graph
  3. emission: one 68000 snippet per Z80 instruction, labelled Z<pc>

Machine conventions of the generated code
-----------------------------------------
  d0.b  A                      a0..a2  BC' DE' HL'  (exx = exg)
  d1.w  BC                     a3.b    A'            (ex af,af' = exg d0,a3)
  d2.w  DE                     a4      dispatch table (Z80 pc*4 -> 68k address)
  d3.w  HL                     a5      Z80 SP, a real pointer into the block
  d4.w  IX                     a6      Z80 memory block (32 KiB, base of $0000)
  d5    scratch 2              a7      native stack (interrupt/runtime only)
  d6.w  Z80 flags image: 68k CCR bits N=S(8) Z(4) C(1); bit5 = H, bit6 = N
        (V/PV, X, Y are not tracked)
  d7    scratch 1
  IY and F' live in the block at IYADDR / FSHADOW (little used)

The Z80 flags live in d6 between instructions, never in the 68k CCR, so an
instruction that doesn't touch flags may clobber the CCR freely.  A flag
producing instruction leaves its result in the CCR and stores it into d6 only
where the liveness pass says somebody reads it (`FLAGS` marker).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from z80dis import decode

# tracked flags
S, Z, C, H, N = 1, 2, 4, 8, 16
ALLF = S | Z | C | H | N
CCRF = S | Z | C
CCRBIT = {S: 0x08, Z: 0x04, C: 0x01}           # 68k CCR bit for a Z80 flag
D6BIT = {H: 5, N: 6}

IYADDR = 0x7FF0
FSHADOW = 0x7FF2
IO_READ_REDIRECT = {0x7C00: 0x7E00, 0x7C80: 0x7E80, 0x7D00: 0x7F00, 0x7D80: 0x7F80}
NMI_TOKEN = 0x4001
TABLE_ENTRIES = 0x4002

CC_NAMES = ["nz", "z", "nc", "c", "po", "pe", "p", "m"]
CC_68K = {"nz": "ne", "z": "eq", "nc": "cc", "c": "cs", "p": "pl", "m": "mi"}
CC_68K_INV = {"nz": "eq", "z": "ne", "nc": "cs", "c": "cc", "p": "mi", "m": "pl"}
CC_USES = {"nz": Z, "z": Z, "nc": C, "c": C, "p": S, "m": S}


class Unsupported(Exception):
    pass


# --------------------------------------------------------------------------
# flag effects per instruction
# --------------------------------------------------------------------------

def uses_defs(ins):
    """(uses, defs) over the tracked flags S Z C H N."""
    mn = ins.mn
    ops = ins.ops
    if mn in ("add", "adc", "sbc", "sub", "cp"):
        if ops and ops[0] == ("r16", "hl") or (ops and ops[0][0] == "r16"):
            if mn == "add":
                return 0, C | H | N
            return (C if mn in ("adc", "sbc") else 0), ALLF
        return (C if mn in ("adc", "sbc") else 0), ALLF
    if mn == "neg":
        return 0, ALLF
    if mn in ("and", "or", "xor"):
        return 0, ALLF
    if mn in ("inc", "dec"):
        if ops[0][0] == "r16":
            return 0, 0
        return 0, S | Z | H | N
    if mn in ("rlca", "rrca"):
        return 0, C | H | N
    if mn in ("rla", "rra"):
        return C, C | H | N
    if mn in ("rlc", "rrc", "sla", "sra", "sll", "srl"):
        return 0, ALLF
    if mn in ("rl", "rr"):
        return C, ALLF
    if mn == "bit":
        return 0, Z | H | N          # S after BIT is not modelled
    if mn == "cpl":
        return 0, H | N
    if mn == "scf":
        return 0, C | H | N
    if mn == "ccf":
        return C, C | H | N
    if mn == "daa":
        return C | H | N, S | Z | C | H
    if mn in ("jr", "jp", "call", "ret") and ops and ops[0][0] == "cc":
        return CC_USES.get(ops[0][1], 0), 0
    if mn == "push" and ops[0] == ("r16", "af"):
        return CCRF, 0
    if mn == "pop" and ops[0] == ("r16", "af"):
        return 0, ALLF          # H and N come back as 0 (the stack image keeps S Z C only)
    if mn == "ex af,af'":
        return CCRF, CCRF
    if mn in ("cpir", "cpi", "cpd", "cpdr"):
        return 0, S | Z | H | N
    if mn in ("ldir", "ldi", "ldd", "lddr"):
        return 0, H | N
    return 0, 0


def flow_uses(ins):
    """Extra liveness 'uses' at control-flow boundaries (flags a callee/caller may read)."""
    if ins.flow in ("call", "ccall", "ret", "cret", "rst"):
        return CCRF
    return 0


def compute_liveness(code, extra_succ=None):
    """live_in / live_out per pc (bitmask of tracked flags)."""
    succs = {}
    for pc, ins in code.items():
        nxt = pc + ins.length
        fl = ins.flow
        s = []
        if fl == "seq":
            s = [nxt]
        elif fl == "jmp":
            s = [ins.target]
        elif fl == "jcc":
            s = [ins.target, nxt]
        elif fl in ("call", "ccall", "rst"):
            s = [nxt] if not (fl == "rst" and ins.target == 0x28) else []
        elif fl == "cret":
            s = [nxt]
        succs[pc] = [x for x in s if x in code]
    uses = {}
    defs = {}
    for pc, ins in code.items():
        u, d = uses_defs(ins)
        uses[pc] = u | flow_uses(ins)
        defs[pc] = d
    live_in = {pc: 0 for pc in code}
    live_out = {pc: 0 for pc in code}
    order = sorted(code, reverse=True)
    changed = True
    while changed:
        changed = False
        for pc in order:
            lo = 0
            for s in succs[pc]:
                lo |= live_in[s]
            ins = code[pc]
            if ins.flow in ("call", "ccall", "rst"):
                lo &= ~(H | N)           # H/N are not preserved across calls
            li = uses[pc] | (lo & ~defs[pc])
            if li != live_in[pc] or lo != live_out[pc]:
                live_in[pc] = li
                live_out[pc] = lo
                changed = True
    return live_in, live_out


# --------------------------------------------------------------------------
# emitter
# --------------------------------------------------------------------------

REG16 = {"bc": "d1", "de": "d2", "hl": "d3", "ix": "d4"}
HALF = {"b": ("d1", True), "c": ("d1", False), "d": ("d2", True), "e": ("d2", False),
        "h": ("d3", True), "l": ("d3", False)}


def hx(v, w=4):
    return "$%0*X" % (w, v & ((1 << (4 * w)) - 1))


class Emitter:
    def __init__(self, code, live_in=None, live_out=None, leaders=None):
        self.code = code
        if live_in is None:
            live_in, live_out = compute_liveness(code)
        self.live_in = live_in
        self.live_out = live_out
        self.leaders = leaders if leaders is not None else set()
        self.lines = []
        self.uid = 0
        self.refs = set()
        self.unsupported = []
        self.lo = 0          # live-out of the instruction being emitted
        self.cur = None
        self.hooks = set()   # test builds: pcs that first call z80_hook (d7 = pc)

    # ---- small helpers -------------------------------------------------
    def new_label(self):
        self.uid += 1
        return "Lx%d" % self.uid

    def e(self, s):
        self.lines.append("\t" + s)

    def label_of(self, pc):
        self.refs.add(pc)
        return "Z%04X" % pc

    def mem(self, addr, off=0, io_read=False):
        a = (addr + off) & 0xFFFF
        if io_read and addr in IO_READ_REDIRECT:
            a = IO_READ_REDIRECT[addr]
        if a >= 0x8000:
            raise Unsupported("address %04X outside the 32 KiB block" % a)
        return "%s(a6)" % hx(a)

    # operand access --------------------------------------------------------
    def read8(self, op, io_read=True):
        """-> (pre_lines, ea) with ea usable as a byte source operand."""
        k = op[0]
        if k == "r8":
            n = op[1]
            if n == "a":
                return [], "d0"
            if n in HALF:
                reg, hi = HALF[n]
                if hi:
                    return ["move.w %s,d7" % reg, "lsr.w #8,d7"], "d7"
                return [], reg
            raise Unsupported("8-bit register %s" % n)
        if k == "imm":
            return [], "#%s" % hx(op[1], 2)
        if k == "ind":
            b, d = op[1], op[2]
            if b == "hl":
                return [], "(a6,d3.w)"
            if b == "de":
                return [], "(a6,d2.w)"
            if b == "bc":
                return [], "(a6,d1.w)"
            if b == "ix":
                return [], "%d(a6,d4.w)" % d
            if b == "iy":
                return ["move.w %s(a6),d5" % hx(IYADDR)], "%d(a6,d5.w)" % d
            raise Unsupported("indirect %s" % b)
        if k == "ind16":
            return [], self.mem(op[1], 0, io_read)
        raise Unsupported("operand %r" % (op,))

    def write8(self, op, src_ea):
        """store byte `src_ea` (Dn / #imm) into op; may use d7."""
        k = op[0]
        out = []
        if k == "r8":
            n = op[1]
            if n == "a":
                return ["move.b %s,d0" % src_ea]
            reg, hi = HALF[n]
            if not hi:
                return ["move.b %s,%s" % (src_ea, reg)]
            if src_ea.startswith("#"):
                v = int(src_ea[1:].replace("$", "0x"), 16) & 0xFF
                return ["andi.w #$00FF,%s" % reg, "ori.w #%s,%s" % (hx(v << 8), reg)]
            if src_ea != "d7":
                out.append("move.b %s,d7" % src_ea)
            out += ["lsl.w #8,d7", "andi.w #$00FF,%s" % reg, "or.w d7,%s" % reg]
            return out
        pre, ea = self.read8(op, io_read=False)
        return pre + ["move.b %s,%s" % (src_ea, ea)]

    # flag marker ------------------------------------------------------------
    def flags(self, provided, const_set=0, const_clear=0, hcomp=None):
        """Store CCR-provided flags (subset of S|Z|C) into d6 where live.

        const_set/const_clear: H/N constants (flags in H|N).  hcomp: callable that
        emits the H computation (called after the CCR was stored) or None.
        """
        lo = self.lo
        need = provided & lo
        keep = lo & ~need
        if need:
            m = 0
            for f in (S, Z, C):
                if need & f:
                    m |= CCRBIT[f]
            # H/N bits that stay must survive; also flags we don't define but are live
            passthru = lo & ~need
            # constants set below also count as defined
            passthru &= ~(const_set | const_clear)
            if hcomp is not None:
                passthru &= ~H
            if passthru == 0:
                self.e("move sr,d6")
            else:
                self.e("move sr,d7")
                self.e("eor.b d6,d7")
                self.e("and.b #%s,d7" % hx(m, 2))
                self.e("eor.b d7,d6")
        for f in (H, N):
            if const_set & f and lo & f:
                self.e("ori.b #%s,d6" % hx(1 << D6BIT[f], 2))
            if const_clear & f and lo & f:
                self.e("andi.b #%s,d6" % hx(0xFF ^ (1 << D6BIT[f]), 2))
        if hcomp is not None and lo & H:
            hcomp()

    def ctoc(self, setz=False):
        """Load the CCR with X=C=Z80 carry (and Z set if setz) from d6."""
        l = self.new_label()
        self.e("moveq #%d,d7" % (4 if setz else 0))
        self.e("btst #0,d6")
        self.e("beq.s %s" % l)
        self.e("moveq #%d,d7" % (0x15 if setz else 0x11))
        self.lines.append(l + ":")
        self.e("move d7,ccr")

    def load_cc(self, cc):
        self.e("move d6,ccr")

    # ---- instruction dispatch --------------------------------------------
    def emit_all(self, order=None):
        pcs = sorted(self.code) if order is None else order
        for i, pc in enumerate(pcs):
            self.emit_ins(pc)
            ins = self.code[pc]
            if ins.flow in ("seq", "jcc", "ccall", "cret"):
                nxt = pc + ins.length
                follow = pcs[i + 1] if i + 1 < len(pcs) else None
                if follow != nxt and not (self.lines and self.lines[-1].strip().startswith("jmp z80_unsupported")):
                    self.jmp_to(nxt)

    def emit_ins(self, pc, live_out_override=None, with_label=True):
        ins = self.code[pc]
        self.cur = ins
        self.lo = self.live_out[pc] if live_out_override is None else live_out_override
        if with_label:
            self.lines.append("Z%04X:\t\t; %s" % (pc, ins.text))
            if pc in self.hooks:
                self.e("move.w #%s,d7" % hx(pc))
                self.e("jmp z80_hook")
                self.lines.append("Z%04X_r:" % pc)
        start = len(self.lines)
        try:
            fn = getattr(self, "x_" + ins.mn.replace(" ", "_").replace(",", "_").replace("'", "p"), None)
            if fn is None:
                raise Unsupported("mnemonic %s" % ins.mn)
            fn(ins)
        except Unsupported as ex:
            del self.lines[start:]
            self.unsupported.append((pc, ins.text, str(ex)))
            self.e("move.w #%s,d7" % hx(pc))
            self.e("jmp z80_unsupported")
            return

    # ---- simple instructions ------------------------------------------------
    def x_nop(self, ins):
        pass

    def x_di(self, ins):
        pass

    def x_ei(self, ins):
        pass

    def x_im(self, ins):
        pass

    def x_halt(self, ins):
        raise Unsupported("halt")

    # ---- loads ------------------------------------------------------------
    def x_ld(self, ins):
        dst, src = ins.ops
        kd, ks = dst[0], src[0]
        bytek = ("r8", "ind", "ind16")
        if kd in bytek and ks in ("r8", "imm", "ind", "ind16"):
            if kd == "ind" and dst[1] == "sp":
                raise Unsupported("ld (sp)")
            if dst == ("r8", "a") and ks == "imm":
                v = src[1]
                if v < 128:
                    self.e("moveq #%d,d0" % v)
                else:
                    self.e("move.b #%s,d0" % hx(v, 2))
                return
            pre, sea = self.read8(src)
            for l in pre:
                self.e(l)
            for l in self.write8(dst, sea):
                self.e(l)
            return
        if kd == "r16" and ks == "imm":
            self.set16(dst[1], src[1])
            return
        if kd == "r16" and ks == "ind16":
            self.load16(dst[1], src[1])
            return
        if kd == "ind16" and ks == "r16":
            self.store16(src[1], dst[1])
            return
        if kd == "r16" and dst[1] == "sp" and ks == "r16":
            self.e("lea (a6,%s.w),a5" % self.reg16(src[1], 7))
            return
        raise Unsupported("ld %r,%r" % (dst, src))

    def reg16(self, name, scratch):
        """data register holding a 16-bit register (loading IY into d<scratch> if needed)."""
        if name in REG16:
            return REG16[name]
        if name == "iy":
            self.e("move.w %s(a6),d%d" % (hx(IYADDR), scratch))
            return "d%d" % scratch
        raise Unsupported("reg16 %s" % name)

    def set16(self, name, v):
        v &= 0xFFFF
        if name in REG16:
            r = REG16[name]
            if v < 128:
                self.e("moveq #%d,%s" % (v, r))
            else:
                self.e("move.w #%s,%s" % (hx(v), r))
        elif name == "sp":
            if v >= 0x8000:
                raise Unsupported("sp outside block")
            self.e("lea %s(a6),a5" % hx(v))
        elif name == "iy":
            self.e("move.w #%s,%s(a6)" % (hx(v), hx(IYADDR)))
        else:
            raise Unsupported("ld %s,imm" % name)

    def load16(self, name, addr):
        lo = self.mem(addr)
        hi = self.mem(addr, 1)
        if name in REG16:
            r = REG16[name]
            self.e("move.b %s,%s" % (hi, r))
            self.e("lsl.w #8,%s" % r)
            self.e("move.b %s,%s" % (lo, r))
        elif name == "sp":
            self.e("move.b %s,d7" % hi)
            self.e("lsl.w #8,d7")
            self.e("move.b %s,d7" % lo)
            self.e("lea (a6,d7.w),a5")
        elif name == "iy":
            self.e("move.b %s,d7" % hi)
            self.e("lsl.w #8,d7")
            self.e("move.b %s,d7" % lo)
            self.e("move.w d7,%s(a6)" % hx(IYADDR))
        else:
            raise Unsupported("ld %s,(nn)" % name)

    def store16(self, name, addr):
        lo = self.mem(addr)
        hi = self.mem(addr, 1)
        if name == "sp":
            self.e("move.l a5,d7")
            self.e("sub.l a6,d7")
            r = "d7"
        else:
            r = self.reg16(name, 7)
        self.e("move.b %s,%s" % (r, lo))
        if r != "d7":
            self.e("move.w %s,d7" % r)
        self.e("lsr.w #8,d7")
        self.e("move.b d7,%s" % hi)

    # ---- inc/dec ----------------------------------------------------------
    def x_inc(self, ins):
        self._incdec(ins, "addq")

    def x_dec(self, ins):
        self._incdec(ins, "subq")

    def _incdec(self, ins, op):
        (dst,) = ins.ops
        isinc = op == "addq"
        if dst[0] == "r16":
            n = dst[1]
            if n in REG16:
                self.e("%s.w #1,%s" % (op, REG16[n]))
            elif n == "sp":
                self.e("%s.l #1,a5" % op)
            elif n == "iy":
                self.e("%s.w #1,%s(a6)" % (op, hx(IYADDR)))
            else:
                raise Unsupported("inc %s" % n)
            return
        # 8-bit: flags S Z (H N) ; C preserved
        post = []
        if dst[0] == "r8":
            n = dst[1]
            if n == "a":
                ea = "d0"
            elif n in HALF:
                reg, hi = HALF[n]
                if hi:
                    self.e("ror.w #8,%s" % reg)
                    post = ["ror.w #8,%s" % reg]
                ea = reg
            else:
                raise Unsupported(n)
        else:
            pre, ea = self.read8(dst, io_read=False)
            for l in pre:
                self.e(l)
        if self.lo & H:
            raise Unsupported("H flag after inc/dec")
        self.e("%s.b #1,%s" % (op, ea))
        self.flags(S | Z, const_set=0 if isinc else N, const_clear=N if isinc else 0)
        for l in post:
            self.e(l)

    # ---- 8-bit ALU --------------------------------------------------------
    def _alu_src(self, ins):
        dst, src = ins.ops
        if dst != ("r8", "a"):
            raise Unsupported("alu dst %r" % (dst,))
        return self.read8(src)

    def _hpre(self, src, isub, withcarry):
        """Before the ALU op: push H (bit 4 of a nibble sum/difference) on the stack."""
        pre, ea = self.read8(src)
        for l in pre:
            self.e(l)
        if ea == "d7":
            self.e("move.b d7,d5")
        else:
            self.e("move.b %s,d5" % ea)
        self.e("move.b d0,d7")
        self.e("andi.b #$0F,d7")
        self.e("andi.b #$0F,d5")
        self.e("%s.b d5,d7" % ("sub" if isub else "add"))
        if withcarry:
            l = self.new_label()
            self.e("btst #0,d6")
            self.e("beq.s %s" % l)
            self.e("%s.b #1,d7" % ("subq" if isub else "addq"))
            self.lines.append(l + ":")
        self.e("move.b d7,-(a7)")

    def _hpost(self):
        l1 = self.new_label()
        self.e("move.b (a7)+,d7")
        self.e("bclr #5,d6")
        self.e("btst #4,d7")
        self.e("beq.s %s" % l1)
        self.e("bset #5,d6")
        self.lines.append(l1 + ":")

    def _simple_alu(self, ins, op, hknown=None, nconst=0, isub=False, store=True):
        pre, ea = self._alu_src(ins)
        hc = None
        if op in ("add", "sub", "cmp") and self.lo & H:
            self._hpre(ins.ops[1], isub, False)
            hc = self._hpost
        for l in pre:
            self.e(l)
        self.e("%s.b %s,d0" % (op, ea))
        self.flags(S | Z | C, const_set=(N if nconst else 0), const_clear=(0 if nconst else N), hcomp=hc)

    def x_add(self, ins):
        if ins.ops[0][0] == "r16":
            return self._add16(ins)
        self._simple_alu(ins, "add")

    def x_sub(self, ins):
        self._simple_alu(ins, "sub", nconst=1, isub=True)

    def x_cp(self, ins):
        self._simple_alu(ins, "cmp", nconst=1, isub=True)

    def x_and(self, ins):
        pre, ea = self._alu_src(ins)
        for l in pre:
            self.e(l)
        self.e("and.b %s,d0" % ea)
        self.flags(S | Z | C, const_set=H, const_clear=N)

    def x_or(self, ins):
        pre, ea = self._alu_src(ins)
        for l in pre:
            self.e(l)
        self.e("or.b %s,d0" % ea)
        self.flags(S | Z | C, const_clear=H | N)

    def x_xor(self, ins):
        pre, ea = self._alu_src(ins)
        for l in pre:
            self.e(l)
        if ea.startswith("#"):
            self.e("eori.b %s,d0" % ea)
        elif len(ea) == 2 and ea[0] == "d":
            self.e("eor.b %s,d0" % ea)
        else:
            self.e("move.b %s,d7" % ea)
            self.e("eor.b d7,d0")
        self.flags(S | Z | C, const_clear=H | N)

    def _adcsbc(self, ins, op, isub):
        dst, src = ins.ops
        if dst[0] == "r16":                       # adc/sbc hl,rr
            if self.lo & H:
                raise Unsupported("H after %s hl,rr" % op)
            sn = src[1]
            if sn == "sp":
                self.e("move.l a5,d5")
                self.e("sub.l a6,d5")
                sreg = "d5"
            elif sn in REG16:
                sreg = REG16[sn]
            else:
                raise Unsupported("%s hl,%s" % (op, sn))
            self.ctoc(setz=True)
            self.e("%s.w %s,d3" % ("subx" if isub else "addx", sreg))
            self.flags(S | Z | C, const_set=(N if isub else 0), const_clear=(0 if isub else N))
            return
        pre, ea = self.read8(src)
        hc = None
        if self.lo & H:
            self._hpre(src, isub, True)
            hc = self._hpost
        for l in pre:
            self.e(l)
        if not (len(ea) == 2 and ea[0] == "d") or ea == "d7":
            self.e("move.b %s,d5" % ea)
            ea = "d5"
        self.ctoc(setz=True)
        self.e("%s.b %s,d0" % ("subx" if isub else "addx", ea))
        self.flags(S | Z | C, const_set=(N if isub else 0), const_clear=(0 if isub else N), hcomp=hc)

    def x_adc(self, ins):
        self._adcsbc(ins, "adc", False)

    def x_sbc(self, ins):
        self._adcsbc(ins, "sbc", True)

    def x_neg(self, ins):
        if self.lo & H:
            raise Unsupported("H after neg")
        self.e("neg.b d0")
        self.flags(S | Z | C, const_set=N)

    def x_cpl(self, ins):
        self.e("not.b d0")
        self.flags(0, const_set=H | N)

    def x_scf(self, ins):
        if self.lo & C:
            self.e("ori.b #1,d6")
        self.flags(0, const_clear=H | N)

    def x_ccf(self, ins):
        if self.lo & C:
            self.e("eori.b #1,d6")
        self.flags(0, const_clear=H | N)

    def x_daa(self, ins):
        self.e("jsr z80_daa")

    # ---- 16-bit add -----------------------------------------------------------
    def _add16(self, ins):
        dst, src = ins.ops
        dn = dst[1]
        sn = src[1]
        if self.lo & H:
            raise Unsupported("H after add16")
        if sn == "sp":
            self.e("move.l a5,d5")
            self.e("sub.l a6,d5")
            sreg = "d5"
        elif sn == "iy":
            self.e("move.w %s(a6),d5" % hx(IYADDR))
            sreg = "d5"
        else:
            sreg = REG16[sn]
        if dn == "iy":
            if sreg == "d5":
                raise Unsupported("add iy,sp/iy")
            self.e("move.w %s(a6),d5" % hx(IYADDR))
            self.e("add.w %s,d5" % sreg)
            self.flags(C, const_clear=N)
            self.e("move.w d5,%s(a6)" % hx(IYADDR))
            return
        self.e("add.w %s,%s" % (sreg, REG16[dn]))
        self.flags(C, const_clear=N)

    # ---- rotates/shifts -------------------------------------------------------
    def x_rlca(self, ins):
        self.e("rol.b #1,d0")
        self.flags(C, const_clear=H | N)

    def x_rrca(self, ins):
        self.e("ror.b #1,d0")
        self.flags(C, const_clear=H | N)

    def x_rla(self, ins):
        self.ctoc()
        self.e("roxl.b #1,d0")
        self.flags(C, const_clear=H | N)

    def x_rra(self, ins):
        self.ctoc()
        self.e("roxr.b #1,d0")
        self.flags(C, const_clear=H | N)

    def _rotate(self, ins, op, usex):
        (dst,) = ins.ops[:1]
        if len(ins.ops) > 1:
            raise Unsupported("undocumented rotate copy")
        post = []
        store = None
        if dst[0] == "r8":
            n = dst[1]
            if n == "a":
                ea = "d0"
            else:
                reg, hi = HALF[n]
                if hi:
                    self.e("ror.w #8,%s" % reg)
                    post = ["ror.w #8,%s" % reg]
                ea = reg
        else:
            if dst[0] == "ind" and dst[1] == "iy":
                raise Unsupported("rotate (iy+d)")
            pre, mea = self.read8(dst, io_read=False)
            for l in pre:
                self.e(l)
            self.e("move.b %s,d5" % mea)
            ea = "d5"
            store = "move.b d5,%s" % mea
        if usex:
            self.ctoc()
        self.e("%s.b #1,%s" % (op, ea))
        self.flags(S | Z | C, const_clear=H | N)
        if store:
            self.e(store)
        for l in post:
            self.e(l)

    def x_rlc(self, ins): self._rotate(ins, "rol", False)
    def x_rrc(self, ins): self._rotate(ins, "ror", False)
    def x_rl(self, ins): self._rotate(ins, "roxl", True)
    def x_rr(self, ins): self._rotate(ins, "roxr", True)
    def x_sla(self, ins): self._rotate(ins, "lsl", False)
    def x_sra(self, ins): self._rotate(ins, "asr", False)
    def x_srl(self, ins): self._rotate(ins, "lsr", False)

    # ---- bit ops ------------------------------------------------------------------
    def _bitea(self, tgt, bit):
        """(ea, bit) for btst/bset/bclr on a register or memory byte."""
        if tgt[0] == "r8":
            n = tgt[1]
            if n == "a":
                return "d0", bit, []
            reg, hi = HALF[n]
            return reg, (bit + 8 if hi else bit), []
        pre, ea = self.read8(tgt, io_read=False)
        return ea, bit, pre

    def x_bit(self, ins):
        bit = ins.ops[0][1]
        ea, b, pre = self._bitea(ins.ops[1], bit)
        for l in pre:
            self.e(l)
        self.e("btst #%d,%s" % (b, ea))
        self.flags(Z, const_set=H, const_clear=N)

    def x_res(self, ins):
        if len(ins.ops) > 2:
            raise Unsupported("res with copy")
        bit = ins.ops[0][1]
        ea, b, pre = self._bitea(ins.ops[1], bit)
        for l in pre:
            self.e(l)
        self.e("bclr #%d,%s" % (b, ea))

    def x_set(self, ins):
        if len(ins.ops) > 2:
            raise Unsupported("set with copy")
        bit = ins.ops[0][1]
        ea, b, pre = self._bitea(ins.ops[1], bit)
        for l in pre:
            self.e(l)
        self.e("bset #%d,%s" % (b, ea))

    # ---- stack ------------------------------------------------------------------------
    def x_push(self, ins):
        n = ins.ops[0][1]
        if n == "af":
            self.e("move.b d6,d7")
            self.e("andi.b #$0C,d7")
            self.e("lsl.b #4,d7")
            self.e("move.b d6,d5")
            self.e("andi.b #1,d5")
            self.e("or.b d5,d7")
            self.e("move.b d0,-(a5)")
            self.e("move.b d7,-(a5)")
            return
        r = self.reg16(n, 5)
        self.e("move.w %s,d7" % r)
        self.e("lsr.w #8,d7")
        self.e("move.b d7,-(a5)")
        self.e("move.b %s,-(a5)" % r)

    def x_pop(self, ins):
        n = ins.ops[0][1]
        if n == "af":
            self.e("move.b (a5)+,d7")
            self.e("move.b (a5)+,d0")
            self.e("move.b d7,d6")
            self.e("lsr.b #4,d6")
            self.e("andi.b #$0C,d6")
            self.e("andi.b #1,d7")
            self.e("or.b d7,d6")
            return
        r = "d5" if n == "iy" else REG16[n]
        self.e("move.b (a5)+,d7")
        self.e("move.b (a5)+,%s" % r)
        self.e("lsl.w #8,%s" % r)
        self.e("move.b d7,%s" % r)
        if n == "iy":
            self.e("move.w d5,%s(a6)" % hx(IYADDR))

    def x_ex(self, ins):
        a, b = ins.ops
        if a == ("r16", "de") and b == ("r16", "hl"):
            self.e("exg d2,d3")
            return
        raise Unsupported("ex")

    def x_ex_af_afp(self, ins):
        self.e("exg d0,a3")
        self.e("move.w d6,d7")
        self.e("move.w %s(a6),d6" % hx(FSHADOW))
        self.e("move.w d7,%s(a6)" % hx(FSHADOW))

    def x_exx(self, ins):
        self.e("exg d1,a0")
        self.e("exg d2,a1")
        self.e("exg d3,a2")

    # ---- block ops --------------------------------------------------------------------------
    def x_ldir(self, ins):
        l = self.new_label()
        self.lines.append(l + ":")
        self.e("move.b (a6,d3.w),(a6,d2.w)")
        self.e("addq.w #1,d3")
        self.e("addq.w #1,d2")
        self.e("subq.w #1,d1")
        self.e("bne.s %s" % l)
        self.flags(0, const_clear=H | N)

    def x_cpir(self, ins):
        loop = self.new_label()
        end = self.new_label()
        self.lines.append(loop + ":")
        self.e("cmp.b (a6,d3.w),d0")
        self.e("move sr,d7")
        self.e("addq.w #1,d3")
        self.e("subq.w #1,d1")
        self.e("beq.s %s" % end)
        self.e("btst #2,d7")
        self.e("beq.s %s" % loop)
        self.lines.append(end + ":")
        # flags of the last comparison are in d7 (CCR format); C is unchanged
        lo = self.lo
        if lo & (S | Z):
            m = (0x08 if lo & S else 0) | (0x04 if lo & Z else 0)
            self.e("eor.b d6,d7")
            self.e("and.b #%s,d7" % hx(m, 2))
            self.e("eor.b d7,d6")
        if lo & H:
            raise Unsupported("H after cpir")
        if lo & N:
            self.e("ori.b #$40,d6")

    # ---- control flow -----------------------------------------------------------------------------
    def jmp_to(self, pc):
        self.e("jmp %s" % self.label_of(pc))

    def push_ret(self, pc):
        self.e("move.b #%s,-(a5)" % hx((pc >> 8) & 0xFF, 2))
        self.e("move.b #%s,-(a5)" % hx(pc & 0xFF, 2))

    def dispatch_ret(self):
        self.e("moveq #0,d7")
        self.e("move.b 1(a5),d7")
        self.e("lsl.w #8,d7")
        self.e("move.b (a5),d7")
        self.e("addq.l #2,a5")
        self.dispatch_d7()

    def dispatch_d7(self):
        self.e("cmp.l #%d,d7" % TABLE_ENTRIES)
        self.e("bhs z80_badjump")
        self.e("lsl.l #2,d7")
        self.e("move.l 0(a4,d7.l),-(a7)")
        self.e("rts")

    def x_jp(self, ins):
        ops = ins.ops
        if ops[0][0] == "ind":              # jp (hl)/(ix)/(iy)
            r = ops[0][1]
            self.e("moveq #0,d7")
            self.e("move.w %s,d7" % self.reg16(r, 5))
            self.dispatch_d7()
            return
        if ops[0][0] == "addr":
            self.jmp_to(ops[0][1])
            return
        cc, tgt = ops[0][1], ops[1][1]
        if cc not in CC_68K:
            raise Unsupported("jp %s" % cc)
        self.e("move d6,ccr")
        self.e("b%s %s" % (CC_68K[cc], self.label_of(tgt)))

    def x_jr(self, ins):
        ops = ins.ops
        if ops[0][0] == "addr":
            self.jmp_to(ops[0][1])
            return
        cc, tgt = ops[0][1], ops[1][1]
        self.e("move d6,ccr")
        self.e("b%s %s" % (CC_68K[cc], self.label_of(tgt)))

    def x_djnz(self, ins):
        tgt = ins.ops[0][1]
        self.e("sub.w #$0100,d1")
        self.e("move.w d1,d7")
        self.e("lsr.w #8,d7")
        self.e("bne %s" % self.label_of(tgt))

    def x_call(self, ins):
        ops = ins.ops
        nxt = ins.pc + ins.length
        if ops[0][0] == "addr":
            self.push_ret(nxt)
            self.jmp_to(ops[0][1])
            return
        cc, tgt = ops[0][1], ops[1][1]
        skip = self.new_label()
        self.e("move d6,ccr")
        self.e("b%s %s" % (CC_68K_INV[cc], skip))
        self.push_ret(nxt)
        self.jmp_to(tgt)
        self.lines.append(skip + ":")

    def x_ret(self, ins):
        ops = ins.ops
        if ops:
            cc = ops[0][1]
            skip = self.new_label()
            self.e("move d6,ccr")
            self.e("b%s %s" % (CC_68K_INV[cc], skip))
            self.dispatch_ret()
            self.lines.append(skip + ":")
            return
        self.dispatch_ret()

    def x_retn(self, ins):
        self.dispatch_ret()

    x_reti = x_retn

    def x_rst(self, ins):
        self.push_ret(ins.pc + ins.length)
        self.jmp_to(ins.ops[0][1])
