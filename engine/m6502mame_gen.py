"""Generates engine/m6502mame_ops.py from MAME's NMOS 6502 description (src/devices/cpu/m6502/om6502.lst and the
opcode table dm6502.lst; BSD-3-Clause, copyright-holders Olivier Galibert).

    venv/bin/python engine/m6502mame_gen.py [path/to/mame/src/devices/cpu/m6502]

MAME's m6502make.py turns om6502.lst into a resumable state machine: every line that contains "read" or "write" is a
bus access, followed by 'm_icount--' and a return from execute_run() when icount <= 0 (the instruction goes on in
the next time slice, do_exec_partial); 'prefetch()' expands to prefetch_start(); m_IR = read_sync(m_PC);
prefetch_end() (the read is the access, so the interrupt sampling in prefetch_end runs after the possible return).
This script reads om6502.lst the same way (load_opcodes's prefetch expansion, identify_line_type's "read"/"write"
test) and writes one Python generator per opcode that yields where MAME returns; the run loop in engine/m6502mame.py
resumes it.  The C statements are translated by a small expression parser with C's precedence and the targets'
widths (u8 A X Y P TMP2 IR, u16 PC SP TMP).  m_inst_state = -1 (the end of reset/brk) is the run loop's business.
"""
import os
import re
import sys

DEFAULT_SRC = os.path.expanduser(
    "~/Work/F030Arcade/third_party/jsm68kdisassembler/third_party/mame/src/devices/cpu/m6502")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "m6502mame_ops.py")

U8 = {"m_A": "s.A", "m_X": "s.X", "m_Y": "s.Y", "m_P": "s.P", "m_TMP2": "s.TMP2", "m_IR": "s.IR"}
U16 = {"m_PC": "s.PC", "m_SP": "s.SP", "m_TMP": "s.TMP", "m_NPC": "s.NPC"}
BOOLS = {"m_irq_taken": "s.irq_taken", "m_nmi_pending": "s.nmi_pending"}
CONSTS = {"F_N": 0x80, "F_V": 0x40, "F_E": 0x20, "F_B": 0x10, "F_D": 0x08, "F_I": 0x04, "F_Z": 0x02, "F_C": 0x01,
          "NMI_LINE": '"nmi"', "IRQ_LINE": '"irq"'}
HELPERS = {"do_adc", "do_sbc", "do_cmp", "do_bit", "do_arr", "do_asl", "do_lsr", "do_ror", "do_rol"}
ACCESS = "s.icount -= 1\nif s.icount <= 0:\n    yield"
PREFETCH_END = """s.sync = 0
if (s.nmi_pending or (s.irq_state and not s.P & 0x04)) and not s.inhibit:
    s.irq_taken = 1
    s.IR = 0x00
else:
    s.PC = (s.PC + 1) & 0xFFFF"""

# ---- om6502.lst, as m6502make.py reads it --------------------------------------------------------------------------


def load_opcodes(fname):
    opcodes = []
    for line in open(fname):
        if line.startswith("#"):
            continue
        line = line.rstrip()
        if not line:
            continue
        if line.startswith(" ") or line.startswith("\t"):
            if line == "\tprefetch();":
                opcodes[-1][1].extend(["\tprefetch_start();", "\tm_IR = read_sync(m_PC);", "\tprefetch_end();"])
            elif line == "\tprefetch_noirq();":
                opcodes[-1][1].extend(["\tprefetch_start();", "\tm_IR = read_sync(m_PC);", "\tprefetch_end_noirq();"])
            else:
                opcodes[-1][1].append(line)
        else:
            opcodes.append((line, []))
    return opcodes


def load_disp(fname):
    states = []
    for line in open(fname):
        if line.startswith("#"):
            continue
        states += line.split()
    return states


def line_type(ins):
    if "eat-all-cycles" in ins:
        return "EAT"
    return "MEMORY" if ("read" in ins or "write" in ins) else "NONE"


