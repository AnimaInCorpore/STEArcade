"""MC6801 -> 68000 static translator (the Bubble Bobble protection MCU's 4 KB program).

One snippet per 6801 instruction, labelled M<pc>.  Registers: d0 = A, d1 = B, d2 = X (word
writes only: the upper word stays 0), a5 = SP + 1 (pre-decrement pushes), a6 = the MCU's memory
block (`mcu_mem`: internal registers $00-$1F, RAM $40-$FF, ROM at $F000); d6/d7/d3 scratch.
The 6801 N Z V C live in the 68000's CCR (same bits); an instruction whose natural 68000 form
leaves a flag in a different state than the 6801 does gets a wrapper that keeps the flag, if the
flag is live (backward analysis over the code).  JSR/RTS use the native stack, RTI is RTS (the
runtime calls the IRQ handler), `sei`/`cli` are no-ops (the runtime delivers the interrupt).

I/O: the registers are plain memory except P1 and P3 reads (hooks mcu_rd_p1 / mcu_rd_p3 return
the value in d7) and P1 / P2 writes (mcu_wr_p1 / mcu_wr_p2 take it in d7): P2 is the clocked
bus to the main CPU's shared RAM and the DIP switch / input ports.  Hooks keep d0-d3, a0-a6.

Patches: `skip` maps a pc to the pc execution continues at (busy-wait loops), `restart`
pcs jump to the runtime's restart.  The self-test at $FEBB cannot pass on the board (its port
loop-back test fails) and always ends at $F003, so the reset entry is $F003.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from m6801dis import decode, discover

N, Z, V, C = 8, 4, 2, 1
ALL = N | Z | V | C
BASE = 0xF000

USES = {"bhi": C | Z, "bls": C | Z, "bcc": C, "bcs": C, "bne": Z, "beq": Z, "bvc": V, "bvs": V,
        "bpl": N, "bmi": N, "bge": N | V, "blt": N | V, "bgt": N | Z | V, "ble": N | Z | V}
M68K_BRANCH = {"bra": "bra", "bhi": "bhi", "bls": "bls", "bcc": "bcc", "bcs": "bcs", "bne": "bne", "beq": "beq",
               "bvc": "bvc", "bvs": "bvs", "bpl": "bpl", "bmi": "bmi", "bge": "bge", "blt": "blt", "bgt": "bgt",
               "ble": "ble"}


class Unsupported(Exception):
    pass


def defs_uses(ins):
    """(flags the 6801 instruction defines, flags it reads) over N Z V C."""
    mn = ins.mn
    base = mn[:-1] if mn[-1] in "ab" and mn not in ("sba", "cba", "aba", "tab", "tba", "rola", "rora") and \
        mn[:-1] in ("neg", "com", "lsr", "ror", "asr", "asl", "rol", "dec", "inc", "tst", "clr", "sub", "cmp",
                    "sbc", "and", "bit", "ld", "st", "eor", "adc", "ora", "add") else mn
    if mn in USES:
        return 0, USES[mn]
    if mn in ("bra", "brn", "nop", "jmp", "jsr", "bsr", "rts", "rti", "sei", "cli", "abx", "psha", "pshb",
              "pula", "pulb", "pshx", "pulx", "ins", "des", "tsx", "txs", "wai"):
        return 0, 0
    if base in ("ld", "st", "and", "bit", "ora", "eor") or mn in ("tab", "tba", "ldd", "std", "ldx", "stx", "lds", "sts"):
        return N | Z | V, 0
    if base in ("inc", "dec"):
        return N | Z | V, 0
    if mn in ("inx", "dex"):
        return Z, 0
    if base in ("clr", "tst", "neg", "com", "lsr", "ror", "asr", "asl", "rol", "sub", "cmp", "sbc", "add", "adc") \
            or mn in ("sba", "cba", "aba", "cpx", "subd", "addd", "lsrd", "asld", "mul"):
        uses = C if base in ("ror", "rol", "sbc", "adc") else 0
        return ALL, uses
    raise Unsupported("flags of %s" % ins.text)


def liveness(code, entries):
    """live[pc] = flags live before the instruction.  A call passes the flags through (a callee
    that does not define a flag leaves it); the flags live at a return are those some caller reads
    after the call returns (a fixpoint), none at `rti`."""
    ret_live = 0
    while True:
        live_in = {pc: 0 for pc in code}
        changed = True
        order = sorted(code, reverse=True)

        def out_of(pc, ins):
            if ins.flow == "ret":
                return 0 if ins.mn == "rti" else ret_live
            out = 0
            nxt = pc + ins.length
            if ins.flow in ("seq", "jcc", "call") and nxt in live_in:
                out |= live_in[nxt]
            if ins.flow in ("jmp", "jcc") and ins.target in live_in:
                out |= live_in[ins.target]
            return out
        while changed:
            changed = False
            for pc in order:
                ins = code[pc]
                out = out_of(pc, ins)
                d, u = defs_uses(ins)
                li = (out | u) if ins.flow == "call" else ((out & ~d) | u)
                if li != live_in[pc]:
                    live_in[pc] = li
                    changed = True
        new_ret = 0
        for pc, ins in code.items():
            if ins.flow == "call" and pc + ins.length in live_in:
                new_ret |= live_in[pc + ins.length]
        if new_ret == ret_live:
            break
        ret_live = new_ret
    live_out = {pc: out_of(pc, ins) for pc, ins in code.items()}
    return live_in, live_out


class MCUEmitter:
    def __init__(self, code, live_out, skip=None, restart=()):
        self.code = code
        self.live_out = live_out
        self.skip = skip or {}
        self.restart = set(restart)
        self.lines = []
        self.uid = 0
        self.refs = set()
        self.stats = {"wrapped": 0}

    def e(self, s):
        self.lines.append("\t" + s)

    def label(self, pc):
        self.refs.add(pc)
        return "M%04X" % self.skip.get(pc, pc)

    # ---- operands ------------------------------------------------------
    def mem_ea(self, ins):
        """(68000 operand string, setup lines) of the memory operand; static I/O is handled by the callers"""
        mode, a = ins.mode, ins.arg
        if mode == "idx":
            if a <= 127:
                return "%d(a6,d2.l)" % a, []
            return "(a0,d2.l)", ["lea %d(a6),a0" % a]
        if a < 0x100:
            return "$%X(a6)" % a, []
        return "mcu_mem+$%04X" % a, []

    def is_io(self, ins):
        return ins.mode in ("dir", "ext") and ins.arg < 0x20 and ins.mn not in ("jmp", "jsr")

    def load8(self, ins, reg):
        """value of the operand into data register reg (byte)"""
        if ins.mode == "imm8":
            self.e("move.b #$%02X,%s" % (ins.arg, reg))
            return
        if self.is_io(ins):
            self.read_io(ins.arg, reg)
            return
        ea, pre = self.mem_ea(ins)
        for p in pre:
            self.e(p)
        self.e("move.b %s,%s" % (ea, reg))

    def read_io(self, a, reg):
        if a == 0x02:
            self.e("bsr mcu_rd_p1")
        elif a == 0x06:
            self.e("bsr mcu_rd_p3")
        else:
            self.e("move.b $%X(a6),d7" % a)
        if reg != "d7":
            self.e("move.b d7,%s" % reg)

    def src8(self, ins):
        """operand usable as a source of an ALU instruction: returns the string (loads into d7 if needed)"""
        if ins.mode == "imm8":
            return "#$%02X" % ins.arg
        if self.is_io(ins):
            self.read_io(ins.arg, "d7")
            return "d7"
        ea, pre = self.mem_ea(ins)
        for p in pre:
            self.e(p)
        return ea

    def dst_ea(self, ins):
        ea, pre = self.mem_ea(ins)
        for p in pre:
            self.e(p)
        return ea

    def store8(self, ins, reg):
        if self.is_io(ins):
            a = ins.arg
            self.e("move.b %s,$%X(a6)" % (reg, a))
            if a == 0x02:
                self.e("move.b %s,d7" % reg)
                self.e("bsr mcu_wr_p1")
            elif a == 0x03:
                self.e("move.b %s,d7" % reg)
                self.e("bsr mcu_wr_p2")
            self.e("tst.b %s" % reg)
            return
        ea = self.dst_ea(ins)
        self.e("move.b %s,%s" % (reg, ea))

    def word_src(self, ins):
        if ins.mode == "imm16":
            return "#$%04X" % ins.arg
        if self.is_io(ins):
            raise Unsupported("16-bit access to an I/O register: " + ins.text)
        ea, pre = self.mem_ea(ins)
        for p in pre:
            self.e(p)
        return ea

    # ---- flag fixing ---------------------------------------------------
    def wrap(self, pc, ok, body):
        """body(): emits the translation whose natural result is right for the flags in ok; keeps
        the live flags it gets wrong (the 6801 leaves them alone)"""
        need = self.live_out[pc] & ~ok
        if need:
            self.stats["wrapped"] += 1
            self.e("move.w sr,d6")
            body()
            self.e("move.w sr,d7")
            self.e("move.b d6,d3")
            self.e("eor.b d7,d3")
            self.e("and.b #%d,d3" % need)
            self.e("eor.b d3,d7")
            self.e("move.w d7,ccr")
        else:
            body()

    # ---- instructions --------------------------------------------------
    def emit_all(self):
        for pc in sorted(self.code):
            ins = self.code[pc]
            if pc in self.skip:
                # execution jumps over the code here; the label stays for the dispatch of the targets
                pass
            self.lines.append("M%04X:\t\t; %s" % (pc, ins.text))
            self.emit(ins)

    def emit(self, ins):
        pc, mn = ins.pc, ins.mn
        lo = self.live_out[pc]
        if pc in self.skip:
            self.e("bra M%04X" % self.skip[pc])
            return
        regs = {"a": "d0", "b": "d1"}
        if mn == "bra" and ins.target == pc:          # the idle loop: back to the runtime
            self.e("rts")
            return
        if mn in M68K_BRANCH and ins.mode == "rel":
            self.e("%s M%04X" % (M68K_BRANCH[mn], ins.target if ins.target not in self.skip else self.skip[ins.target]))
            self.refs.add(ins.target)
            return
        if mn == "brn" or mn == "nop" or mn in ("sei", "cli"):
            return
        if mn in ("jmp",) and ins.mode == "ext":
            if ins.arg in self.restart:
                self.e("bra mcu_restart")
            else:
                self.e("jmp %s" % self.label(ins.arg))
            return
        if mn == "jsr" and ins.mode == "ext":
            self.e("bsr %s" % self.label(ins.arg))
            return
        if mn == "bsr":
            self.e("bsr %s" % self.label(ins.target))
            return
        if mn in ("rts", "rti"):
            self.e("rts")
            return
        if mn == "wai":
            self.e("rts")
            return
        if mn in ("psha", "pshb"):
            self.wrap(pc, 0, lambda: self.e("move.b %s,-(a5)" % regs[mn[-1]]))
            return
        if mn in ("pula", "pulb"):
            self.wrap(pc, 0, lambda: self.e("move.b (a5)+,%s" % regs[mn[-1]]))
            return
        if mn == "pshx":
            def b():
                self.e("move.b d2,-(a5)")
                self.e("move.w d2,d7")
                self.e("lsr.w #8,d7")
                self.e("move.b d7,-(a5)")
            self.wrap(pc, 0, b)
            return
        if mn == "pulx":
            def b():
                self.e("moveq #0,d7")
                self.e("move.b (a5)+,d7")
                self.e("lsl.w #8,d7")
                self.e("move.b (a5)+,d7")
                self.e("move.w d7,d2")
            self.wrap(pc, 0, b)
            return
        if mn == "abx":
            def b():
                self.e("moveq #0,d7")
                self.e("move.b d1,d7")
                self.e("add.w d7,d2")
            self.wrap(pc, 0, b)
            return
        if mn in ("inx", "dex"):
            self.wrap(pc, Z, lambda: self.e("%s.w #1,d2" % ("addq" if mn == "inx" else "subq")))
            return
        if mn in ("tab", "tba"):
            src, dst = ("d0", "d1") if mn == "tab" else ("d1", "d0")
            self.wrap(pc, N | Z | V, lambda: self.e("move.b %s,%s" % (src, dst)))
            return
        if mn in ("aba", "sba", "cba"):
            op = {"aba": "add", "sba": "sub", "cba": "cmp"}[mn]
            self.e("%s.b d1,d0" % op)
            return
        if mn == "ldx":
            def b():
                self.e("move.w %s,d2" % self.word_src(ins))
            self.wrap(pc, N | Z | V, b)
            return
        if mn == "stx":
            def b():
                self.e("move.w d2,%s" % self.dst_ea(ins))
                self.e("tst.w d2")
            self.wrap(pc, N | Z | V, b)
            return
        if mn == "cpx":
            self.e("cmp.w %s,d2" % self.word_src(ins))
            return
        if mn in ("lds",):
            if ins.mode != "imm16":
                raise Unsupported(ins.text)
            self.e("lea mcu_mem+$%04X+1,a5" % ins.arg)
            return
        if mn in ("ldd", "subd", "addd", "std", "lsrd", "asld"):
            self.emit_d(ins)
            return
        if mn[-1] in "ab" and mn[:-1] in ("clr", "tst", "neg", "com", "lsr", "asl", "inc", "dec"):
            self.emit_unary(ins, mn[:-1], regs[mn[-1]])
            return
        if mn in ("clr", "tst", "neg", "com", "lsr", "asl", "inc", "dec") and ins.mode in ("dir", "ext", "idx"):
            self.emit_unary(ins, mn, None)
            return
        if mn[-1] in "ab" and mn[:-1] in ("ld", "st", "sub", "cmp", "and", "bit", "eor", "ora", "add"):
            self.emit_alu(ins, mn[:-1], regs[mn[-1]])
            return
        raise Unsupported("%04X %s" % (pc, ins.text))

    def emit_alu(self, ins, op, r):
        pc = ins.pc
        if op == "ld":
            self.wrap(pc, N | Z | V, lambda: self.load8(ins, r))
        elif op == "st":
            self.wrap(pc, N | Z | V, lambda: self.store8(ins, r))
        elif op in ("sub", "add", "cmp"):
            s = self.src8(ins)
            self.e("%s.b %s,%s" % (op, s, r))
        elif op in ("and", "ora"):
            def b():
                self.e("%s.b %s,%s" % ("and" if op == "and" else "or", self.src8(ins), r))
            self.wrap(pc, N | Z | V, b)
        elif op == "eor":
            def b():
                s = self.src8(ins)
                if not s.startswith("d"):
                    self.e("move.b %s,d7" % s)
                    s = "d7"
                self.e("eor.b %s,%s" % (s, r))
            self.wrap(pc, N | Z | V, b)
        elif op == "bit":
            def b():
                s = self.src8(ins)
                self.e("move.b %s,d3" % r)
                self.e("and.b %s,d3" % s)
            self.wrap(pc, N | Z | V, b)
        else:
            raise Unsupported(ins.text)

    def emit_unary(self, ins, op, r):
        pc = ins.pc
        lo = self.live_out[pc]
        tgt = r if r else None

        def operand():
            return r if r else self.dst_ea(ins)
        if op == "clr":
            if r:
                self.e("moveq #0,%s" % r)
            else:
                self.store_clr(ins)
        elif op == "tst":
            if r:
                self.e("tst.b %s" % r)
            else:
                self.e("tst.b %s" % operand_ea_ro(self, ins))
        elif op == "neg":
            self.e("neg.b %s" % operand())
        elif op == "com":
            self.e("not.b %s" % operand())
            self.e("ori #1,ccr")
        elif op == "asl":
            if r:
                self.e("add.b %s,%s" % (r, r))
            else:                               # (memory shifts are word sized on the 68000)
                ea = operand()
                self.e("move.b %s,d7" % ea)
                self.e("add.b d7,d7")
                self.e("move.w sr,d6")
                self.e("move.b d7,%s" % ea)
                self.e("move.w d6,ccr")
        elif op == "lsr":
            if lo & V:
                raise Unsupported("V live after lsr at %04X" % pc)
            self.wrap(pc, N | Z | C, lambda: self.e("lsr.b #1,%s" % r) if r else self.e("lsr.b %s" % operand()))
        elif op in ("inc", "dec"):
            o = "addq" if op == "inc" else "subq"
            self.wrap(pc, N | Z | V, lambda: self.e("%s.b #1,%s" % (o, operand())))
        else:
            raise Unsupported(ins.text)

    def store_clr(self, ins):
        if self.is_io(ins):
            a = ins.arg
            self.e("clr.b $%X(a6)" % a)
            if a in (0x02, 0x03):
                self.e("moveq #0,d7")
                self.e("bsr %s" % ("mcu_wr_p1" if a == 2 else "mcu_wr_p2"))
                self.e("moveq #0,d7")                 # (flags of clr)
            return
        self.e("clr.b %s" % self.dst_ea(ins))

    def emit_d(self, ins):
        pc, mn = ins.pc, ins.mn
        compose = ["move.b d0,d7", "lsl.w #8,d7", "move.b d1,d7"]
        split = ["move.b d7,d1", "lsr.w #8,d7", "move.b d7,d0"]
        if mn == "ldd":
            def b():
                if ins.mode == "imm16":
                    self.e("move.w #$%04X,d7" % ins.arg)
                else:
                    self.e("move.w %s,d7" % self.word_src(ins))
                self.e("move.w d7,d3")
                self.e("move.b d3,d1")
                self.e("lsr.w #8,d3")
                self.e("move.b d3,d0")
                self.e("tst.w d7")
            self.wrap(pc, N | Z | V, b)
        elif mn == "std":
            def b():
                ea = self.word_ea(ins)
                for s in compose:
                    self.e(s)
                self.e("move.w d7,%s" % ea)
                self.e("tst.w d7")
            self.wrap(pc, N | Z | V, b)
        elif mn in ("subd", "addd"):
            for s in compose:
                self.e(s)
            self.e("%s.w %s,d7" % ("sub" if mn == "subd" else "add", self.word_src(ins)))
            self.e("move.w sr,d6")
            for s in split:
                self.e(s)
            self.e("move.w d6,ccr")
        elif mn in ("lsrd", "asld"):
            if mn == "lsrd" and self.live_out[pc] & V:
                raise Unsupported("V live after lsrd")
            for s in compose:
                self.e(s)
            self.e("%s #1,d7" % ("lsr.w" if mn == "lsrd" else "asl.w"))
            self.e("move.w sr,d6")
            for s in split:
                self.e(s)
            self.e("move.w d6,ccr")

    def word_ea(self, ins):
        if self.is_io(ins):
            raise Unsupported("16-bit store to an I/O register: " + ins.text)
        return self.dst_ea(ins)


def operand_ea_ro(em, ins):
    if em.is_io(ins):
        em.read_io(ins.arg, "d7")
        return "d7"
    return em.dst_ea(ins)


# busy-wait loops of the MCU program: the pc they continue at.  $F089: the delay at the end of the
# IRQ handler (368 iterations), $F198: the one in the init.
SKIP = {0xF089: 0xF091, 0xF198: 0xF1A0}


def translate(rom, skip=SKIP, restart=(0xF000,), roots=(0xF003, 0xF046)):
    code, ij = discover(rom, list(roots), stop=restart)
    if ij:
        raise Unsupported("indirect flow at %s" % ij)
    live_in, live_out = liveness(code, roots)
    em = MCUEmitter(code, live_out, skip, restart)
    em.emit_all()
    return em, code


def generate(rom=None):
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if rom is None:
        rom = open(os.path.join(root, "assets", "roms", "extracted", "bublbobl", "a78-01.17"), "rb").read()
    em, code = translate(rom)
    head = ["; generated by m6801x.py -- the Bubble Bobble MCU program, 6801 -> 68000", "\tsection text,code"]
    return "\n".join(head + em.lines) + "\n", em, code


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build", "bb_mcu.s")
    text, em, code = generate()
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w").write(text)
    print("%d instructions, %d wrapped, %d lines -> %s" % (len(code), em.stats["wrapped"], len(em.lines), out))
