"""Generates engine/z80mame_ops.py from MAME's Z80 description (src/devices/cpu/z80/z80.lst, BSD-3-Clause,
copyright-holders Juergen Buchmueller, Andrei I. Holub).

    venv/bin/python engine/z80mame_gen.py [path/to/mame/src/devices/cpu/z80]

MAME's z80make.py turns z80.lst into a resumable C++ state machine: every '+ n' (internal cycles) and every
'n !! access' (the access, then n cycles off icount) ends a step, and the CPU returns from execute_run() after any
step that leaves icount <= 0, going on with the rest of the instruction in the next time slice.  This script reads
z80.lst with z80make.py's own parser (its macros expanded the same way) and writes one Python function per opcode:
a generator that yields where MAME would return (the run loop in engine/z80mame.py resumes it), or a plain function
when the opcode has no steps.  The C statements are translated by a small expression parser with C's precedence
and the targets' widths (u8 registers, u16 pairs, bool flags).
"""
import os
import re
import sys

DEFAULT_SRC = os.path.expanduser("~/Work/F030Arcade/third_party/jsm68kdisassembler/third_party/mame/src/devices/cpu/z80")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "z80mame_ops.py")

CYCLES = {"m_mreq_cycles": "3", "m_iorq_cycles": "4", "m_m1_cycles-2": "2", "m_m1_cycles": "4"}
FALSE_CONDS = {"HAS_LDAIR_QUIRK", "nomreq_en", "refresh_en"}
SKIP_CALLS = ("illegal_1", "illegal_2", "LOGMASKED", "logerror", "daisy_call_reti_device", "debugger_wait_hook",
              "m_irqack_cb", "m_nomreq_cb", "m_refresh_cb")

# ---- names -------------------------------------------------------------------------------------------------------
R8 = {"A": "s.A", "F": "s.F", "B": "s.B", "C": "s.C", "D": "s.D", "E": "s.E", "H": "s.H", "L": "s.L",
      "TDAT8": "s.TL", "TDAT_L": "s.TL", "TDAT_H": "s.TH", "I": "s.I", "m_i": "s.I", "R": "s.R", "m_r": "s.R",
      "R2": "s.R2", "m_r2": "s.R2", "Q": "s.q", "QT": "s.qt", "m_im": "s.im",
      "m_f.s_val": "s.fs", "m_f.z_val": "s.fz", "m_f.yx_val": "s.fyx", "m_f.h_val": "s.fh", "m_f.pv_val": "s.fpv"}
R16 = {"IX": "s.IX", "IY": "s.IY", "SP": "s.SP", "PC": "s.PC", "m_pc.w": "s.PC", "PRVPC": "s.PRVPC", "WZ": "s.WZ",
       "TDAT2": "s.TDAT2", "m_ea": "s.ea"}
PAIRS = {"BC": ("s.B", "s.C"), "DE": ("s.D", "s.E"), "HL": ("s.H", "s.L"), "AF": ("s.A", "s.F"),
         "TDAT": ("s.TH", "s.TL")}
HALVES = {"HX": ("s.IX", 1), "LX": ("s.IX", 0), "HY": ("s.IY", 1), "LY": ("s.IY", 0), "WZ_H": ("s.WZ", 1),
          "WZ_L": ("s.WZ", 0)}
BOOLS = {"m_f.n": "s.fn", "m_f.c": "s.fc", "m_iff1": "s.iff1", "m_iff2": "s.iff2"}
INTS = {"m_tmp_irq_vector": "s.tmp_vec", "m_icount": "s.icount", "m_irq_state": "s.irq_state",
        "m_service_attention": "s.sa", "m_halt": "s.halt_", "m_busreq_state": "s.busreq",
        "m_busack_state": "s.busack"}
CONSTS = {"SF": "0x80", "ZF": "0x40", "YXF": "0x28", "HF": "0x10", "PF": "0x04", "VF": "0x04", "NF": "0x02",
          "CF": "0x01", "CLEAR_LINE": "0", "ASSERT_LINE": "1", "SA_BUSREQ": "0", "SA_NMI_PENDING": "1",
          "SA_IRQ_ON": "2", "SA_HALT": "3", "SA_AFTER_EI": "4", "SA_AFTER_LDAIR": "5", "SA_NSC800_IRQ_ON": "6"}