# ---- C expressions -> Python ---------------------------------------------------------------------------------------
TOK = re.compile(r"\s*(0[xX][0-9a-fA-F]+|\d+|[A-Za-z_][A-Za-z_0-9]*|<<|>>|<=|>=|==|!=|&&|\|\||[-+&|^~!<>()?:,])")
BIN = [("||",), ("&&",), ("|",), ("^",), ("&",), ("==", "!="), ("<", ">", "<=", ">="), ("<<", ">>"), ("+", "-")]
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
    """tokens -> (python source, width in bits or None when it may exceed 16 bits / go negative)"""

    def __init__(self, toks):
        self.t = toks
        self.i = 0

    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else None

    def take(self, want=None):
        tok = self.peek()
        if want is not None and tok != want:
            raise ValueError("expected %r, got %r in %r" % (want, tok, " ".join(self.t)))
        self.i += 1
        return tok

    def parse(self):
        e = self.ternary()
        if self.peek() is not None:
            raise ValueError("trailing %r in %r" % (self.t[self.i:], " ".join(self.t)))
        return e

    def ternary(self):
        c = self.binary(0)
        if self.peek() != "?":
            return c
        self.take()
        a = self.ternary()
        self.take(":")
        b = self.ternary()
        return "(%s if %s else %s)" % (a[0], c[0], b[0]), wmax(a[1], b[1])

    def binary(self, level):
        if level == len(BIN):
            return self.unary()
        left = self.binary(level + 1)
        while self.peek() in BIN[level]:
            op = self.take()
            right = self.binary(level + 1)
            if op == "&":
                w = wmin(left[1], right[1])
            elif op in ("|", "^"):
                w = wmax(left[1], right[1])
            elif op == ">>" and right[0].isdigit():
                w = None if left[1] is None else max(left[1] - int(right[0]), 1)
            elif op in ("<", ">", "<=", ">=", "==", "!=", "&&", "||"):
                w = 1
            else:
                w = None
            left = "(%s %s %s)" % (left[0], PYOP.get(op, op), right[0]), w
        return left

    def unary(self):
        tok = self.peek()
        if tok == "!":
            self.take()
            return "(not %s)" % self.unary()[0], 1
        if tok == "~":
            self.take()
            return "(~%s)" % self.unary()[0], None
        if tok == "-":
            self.take()
            return "(-%s)" % self.unary()[0], None
        return self.postfix()

    def postfix(self):
        tok = self.take()
        if tok == "(":
            e = self.ternary()
            self.take(")")
            return "(%s)" % e[0], e[1]
        if re.match(r"\d", tok):
            v = int(tok, 0)
            return tok, max(v.bit_length(), 1)
        if self.peek() == "(":
            self.take()
            args = []
            while self.peek() != ")":
                args.append(self.ternary())
                if self.peek() == ",":
                    self.take()
            self.take(")")
            return call(tok, args)
        if tok in U8:
            return U8[tok], 8
        if tok in U16:
            return U16[tok], 16
        if tok in BOOLS:
            return BOOLS[tok], 1
        if tok in CONSTS:
            v = CONSTS[tok]
            return ("0x%02X" % v, 8) if isinstance(v, int) else (v, None)
        if tok in ("false", "true"):
            return ("1" if tok == "true" else "0"), 1
        raise ValueError("unknown name %r" % tok)


