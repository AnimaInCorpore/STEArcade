"""MC6809 -> 68000 static translator for the CPUs behind Namco's CUS117 MMU (engine/namcos1.py).

One 68000 snippet per 6809 instruction, labelled <prefix><virtual address, 6 hex digits>: the code lives in 8 KB pages of
the 23 bit virtual space, and a page runs from one bank slot of the CPU (slot = address bits 13-15; coverage says which,
`Program.slot_of`).  No interpreter runs.

Registers (the 6809's in the 68000's):
    d0 = A, d1 = B (low bytes; D is composed where needed: ADDD is add.b/addx.b, exact N Z V C)
    d2 = X, d3 = Y, d4 = U (16 bit values, the upper words always 0: they index as longs)
    a5 = S as a 68000 pointer into the stack's page (the stack lives in one slot, `a3_slot`: Splatterhouse slot 0,
         Galaga '88 slot 2; the runtime moves a5 when that slot is switched)
    a6 = the CPU's context block: +0 PB[8] the 68000 address of the page in each slot, +32 VB[8] = PB - slot * $2000
         (so VB[k] + a 6809 address in slot k is the byte), +112 the CC bits E F H I (6809 positions)
    a3 = VB[a3_slot] (the direct page and the stack: S = a5 - a3), a4 = VB[a4_slot], a2 = PB[7] (the runtime keeps
         them when a slot changes): the most used slots without a load (default slots 0 and 1)
    d5 d6 d7 a0 a1: scratch
DP is a constant of each instruction: the program's (`dp`: 0 in Splatterhouse, $40 in Galaga '88), or what the coverage
saw there (`dp_sites`: Galaga '88's main IRQ runs a routine with DP 0); TFR / EXG into DP and PULS DP change nothing.
Direct addressing is a static address in the slot of DP << 8 (the program's DP: a3_slot).

`dynamic_stack` (Galaga '88: the main IRQ's routine moves S into slot 0 for a while): the stack's slot is the
context's SSLOT (slot * 4) and SBASE its VB (S = a5 - SBASE); an assignment to S takes the slot of S - 1 (the stack
grows down from S), a static bank write to that slot moves a5 (the runtime's bank_set too).

Flags: the 6809's N Z V C are the low nibble of the 68000's CCR, so they live there.  Each instruction's 68000 code
leaves some of them right (`ok`); the others that the code after it reads (backward liveness, `live_out`) are fixed by a
wrapper that saves the CCR before and merges after (`wrap`), or set to their constant value.  H exists only for DAA:
an 8 bit add whose H is live computes it into the context byte.

Memory: an access with a static address (direct, extended, PC relative) uses PB[slot] + offset; an indexed one
VB[slot] + register, with the slot the coverage saw at that site (one slot), else computed at run time.  16 bit accesses
are two byte accesses (the 6809 has no alignment; the 68000 faults on odd words).  Accesses to the I/O pages a game
names (`io_pages`) and every store to $E000-$FFFF (the MMU's registers) go through the runtime (<cpu>_io_r / _io_w).

Control flow: branches inside a page are 68000 branches.  JSR / BSR push the 6809 return address on the 6809 stack and
branch; RTS pops it and compares it with the return points of the function's callers (`ret_cands`), else
<cpu>_dispatch (d7 = the 6809 pc) finds the label through the slot's current page.  A jump into another slot checks
that the slot holds the page the coverage saw there.
"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from m6809dis import decode

N, Z, V, C, H = 8, 4, 2, 1, 0x20
NZVC = N | Z | V | C
ALL = NZVC | H

BRANCH_USES = {"bhi": C | Z, "bls": C | Z, "bcc": C, "bcs": C, "bne": Z, "beq": Z, "bvc": V, "bvs": V,
               "bpl": N, "bmi": N, "bge": N | V, "blt": N | V, "bgt": N | Z | V, "ble": N | Z | V}
M68_BRANCH = {k: k for k in BRANCH_USES}
M68_BRANCH.update({"bra": "bra"})
INV = {"bhi": "bls", "bls": "bhi", "bcc": "bcs", "bcs": "bcc", "bne": "beq", "beq": "bne", "bvc": "bvs", "bvs": "bvc",
       "bpl": "bmi", "bmi": "bpl", "bge": "blt", "blt": "bge", "bgt": "ble", "ble": "bgt"}

REG8 = {"a": "d0", "b": "d1"}
REG16 = {"x": "d2", "y": "d3", "u": "d4"}
VB_OFF, CCHI_OFF = 32, 112
SSLOT_OFF, SBASE_OFF = 160, 164                   # (dynamic_stack: the stack's slot * 4 and its VB)
TBL_OFF, PID_OFF, TABLES_OFF = 64, 96, 152        # (the runtime's context block: games/splatter/src/core.s)


class Unsupported(Exception):
    pass


def base_mn(mn):
    """lbne -> bne, xlbra -> bra"""
    if mn.startswith("x"):
        mn = mn[1:]
    if mn.startswith("lb") and mn[1:] in BRANCH_USES or mn in ("lbra", "lbsr", "lbrn"):
        return mn[1:]
    return mn


def defs_uses(ins):
    """(flags the instruction defines, flags it reads), over N Z V C H (MAME's m6809 core)"""
    mn = base_mn(ins.mn)
    if mn in BRANCH_USES:
        return 0, BRANCH_USES[mn]
    if mn in ("bra", "brn", "bsr", "jmp", "jsr", "nop", "rts", "abx", "pshs", "pshu", "leas", "leau", "sync"):
        if mn in ("pshs", "pshu") and ins.arg & 1:
            return 0, ALL
        return 0, 0
    if mn in ("puls", "pulu"):
        return (ALL, 0) if ins.arg & 1 else (0, 0)
    if mn in ("tfr", "exg"):
        hi, lo = ins.arg >> 4, ins.arg & 15
        d = ALL if lo == 10 or (mn == "exg" and hi == 10) else 0
        u = ALL if hi == 10 or (mn == "exg" and lo == 10) else 0
        return d, u
    if mn in ("andcc", "orcc"):
        # the bits the immediate forces are defined; the others pass through (no read of their own)
        forced = (~ins.arg if mn == "andcc" else ins.arg) & ALL
        return forced, 0
    if mn == "rti":
        return ALL, 0                     # (CC comes from the stack)
    if mn == "cwai":
        return ALL, ALL
    if mn in ("leax", "leay"):
        return Z, 0
    if mn == "mul":
        return Z | C, 0
    if mn == "sex":
        return N | Z, 0
    if mn == "daa":
        return N | Z | V | C, C | H
    stem = mn[:-1] if mn[-1] in "abd" and mn not in ("sbca", "sbcb") else mn
    if mn in ("sbca", "sbcb"):
        stem = "sbc"
    if mn in ("lda", "ldb", "ldd", "ldx", "ldy", "ldu", "lds", "sta", "stb", "std", "stx", "sty", "stu", "sts",
              "anda", "andb", "ora", "orb", "eora", "eorb", "bita", "bitb", "tsta", "tstb", "tst"):
        return N | Z | V, 0
    if mn in ("adda", "addb", "adca", "adcb"):
        return N | Z | V | C | H, (C if mn.startswith("adc") else 0)
    if mn in ("suba", "subb", "cmpa", "cmpb", "sbca", "sbcb", "addd", "subd", "cmpd", "cmpx", "cmpy", "cmpu", "cmps"):
        return NZVC, (C if mn.startswith("sbc") else 0)
    if stem in ("neg", "com", "asl", "lsl", "clr") or mn in ("nega", "negb", "coma", "comb", "asla", "aslb", "lsla",
                                                             "lslb", "clra", "clrb"):
        return NZVC, 0
    if stem in ("rol",) or mn in ("rola", "rolb"):
        return NZVC, C
    if stem in ("inc", "dec") or mn in ("inca", "incb", "deca", "decb"):
        return N | Z | V, 0
    if stem in ("lsr", "asr") or mn in ("lsra", "lsrb", "asra", "asrb"):
        return N | Z | C, 0
    if stem in ("ror",) or mn in ("rora", "rorb"):
        return N | Z | C, C
    raise Unsupported("flags of %s" % ins.text)


class Program:
    """One CPU's program as the translator sees it.

    name / prefix   'main' / 'M'
    page_bytes(p)   the 8 KB of virtual page p (p = virtual address >> 13)
    slot_of         {page: slot} of the code pages (coverage)
    roots           virtual addresses of the entries (vectors, the idle point...)
    exec_cover      virtual pcs seen executing
    acc_cover       {virtual pc: set of (r|w, slot, page, oddword)} data accesses per site
    targets         {virtual pc: set of virtual targets} where computed jumps / returns / cross-slot jumps went
    io_pages        pages whose accesses go through the runtime (the key custom ...)
    hooks           {virtual pc: 68000 label} a pc where the runtime takes over (the idle loop)
    wrap_sites      virtual pcs whose indexed operand (register + constant offset) crossed $FFFF / $0000 (the coverage):
                    the 16 bit sum, its slot and base computed at run time (a1 the index), as the 6809 wraps
    static_write    {6809 address: 68000 label}: a store with that static address calls the label (d5 = the byte;
                    every register but d5-d7 / a0 kept) instead of the generic <cpu>_io_w (a bank register)
    natives         {virtual pc: 68000 label} hand-written replacements
    """

    def __init__(self, name, prefix, page_bytes, slot_of, roots, exec_cover=(), acc_cover=None, targets=None,
                 io_pages=(), hooks=None, natives=None, page_addr=None, hook_flags=NZVC, io_sites=None,
                 hook_next=None, static_read=None, inline_banks=False, io_fold=None, indirect_live=False, after=None, nf_dispatch=False, pid_checks=False,
                 dp=0, a3_slot=0, a4_slot=1, dp_sites=None, dynamic_stack=False, static_write=None, wrap_sites=()):
        self.name, self.prefix = name, prefix
        self.static_write = dict(static_write or {})
        self.wrap_sites = set(wrap_sites)
        self.dp = dp                              # the direct page register's usual value
        self.dp_sites = dict(dp_sites or {})      # {virtual pc: DP} where the coverage saw another (constant there)
        self.dynamic_stack = dynamic_stack        # S may move to another slot: the context's SSLOT / SBASE say where
        self.a3_slot, self.a4_slot = a3_slot, a4_slot     # the slots whose VB a3 / a4 hold (a3: DP's and the stack's)
        assert a3_slot <= 3 and a4_slot <= 3 and a3_slot != a4_slot and dp >> 5 == a3_slot
        self.nf_dispatch = nf_dispatch            # the runtime has <cpu>_dispatch_nf: no CCR kept (no flags live)
        self.pid_checks = pid_checks              # page checks compare the slot's page number (PID) instead of PB
        self.after = after                        # (v, ins) -> 68000 lines to run after the instruction (seq ones), or None
        self.indirect_live = indirect_live        # computed jumps / calls read what their seen targets read (see liveness)
        self.page_bytes = page_bytes
        self.slot_of = dict(slot_of)
        self.roots = list(roots)
        self.exec_cover = set(exec_cover)
        self.acc_cover = acc_cover or {}
        self.targets = targets or {}
        self.io_pages = set(io_pages)
        self.io_sites = io_sites                  # (when given: exactly the sites that go through the runtime)
        self.hooks = dict(hooks or {})
        self.natives = dict(natives or {})
        self.page_addr = page_addr
        self.hook_flags = hook_flags              # what a hook reads (the tests: H too)
        self.hook_next = dict(hook_next or {})    # hook -> where the code goes on after it (its flags are those read there)
        self.static_read = static_read            # (page, offset) -> 68000 lines leaving the byte in d7, or None
        self.inline_banks = inline_banks          # static MMU writes inline (the runtime has page_base_table)
        self.io_fold = io_fold                    # v -> (base symbol, mask): an I/O site's stores fold into a register file
        self.slot_pages = collections.defaultdict(set)
        for p, s in self.slot_of.items():
            self.slot_pages[s].add(p)
        self._pages = {}

    def page(self, p):
        if p not in self._pages:
            self._pages[p] = bytes(self.page_bytes(p))
        return self._pages[p]

    def reader(self, v):
        """rd(cpu address) for an instruction at virtual address v: its own slot reads its page; the next slot (an
        instruction across the boundary) the page the coverage saw there"""
        page = v >> 13
        slot = self.slot_of[page]
        data = self.page(page)

        def rd(a):
            a &= 0xFFFF
            if a >> 13 == slot:
                return data[a & 0x1FFF]
            other = self.slot_pages.get(a >> 13)
            if other and len(other) == 1:
                return self.page(next(iter(other)))[a & 0x1FFF]
            return 0
        return rd, slot

    def dp_at(self, v):
        return self.dp_sites.get(v, self.dp)

    def cpu_pc(self, v):
        return (self.slot_of[v >> 13] << 13) | (v & 0x1FFF)

    def label(self, v):
        return "%s%06X" % (self.prefix, v)


def discover(prog):
    """Recursive descent over the virtual code from the roots and the coverage.  -> {virtual pc: Ins}, joins"""
    code = {}
    joins = set(prog.roots) | set(prog.hooks)
    work = list(prog.roots) + sorted(prog.exec_cover)
    for site, ts in prog.targets.items():
        for t in ts:
            if t >> 13 in prog.slot_of:
                work.append(t)
                joins.add(t)
    while work:
        v = work.pop()
        while v not in code:
            if v >> 13 not in prog.slot_of:
                break
            rd, slot = prog.reader(v)
            pc = (slot << 13) | (v & 0x1FFF)
            ins = decode(rd, pc, prog.dp_at(v))
            code[v] = ins
            nxt = pc + ins.length
            if ins.target is not None and ins.flow in ("jmp", "jcc", "call"):
                for t in branch_targets(prog, v, ins):
                    work.append(t)
                    joins.add(t)
            if ins.flow in ("call", "icall", "swi"):
                joins.add((v & ~0x1FFF) | (nxt & 0x1FFF))
            if ins.flow in ("seq", "jcc", "call", "icall") and nxt >> 13 == slot:
                v = (v & ~0x1FFF) | (nxt & 0x1FFF)
                continue
            break
    return code, joins


def branch_targets(prog, v, ins):
    """the virtual targets of a direct jump / branch / call at virtual v"""
    slot = prog.slot_of[v >> 13]
    t = ins.target
    if t >> 13 == slot:
        return [(v & ~0x1FFF) | (t & 0x1FFF)]
    out = [x for x in prog.targets.get(v, ()) if x & 0x1FFF == t & 0x1FFF and prog.slot_of.get(x >> 13) == t >> 13]
    if not out:
        pages = prog.slot_pages.get(t >> 13, ())
        if len(pages) == 1:
            out = [(next(iter(pages)) << 13) | (t & 0x1FFF)]
    return out


def next_virtual(prog, v, ins):
    """the virtual address after the instruction at v (None: it runs into the next slot)"""
    slot = prog.slot_of[v >> 13]
    nxt = (slot << 13) + (v & 0x1FFF) + ins.length
    return (v & ~0x1FFF) | (nxt & 0x1FFF) if nxt >> 13 == slot else None


def call_targets(prog, code, v, ins):
    """the virtual targets of a call (JSR / BSR, or a JSR indirect: where the coverage saw it go)"""
    if ins.flow == "call":
        return branch_targets(prog, v, ins)
    return [t for t in prog.targets.get(v, ()) if t in code]


def function_returns(prog, code):
    """{virtual pc of an RTS / PULS PC: set of virtual return points}: the returns the code of each call target reaches
    without entering calls (following jumps and branches), with the return points of the calls to it.  An RTS that
    no call target reaches is missing (anything may follow it)."""
    out = collections.defaultdict(set)
    calls = collections.defaultdict(set)          # target -> return points
    for v, ins in code.items():
        if ins.flow in ("call", "icall"):
            nv = next_virtual(prog, v, ins)
            if nv is not None:
                for t in call_targets(prog, code, v, ins):
                    calls[t].add(nv)
    body = {}
    for t, rets in calls.items():
        seen = set()
        work = [t]
        while work:
            x = work.pop()
            if x in seen or x not in code:
                continue
            seen.add(x)
            ins = code[x]
            if ins.flow == "ret":
                out[x] |= rets
                continue
            if ins.flow in ("jmp", "jcc"):
                work += branch_targets(prog, x, ins)
            if ins.flow in ("seq", "jcc", "call", "icall"):
                nv = next_virtual(prog, x, ins)
                if nv is not None:
                    work.append(nv)
    return out


def liveness(prog, code, ret_points=None, intrinsic=False):
    """live_out[v] = flags read after the instruction at v.  A call's are its callee's (the flags the callee does not
    define reach its returns, whose live sets are what the return points of its callers read: `ret_points`, a
    fixpoint); a return no call target reaches, computed jumps, RTI and hooks read N Z V C (H only for DAA).
    With indirect_live, a computed call reads what its seen targets read, what follows it (a target the coverage did
    not see passes the flags it does not define back) and what any computed jump's or call's target reads before it
    returns (intrinsic: the liveness with returns reading nothing and calls passing everything on: entry_reads)."""
    if ret_points is None:
        ret_points = function_returns(prog, code)
    entry_reads = None
    if prog.indirect_live and not intrinsic:
        li0, _ = liveness(prog, code, ret_points, intrinsic=True)
        entry_reads = 0
        for v, ins in code.items():
            if ins.flow in ("ijmp", "icall"):
                for t in prog.targets.get(v, ()):
                    if t in code and (not prog.exec_cover or t in prog.exec_cover):
                        entry_reads |= li0[t]
    succ = {}
    calls = {}
    for v, ins in code.items():
        nv = next_virtual(prog, v, ins)
        s = []
        fl = ins.flow
        if fl in ("seq", "jcc") and nv is not None:
            s.append(nv)
        if fl in ("jmp", "jcc") and ins.target is not None:
            s += branch_targets(prog, v, ins)
        if fl in ("call", "icall"):
            calls[v] = call_targets(prog, code, v, ins)
        succ[v] = s
    live_in = {v: 0 for v in code}
    live_out = {}
    order = sorted(code, reverse=True)
    # the targets of computed jumps and calls the coverage saw (entry_live: the flags any of them reads)
    ijmp_tg = {v: [t for t in prog.targets.get(v, ()) if t in code] for v, ins in code.items() if ins.flow == "ijmp"}
    # (targets the coverage executed: a table's plausible entries it did not reach may be data read as code)
    ran = prog.exec_cover if prog.exec_cover else code
    entries = {t for v, ins in code.items() if ins.flow in ("ijmp", "icall") for t in prog.targets.get(v, ())
               if t in code and t in ran}
    changed = True
    while changed:
        changed = False
        entry_live = 0
        for t in entries:
            entry_live |= live_in[t]
        for v in order:
            ins = code[v]
            fl = ins.flow
            if v in prog.hooks:
                if v in prog.hook_next:
                    out = live_in.get(prog.hook_next[v], NZVC)
                else:
                    out = prog.hook_flags
            elif fl == "ret" and intrinsic:
                out = 0
            elif fl == "ret":
                rp = ret_points.get(v)
                if rp:
                    out = 0
                    for t in rp:
                        out |= live_in.get(t, NZVC)
                else:
                    out = NZVC
            elif fl == "ijmp" and prog.indirect_live and ijmp_tg.get(v):
                out = entry_live
                for t in ijmp_tg[v]:
                    out |= live_in[t]
            elif fl in ("rti", "ijmp", "swi", "wait", "halt"):
                out = NZVC
            elif fl in ("call", "icall"):
                tg = calls[v]
                if not tg or fl == "icall" and v not in prog.targets:
                    out = NZVC
                else:
                    out = 0
                    for t in tg:
                        out |= live_in.get(t, NZVC)
                    nv = next_virtual(prog, v, ins)
                    if intrinsic and nv is not None:
                        out |= live_in.get(nv, NZVC)        # (the return: everything passed on)
                    if fl == "icall":
                        # a target the coverage did not see: anything (or, with indirect_live, what any target of a
                        # computed jump or call reads before it returns, and what it passes back to the return point)
                        if not prog.indirect_live:
                            out |= NZVC
                        elif entry_reads is None:
                            out |= entry_live
                        else:
                            out |= entry_reads | (live_in.get(nv, NZVC) if nv is not None else NZVC)
            else:
                out = 0
                for t in succ[v]:
                    out |= live_in.get(t, NZVC)
                if fl in ("seq", "jcc") and next_virtual(prog, v, ins) is None:
                    out = NZVC             # runs into the next slot: unknown
            d, u = defs_uses(ins)
            li = (out & ~d) | u
            live_out[v] = out
            if li != live_in[v]:
                live_in[v] = li
                changed = True
    return live_in, live_out


class Emitter:
    def __init__(self, prog, code, joins, live_out):
        self.p = prog
        self.code = code
        self.joins = joins
        self.live_out = live_out
        self.live_in = {}                       # (set by translate: the flags each instruction reads)
        self.lines = []
        self._a0 = None
        self.tail = []                          # (data after the code: the jump tables)
        self.refs = set()
        self.uid = 0
        self.unsupported = []
        self.stats = collections.Counter()
        self.callers = collections.defaultdict(set)      # callee -> return points
        self.func_of = {}
        for v, ins in code.items():
            if ins.flow == "call":
                for t in branch_targets(prog, v, ins):
                    pc = prog.cpu_pc(v) + ins.length
                    self.callers[t].add(pc & 0xFFFF)

    # ---- small helpers -----------------------------------------------------
    def e(self, s):
        # (peephole: a0 loaded again from the same context field with nothing in between that can change either)
        if s.startswith("move.l ") and s.endswith(",a0") and "(a6)" in s and self._a0 is not None:
            src, at = self._a0
            if src == s and all(self._a0_safe(x) for x in self.lines[at + 1:]):
                return
        self.lines.append("\t" + s)
        if s.startswith("move.l ") and s.endswith(",a0") and "(a6)" in s and "a0" not in s[:-3]:
            self._a0 = (s, len(self.lines) - 1)

    @staticmethod
    def _a0_safe(line):
        """the line keeps a0 and the context's fields (an instruction, not a label, branch or call)"""
        if not line.startswith("\t"):
            return False
        op, _, args = line[1:].partition(" ")
        if op[:1] in ("b", "j", "d") and not op.startswith(("btst", "bset", "bclr", "bchg")):
            return False                      # (branches, jumps, calls, dbf)
        dst = args.rsplit(",", 1)[-1] if "," in args else args
        if "a0" in dst or "(a6" in dst or "a0)+" in args or "-(a0)" in args:
            return False
        return op.split(".")[0] in ("move", "moveq", "add", "addq", "sub", "subq", "and", "or", "eor", "lsl", "lsr",
                                    "asl", "asr", "rol", "ror", "roxl", "roxr", "ext", "tst", "cmp", "clr", "neg",
                                    "not", "addx", "subx", "scs", "scc", "seq", "sne", "smi", "spl", "svs", "svc",
                                    "mulu", "muls", "swap", "lea") and not (op.startswith("lea") and dst == "a0")

    def new_label(self):
        self.uid += 1
        return ".L%d" % self.uid

    def lab(self, v):
        self.refs.add(v)
        return self.p.label(v)

    # ---- effective addresses -----------------------------------------------
    def site_slots(self, v):
        acc = self.p.acc_cover.get(v)
        if not acc:
            return None
        return {s for rw, s, pg, odd in acc}

    def site_pages(self, v):
        acc = self.p.acc_cover.get(v)
        return {pg for rw, s, pg, odd in acc} if acc else set()

    def is_io(self, v, addr=None):
        if addr is not None and addr >= 0xE000:
            return True
        return bool(self.site_pages(v) & self.p.io_pages)

    def static_addr(self, ins):
        """the address of a direct / extended / PC relative operand, else None"""
        if ins.mode == "dir":
            return (self.p.dp_at(self.cur_v) << 8) | ins.arg
        if ins.mode == "ext":
            return ins.arg
        if ins.mode == "idx" and not ins.arg.indirect and ins.arg.kind in ("pcr8", "pcr16"):
            return ins.arg.addr
        return None

    def ea(self, v, ins, off=0, need_reg=False):
        """-> (68000 operand of the byte at EA + off, setup lines emitted).  Static addresses use PB[slot]; indexed ones
        VB[slot] + register.  The caller has made sure the site is not an I/O site."""
        a = self.static_addr(ins)
        if a is not None:
            a = (a + off) & 0xFFFF
            k = a >> 13
            if self.cached(k):
                return "$%X(%s)" % (a, self.cached(k))     # (a3 / a4 = VB of their slots)
            if k == 7:
                return "$%X(a2)" % (a & 0x1FFF)        # (a2 = PB[7])
            self.e("move.l %d(a6),a0" % (k * 4))
            return "$%X(a0)" % (a & 0x1FFF)
        x = ins.arg
        if ins.mode != "idx":
            raise Unsupported("operand of " + ins.text)
        if x.indirect or x.kind == "abs":
            self.ea_to_d7(v, ins)
            self.slot_base_dyn()
            return "%d(a0,d7.l)" % off if off else "(a0,d7.l)"
        r = x.reg
        if r == "s":
            disp = {"off5": x.offset, "off8": x.offset, "off16": x.offset, "zero": 0}.get(x.kind)
            if disp is not None:
                return "%d(a5)" % (disp + off) if disp + off else "(a5)"
            if x.kind in ("inc1", "inc2"):
                # ,S+ / ,S++ (an operand popped: CMPD ,S++): a5 first (addq to an address register keeps the CCR),
                # the operand at -n, as for X
                if not getattr(self, "_inc_done", False):
                    self.e("addq.l #%d,a5" % x.inc)
                d = off - x.inc
                return "%d(a5)" % d
            if x.kind in ("dec1", "dec2"):
                if not getattr(self, "_inc_done", False):
                    self.e("subq.l #%d,a5" % -x.inc)
                return "%d(a5)" % off if off else "(a5)"
            # accumulator offsets on S: the address as a value
            self.e("move.l a5,d7")
            self.e("sub.l %s,d7" % self.s_base())
            self.acc_add_d7(x.kind)
            self.slot_base_dyn()
            return "%d(a0,d7.l)" % off if off else "(a0,d7.l)"
        dr = REG16[r]
        slots = self.site_slots(v)
        self._base = "a0"
        if x.kind in ("off5", "off8", "off16") and v in self.p.wrap_sites:
            # (X = $FFFF and 2,X reads $0001: the sum wrapped to 16 bits, its slot, a1 the index)
            self.stats["wrapping index"] += 1
            self.e("moveq #0,d6")
            self.e("move.w %s,d6" % dr)
            self.e("add.w #%d,d6" % x.offset)
            self.e("move.l d6,a1")
            self.e("rol.w #3,d6")
            self.e("and.w #7,d6")
            self.e("add.w d6,d6")
            self.e("add.w d6,d6")
            self.e("move.l %d(a6,d6.w),a0" % VB_OFF)
            return "%d(a0,a1.l)" % off if off else "(a0,a1.l)"
        if x.kind in ("off5", "off8", "zero", "off16"):
            self.slot_base(v, slots, dr, x.offset)
            b = self._base
            d = x.offset + off
            if -128 <= d <= 127:
                return "%d(%s,%s.l)" % (d, b, dr) if d else "(%s,%s.l)" % (b, dr)
            self.e("lea %d(%s),a0" % (d, b))
            return "(a0,%s.l)" % dr
        if x.kind in ("inc1", "inc2"):
            # post increment: the register first, the operand at -n (the increment must not follow the flag op)
            self.slot_base(v, slots, dr, 0)
            if not getattr(self, "_inc_done", False):
                self.e("addq.w #%d,%s" % (x.inc, dr))
            d = off - x.inc
            return "%d(%s,%s.l)" % (d, self._base, dr)
        if x.kind in ("dec1", "dec2"):
            if not getattr(self, "_inc_done", False):
                self.e("subq.w #%d,%s" % (-x.inc, dr))
            self.slot_base(v, slots, dr, 0)
            b = self._base
            return "%d(%s,%s.l)" % (off, b, dr) if off else "(%s,%s.l)" % (b, dr)
        if x.kind in ("acc_a", "acc_b", "acc_d"):
            self.e("moveq #0,d7")
            self.e("move.w %s,d7" % dr)
            self.acc_add_d7(x.kind)
            b = "a0"
            if slots is not None and len(slots) == 1:
                k = next(iter(slots))
                if self.cached(k):
                    b = self.cached(k)
                else:
                    self.e("move.l %d(a6),a0" % (VB_OFF + 4 * k))
            else:
                self.slot_base_dyn()
            return "%d(%s,d7.l)" % (off, b) if off else "(%s,d7.l)" % b
        raise Unsupported("indexed mode %s: %s" % (x.kind, ins.text))

    def acc_add_d7(self, kind):
        """d7 (16 bit, upper word 0) += the accumulator offset (A and B signed)"""
        if kind == "acc_d":
            self.e("move.b d0,-(sp)")
            self.e("move.w (sp)+,d6")
            self.e("move.b d1,d6")
            self.e("add.w d6,d7")
        else:
            self.e("move.b %s,d6" % ("d0" if kind == "acc_a" else "d1"))
            self.e("ext.w d6")
            self.e("add.w d6,d7")

    def cached(self, k):
        """the 68000 register holding VB of slot k, or None"""
        return "a3" if k == self.p.a3_slot else "a4" if k == self.p.a4_slot else None

    def slot_base(self, v, slots, dr, offset):
        """a0 = VB[slot] of the indexed access; the slot from the coverage, else from the register (a3 / a4 hold VB of
        their slots, a0 is set from them)"""
        if slots is not None and len(slots) == 1:
            k = next(iter(slots))
            if self.cached(k):
                self._base = self.cached(k)
                return
            self.e("move.l %d(a6),a0" % (VB_OFF + 4 * k))
            return
        self.stats["dynamic slot"] += 1
        self.e("move.w %s,d6" % dr)
        if offset:
            self.e("add.w #%d,d6" % offset)
        self.e("rol.w #3,d6")
        self.e("and.w #7,d6")
        self.e("add.w d6,d6")
        self.e("add.w d6,d6")
        self.e("move.l %d(a6,d6.w),a0" % VB_OFF)

    def slot_base_dyn(self):
        """a0 = VB[slot of d7] (d7 = 16 bit address, upper word 0)"""
        self.stats["dynamic slot"] += 1
        self.e("move.w d7,d6")
        self.e("rol.w #3,d6")
        self.e("and.w #7,d6")
        self.e("add.w d6,d6")
        self.e("add.w d6,d6")
        self.e("move.l %d(a6,d6.w),a0" % VB_OFF)

    def ea_to_d7(self, v, ins):
        """d7 = the 16 bit effective address (upper word 0) of an indexed operand, indirection included"""
        x = ins.arg
        if x.kind == "abs":
            self.e("moveq #0,d7")
            self.e("move.w #$%04X,d7" % x.addr)
        elif x.kind in ("pcr8", "pcr16"):
            self.e("moveq #0,d7")
            self.e("move.w #$%04X,d7" % x.addr)
        else:
            r = x.reg
            if r == "s":
                if x.kind in ("inc1", "inc2", "dec1", "dec2"):
                    raise Unsupported("auto inc/dec on S: " + ins.text)
                self.e("move.l a5,d7")
                self.e("sub.l %s,d7" % self.s_base())
                self.e("and.l #$FFFF,d7")
            else:
                dr = REG16[r]
                if x.kind in ("dec1", "dec2"):
                    self.e("subq.w #%d,%s" % (-x.inc, dr))
                self.e("moveq #0,d7")
                self.e("move.w %s,d7" % dr)
                if x.kind in ("inc1", "inc2"):
                    self.e("addq.w #%d,%s" % (x.inc, dr))
            if x.kind in ("off5", "off8", "off16"):
                self.e("add.w #%d,d7" % x.offset)
            elif x.kind in ("acc_a", "acc_b", "acc_d"):
                self.acc_add_d7(x.kind)
        if x.indirect:
            # the pointer: two bytes at d7 (its slot from the coverage when the instruction reads nothing else: a
            # computed jump or call)
            ptr = None
            if ins.mn in ("jmp", "jsr"):
                reads = {sl for rw, sl, pg, odd in self.p.acc_cover.get(v, ()) if rw == "r"}
                if len(reads) == 1:
                    ptr = next(iter(reads))
            if ptr is not None and self.cached(ptr):
                b = self.cached(ptr)
            elif ptr is not None:
                self.e("move.l %d(a6),a0" % (VB_OFF + 4 * ptr))
                b = "a0"
            else:
                self.slot_base_dyn()
                b = "a0"
            self.e("move.b (%s,d7.l),-(sp)" % b)
            self.e("move.w (sp)+,d6")
            self.e("move.b 1(%s,d7.l),d6" % b)
            self.e("moveq #0,d7")
            self.e("move.w d6,d7")

    # ---- reads and writes ----------------------------------------------------
    def io_site(self, v, ins):
        """the access goes through the runtime: a static address in $E000-$FFFF (stores there are the MMU's
        registers), an I/O page, or a site that the coverage saw storing into slot 7 (an indexed store to the MMU)"""
        a = self.static_addr(ins)
        if a is not None and a >= 0xE000:
            return self.writes(ins)
        acc = self.p.acc_cover.get(v, ())
        if any(rw == "w" and s == 7 for rw, s, pg, odd in acc):
            return True
        if self.p.io_sites is not None:
            return v in self.p.io_sites
        return bool(self.site_pages(v) & self.p.io_pages)

    def writes(self, ins):
        """the instruction stores to its operand"""
        mn = base_mn(ins.mn)
        return mn.startswith("st") or mn in ("clr", "neg", "com", "inc", "dec", "asl", "lsl", "lsr", "asr", "rol", "ror")

    def load8(self, v, ins, reg, off=0):
        """reg = the operand byte (a move: N Z right, V C cleared)"""
        if ins.mode == "imm8":
            self.e("move.b #$%02X,%s" % (ins.arg, reg))
            return
        if self.io_site(v, ins):
            self.io_read(v, ins, off)
            self.e("move.b d7,%s" % reg)
            return
        self.e("move.b %s,%s" % (self.ea(v, ins, off), reg))

    def io_read(self, v, ins, off=0):
        """d7 = the byte through the runtime (<cpu>_io_r: d7 = address in, byte out)"""
        self.stats["io read"] += 1
        a = self.static_addr(ins)
        pages = self.site_pages(v)
        if a is not None and self.p.static_read and len(pages) == 1:
            code = self.p.static_read(next(iter(pages)), (a + off) & 0x1FFF)
            if code is not None:
                self.stats["io read static"] += 1
                for line in code:
                    self.e(line)
                return
        if a is not None:
            self.e("move.w #$%04X,d7" % ((a + off) & 0xFFFF))
        else:
            self.ea_to_d7(v, ins)
            if off:
                self.e("addq.w #%d,d7" % off)
        self.e("bsr %s_io_r" % self.p.name)

    def mmu_static(self, a, src, word=False):
        """a store to the MMU's registers at a static address: a slot's page (<cpu>_bank_hi / _lo / _word with d6 =
        slot * 2, d5 = the value), the registers the port needs (SUBRES $F000, FIRQ $FA00, the sub CPU's slot 7
        $FC00: <cpu>_io_w, which stops a test build), the others (watchdog, IRQ acknowledges) only set the flags"""
        reg = (a >> 9) & 0xF
        if reg < 8 and self.p.inline_banks:
            self.bank_inline(reg, a & 1, src, word)
            return
        if reg < 8:
            self.stats["bank write"] += 1
            self.e("move.%s %s,d5" % ("w" if word else "b", src))
            self.e("moveq #%d,d6" % (reg * 2))
            self.e("bsr %s_bank_%s" % (self.p.name, "word" if word else ("lo" if a & 1 else "hi")))
        elif reg in (8, 13, 14):
            self.e("move.w #$%04X,d7" % a)
            self.e("move.%s %s,d5" % ("w" if word else "b", src))
            self.e("bsr %s_io_w" % self.p.name)
        self.e("tst.%s %s" % ("w" if word else "b", src))

    def bank_inline(self, k, odd, src, word):
        """slot k's page from a static store, inline: PID, PB (page_base_table), VB, the dispatcher's table when code
        runs from the slot, the cached registers (a3 and the stack, a4, a2: slot 7)"""
        self.stats["bank write inline"] += 1
        e = self.e
        if word:
            e("move.w %s,d7" % src)
            e("and.w #$3FF,d7")
        elif odd:
            e("move.w %d(a6),d7" % (PID_OFF + 2 * k))
            e("move.b %s,d7" % src)
        else:
            e("move.b %s,d7" % src)
            e("and.w #3,d7")
            e("lsl.w #8,d7")
            e("move.b %d(a6),d7" % (PID_OFF + 2 * k + 1))
        skip = self.new_label()
        e("cmp.w %d(a6),d7" % (PID_OFF + 2 * k))       # (the same page again: nothing changes; 2 of 3 writes)
        e("beq.s %s" % skip)
        e("move.w d7,%d(a6)" % (PID_OFF + 2 * k))
        e("add.w d7,d7")
        e("add.w d7,d7")
        if k in set(self.p.slot_of.values()):
            e("move.l %d(a6),a1" % TABLES_OFF)
            e("move.l (a1,d7.w),%d(a6)" % (TBL_OFF + 4 * k))
        e("lea page_base_table,a0")
        e("move.l (a0,d7.w),a0")
        e("move.l a0,%d(a6)" % (4 * k))
        if k == 7:
            e("move.l a0,a2")
        if k:
            e("suba.l #$%X,a0" % (k * 0x2000))
        e("move.l a0,%d(a6)" % (VB_OFF + 4 * k))
        if self.p.dynamic_stack:
            stay = self.new_label()
            e("cmp.w #%d,%d(a6)" % (4 * k, SSLOT_OFF))
            e("bne.s %s" % stay)
            e("suba.l %d(a6),a5" % SBASE_OFF)
            e("adda.l a0,a5")
            e("move.l a0,%d(a6)" % SBASE_OFF)
            self.lines.append(stay + ":")
            if k == self.p.a3_slot:
                e("move.l a0,a3")
            elif k == self.p.a4_slot:
                e("move.l a0,a4")
        elif k == self.p.a3_slot:
            e("suba.l a3,a5")
            e("adda.l a0,a5")
            e("move.l a0,a3")
        elif k == self.p.a4_slot:
            e("move.l a0,a4")
        self.lines.append(skip + ":")
        e("tst.%s %s" % ("w" if word else "b", src))

    def store8(self, v, ins, src, off=0):
        """the byte in register src to the operand (a move: N Z right, V C cleared)"""
        a = self.static_addr(ins)
        if a is not None and (a + off) & 0xFFFF in self.p.static_write:
            self.stats["static write"] += 1
            self.e("move.b %s,d5" % src)
            self.e("bsr %s" % self.p.static_write[(a + off) & 0xFFFF])
            self.e("tst.b %s" % src)
            return
        if a is not None and (a + off) & 0xFFFF >= 0xE000:
            self.mmu_static((a + off) & 0xFFFF, src)
            return
        fold = self.p.io_fold(v) if self.p.io_fold else None
        if fold and self.io_site(v, ins):
            # a register file mirrored over the page (the CUS123 control): the address folded inline
            self.stats["io write folded"] += 1
            base, mask = fold
            a = self.static_addr(ins)
            if a is not None:
                self.e("move.b %s,%s+$%X" % (src, base, (a + off) & mask))
            else:
                self.ea_to_d7(v, ins)
                if off:
                    self.e("addq.w #%d,d7" % off)
                self.e("and.w #$%X,d7" % mask)
                self.e("lea %s,a0" % base)
                self.e("move.b %s,(a0,d7.w)" % src)
            self.e("tst.b %s" % src)
            return
        if self.io_site(v, ins):
            self.stats["io write"] += 1
            a = self.static_addr(ins)
            if a is not None:
                self.e("move.w #$%04X,d7" % ((a + off) & 0xFFFF))
            else:
                self.ea_to_d7(v, ins)
                if off:
                    self.e("addq.w #%d,d7" % off)
            self.e("move.b %s,d5" % src)
            self.e("bsr %s_io_w" % self.p.name)
            self.e("tst.b %s" % src)
            return
        self.e("move.b %s,%s" % (src, self.ea(v, ins, off)))

    def load16(self, v, ins, dst="d7"):
        """dst.w = the 16 bit operand (flags: N Z of the word, V C cleared)"""
        if ins.mode == "imm16":
            self.e("move.w #$%04X,%s" % (ins.arg, dst))
            return
        if self.io_site(v, ins):
            if self.static_addr(ins) is not None:
                self.io_read(v, ins, 0)
                self.e("move.b d7,d5")
                self.e("lsl.w #8,d5")
                self.io_read(v, ins, 1)
            else:
                # the address once (LDD ,X++ increments X once), the second byte at + 1
                self.stats["io read"] += 2
                self.ea_to_d7(v, ins)
                self.e("move.w d7,-(sp)")
                self.e("bsr %s_io_r" % self.p.name)
                self.e("move.b d7,d5")
                self.e("lsl.w #8,d5")
                self.e("move.w (sp)+,d7")
                self.e("addq.w #1,d7")
                self.e("bsr %s_io_r" % self.p.name)
            self.e("move.b d7,d5")
            self.e("move.w d5,%s" % dst)
            return
        a = self.static_addr(ins)
        if a is not None and not a & 1 and (a & 0x1FFF) != 0x1FFF:
            self.e("move.w %s,%s" % (self.ea(v, ins), dst))
            return
        op0, op1 = self.byte_operands(v, ins)
        self.e("move.b %s,-(sp)" % op0)              # (a byte pushed on a7 is the high byte of a word)
        self.e("move.w (sp)+,d6")
        self.e("move.b %s,d6" % op1)
        self.e("move.w d6,%s" % dst)

    def byte_operands(self, v, ins):
        """(high byte operand, low byte operand) of a 16 bit memory operand, its setup emitted (auto increments once)"""
        x = ins.arg if ins.mode == "idx" else None
        if x is not None and x.kind in ("inc1", "inc2", "dec1", "dec2") and not x.indirect:
            op0 = self.ea(v, ins, 0)
            self._inc_done = True
            op1 = self.ea(v, ins, 1)
            self._inc_done = False
        else:
            op0 = self.ea(v, ins, 0)
            op1 = self.ea_again(op0, 1)
        return op0, op1

    def ea_again(self, op, off):
        """the operand string `op` (from ea()) moved by `off` bytes, without new setup code"""
        if op.startswith("("):
            return "%d%s" % (off, op)
        if op.startswith("$"):
            n, rest = op[1:].split("(", 1)
            return "$%X(%s" % (int(n, 16) + off, rest)
        n, rest = op.split("(", 1)
        return "%d(%s" % (int(n) + off, rest)

    def store16(self, v, ins, src):
        """the word in src (a data register) to the operand (flags: N Z of the word, V cleared, C cleared)"""
        a = self.static_addr(ins)
        if a is not None and a >= 0xE000 and not a & 1 and ((a >> 9) & 0xF) < 8:
            self.mmu_static(a, src, word=True)
            return
        fold = self.p.io_fold(v) if self.p.io_fold else None
        if fold and self.io_site(v, ins):
            self.stats["io write folded"] += 2
            base, mask = fold
            self.ea_to_d7(v, ins) if self.static_addr(ins) is None else self.e("move.w #$%04X,d7" % self.static_addr(ins))
            self.e("move.w d7,d6")
            self.e("and.w #$%X,d7" % mask)
            self.e("lea %s,a0" % base)
            self.e("move.w %s,-(sp)" % src)
            self.e("move.b (sp)+,(a0,d7.w)")
            self.e("addq.w #1,d6")
            self.e("and.w #$%X,d6" % mask)
            self.e("move.b %s,(a0,d6.w)" % src)
            self.e("tst.w %s" % src)
            return
        if self.io_site(v, ins):
            self.stats["io write"] += 2
            a = self.static_addr(ins)
            self.e("move.w %s,-(sp)" % src)           # (the runtime uses d5-d7)
            if a is None:
                self.ea_to_d7(v, ins)
                self.e("move.w d7,-(sp)")
            for k in (0, 1):
                if a is not None:
                    self.e("move.w #$%04X,d7" % ((a + k) & 0xFFFF))
                else:
                    self.e("move.w (sp),d7")
                    if k:
                        self.e("addq.w #1,d7")
                off = 0 if a is not None else 2
                if k == 0:
                    self.e("move.w %d(sp),d5" % off)
                    self.e("lsr.w #8,d5")
                else:
                    self.e("move.b %d(sp),d5" % (off + 1))
                self.e("bsr %s_io_w" % self.p.name)
            if a is None:
                self.e("addq.l #2,sp")
            self.e("tst.w (sp)+")
            return
        a = self.static_addr(ins)
        if a is not None and not a & 1 and (a & 0x1FFF) != 0x1FFF:
            self.e("move.w %s,%s" % (src, self.ea(v, ins)))
            return
        op0, op1 = self.byte_operands(v, ins)
        self.e("move.b %s,%s" % (src, op1))
        self.e("move.w %s,-(sp)" % src)
        self.e("move.b (sp)+,%s" % op0)
        self.e("tst.w %s" % src)

    def rmw8(self, v, ins):
        """(operand string, writeback lines) for a read-modify-write of a memory byte"""
        if self.io_site(v, ins):
            raise Unsupported("read-modify-write of I/O: " + ins.text)
        return self.ea(v, ins)

    # ---- flag fixing ---------------------------------------------------------
    def wrap(self, v, ok, body, const_set=0, const_clear=0):
        """body() emits code that leaves the flags in `ok` right (as the 6809 defines them); the live flags the
        6809 leaves unchanged but the body spoils come back from the CCR saved before; flags with a constant
        6809 value (const_set / const_clear) are set after"""
        live = self.live_out.get(v, NZVC) & NZVC
        d, u = defs_uses(self.code[v])
        keep = live & ~d & ~ok                  # unchanged by the 6809, spoiled by the 68000 code
        if keep:
            self.stats["wrapped"] += 1
            self.e("move.w sr,-(sp)")
            body()
            self.e("move.w sr,d6")              # new
            self.e("move.w (sp)+,d7")           # old
            self.e("eor.b d6,d7")
            self.e("and.b #%d,d7" % keep)
            self.e("eor.b d7,d6")               # new with the kept bits from old
            self.e("move.w d6,ccr")
        else:
            body()
        cs, cc = const_set & live, const_clear & live
        if cs:
            self.e("ori #%d,ccr" % cs)
        if cc:
            self.e("andi #%d,ccr" % (0xFF & ~cc))

    def preserve_all(self, v, body):
        """body() spoils every flag and the 6809 instruction keeps them all"""
        live = self.live_out.get(v, NZVC) & NZVC
        if live:
            self.stats["wrapped"] += 1
            self.e("move.w sr,-(sp)")
            body()
            self.e("move.w (sp)+,ccr")
        else:
            body()

    # ---- emission ------------------------------------------------------------
    def emit_all(self):
        for v in sorted(self.code):
            ins = self.code[v]
            self.lines.append("%s:\t\t; %04X %s" % (self.p.label(v), self.p.cpu_pc(v), ins.text))
            if v in self.p.hooks:
                self.e("jmp %s" % self.p.hooks[v])
                continue
            if v in self.p.natives:
                # a hand-written routine replaces the code from here; the translation stays under <label>_t (its
                # fallback, and what the native tests compare it with)
                self.e("jmp %s" % self.p.natives[v])
                self.lines.append("%s_t:" % self.p.label(v))
            try:
                self.emit(v, ins)
            except Unsupported as ex:
                self.unsupported.append("%06X %s: %s" % (v, ins.text, ex))
                self.e("move.w #$%04X,d7" % self.p.cpu_pc(v))
                self.e("jmp %s_unsupported" % self.p.name)
                continue
            # falling through to the next instruction: if it is not the next label, branch
            slot = self.p.slot_of[v >> 13]
            if ins.flow in ("seq", "jcc", "call", "icall"):
                pass

    def next_v(self, v, ins):
        slot = self.p.slot_of[v >> 13]
        nxt = self.p.cpu_pc(v) + ins.length
        if nxt >> 13 != slot:
            return None
        return (v & ~0x1FFF) | (nxt & 0x1FFF)

    def fallthrough(self, v, ins):
        """after a sequential instruction: the next one must follow in the output (else a branch to it)"""
        if self.p.after is not None:
            for line in self.p.after(v, ins) or ():
                self.e(line)
        nv = self.next_v(v, ins)
        if nv is None:
            # the code runs into the next slot: dispatch through its page
            self.e("move.w #$%04X,d7" % ((self.p.cpu_pc(v) + ins.length) & 0xFFFF))
            self.e("jmp %s_dispatch" % self.p.name)
            return
        if nv not in self.code:
            self.e("bra %s" % self.lab(nv))
            return
        # the next label in sorted order is nv when the code is contiguous
        later = [x for x in self.code if v < x < nv]
        if later:
            self.e("bra %s" % self.lab(nv))
        self.refs.add(nv)

    def emit(self, v, ins):
        self.cur_v = v
        mn = ins.mn
        if mn.startswith("x") and mn not in ("xdec",):
            raise Unsupported("undocumented " + mn)
        bm = base_mn(mn)
        fl = ins.flow
        if bm in BRANCH_USES and ins.mode in ("rel8", "rel16"):
            tg = branch_targets(self.p, v, ins)
            if len(tg) == 1 and tg[0] >> 13 == v >> 13:
                self.e("%s %s" % (bm, self.lab(tg[0])))
            else:
                skip = self.new_label()
                self.e("%s %s" % (INV[bm], skip))
                self.jump_to(v, ins.target, tg)
                self.lines.append(skip + ":")
            self.fallthrough(v, ins)
            return
        if bm in ("bra",):
            self.jump_to(v, ins.target, branch_targets(self.p, v, ins))
            return
        if bm == "brn" or mn == "nop":
            self.fallthrough(v, ins)
            return
        if mn == "jmp":
            if fl == "jmp":
                self.jump_to(v, ins.target, branch_targets(self.p, v, ins))
            else:
                self.e("move.w sr,d5")
                self.jump_table(v, ins, None)
                self.ea_to_d7(v, ins)
                self.dispatch(v, saved=True)
            return
        if bm in ("bsr", "jsr"):
            ret = (self.p.cpu_pc(v) + ins.length) & 0xFFFF
            live = self.live_out.get(v, NZVC) & NZVC
            if live or not self.p.nf_dispatch:
                self.e("move.w sr,d5")
            if fl == "icall":
                self.jump_table(v, ins, ret)
                self.ea_to_d7(v, ins)
            self.e("move.b #$%02X,-(a5)" % (ret & 0xFF))
            self.e("move.b #$%02X,-(a5)" % (ret >> 8))
            if fl == "icall":
                self.dispatch(v, saved=True)
            else:
                self.jump_to(v, ins.target, branch_targets(self.p, v, ins), saved=bool(live or not self.p.nf_dispatch),
                             live=live or not self.p.nf_dispatch)
            return
        if mn == "rts":
            self.emit_ret(v)
            return
        if mn in ("puls", "pulu"):
            self.emit_pull(v, ins)
            if not ins.arg & 0x80:
                self.fallthrough(v, ins)
            return
        if mn in ("pshs", "pshu"):
            self.emit_push(v, ins)
            self.fallthrough(v, ins)
            return
        if mn == "rti":
            self.emit_rti(v)
            return
        self.emit_data(v, ins)
        if ins.flow == "ijmp":
            return
        self.fallthrough(v, ins)

    # ---- control flow --------------------------------------------------------
    def jump_to(self, v, target, tg, saved=False, live=True):
        """a jump to the 6809 address target (tg: its virtual targets: one in this slot, or the pages the coverage saw).
        saved: d5 holds the SR to restore before the transfer (the code before spoiled the CCR).  live false: no
        flags are read at the target (nothing to keep)."""
        slot = self.p.slot_of[v >> 13]
        if target >> 13 == slot and tg:
            if saved:
                self.e("move.w d5,ccr")
            self.e("bra %s" % self.lab(tg[0]))
            return
        tslot = target >> 13
        if not saved and tg and live:
            self.e("move.w sr,d5")
            saved = True
        if len(tg) == 1 and self.fixed_slot(tslot):
            # (the only code page that runs from that slot)
            if saved:
                self.e("move.w d5,ccr")
            self.e("bra %s" % self.lab(tg[0]))
            return
        for t in tg:
            skip = self.new_label()
            self.page_cmp(t >> 13, tslot)
            self.e("bne.s %s" % skip)
            if saved:
                self.e("move.w d5,ccr")
            self.e("bra %s" % self.lab(t))
            self.lines.append(skip + ":")
        self.stats["cross-slot dispatch"] += 1
        self.e("move.w #$%04X,d7" % target)
        if saved:
            self.e("move.w d5,ccr")
        self.dispatch_jump(live)

    def jump_table(self, v, ins, ret):
        """JMP / JSR [A,X] or [B,X] right after LDX #table (only A / B loads and shifts between): when the entries are
        code in slot 7 or in this instruction's page, a 68000 table of labels serves the even indexes up to its
        length (the ROM table's page checked when its slot has others); anything else goes on to the generic code
        after this.  d5 = the SR to restore."""
        x = ins.arg
        if ins.mode != "idx" or not x.indirect or x.reg != "x" or x.kind not in ("acc_a", "acc_b"):
            return
        prev = []
        w = v
        xcheck = False                  # (a join between the LDX and here: X is checked at run time)
        for _ in range(4):
            cands = [u for u in self.code if u < w and self.next_v(u, self.code[u]) == w]
            if len(cands) != 1:
                return
            if w in self.joins and w != v:
                xcheck = True
            w = cands[0]
            pi = self.code[w]
            if pi.mn == "ldx" and pi.mode == "imm16":
                table = pi.arg
                break
            if pi.mn not in ("lda", "ldb", "asla", "aslb", "lsla", "lslb", "pshs", "tsta", "tstb"):
                return
            if pi.mn == "pshs" and pi.arg & 0x10:
                return
        else:
            return
        tslot = table >> 13
        own = self.p.slot_of[v >> 13]
        if tslot == own:
            tpage = v >> 13
        elif self.fixed_slot(tslot) and len(self.p.slot_pages.get(tslot, ())) == 1:
            tpage = next(iter(self.p.slot_pages[tslot]))
        else:
            pages = {pg for rw, sl, pg, odd in self.p.acc_cover.get(v, ()) if rw == "r" and sl == tslot}
            if len(pages) != 1:
                return
            tpage = next(iter(pages))
        data = self.p.page(tpage)
        entries = []
        # targets in another bankable slot: the page the coverage saw this site go to there (one page: checked at run
        # time before the table is used)
        seen = collections.defaultdict(set)
        for t in self.p.targets.get(v, ()):
            seen[self.p.slot_of.get(t >> 13)].add(t >> 13)
        checks = set()
        for k in range(64):
            o = (table & 0x1FFF) + 2 * k
            if o + 1 >= 0x2000:
                break
            t = (data[o] << 8) | data[o + 1]
            ts = t >> 13
            if ts == own:
                tv = (v & ~0x1FFF) | (t & 0x1FFF)
            elif self.fixed_slot(ts) and len(self.p.slot_pages.get(ts, ())) == 1:
                tv = (next(iter(self.p.slot_pages[ts])) << 13) | (t & 0x1FFF)
            elif len(seen.get(ts, ())) == 1:
                pg = next(iter(seen[ts]))
                tv = (pg << 13) | (t & 0x1FFF)
                if not (self.fixed_slot(ts) and len(self.p.slot_pages.get(ts, ())) == 1):
                    checks.add((ts, pg))
            else:
                break
            if tv not in self.code:
                break
            entries.append(tv)
        if len(entries) < 2:
            return
        self.stats["jump table"] += 1
        generic = self.new_label()
        generic = "%s_jx%s" % (self.p.label(v), generic[2:])     # (global: the table's stubs lie between)
        tab = "%s_jt%d" % (self.p.label(v), self.uid)
        if tpage != v >> 13 and not (self.fixed_slot(tslot) and len(self.p.slot_pages.get(tslot, ())) == 1):
            checks.add((tslot, tpage))
        if xcheck:
            self.e("cmp.w #$%04X,d2" % table)
            self.e("bne %s" % generic)
        for ts, pg in sorted(checks):
            self.page_cmp(pg, ts)
            self.e("bne %s" % generic)
        # the table has an entry for every index below its length: the odd ones go to the generic code (a global
        # label: the table lies after the code); a target that is an RTS returns at once (a JSR's own return: the
        # pushed address, the page as it is); no CCR restore when no target reads flags
        gl = "%s_jg%d" % (self.p.label(v), self.uid)
        reg = "d0" if x.kind == "acc_a" else "d1"
        self.e("cmp.b #%d,%s" % (2 * len(entries), reg))
        self.e("bcc %s" % generic)
        self.e("moveq #0,d7")
        self.e("move.b %s,d7" % reg)
        self.e("add.w d7,d7")
        self.e("add.w d7,d7")
        self.e("lea %s,a0" % tab)
        self.e("move.l (a0,d7.w),a0")
        if ret is not None:
            self.e("move.b #$%02X,-(a5)" % (ret & 0xFF))
            self.e("move.b #$%02X,-(a5)" % (ret >> 8))
        rv = (v & ~0x1FFF) | (ret & 0x1FFF) if ret is not None else None
        stub = None
        if rv is not None and ret >> 13 == self.p.cpu_pc(v) >> 13 and rv in self.code and \
                any(self.code[tv].mn == "rts" and tv not in self.p.hooks for tv in entries):
            stub = "%s_jr%d" % (self.p.label(v), self.uid)
        if any(self.live_in.get(tv, NZVC) & NZVC for tv in entries if not (stub and self.code[tv].mn == "rts")):
            self.e("move.w d5,ccr")
        elif stub and any(self.live_in.get(rv, NZVC) & NZVC for tv in entries):
            self.e("move.w d5,ccr")
        self.e("jmp (a0)")
        self.lines.append(gl + ":")
        self.e("bra %s" % generic)
        if stub:
            self.lines.append(stub + ":")
            self.e("addq.l #2,a5")                          # (the RTS: the address just pushed)
            self.e("bra %s" % self.lab(rv))
        self.tail.append("\teven")
        self.tail.append("%s:" % tab)
        for tv in entries:
            t = stub if stub and self.code[tv].mn == "rts" and tv not in self.p.hooks else self.lab(tv)
            self.tail.append("\tdc.l %s" % t)
            self.tail.append("\tdc.l %s" % gl)
        self.lines.append(generic + ":")

    def page_cmp(self, page, slot):
        """the CCR's Z = the slot holds the page (its page number when the runtime keeps them: cheaper than PB)"""
        if self.p.pid_checks:
            self.e("cmp.w #$%X,%d(a6)" % (page, PID_OFF + 2 * slot))
        else:
            self.e("cmp.l #%s,%d(a6)" % (self.p.page_addr(page), 4 * slot))

    def live_flags(self, v):
        return self.live_out.get(v, NZVC) & NZVC

    def dispatch_jump(self, live):
        """jmp to the dispatcher (the one that keeps no CCR when no flags are live and the runtime has it)"""
        if not live and self.p.nf_dispatch:
            self.e("jmp %s_dispatch_nf" % self.p.name)
        else:
            self.e("jmp %s_dispatch" % self.p.name)

    def dispatch(self, v, saved=False):
        """jump to the 6809 address in d7 (computed jump); the CCR is right (or in d5 when saved)"""
        live = self.live_flags(v)
        if not live and self.p.nf_dispatch:
            known = [t for t in sorted(self.p.targets.get(v, ())) if t >> 13 in self.p.slot_of and t in self.code]
            if len(known) > 3:
                known = []
            for t in known:
                pc = self.p.cpu_pc(t)
                skip = self.new_label()
                self.e("cmp.w #$%04X,d7" % pc)
                self.e("bne.s %s" % skip)
                if not self.fixed_slot(pc >> 13):
                    self.page_cmp(t >> 13, pc >> 13)
                    self.e("bne.s %s" % skip)
                self.e("bra %s" % self.lab(t))
                self.lines.append(skip + ":")
            self.dispatch_jump(0)
            return
        if not saved:
            self.e("move.w sr,d5")
        known = [t for t in sorted(self.p.targets.get(v, ())) if t >> 13 in self.p.slot_of and t in self.code]
        if len(known) > 3:
            known = []                            # (a jump table: the dispatcher is cheaper than the compares)
        for t in known:
            if True:
                pc = self.p.cpu_pc(t)
                skip = self.new_label()
                self.e("cmp.w #$%04X,d7" % pc)
                self.e("bne.s %s" % skip)
                self.page_cmp(t >> 13, pc >> 13)
                self.e("bne.s %s" % skip)
                self.e("move.w d5,ccr")
                self.e("bra %s" % self.lab(t))
                self.lines.append(skip + ":")
        self.e("move.w d5,ccr")
        self.e("jmp %s_dispatch" % self.p.name)

    def ret_cands(self, v):
        """return points of the functions whose code reaches the RTS at v (a guess, checked at run time)"""
        return self.ret_points.get(v, set())

    def emit_ret(self, v):
        """pop the return address; its callers' return points directly, else the dispatcher.  The flags pass: the
        pops are byte moves into d7 under a saved SR when the callers read flags."""
        live = self.live_out.get(v, NZVC) & NZVC
        if live:
            self.e("move.w sr,d5")
        self.e("move.b (a5)+,-(sp)")
        self.e("move.w (sp)+,d7")
        self.e("move.b (a5)+,d7")
        cands = sorted(self.ret_cands(v))
        for t in cands:
            pc = self.p.cpu_pc(t)
            skip = self.new_label()
            self.e("cmp.w #$%04X,d7" % pc)
            self.e("bne.s %s" % skip)
            if not self.fixed_slot(pc >> 13):
                self.page_cmp(t >> 13, pc >> 13)
                self.e("bne.s %s" % skip)
            if live:
                self.e("move.w d5,ccr")
            self.e("bra %s" % self.lab(t))
            self.lines.append(skip + ":")
        if live:
            self.e("move.w d5,ccr")
        self.dispatch_jump(live)

    def fixed_slot(self, slot):
        """a slot from which only one code page runs (Program.fixed_slots; default slot 7, the vectors): code that
        returns or jumps there needs no page check"""
        return slot in getattr(self.p, "fixed_slots", (7,))

    def emit_rti(self, v):
        """pull CC; E set: A B DP X Y U; PC; then dispatch with the pulled flags"""
        self.e("move.b (a5)+,d5")                       # CC
        self.e("move.b d5,%d(a6)" % CCHI_OFF)
        self.e("tst.b d5")
        skip = self.new_label()
        self.e("bpl.s %s" % skip)                       # E (bit 7)
        self.e("move.b (a5)+,d0")
        self.e("move.b (a5)+,d1")
        self.e("addq.l #1,a5")                          # DP (the program's constant)
        for r in ("d2", "d3", "d4"):
            self.e("move.b (a5)+,d6")
            self.e("lsl.w #8,d6")
            self.e("move.b (a5)+,d6")
            self.e("move.w d6,%s" % r)
        self.lines.append(skip + ":")
        self.e("moveq #0,d7")
        self.e("move.b (a5)+,d7")
        self.e("lsl.w #8,d7")
        self.e("move.b (a5)+,d7")
        self.e("and.w #$0F,d5")
        self.e("move.w d5,ccr")
        self.e("jmp %s_dispatch" % self.p.name)

    # ---- stack ---------------------------------------------------------------
    STACK_REGS = [(0x80, "pc"), (0x40, "us"), (0x20, "y"), (0x10, "x"), (0x08, "dp"), (0x04, "b"), (0x02, "a"),
                  (0x01, "cc")]

    def stack_ptr(self, mn):
        """(68000 operand prefix: a5 for S, else a1 loaded from U)"""
        return "a5" if mn.endswith("s") else "a1"

    def emit_push(self, v, ins):
        user = ins.mn == "pshu"
        mask = ins.arg
        live = self.live_out.get(v, NZVC) & NZVC
        self.e("move.w sr,d5")                    # (the CC byte comes from here; pushes spoil the CCR)
        if user:
            self.u_to_a1()
        sp = "a1" if user else "a5"
        ret = (self.p.cpu_pc(v) + ins.length) & 0xFFFF
        for bit, r in self.STACK_REGS:
            if not mask & bit:
                continue
            if r == "pc":
                self.e("move.b #$%02X,-(%s)" % (ret & 0xFF, sp))
                self.e("move.b #$%02X,-(%s)" % (ret >> 8, sp))
            elif r in ("x", "y", "us"):
                if r == "us":
                    if user:
                        self.s_value_d6()
                        src = "d6"
                    else:
                        src = "d4"
                else:
                    src = REG16[r]
                self.e("move.b %s,-(%s)" % (src, sp))
                self.e("move.w %s,-(sp)" % src)         # (the high byte through the stack: no shift)
                self.e("move.b (sp)+,-(%s)" % sp)
            elif r == "dp":
                dp = self.p.dp_at(v)
                self.e("move.b #$%02X,-(%s)" % (dp, sp) if dp else "clr.b -(%s)" % sp)
            elif r == "b":
                self.e("move.b d1,-(%s)" % sp)
            elif r == "a":
                self.e("move.b d0,-(%s)" % sp)
            elif r == "cc":
                self.e("move.b d5,d7")
                self.e("and.b #$0F,d7")
                self.e("move.b %d(a6),d6" % CCHI_OFF)
                self.e("and.b #$F0,d6")
                self.e("or.b d6,d7")
                self.e("move.b d7,-(%s)" % sp)
        if user:
            self.a1_to_u()
        if live:
            self.e("move.w d5,ccr")

    def emit_pull(self, v, ins):
        user = ins.mn == "pulu"
        mask = ins.arg
        sp = "a1" if user else "a5"
        live = self.live_out.get(v, NZVC) & NZVC
        cc_pulled = bool(mask & 1)
        save = live and not cc_pulled
        if save:
            self.stats["wrapped"] += 1
            self.e("move.w sr,-(sp)")
        if user:
            self.u_to_a1()
        new_s = False
        for bit, r in reversed(self.STACK_REGS):
            if not mask & bit:
                continue
            if r == "cc":
                self.e("move.b (%s)+,d5" % sp)
                self.e("move.b d5,%d(a6)" % CCHI_OFF)
            elif r == "a":
                self.e("move.b (%s)+,d0" % sp)
            elif r == "b":
                self.e("move.b (%s)+,d1" % sp)
            elif r == "dp":
                self.e("addq.l #1,%s" % sp)
            elif r in ("x", "y", "us"):
                if r == "us" and user:
                    new_s = True
                    self.e("move.b (%s)+,d6" % sp)
                    self.e("lsl.w #8,d6")
                    self.e("move.b (%s)+,d6" % sp)
                    self.e("move.w d6,-(sp)")
                else:
                    dr = "d4" if r == "us" else REG16[r]     # (the high byte through the stack: no shift)
                    self.e("move.b (%s)+,-(sp)" % sp)
                    self.e("move.w (sp)+,%s" % dr)
                    self.e("move.b (%s)+,%s" % (sp, dr))
            elif r == "pc":
                self.e("move.b (%s)+,-(sp)" % sp)
                self.e("move.w (sp)+,d7")
                self.e("move.b (%s)+,d7" % sp)
        if user:
            self.a1_to_u()
            if new_s:
                raise Unsupported("PULU S")
        if save:
            self.e("move.w (sp)+,ccr")
        if cc_pulled:
            self.e("move.b %d(a6),d5" % CCHI_OFF)
            self.e("and.w #$0F,d5")
            self.e("move.w d5,ccr")
        if mask & 0x80:
            if user:
                raise Unsupported("PULU PC")
            # a return: the callers' return points, else dispatch (the flags as pulled / as they were)
            cands = sorted(self.ret_cands(v))
            keep = bool(self.live_flags(v) or not self.p.nf_dispatch)
            if cands and keep:
                self.e("move.w sr,d5")
            for t in cands:
                pc = self.p.cpu_pc(t)
                skip = self.new_label()
                self.e("cmp.w #$%04X,d7" % pc)
                self.e("bne.s %s" % skip)
                if not self.fixed_slot(pc >> 13):
                    self.page_cmp(t >> 13, pc >> 13)
                    self.e("bne.s %s" % skip)
                if keep:
                    self.e("move.w d5,ccr")
                self.e("bra %s" % self.lab(t))
                self.lines.append(skip + ":")
            if cands and keep:
                self.e("move.w d5,ccr")
            self.dispatch_jump(keep)

    def u_to_a1(self):
        """a1 = the 68000 address of U (its slot from the value)"""
        self.e("move.w d4,d6")
        self.e("rol.w #3,d6")
        self.e("and.w #7,d6")
        self.e("add.w d6,d6")
        self.e("add.w d6,d6")
        self.e("move.l %d(a6,d6.w),a1" % VB_OFF)
        self.e("move.l a1,-(sp)")
        self.e("add.l d4,a1")

    def a1_to_u(self):
        self.e("move.l a1,d6")
        self.e("sub.l (sp)+,d6")
        self.e("move.w d6,d4")

    def s_value_d6(self):
        """d6 = S as a 6809 value"""
        self.e("move.l a5,d6")
        self.e("sub.l %s,d6" % self.s_base())

    def s_base(self):
        """the operand holding VB of the stack's slot"""
        return "%d(a6)" % SBASE_OFF if self.p.dynamic_stack else "a3"

    def set_s_d7(self):
        """S = d7.w (upper word may be anything): a5 from the stack's slot (dynamic_stack: the slot of S - 1)"""
        self.e("and.l #$FFFF,d7")
        if not self.p.dynamic_stack:
            self.e("move.l a3,a5")
            self.e("add.l d7,a5")
            return
        self.e("move.w d7,d6")
        self.e("subq.w #1,d6")
        self.e("rol.w #3,d6")
        self.e("and.w #7,d6")
        self.e("add.w d6,d6")
        self.e("add.w d6,d6")
        self.e("move.w d6,%d(a6)" % SSLOT_OFF)
        self.e("move.l %d(a6,d6.w),a5" % VB_OFF)
        self.e("move.l a5,%d(a6)" % SBASE_OFF)
        self.e("add.l d7,a5")

    def cc_byte_d7(self):
        """d7 = the 6809 CC byte: N Z V C from the CCR, E F H I from the context"""
        self.e("move.w sr,d7")
        self.e("and.b #$0F,d7")
        self.e("move.b %d(a6),d6" % CCHI_OFF)
        self.e("and.b #$F0,d6")
        self.e("or.b d6,d7")

    # ---- data instructions ---------------------------------------------------
    def emit_data(self, v, ins):
        mn = ins.mn
        if mn in ("lda", "ldb"):
            r = REG8[mn[-1]]
            self.wrap(v, N | Z | V, lambda: self.load8(v, ins, r))
            return
        if mn in ("sta", "stb"):
            r = REG8[mn[-1]]
            a = self.static_addr(ins)
            if a is not None and self.is_watchdog(a):
                self.wrap(v, N | Z | V, lambda: self.e("tst.b %s" % r))
                return
            self.wrap(v, N | Z | V, lambda: self.store8(v, ins, r))
            return
        if mn in ("ldx", "ldy", "ldu"):
            r = REG16[mn[-1]]
            self.wrap(v, N | Z | V, lambda: self.load16(v, ins, r))
            return
        if mn == "lds":
            def b():
                self.load16(v, ins, "d7")
                self.e("move.w d7,-(sp)")
                self.set_s_d7()
                self.e("tst.w (sp)+")
            self.wrap(v, N | Z | V, b)
            return
        if mn == "ldd":
            live = self.live_out.get(v, NZVC) & NZVC
            if ins.mode == "imm16":
                if not live:
                    self.e("move.b #$%02X,d0" % (ins.arg >> 8))
                    self.e("move.b #$%02X,d1" % (ins.arg & 0xFF))
                    return

                def bi():
                    self.e("move.b #$%02X,d0" % (ins.arg >> 8))
                    self.e("move.b #$%02X,d1" % (ins.arg & 0xFF))
                    self.e("move.w #$%04X,d6" % ins.arg)       # (N Z of the word; C comes back in the wrapper)
                self.wrap(v, N | Z | V, bi)
                return

            def b():
                a = self.static_addr(ins)
                if self.io_site(v, ins) or (a is not None and not a & 1 and (a & 0x1FFF) != 0x1FFF):
                    self.load16(v, ins, "d7")
                    self.e("move.b d7,d1")
                    self.e("move.w d7,-(sp)")
                    self.e("move.b (sp)+,d0")
                    if live:
                        self.e("tst.w d7")
                    return
                op0, op1 = self.byte_operands(v, ins)
                self.e("move.b %s,d0" % op0)
                self.e("move.b %s,d1" % op1)
                if live:
                    self.e("move.b d0,-(sp)")
                    self.e("move.w (sp)+,d6")
                    self.e("move.b d1,d6")
                    self.e("tst.w d6")
            self.wrap(v, N | Z | V, b)
            return
        if mn in ("stx", "sty", "stu"):
            r = REG16[mn[-1]]
            self.wrap(v, N | Z | V, lambda: self.store16(v, ins, r))
            return
        if mn == "sts":
            def b():
                self.s_value_d6()
                self.e("move.w d6,d5")
                self.store16(v, ins, "d5")
            self.wrap(v, N | Z | V, b)
            return
        if mn == "std":
            live = self.live_out.get(v, NZVC) & NZVC
            a = self.static_addr(ins)

            def b():
                if self.io_site(v, ins) or (a is not None and (a >= 0xE000 or not a & 1)):
                    self.d_to("d5")
                    self.store16(v, ins, "d5")
                    return
                op0, op1 = self.byte_operands(v, ins)
                self.e("move.b d0,%s" % op0)
                self.e("move.b d1,%s" % op1)
                if live:
                    self.e("move.b d0,-(sp)")
                    self.e("move.w (sp)+,d6")
                    self.e("move.b d1,d6")
                    self.e("tst.w d6")
            self.wrap(v, N | Z | V, b)
            return
        if mn[:-1] in ("add", "sub", "cmp") and mn[-1] in "ab" and mn not in ("addd", "subd"):
            r = REG8[mn[-1]]
            op = mn[:-1]
            h_live = self.live_out.get(v, NZVC) & H and op == "add"
            if h_live:
                self.half_carry(v, ins, r, False)       # (loads the operand into d6)
                self.e("add.b d6,%s" % r)
                return
            src = self.src8(v, ins)
            self.e("%s.b %s,%s" % (op, src, r))
            return
        if mn in ("adca", "adcb", "sbca", "sbcb"):
            r = REG8[mn[-1]]
            h_live = self.live_out.get(v, NZVC) & H and mn.startswith("adc")
            if h_live:
                self.half_carry(v, ins, r, True)
            if not h_live:
                self.e("scs d5")                      # C before the operand's load spoils it
                self.load_src_d6(v, ins)
            self.e("neg.b d5")
            self.e("lsr.b #1,d5")                     # X = C, Z = 1
            self.e("%s.b d6,%s" % ("addx" if mn.startswith("adc") else "subx", r))
            return
        if mn in ("anda", "andb", "ora", "orb", "eora", "eorb", "bita", "bitb"):
            r = REG8[mn[-1]]
            op = {"and": "and", "or": "or", "eor": "eor", "bit": "and"}[mn[:-1]]

            def b():
                if op == "eor":
                    self.load_src_d6(v, ins)
                    self.e("eor.b d6,%s" % r)
                elif mn.startswith("bit"):
                    s_ = self.src8(v, ins)
                    self.e("move.b %s,d5" % r)
                    self.e("and.b %s,d5" % s_)
                else:
                    self.e("%s.b %s,%s" % (op, self.src8(v, ins), r))
            self.wrap(v, N | Z | V, b)
            return
        if mn in ("addd", "subd"):
            op = "add" if mn == "addd" else "sub"

            if ins.mode == "imm16":
                self.e("move.b #$%02X,d6" % (ins.arg >> 8))
                self.e("%s.b #$%02X,d1" % (op, ins.arg & 0xFF))
            elif self.io_site(v, ins):
                self.load16(v, ins, "d7")
                self.e("move.w d7,-(sp)")
                self.e("move.b (sp)+,d6")
                self.e("%s.b d7,d1" % op)
            else:
                op0, op1 = self.byte_operands(v, ins)
                self.e("move.b %s,d6" % op0)
                self.e("%s.b %s,d1" % (op, op1))
            self.e("%sx.b d6,d0" % op)
            return
        if mn in ("cmpd", "cmpx", "cmpy", "cmpu", "cmps"):
            if mn == "cmpd":
                self.d_to("d5")
                reg = "d5"
            elif mn == "cmps":
                self.s_value_d6()
                self.e("move.w d6,d5")
                reg = "d5"
            else:
                reg = REG16[mn[-1]]
            if ins.mode == "imm16":
                self.e("cmp.w #$%04X,%s" % (ins.arg, reg))
            else:
                self.load16(v, ins, "d7")
                self.e("cmp.w d7,%s" % reg)
            return
        if mn in ("clra", "clrb"):
            self.e("moveq #0,%s" % REG8[mn[-1]]) if self.live_out.get(v, NZVC) else self.e("clr.b %s" % REG8[mn[-1]])
            return
        if mn == "clr":
            a = self.static_addr(ins)
            if a is not None and a >= 0xE000:
                self.e("moveq #0,d6")
                self.mmu_static(a, "d6") if ((a >> 9) & 0xF) not in range(8) or True else None
                self.e("moveq #0,d6")
                return
            if self.io_site(v, ins):
                self.e("moveq #0,d6")
                self.store8(v, ins, "d6")
                self.e("moveq #0,d6")
                return
            self.e("clr.b %s" % self.ea(v, ins))
            return
        if mn in ("nega", "negb", "coma", "comb", "inca", "incb", "deca", "decb", "tsta", "tstb", "asla", "aslb",
                  "lsla", "lslb", "lsra", "lsrb", "asra", "asrb", "rola", "rolb", "rora", "rorb"):
            self.unary(v, ins, mn[:-1], REG8[mn[-1]])
            return
        if mn in ("neg", "com", "inc", "dec", "tst", "asl", "lsl", "lsr", "asr", "rol", "ror"):
            if self.io_site(v, ins):
                raise Unsupported("read-modify-write of I/O: " + ins.text)
            self.unary(v, ins, mn, None)
            return
        if mn in ("leax", "leay", "leau", "leas"):
            self.emit_lea(v, ins)
            return
        if mn in ("tfr", "exg"):
            self.emit_tfr(v, ins)
            return
        if mn == "abx":
            def b():
                self.e("moveq #0,d7")
                self.e("move.b d1,d7")
                self.e("add.w d7,d2")
            self.preserve_all(v, b)
            return
        if mn == "sex":
            def b():
                self.e("move.b d1,d0")
                self.e("ext.w d0")
                self.e("lsr.w #8,d0")
                self.e("tst.b d1")
            self.wrap(v, N | Z, b)
            return
        if mn == "mul":
            if self.live_out.get(v, NZVC) & (Z | C):
                self.e("bsr m6809_mul")
                return
            def b():
                self.e("moveq #0,d7")
                self.e("move.b d0,d7")
                self.e("moveq #0,d6")
                self.e("move.b d1,d6")
                self.e("mulu d6,d7")
                self.e("move.b d7,d1")
                self.e("move.w d7,-(sp)")
                self.e("move.b (sp)+,d0")
            self.preserve_all(v, b)
            return
        if mn == "daa":
            self.e("bsr m6809_daa")
            return
        if mn in ("andcc", "orcc"):
            # the CC byte: N Z V C in the CCR, the others in the context
            self.cc_byte_d7()
            self.e("%s.b #$%02X,d7" % ("and" if mn == "andcc" else "or", ins.arg))
            self.e("move.b d7,%d(a6)" % CCHI_OFF)
            self.e("and.w #$0F,d7")
            self.e("move.w d7,ccr")
            return
        raise Unsupported(ins.text)

    def is_watchdog(self, a):
        return 0xF200 <= a < 0xF400

    def d_to(self, reg):
        self.e("move.b d0,-(sp)")
        self.e("move.w (sp)+,%s" % reg)
        self.e("move.b d1,%s" % reg)

    def set_const_flags(self, v, mask, value):
        """flags in mask to value (the others kept)"""
        self.e("andi #%d,ccr" % (0xFF & ~mask))
        if value:
            self.e("ori #%d,ccr" % value)

    def src8(self, v, ins):
        """a source operand for an ALU op (an immediate, a memory operand, or d6 for I/O)"""
        if ins.mode == "imm8":
            return "#$%02X" % ins.arg
        if self.io_site(v, ins):
            self.io_read(v, ins)
            self.e("move.b d7,d6")
            return "d6"
        return self.ea(v, ins)

    def load_src_d6(self, v, ins):
        if ins.mode == "imm8":
            self.e("move.b #$%02X,d6" % ins.arg)
        else:
            self.e("move.b %s,d6" % self.src8(v, ins))

    def half_carry(self, v, ins, r, with_carry):
        """H of an 8 bit add into the context (bit 5 of the CC byte), for the DAA after it; leaves the operand in
        d6 (loaded once: an auto increment must happen once), and for ADC the carry in d5 (scs)"""
        self.stats["half carry"] += 1
        self.e("scs d5")
        self.load_src_d6(v, ins)
        self.e("move.b d6,d7")
        self.e("and.b #$0F,d7")
        self.e("move.b %s,-(sp)" % r)
        self.e("and.b #$0F,(sp)")
        self.e("add.b (sp)+,d7")
        if with_carry:
            self.e("tst.b d5")
            self.e("beq.s *+4")
            self.e("addq.b #1,d7")
        self.e("and.b #$%02X,%d(a6)" % (0xFF & ~H, CCHI_OFF))
        self.e("cmp.b #$10,d7")
        self.e("bcs.s *+8")
        self.e("or.b #$%02X,%d(a6)" % (H, CCHI_OFF))

    def unary(self, v, ins, op, r):
        """NEG COM INC DEC TST ASL LSR ASR ROL ROR on a register (r) or memory (r None).  The operand's address code
        runs inside the flag wrapper (it may spoil the CCR: increments, slot lookups); ROL / ROR take C first."""
        def opnd():
            return r if r else self.ea(v, ins)
        if op == "neg":
            self.e("neg.b %s" % opnd())
        elif op == "com":
            self.wrap(v, N | Z | V, lambda: self.e("not.b %s" % opnd()), const_set=C)
        elif op in ("inc", "dec"):
            self.wrap(v, N | Z | V, lambda: self.e("%s.b #1,%s" % ("addq" if op == "inc" else "subq", opnd())))
        elif op == "tst":
            self.wrap(v, N | Z | V, lambda: self.e("tst.b %s" % opnd()))
        elif op in ("asl", "lsl"):
            if r:
                self.e("add.b %s,%s" % (r, r))
            else:
                ea = opnd()
                self.e("move.b %s,d5" % ea)
                self.e("add.b d5,d5")
                self.e("move.w sr,d6")
                self.e("move.b d5,%s" % ea)
                self.e("move.w d6,ccr")
        elif op in ("lsr", "asr"):
            def b():
                if r:
                    self.e("%s.b #1,%s" % (op, r))
                else:
                    ea = opnd()
                    self.e("move.b %s,d5" % ea)
                    self.e("%s.b #1,d5" % op)
                    self.e("move.w sr,d6")
                    self.e("move.b d5,%s" % ea)
                    self.e("move.w d6,ccr")
            self.wrap(v, N | Z | C, b)
        elif op in ("rol", "ror"):
            live = self.live_out.get(v, NZVC)
            rol_v = op == "rol" and live & V
            rot = "roxl" if op == "rol" else "roxr"

            def b():
                self.e("scs d5")
                if r:
                    self.e("neg.b d5")
                    self.e("lsr.b #1,d5")             # X = C
                    self.e("%s.b #1,%s" % (rot, r))
                else:
                    ea = opnd()
                    self.e("move.b %s,d6" % ea)
                    self.e("neg.b d5")
                    self.e("lsr.b #1,d5")
                    self.e("%s.b #1,d6" % rot)
                    self.e("move.w sr,d5")
                    self.e("move.b d6,%s" % ea)
                    self.e("move.w d5,ccr")
                if rol_v:
                    # V = N xor C (roxl clears it)
                    self.e("move.w sr,d6")
                    self.e("move.b d6,d7")
                    self.e("lsr.b #3,d7")
                    self.e("eor.b d6,d7")
                    self.e("and.b #1,d7")
                    self.e("add.b d7,d7")
                    self.e("or.b d7,d6")
                    self.e("move.w d6,ccr")
            self.wrap(v, N | Z | C | (V if rol_v else 0), b)
        else:
            raise Unsupported(ins.text)

    def emit_lea(self, v, ins):
        mn = ins.mn
        x = ins.arg
        dst = mn[-1]

        def ea_value():
            """d7 = the effective address as a 16 bit value (upper word 0); increments done"""
            if x.indirect:
                self.ea_to_d7(v, ins)
                return
            if x.reg == "s" and x.kind in ("off5", "off8", "off16", "zero"):
                self.s_value_d6()
                self.e("moveq #0,d7")
                self.e("move.w d6,d7")
                if x.offset:
                    self.e("add.w #%d,d7" % x.offset)
                return
            self.ea_to_d7(v, ins)
        if dst == "s" and x.reg == "s" and not x.indirect and x.kind in ("off5", "off8", "off16", "zero"):
            if x.offset:
                self.e("lea %d(a5),a5" % x.offset)
            return
        if dst in ("x", "y") and x.reg == dst and not x.indirect and x.kind in ("off5", "off8", "off16"):
            r = REG16[dst]

            def b():
                off = x.offset
                if 1 <= off <= 8:
                    self.e("addq.w #%d,%s" % (off, r))
                elif -8 <= off <= -1:
                    self.e("subq.w #%d,%s" % (-off, r))
                else:
                    self.e("add.w #%d,%s" % (off, r))
            self.wrap(v, Z, b)
            return
        if dst in ("x", "y") and x.reg == dst and not x.indirect and x.kind in ("acc_a", "acc_b", "acc_d"):
            r = REG16[dst]

            def b():
                if x.kind == "acc_d":
                    self.e("move.b d0,-(sp)")
                    self.e("move.w (sp)+,d6")
                    self.e("move.b d1,d6")
                else:
                    self.e("move.b %s,d6" % ("d0" if x.kind == "acc_a" else "d1"))
                    self.e("ext.w d6")
                self.e("add.w d6,%s" % r)
            self.wrap(v, Z, b)
            return
        if dst in ("x", "y"):
            r = REG16[dst]

            def b():
                ea_value()
                self.e("move.w d7,%s" % r)
            self.wrap(v, Z, b)
            return
        if dst == "u":
            def b():
                ea_value()
                self.e("move.w d7,d4")
            self.preserve_all(v, b)
            return
        # LEAS from another register
        def b():
            ea_value()
            self.set_s_d7()
        self.preserve_all(v, b)

    REGNUM = {0: "d", 1: "x", 2: "y", 3: "u", 4: "s", 5: "pc", 8: "a", 9: "b", 10: "cc", 11: "dp"}

    def emit_tfr(self, v, ins):
        mn = ins.mn
        src, dst = self.REGNUM.get(ins.arg >> 4), self.REGNUM.get(ins.arg & 15)
        if mn == "tfr" and dst == "pc" and src in ("d", "x", "y", "u", "s"):
            # a computed jump
            self.e("move.w sr,d5")
            self.get16_d7(src)
            self.dispatch(v, saved=True)
            return
        if src is None or dst is None or "pc" in (src, dst):
            raise Unsupported(ins.text)
        size = lambda r: 16 if r in ("d", "x", "y", "u", "s") else 8
        if size(src) != size(dst):
            raise Unsupported("mixed sizes " + ins.text)
        if mn == "exg":
            if "cc" in (src, dst) or "dp" in (src, dst):
                raise Unsupported(ins.text)

            def b():
                self.get16_d7(src) if size(src) == 16 else self.e("move.b %s,d7" % REG8[src])
                if size(src) == 16:
                    self.e("move.w d7,-(sp)")
                    self.get16_d7(dst)
                    self.set16(src, "d7")
                    self.e("move.w (sp)+,d7")
                    self.set16(dst, "d7")
                else:
                    self.e("move.b %s,%s" % (REG8[dst], REG8[src]))
                    self.e("move.b d7,%s" % REG8[dst])
            self.preserve_all(v, b)
            return
        if dst == "cc":
            if src == "cc":
                return
            if src == "dp":
                self.e("moveq #$%02X,d7" % self.p.dp_at(v))
            else:
                self.e("move.b %s,d7" % REG8[src])
            self.e("move.b d7,%d(a6)" % CCHI_OFF)
            self.e("and.w #$0F,d7")
            self.e("move.w d7,ccr")
            return
        if src == "cc":
            if dst == "dp":
                self.stats["tfr dp"] += 1
                return

            def b():
                self.cc_byte_d7()
                self.e("move.b d7,%s" % REG8[dst])
            self.preserve_all(v, b)
            return
        if src == "dp":
            if dst != "dp":
                dp = self.p.dp_at(v)
                self.preserve_all(v, lambda: self.e("move.b #$%02X,%s" % (dp, REG8[dst]) if dp
                                                    else "clr.b %s" % REG8[dst]))
            return
        if dst == "dp":
            # DP must keep the program's value for the translation (the programs write only that after the boot)
            self.stats["tfr dp"] += 1
            return

        def b():
            if size(src) == 8:
                self.e("move.b %s,%s" % (REG8[src], REG8[dst]))
            else:
                self.get16_d7(src)
                self.set16(dst, "d7")
        self.preserve_all(v, b)

    def get16_d7(self, r):
        if r == "d":
            self.e("moveq #0,d7")
            self.d_to("d7")
        elif r == "s":
            self.s_value_d6()
            self.e("moveq #0,d7")
            self.e("move.w d6,d7")
        else:
            self.e("moveq #0,d7")
            self.e("move.w %s,d7" % REG16[r])

    def set16(self, r, src):
        if r == "d":
            self.e("move.b %s,d1" % src)
            self.e("move.w %s,d6" % src)
            self.e("lsr.w #8,d6")
            self.e("move.b d6,d0")
        elif r == "s":
            if src != "d7":
                self.e("move.l %s,d7" % src)
            self.set_s_d7()
        else:
            self.e("move.w %s,%s" % (src, REG16[r]))


def translate(prog):
    """-> (asm lines, report dict, emitter)"""
    code, joins = discover(prog)
    rets = function_returns(prog, code)
    live_in, live_out = liveness(prog, code, rets)
    em = Emitter(prog, code, joins, live_out)
    em.live_in = live_in
    # direct returns: up to four return points compared, else the dispatcher
    em.ret_points = {k: set(sorted(v)[:4]) for k, v in rets.items()}
    em.emit_all()
    missing = sorted(v for v in em.refs if v not in code)
    lines = list(em.lines) + em.tail
    lines.append("; --- referenced but not code")
    for v in missing:
        lines.append("%s:\tmove.w #$%04X,d7\n\tjmp %s_badpc" % (prog.label(v), prog.cpu_pc(v) if v >> 13 in prog.slot_of else v & 0xFFFF, prog.name))
    report = dict(instructions=len(code), unsupported=em.unsupported, missing=[hex(v) for v in missing],
                  stats=dict(em.stats))
    return lines, report, em, code