FLAGCALLS = {"m_f.s": "(s.fs & 0x80)", "m_f.z": "(0 if s.fz else 0x40)", "m_f.yx": "(s.fyx & 0x28)",
             "m_f.h": "(s.fh & 0x10)", "m_f.pv": "PV[s.fpv]"}
FUNCS = {"data_read": "s.rd", "stack_read": "s.rd", "data_write": "s.wr", "stack_write": "s.wr",
         "m_io.read_interruptible": "s.io_in", "m_io.write_interruptible": "s.io_out",
         "opcode_read": "s.rd_pc", "arg_read": "s.rd_pc", "standard_irq_callback": "s.irq_ack",
         "sa_set": "s.sa_set", "sa_get": "s.sa_get"}
HELPERS = {"halt", "leave_halt", "inc", "dec", "rlca", "rrca", "rla", "rra", "add_a", "adc_a", "sub_a", "sbc_a",
           "neg", "daa", "and_a", "or_a", "xor_a", "cp", "exx", "rlc", "rrc", "rl", "rr", "sla", "sra", "sll", "srl",
           "bit", "bit_hl", "bit_xy", "res", "set", "ei", "block_io_interrupted_flags", "get_f", "set_f"}
TYPES = {"u8": 0xFF, "u16": 0xFFFF, "u32": 0xFFFFFFFF, "s8": None, "int": None, "s32": None}


def target_type(name, local):
    if name in local:
        return local[name]
    if name in R8:
        return "u8"
    if name in R16:
        return "u16"
    if name in PAIRS:
        return "pair"
    if name in HALVES:
        return "half"
    if name in BOOLS:
        return "bool"
    if name in INTS:
        return "int"
    raise ValueError("unknown target %r" % name)


# ---- C expressions -----------------------------------------------------------------------------------------------
TOK = re.compile(r"\s*(0[xX][0-9a-fA-F]+[uU]?|\d+[uU]?|[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*|"
                 r"<<|>>|<=|>=|==|!=|&&|\|\||\+\+|--|->|[-+*/%&|^~!<>()=,?:\[\]])")
BIN = [("||",), ("&&",), ("|",), ("^",), ("&",), ("==", "!="), ("<", ">", "<=", ">="), ("<<", ">>"), ("+", "-"),
       ("*", "/", "%")]
PYOP = {"||": "or", "&&": "and"}


def tokenize(s):
    out, pos = [], 0
    s = s.strip()
    while pos < len(s):
        m = TOK.match(s, pos)
        if not m:
            raise ValueError("cannot tokenize %r at %d" % (s, pos))
        out.append(m.group(1))
        pos = m.end()
    return out


class Expr:
    """C expression tokens -> Python source; pre-increments/decrements become statements in self.pre"""

    def __init__(self, toks, local):
        self.t = toks
        self.i = 0
        self.local = local
        self.pre = []

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self, want=None):
        tok = self.peek()
        if want is not None and tok != want:
            raise ValueError("expected %r, got %r in %r" % (want, tok, " ".join(self.t)))
        self.i += 1
        return tok

    def parse(self):
        e = self.binary(0)
        if self.peek() is not None:
            raise ValueError("trailing %r in %r" % (self.t[self.i:], " ".join(self.t)))
        return e

    def binary(self, level):
        if level == len(BIN):
            return self.unary()
        left = self.binary(level + 1)
        while self.peek() in BIN[level]:
            op = self.take()
            right = self.binary(level + 1)
            if op == "/":
                op = "//"
            left = "(%s %s %s)" % (left, PYOP.get(op, op), right)
        return left

    def unary(self):
        tok = self.peek()
        if tok == "!":
            self.take()
            return "(not %s)" % self.unary()
        if tok == "~":
            self.take()
            return "(~%s)" % self.unary()
        if tok == "-":
            self.take()
            return "(-%s)" % self.unary()
        if tok in ("++", "--"):
            self.take()
            name = self.take()
            self.pre.append(assign(name, "%s %s 1" % (read(name, self.local), "+" if tok == "++" else "-"),
                                   self.local))
            return read(name, self.local)
        if tok == "(" and self.t[self.i + 1] in TYPES and self.t[self.i + 2] == ")":
            self.i += 3
            return cast(self.t[self.i - 2], self.unary())
        return self.postfix()

    def postfix(self):
        tok = self.take()
        if tok == "(":
            e = self.binary(0)
            self.take(")")
            return "(%s)" % e
        if re.match(r"\d|0x", tok, re.I):
            return tok.rstrip("uU")
        if self.peek() == "(":                                # a call
            self.take()
            args = []
            while self.peek() != ")":
                args.append(self.binary(0))
                if self.peek() == ",":
                    self.take()
            self.take(")")
            return call(tok, args)
        if self.peek() in ("++", "--"):
            raise ValueError("postfix in an expression: %r" % " ".join(self.t))
        return read(tok, self.local)