def wmin(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


def wmax(a, b):
    return None if a is None or b is None else max(a, b)


def masked(e, bits):
    """e as a value of `bits` bits (C's truncation)"""
    code, w = e
    if w is not None and w <= bits:
        return code
    return "(%s & 0x%X)" % (code, (1 << bits) - 1)


def call(name, args):
    if name in ("read", "read_arg", "read_sync"):                # one program space on this CPU (no opcodes space)
        return "s.rd(%s)" % masked(args[0], 16), 8
    if name == "read_pc":
        return "s.rd(s.PC)", 8
    if name == "write":
        return "s.wr(%s, %s)" % (masked(args[0], 16), masked(args[1], 8)), None
    if name == "uint8_t":
        return masked(args[0], 8), 8
    if name == "int8_t":
        return "S8[%s]" % masked(args[0], 8), None
    if name == "set_l":
        return "((%s & 0xFF00) | %s)" % (args[0][0], masked(args[1], 8)), 16
    if name == "set_h":
        return "((%s & 0xFF) | (%s << 8))" % (args[0][0], masked(args[1], 8)), 16
    if name == "page_changing":
        return "(((%s + %s) ^ %s) & 0xFF00)" % (args[0][0], args[1][0], args[0][0]), 16
    if name in HELPERS:
        return "s.%s(%s)" % (name, ", ".join(a[0] for a in args)), 8
    if name == "standard_irq_callback":
        return "s.irq_ack(%s)" % args[0][0], None
    raise ValueError("unknown function %r" % name)


def expr(src):
    return Expr(tokenize(src)).parse()


# ---- statements ----------------------------------------------------------------------------------------------------
def target(name):
    if name in U8:
        return U8[name], 8
    if name in U16:
        return U16[name], 16
    if name in BOOLS:
        return BOOLS[name], 1
    raise ValueError("unknown target %r" % name)


def statement(st):
    """one C statement (no ';') -> python lines"""
    st = st.strip()
    if st == "prefetch_start()":
        return ["s.sync = 1", "s.NPC = s.PC"]
    if st == "prefetch_end()":
        return PREFETCH_END.split("\n")
    if st == "prefetch_end_noirq()":
        return ["s.sync = 0", "s.PC = (s.PC + 1) & 0xFFFF"]
    if st == "dec_SP()":
        return ["s.SP = (s.SP & 0xFF00) | ((s.SP - 1) & 0xFF)"]
    if st == "inc_SP()":
        return ["s.SP = (s.SP & 0xFF00) | ((s.SP + 1) & 0xFF)"]
    if st == "m_inst_state = -1":
        return []
    m = re.match(r"set_nz\((\w+)\)$", st)
    if m:
        v = target(m.group(1))[0]
        return ["s.P = (s.P & 0x7D) | NZ[%s]" % v]
    m = re.match(r"(\w+)(\+\+|--)$", st)
    if m:
        t, bits = target(m.group(1))
        return ["%s = (%s %s 1) & 0x%X" % (t, t, m.group(2)[0], (1 << bits) - 1)]
    m = re.match(r"(\w+)\s*([-+&|^])=\s*(.*)$", st)
    if m:
        t, bits = target(m.group(1))
        e = expr("%s %s (%s)" % (m.group(1), m.group(2), m.group(3)))
        return ["%s = %s" % (t, masked(e, bits))]
    m = re.match(r"(\w+)\s*=\s*(\w+)\s*=\s*(.*)$", st)
    if m:
        t1, b1 = target(m.group(1))
        t2, b2 = target(m.group(2))
        e = expr(m.group(3))
        return ["_v = %s" % masked(e, min(b1, b2)), "%s = %s = _v" % (t2, t1)]
    m = re.match(r"(\w+)\s*=\s*(.*)$", st)
    if m:
        t, bits = target(m.group(1))
        e = expr(m.group(2))
        if bits == 1:
            return ["%s = %s" % (t, e[0] if e[0] in ("0", "1") else "1 if %s else 0" % e[0])]
        return ["%s = %s" % (t, masked(e, bits))]
    return [expr(st)[0]]                                      # a call


def translate(name, lines):
    """the opcode's lines -> python source of its generator"""
    out = ["def op_%s(s):" % name]
    depth = 1
    single = []                  # depths of brace-less if/else bodies waiting for their one statement
    n_access = 0

    def emit(code_lines):
        for c in code_lines:
            out.append("    " * depth + c)

    for raw in lines:
        ln = re.sub(r"//.*", "", raw).strip()
        if not ln:
            continue
        lt = line_type(ln)
        if lt == "EAT":
            raise ValueError("eat-all-cycles not supported (%s)" % name)
        m = re.match(r"(\}\s*)?(if\s*\((.*)\)|else|for\s*\(;;\))\s*(\{)?$", ln)
        if m:
            if m.group(1):
                depth -= 1
            head = m.group(2)
            if head.startswith("if"):
                emit(["if %s:" % expr(m.group(3))[0]])
            elif head == "else":
                emit(["else:"])
            else:
                emit(["while True:"])
            depth += 1
            if not m.group(4):
                single.append(depth)
            continue
        if ln == "}":
            depth -= 1
            continue
        if not ln.endswith(";"):
            raise ValueError("cannot read %r in %s" % (ln, name))
        emit(statement(ln[:-1]))
        if lt == "MEMORY":
            emit(ACCESS.split("\n"))
            n_access += 1
        while single and single[-1] == depth:
            single.pop()
            depth -= 1
    if n_access == 0:
        raise ValueError("%s has no access (would not be a generator)" % name)
    return "\n".join(out)


HEADER = '''"""Generated by engine/m6502mame_gen.py from MAME's src/devices/cpu/m6502/om6502.lst and dm6502.lst
(BSD-3-Clause, copyright-holders Olivier Galibert): one generator per opcode; it yields where MAME's 6502 returns
from execute_run() with icount <= 0 after an access (the rest of the instruction runs in the next slice).
Do not edit; regenerate."""

S8 = [i - 256 if i & 0x80 else i for i in range(256)]
NZ = [(0x80 if i & 0x80 else 0) | (0x02 if i == 0 else 0) for i in range(256)]
'''


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC
    ops = load_opcodes(os.path.join(src, "om6502.lst"))
    states = load_disp(os.path.join(src, "dm6502.lst"))
    assert len(states) == 257 and states[256] == "reset", len(states)
    names = {n for n, _ in ops}
    parts = [HEADER]
    for name, lines in ops:
        parts.append(translate(name, lines))
    for n in states:
        if n not in names:
            raise ValueError("no body for %s" % n)
    parts.append("OPS = [%s]" % ",\n       ".join(", ".join("op_" + n for n in states[k:k + 8])
                                                 for k in range(0, 256, 8)))
    parts.append("RESET = op_reset")
    with open(OUT, "w") as f:
        f.write("\n\n\n".join(parts) + "\n")
    print("wrote %s: %d bodies" % (OUT, len(ops)))


if __name__ == "__main__":
    main()