def cast(typ, e):
    if typ == "s8":
        return "S8[(%s) & 0xFF]" % e
    m = TYPES[typ]
    return "((%s) & 0x%X)" % (e, m) if m else e


def call(name, args):
    if name in TYPES:                                          # u16(x)
        return cast(name, args[0])
    if name in FLAGCALLS:
        return FLAGCALLS[name]
    if name in FUNCS:
        return "%s(%s)" % (FUNCS[name], ", ".join(args))
    if name in HELPERS:
        return "s.%s(%s)" % (name, ", ".join(args))
    raise ValueError("unknown function %r" % name)


def read(name, local):
    if name in local:
        return name
    if name in R8:
        return R8[name]
    if name in R16:
        return R16[name]
    if name in PAIRS:
        hi, lo = PAIRS[name]
        return "((%s << 8) | %s)" % (hi, lo)
    if name in HALVES:
        reg, hi = HALVES[name]
        return "(%s >> 8)" % reg if hi else "(%s & 0xFF)" % reg
    if name in BOOLS:
        return BOOLS[name]
    if name in INTS:
        return INTS[name]
    if name in CONSTS:
        return CONSTS[name]
    if name == "nullptr":
        return "None"
    raise ValueError("unknown name %r" % name)


def conv(typ, e):
    if typ == "u8":
        return "(%s) & 0xFF" % e
    if typ in ("u16", "pair", "half"):
        return "(%s) & 0xFFFF" % e
    if typ == "u32":
        return "(%s) & 0xFFFFFFFF" % e
    if typ == "bool":
        return "1 if (%s) else 0" % e
    return e


def assign(name, e, local):
    """Python statement(s) storing C expression value e (Python source) into name"""
    typ = target_type(name, local)
    if name in local:
        return "%s = %s" % (name, conv(typ, e))
    if typ == "pair":
        hi, lo = PAIRS[name]
        return "_t = (%s) & 0xFFFF; %s = _t >> 8; %s = _t & 0xFF" % (e, hi, lo)
    if typ == "half":
        reg, hi = HALVES[name]
        if hi:
            return "%s = (%s & 0xFF) | (((%s) & 0xFF) << 8)" % (reg, reg, e)
        return "%s = (%s & 0xFF00) | ((%s) & 0xFF)" % (reg, reg, e)
    return "%s = %s" % ({**R8, **R16, **BOOLS, **INTS}[name], conv(typ, e))


def top_split(toks, seps):
    """splits tokens at top-level separators (outside parentheses); returns parts and separators"""
    parts, seps_found, depth, cur = [], [], 0, []
    for t in toks:
        if t == "(":
            depth += 1
        elif t == ")":
            depth -= 1
        if depth == 0 and t in seps:
            parts.append(cur)
            seps_found.append(t)
            cur = []
        else:
            cur.append(t)
    parts.append(cur)
    return parts, seps_found


def lvalue(toks):
    if len(toks) != 1:
        raise ValueError("lvalue %r" % toks)
    return toks[0]


def statement(text, local):
    """one C statement (no trailing ';') -> list of Python lines"""
    text = re.sub(r"set_service_attention<(\w+),\s*(\d)>\(\)", r"sa_set(\1, \2)", text)
    text = re.sub(r"get_service_attention<(\w+)>\(\)", r"sa_get(\1)", text)
    if re.match(r"(%s)\b" % "|".join(SKIP_CALLS), text) or text.startswith("using std::"):
        return []
    toks = tokenize(text)
    if not toks:
        return []
    if toks[0] in ("inc", "dec") and toks[1] == "(":            # inc(u8 &r)
        name = toks[2]
        return [assign(name, "s.%s(%s)" % (toks[0], read(name, local)), local)]
    if toks[0] == "swap":
        a, b = toks[2], toks[4]
        if (a, b) == ("m_af", "m_af2"):
            return ["s.A, s.F, s.af2 = s.af2 >> 8, s.af2 & 0xFF, (s.A << 8) | s.F"]
        return ["_u = %s" % read(a, local), assign(a, read(b, local), local), assign(b, "_u", local)]
    if toks[0] == "const":
        toks = toks[1:]
    if toks[0] in TYPES and len(toks) > 2 and toks[2] == "=":  # declaration
        local[toks[1]] = toks[0]
        toks = toks[1:]
    if len(toks) == 2 and toks[1] in ("++", "--"):
        name = toks[0]
        return [assign(name, "%s %s 1" % (read(name, local), "+" if toks[1] == "++" else "-"), local)]
    if len(toks) == 2 and toks[0] in ("++", "--"):
        name = toks[1]
        return [assign(name, "%s %s 1" % (read(name, local), "+" if toks[0] == "++" else "-"), local)]
    # compound assignment (the tokenizer splits "+=" into "+" "=")
    if len(toks) > 2 and toks[1] in ("+", "-", "|", "&", "^") and toks[2] == "=":
        name = toks[0]
        ex = Expr(toks[3:], local)
        e = ex.parse()
        return ex.pre + [assign(name, "%s %s (%s)" % (read(name, local), toks[1], e), local)]
    parts, seps = top_split(toks, ("=",))
    if seps:
        ex = Expr(parts[-1], local)
        e = ex.parse()
        names = [lvalue(p) for p in parts[:-1]]
        out = list(ex.pre)
        if len(names) == 1:
            return out + [assign(names[0], e, local)]
        out.append("_v = %s" % e)
        for name in reversed(names):
            out.append(assign(name, "_v", local))
            out.append("_v = %s" % read(name, local))
        return out
    ex = Expr(toks, local)
    e = ex.parse()
    return ex.pre + [e]


# ---- opcodes -----------------------------------------------------------------------------------------------------
class Body:
    def __init__(self, tables):
        self.lines = []
        self.ind = 1
        self.stack = []
        self.local = {}
        self.gen = False
        self.pending_if = None       # indentation for a one-statement if without braces
        self.skip_next = False
        self.in_comment = False
        self.tables = tables

    def emit(self, line):
        ind = self.ind
        if self.pending_if is not None:
            ind = self.pending_if
            self.pending_if = None
        self.lines.append("    " * ind + line)

    def emit_stmts(self, stmts):
        if not stmts:
            if self.pending_if is not None:
                self.emit("pass")
            return
        if self.pending_if is not None:
            ind = self.pending_if
            self.pending_if = None
            for st in stmts:
                self.lines.append("    " * ind + st)
            return
        for st in stmts:
            self.emit(st)

    def step(self, cycles):
        self.gen = True
        self.emit_stmts(["s.icount -= %s" % cycles])
        self.emit("if s.icount <= 0:")
        self.lines.append("    " * (self.ind + 1) + "yield")

    def jump(self, table_expr, op_expr):
        self.gen = True
        self.emit_stmts(["r = OPS[%s][%s](s)" % (table_expr, op_expr)])
        self.emit("if r is not None:")
        self.lines.append("    " * (self.ind + 1) + "yield from r")

    def cond(self, c):
        ex = Expr(tokenize(c), self.local)
        e = ex.parse()
        for p in ex.pre:
            self.emit(p)
        return e

    def line(self, src):
        if self.in_comment:
            if "*/" not in src:
                return
            src = src.split("*/", 1)[1]
            self.in_comment = False
        src = re.sub(r"/\*.*?\*/", "", src)
        if "/*" in src:
            src = src.split("/*", 1)[0]
            self.in_comment = True
        src = re.sub(r"//.*$", "", src).strip()
        if not src:
            return
        if self.skip_next:
            self.skip_next = False
            return
        m = re.match(r"^\+\s+(.+)$", src)
        if m:
            self.step(m.group(1))
            return
        m = re.match(r"^(\S+)\s+!!\s+(.+?);?$", src)
        if m:
            self.emit_stmts(statement(m.group(2), self.local))
            self.step(CYCLES[m.group(1)])
            return
        m = re.match(r"^m_ref = 0x([0-9a-f]{2})([0-9a-f]{2})00;$", src)
        if m:
            self.jump("0x" + m.group(1), "0x" + m.group(2))
            return
        m = re.match(r"^m_ref = \((\w+) << 16\) \| \(TDAT8 << 8\);$", src)
        if m:
            self.jump(m.group(1), "s.TL")
            return
        if src == "goto process;":
            return
        if src == "{":
            self.stack.append("scope")
            return
        if src == "}":
            if self.stack.pop() == "if":
                self.ind -= 1
            return
        m = re.match(r"^\}\s*else\s*(if\s*\((.*)\))?\s*\{$", src)
        if m:
            assert self.stack[-1] == "if"
            if m.group(1):
                c = self.cond(m.group(2))
                self.lines.append("    " * (self.ind - 1) + "elif %s:" % c)
            else:
                self.lines.append("    " * (self.ind - 1) + "else:")
            self.emit("pass")
            return
        m = re.match(r"^if\s*\((.*)\)\s*(\{)?\s*(.*)$", src)
        if m and balanced(m.group(1)):
            c, brace, rest = m.groups()
            if c.strip() in FALSE_CONDS:
                assert not brace
                if rest:
                    return
                self.skip_next = True
                return
            e = self.cond(c)
            self.emit("if %s:" % e)
            if brace:
                self.stack.append("if")
                self.ind += 1
                self.emit("pass")
            elif rest:
                self.lines.append("    " * (self.ind + 1) + "; ".join(statement(rest.rstrip(";"), self.local)
                                                                      or ["pass"]))
            else:
                self.pending_if = self.ind + 1
            return
        if src == ";":
            self.emit_stmts([])
            return
        if src == "continue;":
            raise ValueError("continue in an opcode")
        if src.startswith("device_z80daisy_interface"):
            return
        if src.startswith("m_tmp_irq_vector = (intf"):
            self.emit("s.tmp_vec = s.irq_ack()")
            return
        if src.startswith("debugger_instruction_hook"):
            self.emit("if s.hook is not None: s.hook()")
            return
        assert src.endswith(";"), src
        self.emit_stmts(statement(src[:-1], self.local))


def balanced(s):
    d = 0
    for ch in s:
        d += ch == "("
        d -= ch == ")"
        if d < 0:
            return False
    return d == 0


def translate(name, lines, tables):
    b = Body(tables)
    for il in lines:
        b.line(il.line())
    assert not b.stack, (name, b.stack)
    body = b.lines or ["    pass"]
    if b.gen:
        head = "def %s(s):" % name
    else:
        head = "def %s(s):" % name
    return [head] + body, b.gen


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC
    sys.path.insert(0, src)
    import z80make
    ol = z80make.OpcodeList(None, os.path.join(src, "z80.lst"))
    out = ['"""Generated by engine/z80mame_gen.py from MAME\'s src/devices/cpu/z80/z80.lst (BSD-3-Clause,',
           'copyright-holders Juergen Buchmueller, Andrei I. Holub): one function per opcode; the generators yield where',
           'MAME\'s Z80 returns from execute_run() with icount <= 0 (the rest of the instruction runs in the next slice).',
           'Do not edit; regenerate."""', "", "S8 = [i - 256 if i & 0x80 else i for i in range(256)]",
           "PV = [0] * 256", "for _i in range(256):",
           "    _v = _i; _v ^= _v >> 4; _v = (_v ^ (_v << 2)) & 0xFF; _v ^= _v >> 1; PV[_i] = ~_v & 0x04", "",
           "OPS = {}", ""]
    tables = {}
    names = {}
    for prefix in ("00", "cb", "dd", "ed", "fd", "fe"):
        ops = ol.opcode_info[prefix]
        assert len(ops) == 256, (prefix, len(ops))
        for op in ops:
            fn = "op_%s_%s" % (prefix, op.code)
            text, gen = translate(fn, op.source, tables)
            out += text + [""]
            names[(prefix, int(op.code, 16))] = fn
    for macro in ("take_nmi", "take_interrupt"):
        lines = ol.pre_process(z80make.IndStr("\t@" + macro))
        text, gen = translate(macro, lines, tables)
        assert gen
        out += text + [""]
    out.append("")
    for prefix in ("00", "cb", "dd", "ed", "fd", "fe"):
        out.append("OPS[0x%s] = [%s]" % (prefix, ", ".join(names[(prefix, i)] for i in range(256))))
    with open(OUT, "w") as f:
        f.write("\n".join(out) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
