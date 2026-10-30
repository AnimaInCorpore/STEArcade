"""NEC V30 -> 68000 static translator (Irem M72: R-Type; games/rtype/tools/gen.py).

One 68000 snippet per V30 instruction, labelled <prefix><linear address, 5 hex digits>: a code address runs with one
CS (the coverage says which; a linear address the coverage saw with two stops the build), so near jumps and returns are
known to stay in their segment.  No interpreter runs.

Registers (the V30's in the 68000's; every data register's upper word stays 0, so any of them indexes as a long):
    d0 = AW, d1 = CW, d2 = DW, d3 = BW (AL..BL their low bytes; AH..BH through the 68000 stack: `move.w d0,-(sp);
         move.b (sp)+,d7` reads AH, a write goes back the same way), d4 = IX, d5 = IY, d6 = BP
    a5 = SS:SP as a 68000 pointer, a4 = the SS base, a3 = the DS0 base, a2 = the DS1 base (base = image + segment * 16:
         the V30's 1 MB is one block, `Program.image`), a6 = the context block (the segment registers' values, IE, DF,
         the parity and AC bytes, the registers while the CPU is idle: engine/rt/v30rt.s), d7 a0 a1 scratch.  CS needs
         no register: every label knows its segment, so PS-relative operands are absolute (image + CS * 16 + offset).
Memory: the image keeps the V30's bytes swapped in every word (V30 byte a at image + (a ^ 1)), so a word at an even
address is one native move (the stack, the work RAM's words, the video and sprite RAM, the palette are all words; R-Type
reads 45 words for every byte) and a byte at a static address costs nothing; a byte at a register address computes
(offset ^ 1) in d7 (`moveq #1,d7; eor.w dX,d7`: 8 cycles).  A word at an odd address is two bytes: at a static odd
address, and at the sites the coverage saw odd (both parities then, chosen at run time); a site the coverage never saw
odd is assumed even (an odd one faults on the 68000).  Offsets wrap at 64 KB only where a 16 bit displacement is
$8000-$FF7F (computed in d7); register + small displacement does not wrap.
Flags: the V30's S Z O C are the 68000's N Z V C, so they live in the CCR.  Each instruction's code leaves some right
(`ok`); the live ones it spoils (backward liveness, `live_out`: a RET reads what its functions' return points read, a
computed call or jump what the targets the coverage saw read) come back from the SR saved before (`wrap`).  P and AC
exist only where read (BPE / BPO, ADJ4A / ADJ4S): producers store the result byte (P) or (dst ^ src ^ result) (AC) in
the context; an unknown continuation reads S Z O C only (`UNKNOWN`).  MAME's quirks kept: BLT / BGE test Z too, NEG
leaves O, DIV sets C and O, shift counts as the host's (shl by c & 31).  IE and DF are context bytes (DI EI CLD STD);
the inline string instructions assume DF = 0 (the REP routines look at it).
Control flow: jumps and branches are 68000 branches; CALL pushes the return IP (a native word) on the V30 stack and
branches; RET pops it and compares it with its functions' most executed return points (`ret_points`, up to two with the
flags dead), else dispatches: in the CS with an IP table (`Program.ip_table_cs`: 64K longs, <name>_ip_mid + 4 * IP
sign-extended) straight through the table without touching the flags, elsewhere <name>_dispatch (d7.l = the linear
address: a hash table of the entry points).  Computed calls and jumps likewise (the seen targets compared when at most
two).  IRET pops IP, CS and the PSW (flags into the CCR, IE, DF) and dispatches.  I/O: IN / OUT with an immediate port
read / write the runtime's port words (`Program.port_in` / `port_out`: lines per port), the rest calls v30_in* /
v30_out* (d7 = the port).  REP MOVBK / STM, PUSHF / POPF / IRET's PSW, ADJ4A / ADJ4S, ADD4S: engine/rt/v30rt.s.
Hooks (the idle loop): the label jumps to the runtime; the instruction's own translation follows under <label>_t.
Tests: engine/v30x_test.py (every opcode, random ModRM / prefixes / states, against engine/v30.py on Musashi).
"""
import bisect
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from v30dec import decode, DS1, PS, SS, DS0

C, V, Z, N = 1, 2, 4, 8
P, A = 0x100, 0x200
CCR = C | V | Z | N
ALLF = CCR | P | A

AW, CW, DW, BW, SP, BP, IX, IY = range(8)
REGW = {AW: "d0", CW: "d1", DW: "d2", BW: "d3", BP: "d6", IX: "d4", IY: "d5"}
SEGB = {DS1: "a2", DS0: "a3", SS: "a4"}
SEG_OFF, IE_OFF, DF_OFF, PB_OFF, AX_OFF = 0, 8, 9, 10, 11          # (context: engine/rt/v30rt.s)
SEGNAME = ("ds1", "ps", "ss", "ds0")

COND = {0: "bvs", 1: "bvc", 2: "bcs", 3: "bcc", 4: "beq", 5: "bne", 6: "bls", 7: "bhi", 8: "bmi", 9: "bpl",
        12: "blt", 13: "bge", 14: "ble", 15: "bgt"}
INV = {"bvs": "bvc", "bvc": "bvs", "bcs": "bcc", "bcc": "bcs", "beq": "bne", "bne": "beq", "bls": "bhi", "bhi": "bls",
       "bmi": "bpl", "bpl": "bmi", "blt": "bge", "bge": "blt", "ble": "bgt", "bgt": "ble"}
COND_USES = {0: V, 1: V, 2: C, 3: C, 4: Z, 5: Z, 6: C | Z, 7: C | Z, 8: N, 9: N, 10: P, 11: P, 12: N | V | Z,
             13: N | V | Z, 14: N | V | Z, 15: N | V | Z}


class Unsupported(Exception):
    pass


def s16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def defs_uses(ins):
    """(flags the instruction always defines, flags it reads) over C V Z N P A (MAME's nec core)"""
    mn = ins.mn
    if mn in ("add", "sub", "cmp"):
        return ALLF, 0
    if mn == "neg":
        return C | Z | N | P, 0                      # (MAME's NEG leaves O and AC)
    if mn in ("addc", "subc"):
        return ALLF, C
    if mn in ("or", "and", "xor", "test"):
        return ALLF, 0
    if mn in ("inc", "dec"):
        return V | Z | N | P | A, 0
    if mn in ("shl", "shr", "shra"):
        cnt = ins.ops[1]
        if cnt[0] == "i":
            if cnt[1] == 0:
                return 0, 0
            return (C | Z | N | P | (V if cnt[1] == 1 and ins.op in (0xD0, 0xD1) else 0)), 0
        return 0, C | Z | N | P | V                    # (CL may be 0: may define)
    if mn in ("rol", "ror", "rolc", "rorc"):
        cnt = ins.ops[1]
        u = C if mn in ("rolc", "rorc") else 0
        if cnt[0] == "i":
            if cnt[1] == 0:
                return 0, 0
            return C | (V if cnt[1] == 1 and ins.op in (0xD0, 0xD1) else 0), u
        return 0, C | V | u
    if mn in ("mulu", "mul", "imul"):
        return C | V, 0
    if mn in ("divu", "div"):
        return C | V, 0
    if mn == "cvtbd":
        return Z | N | P, 0
    if mn == "cvtdb":
        return Z | N | P, 0
    if mn in ("adj4a", "adj4s"):
        return C | Z | N | P | A, C | A
    if mn in ("adjba", "adjbs"):
        return C | A, A
    if mn in ("clr1cy", "set1cy"):
        return C, 0
    if mn == "not1cy":
        return C, C
    if mn == "test1":
        return C | V | Z, 0
    if mn == "sahf":
        return C | Z | N | P | A, 0
    if mn in ("lahf", "pushf", "int", "into"):
        return 0, ALLF
    if mn in ("popf", "reti"):
        return ALLF, 0
    if mn in ("cmpbk", "cmpm"):
        if ins.rep:
            return 0, ALLF
        return ALLF, 0
    if mn == "jcc":
        return 0, COND_USES[ins.cond]
    if mn == "loop":
        return 0, Z if ins.loop in ("dbnzne", "dbnze") else 0
    if mn == "salc":
        return 0, C
    if mn in ("add4s", "sub4s", "cmp4s"):
        return C | Z, 0
    return 0, 0


class Program:
    """One V30 program as the translator sees it.

    name / prefix   'main' / 'R'
    rd(linear)      the ROM's bytes (code and tables)
    roots           (cs, ip) entries (the interrupt handlers, the idle point...)
    exec_cover      (cs, ip) seen executing
    acc_cover       {linear pc: set of (r|w, width, region, odd)} the data accesses per site
    targets         {linear pc: set of (cs, ip)} where computed jumps / calls / returns went
    io_cover        {linear pc: set of (in|out, width, port)}
    hooks           {linear pc: label} the runtime takes over there (hook_next: the pc whose flags it hands on)
    natives         {linear pc: label} hand-written replacements
    after           (linear pc, ins) -> 68000 lines after the instruction (sequential ones), or None
    port_in / port_out  (port, width) -> 68000 lines for IN / OUT with an immediate port (AW / AL in d0), or None
    pal_read        a site reading the palette: the data with bits 5-15 set (M72: lines per (width, odd), or None)
    image           the symbol of the V30's 1 MB (byte swapped in words)
    """

    def __init__(self, name, prefix, rd, roots, exec_cover=(), acc_cover=None, targets=None, io_cover=None,
                 hooks=None, hook_next=None, natives=None, after=None, port_in=None, port_out=None, image="v30_image",
                 code_limit=None, indirect_live=True, pal_sites=None, hook_flags=ALLF, targets_seen=None,
                 exec_counts=None, ip_table_cs=None, store_marks=None):
        self.name, self.prefix, self.rd = name, prefix, rd
        self.roots = list(roots)
        self.exec_cover = set(exec_cover)
        self.acc_cover = acc_cover or {}
        self.targets = targets or {}
        self.targets_seen = self.targets if targets_seen is None else targets_seen
        self.exec_counts = exec_counts or {}        # (linear: executions: the hot return points are compared first)
        self.ip_table_cs = ip_table_cs              # (a CS whose entries <name>_dispatch_ip finds by IP: a table)
        self.store_marks = store_marks              # (pred(lin, ins), base, size, marks): after a store the pred
        #                                             picks, the byte marks[(68000 address - base) >> 8] is set when
        #                                             the address is in base .. base + size (REP: <name>_mark_range)
        self.io_cover = io_cover or {}
        self.hooks = dict(hooks or {})
        self.hook_next = dict(hook_next or {})
        self.natives = dict(natives or {})
        self.after = after
        self.port_in, self.port_out = port_in, port_out
        self.image = image
        self.code_limit = code_limit or (lambda lin: lin < 0x40000)
        self.indirect_live = indirect_live
        self.pal_sites = pal_sites or set()
        self.hook_flags = hook_flags
        self.segments = {cs for cs, ip in self.exec_cover} | {cs for cs, ip in self.roots}
        self.conflicts = []                         # (discovery: code reached with another CS, far jumps elsewhere)

    def label(self, lin):
        return "%s%05X" % (self.prefix, lin)


def lin_of(cs, ip):
    return ((cs << 4) + ip) & 0xFFFFF


def discover(prog):
    """recursive descent from the roots and the coverage -> ({linear: Ins}, joins)"""
    code = {}
    joins = set(lin_of(*r) for r in prog.roots) | set(prog.hooks)
    work = list(prog.roots) + sorted(prog.exec_cover)
    for site, ts in prog.targets.items():
        for t in ts:
            work.append(t)
            joins.add(lin_of(*t))
    while work:
        cs, ip = work.pop()
        while True:
            lin = lin_of(cs, ip)
            if lin in code:
                if code[lin].cs != cs:
                    if (cs, ip) in prog.exec_cover and (code[lin].cs, code[lin].ip) in prog.exec_cover:
                        raise RuntimeError("code at %05X runs with CS %04X and %04X" % (lin, code[lin].cs, cs))
                    prog.conflicts.append((lin, code[lin].cs, cs))
                break
            if not prog.code_limit(lin):
                break
            ins = decode(prog.rd, cs, ip)
            code[lin] = ins
            nip = (ip + ins.length) & 0xFFFF
            if ins.target is not None and ins.flow in ("jmp", "jcc", "call", "jmpf", "callf"):
                if ins.flow in ("jmpf", "callf") and ins.target[0] not in prog.segments:
                    prog.conflicts.append((lin, cs, ins.target[0]))         # (a far target in no known segment)
                else:
                    work.append(ins.target)
                    joins.add(lin_of(*ins.target))
            if ins.flow in ("call", "icall", "callf", "icallf"):
                joins.add(lin_of(cs, nip))
            if ins.flow in ("seq", "jcc", "call", "icall", "callf", "icallf"):
                ip = nip
                continue
            break
    return code, joins


def next_lin(ins):
    return lin_of(ins.cs, (ins.ip + ins.length) & 0xFFFF)


def function_returns(code, targets=None):
    """{linear pc of a RET: set of return points}: the RETs each near call target's code reaches without entering calls
    (following jumps and branches), with the return points of the calls to it (computed calls: to the targets the
    coverage saw, `targets`); RETF likewise for far calls"""
    out = collections.defaultdict(set)
    calls = collections.defaultdict(set)
    for v, ins in code.items():
        if ins.flow in ("call", "callf"):
            calls[(lin_of(*ins.target), ins.flow)].add(next_lin(ins))
        elif ins.flow == "icall":
            for t in (targets or {}).get(v, ()):
                if t[0] == ins.cs:
                    calls[(lin_of(*t), "call")].add(next_lin(ins))
    for (t, kind), rets in calls.items():
        seen = set()
        work = [t]
        want = "ret" if kind == "call" else "retf"
        while work:
            x = work.pop()
            if x in seen or x not in code:
                continue
            seen.add(x)
            ins = code[x]
            if ins.flow == want:
                out[x] |= rets
                continue
            if ins.flow in ("jmp", "jcc") and ins.target is not None:
                work.append(lin_of(*ins.target))
            if ins.flow == "ijmp":
                work += [lin_of(*t) for t in (targets or {}).get(x, ()) if t[0] == ins.cs]
            if ins.flow in ("seq", "jcc", "call", "icall", "callf", "icallf"):
                work.append(next_lin(ins))
    return out


UNKNOWN = CCR          # what an unknown continuation reads (P and AC are read near their producers: BPE / BPO, ADJ4A)


def liveness(prog, code, ret_points):
    """live_out[v]: the flags read after the instruction at v (C V Z N P A).  A call's are its callee's in this call's
    context: what the callee reads before defining (its RETs reading nothing) and, of what it leaves undefined up to its
    RETs, what this call's return point reads - a summary per callee (the fixpoints with RETs reading nothing and
    everything), so a callee that some callers need flag-preserving does not make all of them keep their flags.  The
    callee's own code keeps what the union of its RETs' return points read (what the callee does not define reaches its
    RETs, which read what their return points read); computed jumps / calls read what the targets the coverage saw read
    (S Z O C at most: an entry point does not read P or AC); RETI, INT and hooks per their rules."""
    succ = {}
    for v, ins in code.items():
        s = []
        if ins.flow in ("seq", "jcc"):
            s.append(next_lin(ins))
        if ins.flow in ("jmp", "jcc", "jmpf") and ins.target is not None:
            s.append(lin_of(*ins.target))
        succ[v] = s
    tg = {v: [lin_of(*t) for t in prog.targets_seen.get(v, ()) if lin_of(*t) in code] for v in code}
    # three fixpoints together: [0] the RETs read nothing, [1] the RETs read every flag (the callee summaries:
    # live_in of a callee in a context L = in0 | (L & in1)), [2] the RETs read their return points' (the code)
    ins_ = [{v: 0 for v in code} for _ in range(3)]
    outs = [{} for _ in range(3)]
    order = sorted(code, reverse=True)

    def called(k, t, nx):
        if t not in code:
            return UNKNOWN
        cont = ins_[k].get(nx, UNKNOWN)
        return ins_[0][t] | (cont & ins_[1][t])

    changed = True
    while changed:
        changed = False
        for k in range(3):
            live_in = ins_[k]
            for v in order:
                ins = code[v]
                fl = ins.flow
                if v in prog.hooks:
                    nx = prog.hook_next.get(v)
                    out = live_in.get(nx, UNKNOWN) if nx is not None else prog.hook_flags
                elif fl in ("ret", "retf"):
                    if k == 0:
                        out = 0
                    elif k == 1:
                        out = ALLF
                    else:
                        rp = ret_points.get(v)
                        if rp:
                            out = 0
                            for t in rp:
                                out |= live_in.get(t, UNKNOWN)
                        else:
                            out = UNKNOWN
                elif fl in ("ijmp", "ijmpf"):
                    if prog.indirect_live and tg[v]:
                        out = 0
                        for t in tg[v]:
                            out |= live_in[t]
                        out &= CCR                     # (an entry point reading P or AC: table data, not code)
                    else:
                        out = UNKNOWN
                elif fl in ("call", "callf"):
                    out = called(k, lin_of(*ins.target), next_lin(ins))
                elif fl in ("icall", "icallf"):
                    if tg[v]:
                        out = 0 if prog.indirect_live else UNKNOWN
                        for t in tg[v]:
                            out |= called(k, t, next_lin(ins))
                        out &= CCR
                    else:
                        out = UNKNOWN
                elif fl in ("iret", "int", "halt"):
                    out = 0 if fl == "iret" else UNKNOWN
                else:
                    out = 0
                    for t in succ[v]:
                        out |= live_in.get(t, UNKNOWN)
                d, u = defs_uses(ins)
                li = (out & ~d) | u
                outs[k][v] = out
                if li != live_in[v]:
                    live_in[v] = li
                    changed = True
    return ins_[2], outs[2]


class Emitter:
    def __init__(self, prog, code, joins, live_out, ret_points):
        self.p = prog
        self.code = code
        self.joins = joins
        self.live_out = live_out
        self.ret_points = ret_points
        self.lines = []
        self.refs = set()
        self.uid = 0
        self.unsupported = []
        self.stats = collections.Counter()
        self.entries = set()                    # (linear) labels the dispatcher must know
        self.order = sorted(code)
        self.prev = {next_lin(ins): u for u, ins in code.items() if ins.flow == "seq"}

    # ---- helpers ---------------------------------------------------------------
    def e(self, s):
        self.lines.append("\t" + s)

    def new_label(self):
        self.uid += 1
        return ".L%d" % self.uid

    def lab(self, lin):
        self.refs.add(lin)
        return self.p.label(lin)

    def live(self, v):
        return self.live_out.get(v, ALLF)

    def odd_site(self, v):
        return any(odd for rw, w, reg, odd in self.p.acc_cover.get(v, ()))

    def odd_word(self, v, o, w):
        """a word memory operand that may be at an odd address: a static odd one, or a site the coverage saw odd"""
        if w != 2 or o[0] != "m":
            return False
        if not o[1]:
            return bool(o[2] & 1)
        return self.odd_site(v)

    def regions(self, v):
        return {reg for rw, w, reg, odd in self.p.acc_cover.get(v, ())}

    # ---- flag fixing -------------------------------------------------------------
    def wrap(self, v, ok, body, const_set=0, const_clear=0):
        """body() emits code leaving the flags in `ok` right (as the V30 defines them, or unchanged where it does
        not define them); the live flags the V30 does not define but the body spoils come back from the SR saved
        before; flags with a constant value are set after"""
        live = self.live(v) & CCR
        d, u = defs_uses(self.code[v])
        keep = live & ~d & ~ok
        if keep:
            self.stats["wrapped"] += 1
            self.e("move.w sr,-(sp)")
            body()
            if keep == live:
                self.e("move.w (sp)+,ccr")
            else:
                self.e("move.w sr,d7")
                self.e("eor.w d7,(sp)")
                self.e("andi.w #%d,(sp)" % keep)
                self.e("eor.w d7,(sp)")
                self.e("move.w (sp)+,ccr")
        else:
            body()
        cs, cc = const_set & live, const_clear & live
        if cs:
            self.e("ori #%d,ccr" % cs)
        if cc:
            self.e("andi #%d,ccr" % (0xFF & ~cc))

    def keep_all(self, v, body):
        """body spoils every flag; the V30 instruction changes none"""
        self.wrap(v, 0, body)

    def parity(self, v, loc, w=1):
        """P live after the instruction: its result's low byte (loc: a 68000 operand of the result) to the context"""
        if self.live(v) & P:
            if w == 2 and not loc.startswith("d"):
                loc = self.ea_plus(loc, 1)
            if loc.endswith("(sp)"):
                loc = self.ea_plus(loc, 2)
            self.stats["parity"] += 1
            self.e("move.w sr,-(sp)")
            self.e("move.b %s,%d(a6)" % (loc, PB_OFF))
            self.e("move.w (sp)+,ccr")

    def parity_sub(self, v, r, s, w):
        """P live after a CMP: the result's low byte (r - s) to the context; r a data register, s an operand that does
        not use d7"""
        if self.live(v) & P:
            self.stats["parity"] += 1
            if s == "d7" or (s != "d7" and "d7" in s and r != "d7"):
                raise Unsupported("parity of cmp with d7")
            if w == 2 and not s.startswith("d") and not s.startswith("#"):
                s = self.ea_plus(s, 1)
            if s.startswith("#"):
                s = "#$%X" % (int(s[2:], 16) & 0xFF)
            if s.endswith("(sp)"):
                s = self.ea_plus(s, 2)
            self.e("move.w sr,-(sp)")
            if r != "d7":
                self.e("move.b %s,d7" % r)
            self.e("sub.b %s,d7" % s)
            self.e("move.b d7,%d(a6)" % PB_OFF)
            self.e("move.w (sp)+,ccr")

    def no_aux(self, v):
        if self.live(v) & A:
            raise Unsupported("AC live")

    # ---- operands -----------------------------------------------------------------
    def seg_base(self, ins, seg):
        """(68000 base register, None) or (None, absolute base) of a segment"""
        if seg == PS:
            return None, "%s+$%X" % (self.p.image, ins.cs << 4)
        return SEGB[seg], None

    def mem(self, v, ins, o, w, off=0, in_a0=False):
        """the 68000 operand of a memory operand (byte or even word), its setup emitted; in_a0: the address in a0
        (d7 free after the setup)"""
        if o[0] != "m":
            raise Unsupported("a register where memory is needed")
        _, regs, disp, seg = o
        base, absb = self.seg_base(ins, seg)
        d = (disp + off) & 0xFFFF
        if not regs:
            a = d ^ 1 if w == 1 else d
            if absb:
                ea = "%s+$%X" % (self.p.image, lin_of(ins.cs, a))
                if in_a0:
                    self.e("lea %s,a0" % ea)
                    return "(a0)"
                return ea
            if a < 0x8000:
                if in_a0:
                    self.e("lea $%X(%s),a0" % (a, base))
                    return "(a0)"
                return "$%X(%s)" % (a, base)
            self.e("move.l %s,a0" % base)
            self.e("adda.l #$%X,a0" % a)
            return "(a0)"
        rs = [REGW[r] for r in regs]
        wide = 0x8000 <= d < 0xFF80                     # (a 16 bit displacement >= $8000: the sum wraps at 64 KB)
        if w == 2 and not wide:
            sd = s16(d)
            if absb:
                self.e("lea %s,a0" % absb)
                base = "a0"
            if len(rs) == 2:
                self.e("lea (%s,%s.l),a0" % (base, rs[0]))
                base = "a0"
            if not -128 <= sd <= 127:
                self.e("lea %d(%s),a0" % (sd, base))
                base, sd = "a0", 0
            if in_a0:
                self.e("lea %d(%s,%s.l),a0" % (sd, base, rs[-1]))
                return "(a0)"
            return "%d(%s,%s.l)" % (sd, base, rs[-1]) if sd else "(%s,%s.l)" % (base, rs[-1])
        # the offset in d7 (a byte: offset ^ 1)
        if w == 1 and len(rs) == 1 and not (d & 1 or wide):
            self.e("moveq #1,d7")                       # (the registers' upper words are 0)
            self.e("eor.w %s,d7" % rs[0])
            rs, w_done = [], True
        else:
            self.e("move.l %s,d7" % rs[0])
            w_done = False
        if len(rs) == 2:
            self.e("add.w %s,d7" % rs[1])
        if d & 1 or wide or w == 2:
            sd = s16(d)
            if 1 <= sd <= 8 or -8 <= sd <= -1:
                self.e("%s.w #%d,d7" % ("addq" if sd > 0 else "subq", abs(sd)))
            elif d:
                self.e("add.w #$%X,d7" % d)
            d = 0
        if w == 1 and not w_done:
            self.e("eori.w #1,d7")
        sd = s16(d)
        if absb:
            self.e("lea %s,a0" % absb)
            base = "a0"
        if not -128 <= sd <= 127:
            self.e("lea %d(%s),a0" % (sd, base))
            base, sd = "a0", 0
        if in_a0:
            self.e("lea %d(%s,d7.l),a0" % (sd, base))
            return "(a0)"
        return "%d(%s,d7.l)" % (sd, base) if sd else "(%s,d7.l)" % base

    def free_d7(self, s):
        """an operand that uses d7 as its index: its address into a0 first (d7 is needed)"""
        if s != "d7" and "d7" in s:
            self.e("lea %s,a0" % s)
            return "(a0)"
        return s

    def is_pal(self, v):
        return v in self.p.pal_sites

    def src(self, v, ins, o, w, avoid_d7=False):
        """a 68000 source operand for o (register, immediate, memory), its setup emitted; a high byte register comes
        through d7"""
        k = o[0]
        if k == "i":
            return "#$%X" % (o[1] & (0xFF if w == 1 else 0xFFFF))
        if k == "r":
            i = o[1]
            if w == 2:
                if i == SP:
                    self.e("move.l a5,d7")
                    self.e("sub.l a4,d7")
                    return "d7"
                return REGW[i]
            if i < 4:
                return REGW[i]
            self.e("move.w %s,-(sp)" % REGW[i - 4])
            self.e("move.b (sp)+,d7")
            return "d7"
        if k == "s":
            return "%d(a6)" % (SEG_OFF + 2 * o[1])
        if self.odd_word(v, o, w):
            self.word_any(v, ins, o)
            return "d7"
        ea = self.mem(v, ins, o, w)
        if self.is_pal(v):
            self.e("move.%s %s,d7" % ("b" if w == 1 else "w", ea))
            if w == 2:
                self.e("ori.w #$FFE0,d7")
            else:
                self.e("ori.b #$E0,d7")          # (an even palette byte; odd ones read $FF: not seen)
            return "d7"
        return ea

    def word_any(self, v, ins, o):
        """d7.w = a word at an address of either parity (a site the coverage saw odd)"""
        self.stats["odd word site"] += 1
        _, regs, disp, seg = o
        lo = self.mem(v, ins, o, 1, in_a0=True)       # a0 = the low byte's 68000 address (V30 a ^ 1)
        odd, done = self.new_label(), self.new_label()
        self.e("move.l a0,d7")
        self.e("btst #0,d7")
        self.e("beq.s %s" % odd)                      # (68000 even: V30 odd)
        self.e("move.w -1(a0),d7")
        self.e("bra.s %s" % done)
        self.lines.append(odd + ":")
        self.e("move.b 3(a0),-(sp)")                  # (V30 a odd: low at a - 1, high at a + 2 in the image)
        self.e("move.w (sp)+,d7")
        self.e("move.b (a0),d7")
        self.lines.append(done + ":")

    def word_any_store(self, v, ins, o, src):
        """the word src (a register, an immediate or (sp)+: the value on the 68000 stack) to an address of either
        parity"""
        self.stats["odd word site"] += 1
        if src != "(sp)+":
            self.e("move.w %s,-(sp)" % src)
        self.mem(v, ins, o, 1, in_a0=True)            # a0 = image + (a ^ 1)
        odd, done = self.new_label(), self.new_label()
        self.e("move.l a0,d7")
        self.e("btst #0,d7")
        self.e("beq.s %s" % odd)
        self.e("move.w (sp),-1(a0)")
        self.e("bra.s %s" % done)
        self.lines.append(odd + ":")
        self.e("move.b 1(sp),(a0)")
        self.e("move.b (sp),3(a0)")
        self.lines.append(done + ":")
        self.e("addq.l #2,sp")

    def dst_is_hreg(self, o, w):
        return o[0] == "r" and w == 1 and o[1] >= 4

    # ---- emission -----------------------------------------------------------------------
    def emit_all(self):
        for v in sorted(self.code):
            ins = self.code[v]
            self.lines.append("%s:\t\t; %04X:%04X %s" % (self.p.label(v), ins.cs, ins.ip, ins.text))
            if v in self.p.hooks:
                self.e("jmp %s" % self.p.hooks[v])
                self.lines.append("%s_t:" % self.p.label(v))
            if v in self.p.natives:
                self.e("jmp %s" % self.p.natives[v])
                self.lines.append("%s_t:" % self.p.label(v))
            mark = len(self.lines)
            try:
                if self.marks_store(v, ins) == "rep":
                    self.e("pea (a2,d5.l)")                 # (the REP's first destination address)
                self.emit(v, ins)
            except (Unsupported, KeyError, ValueError, IndexError, TypeError) as ex:
                del self.lines[mark:]
                kind = "" if isinstance(ex, Unsupported) else "(%s) " % type(ex).__name__
                self.unsupported.append("%05X %s: %s%s" % (v, ins.text, kind, ex))
                self.e("move.l #$%X,d7" % v)
                self.e("jmp %s_unsupported" % self.p.name)

    STORES = ("mov", "add", "or", "addc", "subc", "and", "sub", "xor", "inc", "dec", "neg", "not", "shl", "shr", "shra",
              "rol", "ror", "rolc", "rorc", "clr1", "set1", "not1", "pop", "xch")

    def marks_store(self, v, ins):
        """None, "rep", "string" or the memory operand a store_marks site writes"""
        sm = self.p.store_marks
        if sm is None or not sm[0](v, ins):
            return None
        if ins.mn in ("stm", "movbk"):
            return "rep" if ins.rep else "string"
        if ins.mn == "xch":
            for o in ins.ops:
                if o[0] == "m":
                    return o
        elif ins.mn in self.STORES and ins.ops and ins.ops[0][0] == "m":
            return ins.ops[0]
        return None

    def emit_store_mark(self, v, ins):
        """the store's 256-byte block marked (store_marks): a0 = its 68000 address, then the range check"""
        what = self.marks_store(v, ins)
        if what is None:
            return
        pred, base, size, marks = self.p.store_marks
        live = self.live(v) & CCR
        self.stats["store mark"] += 1
        if live:
            self.e("move.w sr,-(sp)")
        if what == "rep":
            self.e("move.l %d(sp),a0" % (2 if live else 0))
            self.e("lea (a2,d5.l),a1")
            self.e("jsr %s_mark_range" % self.p.name)
        else:
            if what == "string":
                self.e("lea %d(a2,d5.l),a0" % -ins.w)
            else:
                regs = set(what[1])
                if ins.mn == "xch" and any(o[0] == "r" and o[1] in regs for o in ins.ops):
                    raise Unsupported("xch of a register its address uses")
                self.mem(v, ins, what, 1, in_a0=True)
            skip = self.new_label()
            self.e("move.l a0,d7")
            self.e("sub.l #%s,d7" % base)
            self.e("cmp.l #$%X,d7" % size)
            self.e("bcc.s %s" % skip)
            self.e("lsr.l #8,d7")
            self.e("lea %s,a0" % marks)
            self.e("st (a0,d7.l)")
            self.lines.append(skip + ":")
        if live:
            self.e("move.w (sp)+,ccr")
        if what == "rep":
            self.e("addq.l #4,sp")

    def fallthrough(self, v, ins):
        self.emit_store_mark(v, ins)
        if self.p.after is not None:
            for line in self.p.after(v, ins) or ():
                self.e(line)
        nv = next_lin(ins)
        k = bisect.bisect_right(self.order, v)
        later = k < len(self.order) and self.order[k] < nv
        if nv not in self.code or later:
            self.e("bra %s" % self.lab(nv))
        else:
            self.refs.add(nv)

    def emit(self, v, ins):
        mn = ins.mn
        fl = ins.flow
        if mn == "jcc":
            self.emit_jcc(v, ins)
            return
        if mn == "loop":
            self.emit_loop(v, ins)
            return
        if fl == "jmp":
            self.e("bra %s" % self.lab(lin_of(*ins.target)))
            return
        if fl == "jmpf":
            self.e("jmp %s" % self.lab(lin_of(*ins.target)))
            return
        if fl == "call":
            self.emit_call(v, ins)
            return
        if fl == "callf":
            self.emit_callf(v, ins)
            return
        if fl in ("icall", "ijmp"):
            self.emit_icall(v, ins)
            return
        if fl == "ret":
            self.emit_ret(v, ins)
            return
        if fl == "retf":
            self.emit_retf(v, ins)
            return
        if fl == "iret":
            self.emit_iret(v, ins)
            return
        if fl in ("halt", "int", "icallf", "ijmpf"):
            raise Unsupported(fl)
        self.emit_data(v, ins)
        self.fallthrough(v, ins)

    # ---- control flow -------------------------------------------------------------------
    def emit_jcc(self, v, ins):
        c = ins.cond
        t = self.lab(lin_of(*ins.target))
        if c in (10, 11):
            self.stats["parity branch"] += 1
            skip = self.new_label()
            self.e("move.w sr,-(sp)")
            self.e("moveq #0,d7")
            self.e("move.b %d(a6),d7" % PB_OFF)
            self.e("lea v30_parity,a0")
            self.e("tst.b (a0,d7.w)")                  # (nonzero: an even count of bits, P set)
            self.e("%s.s %s" % ("beq" if c == 10 else "bne", skip))
            self.e("move.w (sp)+,ccr")
            self.e("bra %s" % t)
            self.lines.append(skip + ":")
            self.e("move.w (sp)+,ccr")
        elif c == 12:
            skip = self.new_label()                   # (MAME's BLT: S != O and not Z)
            self.e("beq.s %s" % skip)
            self.e("blt %s" % t)
            self.lines.append(skip + ":")
        elif c == 13:
            self.e("beq %s" % t)                      # (MAME's BGE: Z or S = O)
            self.e("bge %s" % t)
        else:
            self.e("%s %s" % (COND[c], t))
        self.fallthrough(v, ins)

    def emit_loop(self, v, ins):
        t = self.lab(lin_of(*ins.target))
        live = self.live(v) & CCR
        k = ins.loop
        if k == "bcwz":
            if live:
                self.e("move.w sr,-(sp)")
                skip = self.new_label()
                self.e("tst.w d1")
                self.e("bne.s %s" % skip)
                self.e("move.w (sp)+,ccr")
                self.e("bra %s" % t)
                self.lines.append(skip + ":")
                self.e("move.w (sp)+,ccr")
            else:
                self.e("tst.w d1")
                self.e("beq %s" % t)
            self.fallthrough(v, ins)
            return
        if k == "dbnz" and not live:
            self.e("subq.w #1,d1")
            self.e("bne %s" % t)
            self.fallthrough(v, ins)
            return
        # dbnze / dbnzne (Z read) or live flags: the flags kept around the count
        skip = self.new_label()
        self.e("move.w sr,-(sp)")
        self.e("subq.w #1,d1")
        self.e("beq.s %s" % skip)
        if k == "dbnz":
            self.e("move.w (sp)+,ccr")
            self.e("bra %s" % t)
        else:
            self.e("move.w (sp),ccr")
            self.e("%s.s %s" % ("bne" if k == "dbnze" else "beq", skip))
            self.e("move.w (sp)+,ccr")
            self.e("bra %s" % t)
        self.lines.append(skip + ":")
        self.e("move.w (sp)+,ccr")
        self.fallthrough(v, ins)

    def push_word(self, v, src, live=None, reg="a0"):
        """src (a data register or #imm) onto the V30 stack, the flags kept when live"""
        live = self.live(v) & CCR if live is None else live
        if not live:
            self.e("move.w %s,-(a5)" % src)
        elif src.startswith("#"):
            self.e("move.w %s,%s" % (src, reg))
            self.e("movem.w %s,-(a5)" % reg)
        else:
            self.e("movem.w %s,-(a5)" % src)

    def emit_call(self, v, ins):
        ret = (ins.ip + ins.length) & 0xFFFF
        self.push_word(v, "#$%04X" % ret)
        self.entries.add(next_lin(ins))
        self.e("bra %s" % self.lab(lin_of(*ins.target)))

    def emit_callf(self, v, ins):
        ret = (ins.ip + ins.length) & 0xFFFF
        self.push_word(v, "#$%04X" % ins.cs)
        self.push_word(v, "#$%04X" % ret)
        self.entries.add(next_lin(ins))
        self.e("jmp %s" % self.lab(lin_of(*ins.target)))

    def target_ip_d7(self, v, ins, o):
        """d7.l = the IP a computed call / jump goes to (upper word 0)"""
        if o[0] == "r":
            self.e("moveq #0,d7")
            self.e("move.w %s,d7" % self.src(v, ins, o, 2))
            return
        if self.odd_word(v, o, 2):
            self.word_any(v, ins, o)
            self.e("and.l #$FFFF,d7")
            return
        ea = self.mem(v, ins, o, 2, in_a0=True)
        self.e("moveq #0,d7")
        self.e("move.w %s,d7" % ea)

    def emit_icall(self, v, ins):
        """CALL / BR through a register or memory: the targets the coverage saw (up to three, flags dead), else
        dispatch (a CS with an IP table: straight through it, the flags untouched)"""
        live = self.live(v) & CCR
        known = sorted(lin_of(*t) for t in self.p.targets_seen.get(v, ()) if lin_of(*t) in self.code and t[0] == ins.cs)
        for t in self.p.targets.get(v, ()):
            self.entries.add(lin_of(*t))
        if ins.flow == "icall":
            self.entries.add(next_lin(ins))
        if ins.cs == self.p.ip_table_cs and (live or len(known) > 2):
            o = ins.ops[0]
            if o[0] == "r":
                src = self.src(v, ins, o, 2)
            elif self.odd_word(v, o, 2):
                if live:
                    self.e("move.w sr,-(sp)")
                self.word_any(v, ins, o)
                if live:
                    self.e("move.w (sp)+,ccr")
                src = "d7"
            else:
                src = self.mem(v, ins, o, 2, in_a0=True)
            self.e("move.w %s,a0" % src)
            if ins.flow == "icall":
                self.push_word(v, "#$%04X" % ((ins.ip + ins.length) & 0xFFFF), live=live, reg="a1")
            self.ip_jump()
            return
        if live:
            self.e("move.w sr,-(sp)")
        self.target_ip_d7(v, ins, ins.ops[0])
        if ins.flow == "icall":
            self.e("move.w #$%04X,-(a5)" % ((ins.ip + ins.length) & 0xFFFF))
        for t in known if len(known) <= 3 else []:
            skip = self.new_label()
            self.e("cmp.w #$%04X,d7" % ((t - (ins.cs << 4)) & 0xFFFF))
            self.e("bne.s %s" % skip)
            if live:
                self.e("move.w (sp)+,ccr")
            self.e("bra %s" % self.lab(t))
            self.lines.append(skip + ":")
        self.dispatch_ip(ins, live)

    def ip_jump(self):
        """jump to the IP in a0.w (sign-extended) of the IP table's CS, the CCR untouched"""
        self.e("add.l a0,a0")
        self.e("add.l a0,a0")
        self.e("add.l #%s_ip_mid,a0" % self.p.name)
        self.e("move.l (a0),a1")
        self.e("jmp (a1)")

    def dispatch_ip(self, ins, live):
        """jump to the IP in d7.l (upper word 0) of the instruction's CS; the flags saved on the stack when live"""
        if ins.cs != self.p.ip_table_cs:
            self.e("add.l #$%X,d7" % (ins.cs << 4))
        if live:
            self.e("move.w (sp)+,ccr")
        if ins.cs == self.p.ip_table_cs:
            self.e("jmp %s_dispatch_ip" % self.p.name)
        else:
            self.e("jmp %s_dispatch" % self.p.name)

    def emit_ret(self, v, ins):
        """pop IP: its function's return points (the most executed first, up to two, flags dead), else dispatch (a CS
        with an IP table: straight through it, the flags untouched)"""
        live = self.live(v) & CCR
        cands = sorted(self.ret_points.get(v, ()), key=lambda t: (-self.p.exec_counts.get(t, 0), t))
        for t in self.p.targets.get(v, ()):
            self.entries.add(lin_of(*t))
        table = ins.cs == self.p.ip_table_cs
        if table and (live or len(cands) > 2):
            self.e("move.w (a5)+,a0")
            if ins.ops:
                self.e("lea %d(a5),a5" % s16(ins.ops[0][1]))
            self.ip_jump()
            return
        if live:
            self.e("move.w sr,-(sp)")
        self.e("moveq #0,d7")
        self.e("move.w (a5)+,d7")
        if ins.ops:
            self.e("lea %d(a5),a5" % s16(ins.ops[0][1]))
        for t in cands[:4]:
            ip = (t - (ins.cs << 4)) & 0xFFFF
            if live:
                skip = self.new_label()
                self.e("cmp.w #$%04X,d7" % ip)
                self.e("bne.s %s" % skip)
                self.e("move.w (sp)+,ccr")
                self.e("bra %s" % self.lab(t))
                self.lines.append(skip + ":")
            else:
                self.e("cmp.w #$%04X,d7" % ip)
                self.e("beq %s" % self.lab(t))
        self.dispatch_ip(ins, live)

    def emit_retf(self, v, ins):
        live = self.live(v) & CCR
        if live:
            self.e("move.w sr,-(sp)")
        self.e("moveq #0,d7")
        self.e("move.w (a5)+,a0")                  # IP
        self.e("move.w (a5)+,d7")                  # CS
        if ins.ops:
            self.e("lea %d(a5),a5" % s16(ins.ops[0][1]))
        self.e("lsl.l #4,d7")
        self.e("add.l a0,d7")                      # (IP sign-extended: corrected below)
        self.e("move.w a0,-(sp)")
        self.e("tst.w (sp)+")
        skip = self.new_label()
        self.e("bpl.s %s" % skip)
        self.e("add.l #$10000,d7")
        self.lines.append(skip + ":")
        self.e("and.l #$FFFFF,d7")
        for t in self.p.targets.get(v, ()):
            self.entries.add(lin_of(*t))
        if live:
            self.e("move.w (sp)+,ccr")
        self.e("jmp %s_dispatch" % self.p.name)

    def emit_iret(self, v, ins):
        """IP, CS, PSW from the stack; the flags into the CCR, IE and DF into the context; then dispatch"""
        self.e("moveq #0,d7")
        self.e("move.w 2(a5),d7")                  # CS
        self.e("lsl.l #4,d7")
        self.e("move.w (a5),a0")
        self.e("add.l a0,d7")
        self.e("tst.w (a5)")
        skip = self.new_label()
        self.e("bpl.s %s" % skip)
        self.e("add.l #$10000,d7")
        self.lines.append(skip + ":")
        self.e("and.l #$FFFFF,d7")
        self.e("addq.l #4,a5")
        self.e("move.w (a5)+,a0")                  # PSW
        self.e("move.l d7,-(sp)")
        self.e("jsr v30_psw_in")                   # (a0 = the PSW: IE, DF to the context, the CCR from it)
        self.e("movem.l (sp)+,d7")
        for t in self.p.targets.get(v, ()):
            self.entries.add(lin_of(*t))
        self.e("jmp %s_dispatch" % self.p.name)

    # ---- data instructions ------------------------------------------------------------------
    def emit_data(self, v, ins):
        mn = ins.mn
        w = ins.w
        o = ins.ops
        if mn in ("add", "or", "addc", "subc", "and", "sub", "xor", "cmp"):
            self.alu(v, ins, mn, o[0], o[1], w)
            return
        if mn == "test":
            self.emit_test(v, ins, o[0], o[1], w)
            return
        if mn == "mov":
            self.emit_mov(v, ins, o[0], o[1], w)
            return
        if mn in ("inc", "dec"):
            self.emit_incdec(v, ins, mn, o[0], w)
            return
        if mn in ("neg", "not"):
            self.emit_unary(v, ins, mn, o[0], w)
            return
        if mn in ("shl", "shr", "shra", "rol", "ror", "rolc", "rorc"):
            self.emit_shift(v, ins, mn, o[0], o[1], w)
            return
        if mn == "push":
            self.emit_push(v, ins, o[0])
            return
        if mn == "pop":
            self.emit_pop(v, ins, o[0])
            return
        if mn == "xch":
            self.emit_xch(v, ins, o[0], o[1], w)
            return
        if mn == "lea":
            self.emit_lea(v, ins, o[0], o[1])
            return
        if mn == "ldp":
            self.emit_ldp(v, ins)
            return
        if mn in ("in", "out"):
            self.emit_io(v, ins)
            return
        if mn in ("movbk", "stm", "ldm", "cmpm", "cmpbk"):
            self.emit_string(v, ins)
            return
        if mn in ("mulu", "mul", "imul"):
            self.emit_mul(v, ins)
            return
        if mn in ("divu", "div"):
            self.emit_div(v, ins)
            return
        if mn == "cvtbw":
            self.keep_all(v, lambda: self.e("ext.w d0"))
            return
        if mn == "cvtwl":
            def b():
                self.e("move.w d0,d2")
                self.e("add.w d2,d2")
                self.e("subx.w d2,d2")
            self.keep_all(v, b)
            return
        if mn == "nop":
            return
        if mn in ("di", "ei"):
            self.e("%s %d(a6)" % ("sf" if mn == "di" else "st", IE_OFF))
            return
        if mn == "cld":
            self.e("sf %d(a6)" % DF_OFF)
            return
        if mn == "std":
            self.stats["std"] += 1                       # (only the REP routines look at DF)
            self.e("st %d(a6)" % DF_OFF)
            return
        if mn in ("adj4a", "adj4s"):
            self.e("jsr v30_%s" % mn)
            return
        if mn == "add4s":
            self.e("jsr v30_add4s")
            return
        if mn in ("clr1cy", "set1cy", "not1cy"):
            if self.live(v) & C:
                self.e({"clr1cy": "andi #$FE,ccr", "set1cy": "ori #1,ccr", "not1cy": "eori #1,ccr"}[mn])
            return
        if mn == "salc":
            self.keep_all(v, lambda: self.e("scs d0"))
            return
        if mn == "trans":
            def b():
                self.e("moveq #0,d7")
                self.e("move.b d0,d7")
                self.e("add.w d3,d7")
                self.e("eori.w #1,d7")
                base, absb = self.seg_base(ins, ins.seg if ins.seg is not None else DS0)
                if absb:
                    self.e("lea %s,a0" % absb)
                    base = "a0"
                self.e("move.b (%s,d7.l),d0" % base)
            self.keep_all(v, b)
            return
        if mn in ("pusha", "popa"):
            self.emit_pushpopa(v, ins, mn)
            return
        if mn in ("pushf", "popf", "lahf", "sahf"):
            self.emit_psw(v, ins, mn)
            return
        if mn in ("test1", "clr1", "set1", "not1"):
            self.emit_bit(v, ins, mn, o[0], o[1], w)
            return
        if mn in ("prepare", "dispose"):
            self.emit_frame(v, ins, mn)
            return
        raise Unsupported(mn)

    # -- ALU ------------------------------------------------------------------------------------
    def x_from_c(self):
        """X = the CCR's C (d7 spoiled)"""
        self.e("scs d7")
        self.e("add.b d7,d7")

    def alu(self, v, ins, mn, dst, src, w):
        sz = "b" if w == 1 else "w"
        live = self.live(v)
        if mn in ("addc", "subc"):
            self.alu_carry(v, ins, mn, dst, src, w)
            return
        op = {"add": "add", "or": "or", "and": "and", "sub": "sub", "xor": "eor", "cmp": "cmp"}[mn]
        aux = self.live(v) & A and op in ("add", "sub", "cmp") and dst[0] == "r" and not self.dst_is_hreg(dst, w) \
            and w == 1
        if aux:
            self.aux_before(v, ins, REGW[dst[1]], src, w)
            if op == "cmp":
                raise Unsupported("AC of cmp")
        elif self.live(v) & A and op in ("and", "or", "eor"):
            self.e("sf %d(a6)" % AX_OFF)
        else:
            self.no_aux(v)
        # x86 idioms: xor / sub r,r = 0; and / or r,r = test
        if dst == src and dst[0] == "r" and not self.dst_is_hreg(dst, w) and not (w == 2 and dst[1] == SP):
            r = REGW[dst[1]]
            if mn in ("xor", "sub"):
                self.e("moveq #0,%s" % r if w == 2 else "clr.b %s" % r)
                self.parity(v, r)
                return
            if mn in ("and", "or"):
                self.e("tst.%s %s" % (sz, r))
                self.parity(v, r)
                return
        if dst == src and self.dst_is_hreg(dst, w) and mn in ("xor", "sub"):
            self.e("and.w #$FF,%s" % REGW[dst[1] - 4])
            if live & CCR:
                self.e("move #4,ccr")                  # (Z; S O C clear)
            if live & P:
                self.e("clr.b %d(a6)" % PB_OFF)
            return
        if dst[0] == "r" and w == 2 and dst[1] == SP:
            self.alu_sp(v, ins, mn, src)
            return
        if dst[0] == "r" and not self.dst_is_hreg(dst, w):
            r = REGW[dst[1]]
            if src[0] == "i":
                val = src[1] & (0xFF if w == 1 else 0xFFFF)
                if op in ("add", "sub") and 1 <= val <= 8:
                    self.e("%sq.%s #%d,%s" % (op, sz, val, r))
                else:
                    self.e("%s%s.%s #$%X,%s" % (op, "i" if op != "cmp" else "", sz, val, r))
            else:
                s = self.src(v, ins, src, w)
                if op == "eor" and not s.startswith("d"):
                    self.e("move.%s %s,d7" % (sz, s))
                    s = "d7"
                self.e("%s.%s %s,%s" % (op, sz, s, r))
            if aux:
                self.aux_after(r)
            if op == "cmp":
                if src[0] == "i":
                    s = "#$%X" % (src[1] & 0xFF)
                elif "d7" in s and s != "d7" and self.live(v) & P:
                    raise Unsupported("parity of cmp with an indexed byte")
                self.parity_sub(v, r, s, w)
            else:
                self.parity(v, r)
            return
        if dst[0] == "r":
            # a high byte register: on the 68000 stack
            hr = REGW[dst[1] - 4]
            if src[0] == "i":
                s = "#$%X" % (src[1] & 0xFF)
            elif src[0] == "m":
                s = self.mem(v, ins, src, 1, in_a0=True)          # ((a0): d7 stays free)
                if self.is_pal(v):
                    raise Unsupported("palette into a high byte")
            else:
                s = self.src(v, ins, src, 1)
            if op == "cmp":
                if s == "d7":
                    if self.live(v) & P:
                        raise Unsupported("parity of cmp of two high bytes")
                    self.e("move.b d7,-(sp)")
                    s = "(sp)+"
                self.e("move.w %s,-(sp)" % hr)
                self.e("move.b (sp)+,d7")
                self.e("cmp.b %s,d7" % s)
                self.parity_sub(v, "d7", s, 1)
                return
            if op == "eor" and not (s.startswith("#") or s.startswith("d")):
                self.e("move.b %s,d7" % s)
                s = "d7"
            self.e("move.w %s,-(sp)" % hr)
            if s.startswith("#"):
                val = int(s[2:], 16)
                if op in ("add", "sub") and 1 <= val <= 8:
                    self.e("%sq.b #%d,(sp)" % (op, val))
                else:
                    self.e("%si.b %s,(sp)" % (op, s))
            elif s.startswith("d"):
                self.e("%s.b %s,(sp)" % (op, s))
            else:
                self.e("move.b %s,d7" % s)
                self.e("%s.b d7,(sp)" % op)
            self.finish_rmw(v, "(sp)", ["move.w (sp)+,%s" % hr])
            return
        # memory destination
        if self.odd_word(v, dst, w):
            if not (src[0] == "i" or src[0] == "r" and src[1] != SP):
                raise Unsupported("ALU on an odd word from memory")
            if op != "cmp" and not live & P:
                so = self.src(v, ins, src, 2)
                self.odd_rmw(v, ins, dst, lambda loc: self.e("%s%s.w %s,%s" % (
                    op, "i" if src[0] == "i" else "", so, loc)))
                return
            self.word_any(v, ins, dst)
            so = self.src(v, ins, src, 2)
            self.e("%s%s.w %s,d7" % (op, "i" if src[0] == "i" and op != "cmp" else "", so))
            if op == "cmp":
                self.parity_sub(v, "d7", so, 2)
            else:
                self.parity(v, "d7")
            if op != "cmp":
                self.odd_writeback(v, ins, dst)
            return
        if src[0] == "i":
            val = src[1] & (0xFF if w == 1 else 0xFFFF)
            ea = self.mem(v, ins, dst, w, in_a0=op == "cmp" and bool(live & P))
            if op in ("add", "sub") and 1 <= val <= 8:
                self.e("%sq.%s #%d,%s" % (op, sz, val, ea))
            else:
                self.e("%si.%s #$%X,%s" % (op, sz, val, ea))
            if op == "cmp" and live & P:
                self.e("move.w sr,-(sp)")
                self.e("move.b %s,d7" % (ea if w == 1 else self.ea_plus(ea, 1)))
                self.e("sub.b #$%X,d7" % (val & 0xFF))
                self.e("move.b d7,%d(a6)" % PB_OFF)
                self.e("move.w (sp)+,ccr")
            elif op != "cmp":
                self.parity(v, ea, w)
            return
        if src[0] == "r" and not self.dst_is_hreg(src, w) and not (w == 2 and src[1] == SP):
            s = REGW[src[1]]
            if op == "cmp":
                ea = self.mem(v, ins, dst, w)
                self.e("move.%s %s,d7" % (sz, ea))
                self.e("cmp.%s %s,d7" % (sz, s))
                self.parity_sub(v, "d7", s, w)
                return
            ea = self.mem(v, ins, dst, w)
            self.e("%s.%s %s,%s" % (op, sz, s, ea))
            self.parity(v, ea, w)
            return
        # a high byte (or SP) into memory
        ea = self.mem(v, ins, dst, w, in_a0=True)
        s = self.src(v, ins, src, w)
        if op == "cmp":
            self.e("move.%s %s,-(sp)" % (sz, s))
            self.e("move.%s %s,d7" % (sz, ea))
            self.e("cmp.%s (sp),d7" % sz)
            self.parity_sub(v, "d7", "(sp)" if w == 1 else "(sp)", 1 if w == 1 else 2)
            self.e("addq.l #2,sp")
            return
        self.e("%s.%s %s,%s" % (op, sz, s, ea))
        self.parity(v, ea, w)

    def alu_sp(self, v, ins, mn, src):
        if mn in ("add", "sub") and src[0] == "i" and not self.live(v) & ALLF:
            n = s16(src[1])
            self.e("lea %d(a5),a5" % (n if mn == "add" else -n))
            return
        raise Unsupported("%s sp" % mn)

    def alu_carry(self, v, ins, mn, dst, src, w):
        """ADDC / SUBC: addx / subx with X = C and Z set before (Z right after); a memory or high byte destination
        with the -(Ay),-(Ax) form, the source on the 68000 stack"""
        sz = "b" if w == 1 else "w"
        op = "addx" if mn == "addc" else "subx"
        if dst[0] == "r" and not self.dst_is_hreg(dst, w) and not (w == 2 and dst[1] == SP):
            r = REGW[dst[1]]
            if self.live(v) & A:
                self.aux_before(v, ins, r, src, w)
            if src[0] == "r" and not self.dst_is_hreg(src, w) and not (w == 2 and src[1] == SP):
                self.x_from_c()
                self.e("cmp.w d7,d7")                  # (Z = 1, X kept)
                self.e("%s.%s %s,%s" % (op, sz, REGW[src[1]], r))
            elif src[0] == "i":
                self.x_from_c()
                self.e("move.%s #$%X,d7" % (sz, src[1] & (0xFF if w == 1 else 0xFFFF)))
                self.e("cmp.w d7,d7")
                self.e("%s.%s d7,%s" % (op, sz, r))
            else:
                self.e("move.w sr,-(sp)")
                self.e("move.%s %s,-(sp)" % (sz, self.src(v, ins, src, w)))
                self.e("move.b 3(sp),d7")
                self.e("lsr.b #1,d7")                  # (X = the saved C)
                self.e("move.%s (sp)+,d7" % sz)
                self.e("cmp.w d7,d7")
                self.e("%s.%s d7,%s" % (op, sz, r))
                self.e("addq.l #2,sp")
            if self.live(v) & A:
                self.aux_after(r)
            self.parity(v, r)
            return
        self.no_aux(v)
        if self.odd_word(v, dst, w):
            raise Unsupported("%s to an odd word" % mn)
        if dst[0] == "r" and w == 2:
            raise Unsupported("%s sp" % mn)
        self.e("move.w sr,-(sp)")                      # (C)
        k = 3
        if dst[0] == "m":
            self.mem(v, ins, dst, w, in_a0=True)
            s = self.src(v, ins, src, w)
            self.e("move.%s %s,-(sp)" % (sz, s))
            self.e("lea %d(a0),a0" % w)
        else:
            hr = REGW[dst[1] - 4]
            self.e("move.w %s,-(sp)" % hr)
            s = self.src(v, ins, src, w)
            self.e("move.%s %s,-(sp)" % (sz, s))
            self.e("lea 3(sp),a0")                     # (past the high byte of the register's word at 2(sp))
            k = 5
        self.e("lea %d(sp),a1" % (1 if w == 1 else 2))
        self.e("move.b %d(sp),d7" % k)
        self.e("lsr.b #1,d7")                          # X = C
        self.e("cmp.w d7,d7")                          # Z = 1
        self.e("%s.%s -(a1),-(a0)" % (op, sz))
        self.e("addq.l #2,sp")
        if dst[0] == "r":
            self.parity(v, "(sp)")
            self.e("move.w sr,d7")
            self.e("move.w (sp)+,%s" % hr)
            self.e("move.w d7,ccr")
        else:
            self.parity(v, "(a0)" if w == 1 else "1(a0)")
        self.e("addq.l #2,sp")

    def aux_before(self, v, ins, r, src, w):
        """AC live after an add / sub into a register: (dst ^ src) to the context's AC byte (the flags kept)"""
        if w != 1 or src[0] == "r" and self.dst_is_hreg(src, w):
            raise Unsupported("AC of this form")
        self.stats["aux"] += 1
        self.e("move.w sr,-(sp)")
        s = self.src(v, ins, src, 1)
        self.e("move.b %s,d7" % s)
        self.e("eor.b %s,d7" % r)
        self.e("move.b d7,%d(a6)" % AX_OFF)
        self.e("move.w (sp)+,ccr")

    def aux_after(self, r):
        """... ^ the result: bit 4 is AC"""
        self.e("move.w sr,-(sp)")
        self.e("eor.b %s,%d(a6)" % (r, AX_OFF))
        self.e("move.w (sp)+,ccr")

    def emit_test(self, v, ins, dst, src, w):
        sz = "b" if w == 1 else "w"
        live = self.live(v)
        if dst == src and dst[0] == "r" and not self.dst_is_hreg(dst, w):
            self.e("tst.%s %s" % (sz, REGW[dst[1]]))
            self.parity(v, REGW[dst[1]])
            return
        if src[0] == "m":
            dst, src = src, dst                          # (the memory operand first: into d7)
        if src[0] == "i" and not live & (C | V | N | P):
            val = src[1] & (0xFF if w == 1 else 0xFFFF)
            if val and not val & (val - 1):
                # one bit, only Z read: btst
                bit = val.bit_length() - 1
                if dst[0] == "r" and not self.dst_is_hreg(dst, w) and not (w == 2 and dst[1] == SP):
                    self.e("btst #%d,%s" % (bit, REGW[dst[1]]))
                    return
                if dst[0] == "m" and not self.odd_word(v, dst, w) and not self.is_pal(v):
                    if w == 1:
                        self.e("btst #%d,%s" % (bit, self.mem(v, ins, dst, 1)))
                    else:
                        ea = self.mem(v, ins, dst, 2)
                        if bit >= 8:
                            self.e("btst #%d,%s" % (bit - 8, ea))
                        else:
                            self.e("btst #%d,%s" % (bit, self.ea_plus(ea, 1)))
                    return
        d = self.src(v, ins, dst, w)
        if src[0] == "i" and src[1] & (0xFF if w == 1 else 0xFFFF) == (0xFF if w == 1 else 0xFFFF):
            self.e("tst.%s %s" % (sz, d))
            self.parity(v, d, w)
            return
        if d != "d7":
            self.e("move.%s %s,d7" % (sz, d))
        if src[0] == "i":
            self.e("andi.%s #$%X,d7" % (sz, src[1] & (0xFF if w == 1 else 0xFFFF)))
        elif self.dst_is_hreg(src, w) or (w == 2 and src[1] == SP):
            self.e("move.%s d7,-(sp)" % sz)
            self.src(v, ins, src, w)
            self.e("and.%s (sp)+,d7" % sz)
        else:
            self.e("and.%s %s,d7" % (sz, REGW[src[1]]))
        self.parity(v, "d7")

    @staticmethod
    def ea_plus(ea, k):
        """the 68000 operand ea moved by k bytes"""
        if ea.startswith("("):
            return "%d%s" % (k, ea)
        if ea.startswith("$"):
            n, rest = ea[1:].split("(", 1)
            return "$%X(%s" % (int(n, 16) + k, rest)
        if "(" not in ea:
            return "%s+%d" % (ea, k)
        n, rest = ea.split("(", 1)
        return "%d(%s" % (int(n) + k, rest)

    # -- moves ---------------------------------------------------------------------------------------
    def emit_mov(self, v, ins, dst, src, w):
        sz = "b" if w == 1 else "w"
        if dst[0] == "s":
            self.keep_all(v, lambda: self.set_sreg(v, ins, dst[1], src))
            return
        if dst[0] == "r" and w == 2 and dst[1] == SP:
            def b():
                s = self.free_d7(self.src(v, ins, src, 2))
                if s != "d7":
                    self.e("moveq #0,d7")
                    self.e("move.w %s,d7" % s)
                else:
                    self.e("and.l #$FFFF,d7")
                self.e("lea (a4,d7.l),a5")
            self.keep_all(v, b)
            return
        if src[0] == "s":
            def b():
                self.store(v, ins, dst, "%d(a6)" % (SEG_OFF + 2 * src[1]), 2)
            self.keep_all(v, b)
            return

        def body():
            if dst[0] == "r" and not self.dst_is_hreg(dst, w):
                r = REGW[dst[1]]
                if src[0] == "i" and w == 2 and src[1] == 0:
                    self.e("moveq #0,%s" % r)
                elif src[0] == "i" and w == 1 and src[1] == 0:
                    self.e("clr.b %s" % r)
                else:
                    self.e("move.%s %s,%s" % (sz, self.src(v, ins, src, w), r))
                return
            if dst[0] == "r":
                hr = REGW[dst[1] - 4]
                s = self.src(v, ins, src, 1)
                self.e("move.w %s,-(sp)" % hr)
                self.e("move.b %s,(sp)" % s)
                self.e("move.w (sp)+,%s" % hr)
                return
            if src[0] == "i":
                self.store(v, ins, dst, "#$%X" % (src[1] & (0xFF if w == 1 else 0xFFFF)), w)
                return
            if self.dst_is_hreg(src, w) or (w == 2 and src[1] == SP):
                if self.odd_word(v, dst, w):
                    s = self.src(v, ins, src, w)
                    self.e("move.w %s,-(sp)" % s)
                    self.word_any_store(v, ins, dst, "(sp)+")
                    return
                ea = self.mem(v, ins, dst, w, in_a0=True)
                s = self.src(v, ins, src, w)
                self.e("move.%s %s,%s" % (sz, s, ea))
                return
            self.store(v, ins, dst, self.src(v, ins, src, w), w)
        self.keep_all(v, body)

    def store(self, v, ins, dst, s, w):
        """s (a register, immediate or context operand) to dst"""
        sz = "b" if w == 1 else "w"
        if dst[0] == "r":
            if w == 2 and dst[1] == SP:
                raise Unsupported("store to SP")
            if self.dst_is_hreg(dst, w):
                hr = REGW[dst[1] - 4]
                self.e("move.w %s,-(sp)" % hr)
                self.e("move.b %s,(sp)" % s)
                self.e("move.w (sp)+,%s" % hr)
                return
            self.e("move.%s %s,%s" % (sz, s, REGW[dst[1]]))
            return
        if self.odd_word(v, dst, w):
            self.word_any_store(v, ins, dst, s)
            return
        if s == "d7":
            self.e("move.%s d7,-(sp)" % sz)
            s = "(sp)+"
        if "d7" in s or s.startswith("$") or "(a" in s:
            if s != "d7" and "(" in s:
                self.e("move.%s %s,-(sp)" % (sz, s))
                ea = self.mem(v, ins, dst, w, in_a0=True)
                self.e("move.%s (sp)+,%s" % (sz, ea))
                return
            ea = self.mem(v, ins, dst, w, in_a0=True)
            self.e("move.%s %s,%s" % (sz, s, ea))
            return
        ea = self.mem(v, ins, dst, w)
        if s == "#$0":
            self.e("clr.%s %s" % (sz, ea))
        else:
            self.e("move.%s %s,%s" % (sz, s, ea))

    def set_sreg(self, v, ins, k, src):
        """a segment register from a word: its value in the context, its base register"""
        if k == PS:
            raise Unsupported("mov ps")
        c = self.const_reg(v, src)
        if c is not None and k != SS:
            self.stats["constant segment"] += 1
            self.e("move.w #$%04X,%d(a6)" % (c, SEG_OFF + 2 * k))
            self.e("lea %s+$%X,%s" % (self.p.image, c << 4, SEGB[k]))
            return
        s = self.free_d7(self.src(v, ins, src, 2))
        if s != "d7":
            self.e("moveq #0,d7")
            self.e("move.w %s,d7" % s)
        else:
            self.e("and.l #$FFFF,d7")
        self.sreg_from_d7(k)

    def sreg_from_d7(self, k):
        """segment register k = d7.w (upper word 0): the value, the base (SS: SP keeps its value)"""
        self.e("move.w d7,%d(a6)" % (SEG_OFF + 2 * k))
        self.e("lsl.l #4,d7")
        if k == SS:
            self.e("sub.l a4,a5")
        self.e("lea %s,%s" % (self.p.image, SEGB[k]))
        self.e("add.l d7,%s" % SEGB[k])
        if k == SS:
            self.e("add.l a4,a5")

    def emit_xch(self, v, ins, a, b, w):
        if a[0] == "r" and b[0] == "r" and w == 2 and SP not in (a[1], b[1]):
            self.e("exg %s,%s" % (REGW[a[1]], REGW[b[1]]))
            return
        if a[0] == "m":
            a, b = b, a
        sz = "b" if w == 1 else "w"

        def body():
            if a[0] == "r" and b[0] == "m" and not self.dst_is_hreg(a, w):
                if self.odd_word(v, b, w):
                    raise Unsupported("xch odd word")
                ea = self.mem(v, ins, b, w, in_a0=True)
                r = REGW[a[1]]
                self.e("move.%s (a0),d7" % sz)
                self.e("move.%s %s,(a0)" % (sz, r))
                self.e("move.%s d7,%s" % (sz, r))
                return
            if a[0] == "r" and b[0] == "r" and w == 1:
                ra = self.src(v, ins, a, 1)
                self.e("move.b %s,-(sp)" % ra)              # (a's old value)
                rb = self.src(v, ins, b, 1)
                self.store(v, ins, a, rb, 1)
                self.e("move.b (sp)+,d7")
                self.store(v, ins, b, "d7", 1)
                return
            raise Unsupported("xch %s" % ins.text)
        self.keep_all(v, body)

    def emit_lea(self, v, ins, dst, m):
        if m[0] != "m":
            raise Unsupported("lea of a register")
        _, regs, disp, seg = m
        r = REGW.get(dst[1])
        if r is None:
            raise Unsupported("lea sp")

        def body():
            rs = [REGW[x] for x in regs]
            if not rs:
                self.e("move.w #$%X,%s" % (disp, r))
                return
            if r in rs[1:]:
                rs = [rs[1], rs[0]]
            if rs[0] != r:
                self.e("move.w %s,%s" % (rs[0], r))
            for x in rs[1:]:
                self.e("add.w %s,%s" % (x, r))
            if disp:
                sd = s16(disp)
                if 1 <= sd <= 8:
                    self.e("addq.w #%d,%s" % (sd, r))
                elif -8 <= sd <= -1:
                    self.e("subq.w #%d,%s" % (-sd, r))
                else:
                    self.e("add.w #$%X,%s" % (disp, r))
        if r in [REGW[x] for x in regs] and len(regs) == 2 and REGW[regs[0]] == REGW[regs[1]]:
            raise Unsupported("lea r+r")
        self.keep_all(v, body)

    def emit_ldp(self, v, ins):
        r, m, s = ins.ops

        def body():
            if self.odd_word(v, m, 2):
                raise Unsupported("ldp odd")
            ea = self.mem(v, ins, m, 2, in_a0=True)
            self.e("move.w 2(a0),-(sp)")
            self.e("move.w (a0),%s" % REGW[r[1]])
            self.e("moveq #0,d7")
            self.e("move.w (sp)+,d7")
            self.sreg_from_d7(s[1])
        if r[1] == SP:
            raise Unsupported("ldp sp")
        self.keep_all(v, body)

    # -- inc / dec / neg / not -------------------------------------------------------------------------
    def rmw_operand(self, v, ins, o, w):
        """(68000 operand, writeback lines) of a read-modify-write destination"""
        if o[0] == "r":
            if w == 2:
                if o[1] == SP:
                    raise Unsupported("rmw sp")
                return REGW[o[1]], []
            if o[1] < 4:
                return REGW[o[1]], []
            hr = REGW[o[1] - 4]
            self.e("move.w %s,-(sp)" % hr)
            return "(sp)", ["move.w (sp)+,%s" % hr]
        if self.odd_word(v, o, w):
            self.word_any(v, ins, o)
            return "d7", (lambda: self.odd_writeback(v, ins, o))
        return self.mem(v, ins, o, w), []

    def odd_rmw(self, v, ins, o, op):
        """a read-modify-write of a word at either parity: op(operand) emits the operation (its flags are the
        result); an even V30 address operates on the image's word, an odd one on d7 with the bytes around it"""
        self.stats["odd word site"] += 1
        self.mem(v, ins, o, 1, in_a0=True)            # a0 = image + (a ^ 1)
        odd, done = self.new_label(), self.new_label()
        self.e("move.l a0,d7")
        self.e("btst #0,d7")
        self.e("beq.s %s" % odd)
        op("-1(a0)")
        self.e("bra.s %s" % done)
        self.lines.append(odd + ":")
        self.e("move.b 3(a0),-(sp)")
        self.e("move.w (sp)+,d7")
        self.e("move.b (a0),d7")
        op("d7")
        self.e("move.w sr,-(sp)")
        self.e("move.b d7,(a0)")
        self.e("move.w d7,-(sp)")
        self.e("move.b (sp)+,3(a0)")
        self.e("move.w (sp)+,ccr")
        self.lines.append(done + ":")

    def odd_writeback(self, v, ins, o):
        """d7 back to an odd word operand, the flags kept"""
        self.e("move.w sr,-(sp)")
        self.e("move.w d7,-(sp)")
        self.word_any_store(v, ins, o, "(sp)+")
        self.e("move.w (sp)+,ccr")

    def finish_rmw(self, v, loc, wb, w=1, par=True):
        if callable(wb):
            if par:
                self.parity(v, loc, w)
            wb()
            return
        if not wb:
            if par:
                self.parity(v, loc, w)
            return
        if self.live(v) & (CCR | P):
            self.e("move.w sr,d7")
            if self.live(v) & P and par:
                self.e("move.b (sp),%d(a6)" % PB_OFF)
            for line in wb:
                self.e(line)
            self.e("move.w d7,ccr")
        else:
            for line in wb:
                self.e(line)

    def emit_incdec(self, v, ins, mn, o, w):
        sz = "b" if w == 1 else "w"
        self.no_aux(v)

        def body():
            if self.odd_word(v, o, w) and not self.live(v) & P:
                self.odd_rmw(v, ins, o, lambda loc: self.e("%s.w #1,%s" % ("addq" if mn == "inc" else "subq", loc)))
                return
            loc, wb = self.rmw_operand(v, ins, o, w)
            self.e("%s.%s #1,%s" % ("addq" if mn == "inc" else "subq", sz, loc))
            self.finish_rmw(v, loc, wb, w)
        if o[0] == "r" and w == 2 and o[1] == SP:
            if self.live(v) & ALLF:
                raise Unsupported("inc sp with flags")
            self.e("%s.l #1,a5" % ("addq" if mn == "inc" else "subq"))
            return
        self.wrap(v, N | Z | V, body)

    def emit_unary(self, v, ins, mn, o, w):
        sz = "b" if w == 1 else "w"
        if mn == "neg":
            def nb():
                loc, wb = self.rmw_operand(v, ins, o, w)
                self.e("neg.%s %s" % (sz, loc))
                self.finish_rmw(v, loc, wb, w)
            self.wrap(v, C | Z | N, nb)
            return

        def body():
            loc, wb = self.rmw_operand(v, ins, o, w)
            self.e("not.%s %s" % (sz, loc))
            self.finish_rmw(v, loc, wb, w, par=False)
        self.keep_all(v, body)

    # -- shifts -------------------------------------------------------------------------------------------
    def emit_shift(self, v, ins, mn, o, cnt, w):
        sz = "b" if w == 1 else "w"
        live = self.live(v)
        if cnt[0] != "i":
            k = self.const_cl(v, ins)
            if k is None:
                self.shift_cl(v, ins, mn, o, w)
                return
            cnt = ("i", k)
        n = cnt[1] & 0xFF
        if n == 0:
            return
        if mn == "shl":
            n &= 31                                     # (MAME's host shifts: shl by c & 31, shr / shra by
            if n == 0:                                  # ((c - 1) & 31) + 1)
                raise Unsupported("shl by a multiple of 32")
        elif mn in ("shr", "shra"):
            n = ((n - 1) & 31) + 1
        one = n == 1 and ins.op in (0xD0, 0xD1)
        if live & A and mn in ("shl", "shr", "shra"):
            pass                                        # (AC unchanged by MAME's shifts)
        mem = o[0] == "m"
        hreg = self.dst_is_hreg(o, w)
        par = mn in ("shl", "shr", "shra")
        carry = mn in ("rolc", "rorc")
        if mem and self.odd_word(v, o, w):
            raise Unsupported("shift odd word")
        if hreg or mem and (w == 1 or n != 1):
            def via_d7():
                if carry:
                    self.e("move.w sr,-(sp)")             # (C, for X after the setup)
                if hreg:
                    self.e("move.w %s,-(sp)" % REGW[o[1] - 4])
                    loc, k = "(sp)", 3
                else:
                    self.mem(v, ins, o, w, in_a0=True)
                    loc, k = "(a0)", 1
                if carry:
                    self.e("move.b %d(sp),d7" % k)
                    self.e("lsr.b #1,d7")                 # X = C
                self.e("move.%s %s,d7" % (sz, loc))
                self.shift_reg(v, mn, "d7", n, sz, w, one, x_done=True)
                self.e("move.w sr,-(sp)")
                if one and mn == "shr" and self.live(v) & V:
                    skip = self.new_label()
                    self.e("bclr #1,1(sp)")
                    self.e("btst #%d,d7" % (14 if w == 2 else 6))
                    self.e("beq.s %s" % skip)
                    self.e("bset #1,1(sp)")
                    self.lines.append(skip + ":")
                self.e("move.%s d7,%s" % (sz, "2(sp)" if hreg else "(a0)"))
                if live & P and par:
                    self.e("move.b d7,%d(a6)" % PB_OFF)
                self.e("move.w (sp)+,d7")
                if hreg:
                    self.e("move.w (sp)+,%s" % REGW[o[1] - 4])
                if carry:
                    self.e("addq.l #2,sp")
                self.e("move.w d7,ccr")
            self.shift_flags(v, ins, mn, one, via_d7)
            return

        def direct():
            loc, wb = self.rmw_operand(v, ins, o, w)
            if mem:
                m68 = {"shl": "asl" if one else "lsl", "shr": "lsr", "shra": "asr", "rol": "rol", "ror": "ror",
                       "rolc": "roxl", "rorc": "roxr"}[mn]
                if carry:
                    self.x_from_c()
                self.e("%s.w %s" % (m68, loc))
            else:
                self.shift_reg(v, mn, loc, n, sz, w, one=one)
            if one and mn == "shr" and self.live(v) & V:
                self.shr_v(loc, w)
            self.finish_rmw(v, loc, wb, w, par=par)
        self.shift_flags(v, ins, mn, one, direct)

    def shr_v(self, loc, w):
        """SHR by one: O = the old top bit (the result's next one)"""
        if not loc.startswith("d") or loc == "d7":
            raise Unsupported("shr V of memory")
        self.e("move.w sr,-(sp)")
        self.e("bclr #1,1(sp)")
        self.e("btst #%d,%s" % (14 if w == 2 else 6, loc))
        skip = self.new_label()
        self.e("beq.s %s" % skip)
        self.e("bset #1,1(sp)")
        self.lines.append(skip + ":")
        self.e("move.w (sp)+,ccr")

    def shift_reg(self, v, mn, loc, n, sz, w, one=False, x_done=False):
        """shift / rotate the data register loc by n (immediate); x_done: X already = C"""
        m68 = {"shl": "asl" if one else "lsl", "shr": "lsr", "shra": "asr", "rol": "rol", "ror": "ror",
               "rolc": "roxl", "rorc": "roxr"}[mn]
        if mn in ("rolc", "rorc") and not x_done:
            if loc == "d7":
                raise Unsupported("rotate through carry of d7")
            self.x_from_c()
        if mn in ("rol", "ror"):
            n %= 8 * w
            if n == 0:
                n = 8 * w                                # (the carry is the bit rotated last)
        while n > 8:
            self.e("%s.%s #8,%s" % (m68, sz, loc))
            n -= 8
        if n == 1 and m68 == "lsl":
            self.e("add.%s %s,%s" % (sz, loc, loc))
        else:
            self.e("%s.%s #%d,%s" % (m68, sz, n, loc))

    def shift_flags(self, v, ins, mn, one, body):
        """the flags of a shift / rotate by an immediate count around its body"""
        live = self.live(v) & CCR
        if mn in ("shl", "shr", "shra"):
            ok = C | Z | N
            if one and mn != "shr":
                ok |= V
            if one and mn == "shr" and live & V:
                ok |= V                                 # (shr_v)
            self.wrap(v, ok, body)
            return
        # rotates: C (and V for one bit); Z N unchanged
        if one and live & V:
            raise Unsupported("rotate V")
        self.wrap(v, C, body)

    def const_reg(self, v, o):
        """a word register's value when the instruction before (straight code, no join here) is MOV reg, imm"""
        if o[0] != "r" or v in self.joins:
            return None
        u = self.prev.get(v)
        if u is not None and u < v:
            pi = self.code[u]
            if pi.mn == "mov" and pi.ops[0] == ("r", o[1], 2) and pi.ops[1][0] == "i":
                return pi.ops[1][1] & 0xFFFF
        return None

    def const_cl(self, v, ins):
        """CL's value when the instruction before (straight code, no join here) is MOV CL / CW, imm"""
        if v in self.joins:
            return None
        u = self.prev.get(v)
        if u is not None and u < v:
            pi = self.code[u]
            if pi.mn == "mov" and pi.ops[0] in (("r", 1, 1), ("r", 1, 2)) and pi.ops[1][0] == "i":
                return pi.ops[1][1] & 0xFF
        return None

    def shift_cl(self, v, ins, mn, o, w):
        raise Unsupported("shift by CL")

    # -- stack -----------------------------------------------------------------------------------------------
    def emit_push(self, v, ins, o):
        live = self.live(v) & CCR
        if o[0] == "i":
            self.push_word(v, "#$%04X" % (o[1] & 0xFFFF))
            return
        if o[0] == "r" and o[1] != SP:
            self.push_word(v, REGW[o[1]])
            return
        if o[0] == "s":
            self.keep_all(v, lambda: self.e("move.w %d(a6),-(a5)" % (SEG_OFF + 2 * o[1])) if o[1] != PS else
                          self.e("move.w #$%04X,-(a5)" % ins.cs))
            return
        if o[0] == "r":                               # PUSH SP: the new SP (MAME)
            def b():
                self.e("move.l a5,d7")
                self.e("sub.l a4,d7")
                self.e("subq.w #2,d7")
                self.e("move.w d7,-(a5)")
            self.keep_all(v, b)
            return

        def b2():
            s = self.src(v, ins, o, 2)
            self.e("move.w %s,-(a5)" % s)
        self.keep_all(v, b2)

    def emit_pop(self, v, ins, o):
        if o[0] == "r" and o[1] != SP:
            self.keep_all(v, lambda: self.e("move.w (a5)+,%s" % REGW[o[1]]))
            return
        if o[0] == "s":
            def b():
                self.e("moveq #0,d7")
                self.e("move.w (a5)+,d7")
                self.sreg_from_d7(o[1])
            self.keep_all(v, b)
            return
        if o[0] == "m":
            def b2():
                self.e("move.w (a5)+,-(sp)")
                ea = self.mem(v, ins, o, 2, in_a0=True)
                self.e("move.w (sp)+,%s" % ea)
            if self.odd_word(v, o, 2):
                raise Unsupported("pop odd")
            self.keep_all(v, b2)
            return
        raise Unsupported("pop sp")

    def emit_pushpopa(self, v, ins, mn):
        def b():
            if mn == "pusha":
                self.e("move.l a5,d7")
                self.e("sub.l a4,d7")
                for r in ("d0", "d1", "d2", "d3", "d7", "d6", "d4", "d5"):
                    self.e("move.w %s,-(a5)" % r)
            else:
                for r in ("d5", "d4", "d6"):
                    self.e("move.w (a5)+,%s" % r)
                self.e("addq.l #2,a5")
                for r in ("d3", "d2", "d1", "d0"):
                    self.e("move.w (a5)+,%s" % r)
        self.keep_all(v, b)

    def emit_psw(self, v, ins, mn):
        if mn == "pushf":
            self.e("jsr v30_psw_out")                  # (d7 = the PSW; the CCR kept)
            self.push_word(v, "d7")
            return
        if mn == "popf":
            self.e("move.w (a5)+,a0")
            self.e("jsr v30_psw_in")
            return
        raise Unsupported(mn)

    def emit_frame(self, v, ins, mn):
        raise Unsupported(mn)

    # -- bits -------------------------------------------------------------------------------------------------
    def emit_bit(self, v, ins, mn, o, bit, w):
        if bit[0] != "i":
            raise Unsupported("bit number in CL")
        b = bit[1]
        if mn == "test1":
            raise Unsupported("test1")
        op = {"clr1": "bclr", "set1": "bset", "not1": "bchg"}[mn]

        def body():
            if o[0] == "r":
                loc, wb = self.rmw_operand(v, ins, o, w)
                self.e("%s #%d,%s" % (op, b, loc))
                for line in wb:
                    self.e(line)
                return
            if self.odd_word(v, o, w):
                raise Unsupported("bit op on an odd word")
            ea = self.mem(v, ins, o, w)
            if w == 2:
                self.e("%s #%d,%s" % (op, b - 8, ea) if b >= 8 else "%s #%d,%s" % (op, b, self.ea_plus(ea, 1)))
            else:
                self.e("%s #%d,%s" % (op, b, ea))
        hreg = o[0] == "r" and self.dst_is_hreg(o, w)
        self.wrap(v, 0 if hreg else C | V | N, body)          # (bclr / bset / bchg change only Z)

    # -- I/O --------------------------------------------------------------------------------------------------
    def emit_io(self, v, ins):
        mn, w = ins.mn, ins.w
        reg, port = ins.ops
        if port[0] == "i":
            fn = self.p.port_in if mn == "in" else self.p.port_out
            lines = fn(port[1], w) if fn else None
            if lines is not None:
                self.keep_all(v, lambda: [self.e(x) for x in lines])
                return

        def b():
            if port[0] == "i":
                self.e("move.w #$%02X,d7" % port[1])
            else:
                self.e("move.w d2,d7")
            self.e("jsr v30_%s%s" % (mn, "w" if w == 2 else "b"))
        self.keep_all(v, b)

    # -- strings ------------------------------------------------------------------------------------------------
    def emit_string(self, v, ins):
        mn, w = ins.mn, ins.w
        sz = "b" if w == 1 else "w"
        srcseg = ins.seg if ins.seg is not None else DS0
        sbase, sabs = self.seg_base(ins, srcseg)
        if ins.rep:
            self.emit_rep(v, ins, sbase, sabs)
            return
        live = self.live(v) & CCR
        dsto, srco = ("m", (IY,), 0, DS1), ("m", (IX,), 0, srcseg)
        odd = w == 2 and self.odd_site(v)

        def step(*regs):
            for r in regs:
                self.e("addq.w #%d,%s" % (w, r))

        def body():
            if mn == "stm":
                self.store(v, ins, dsto, "d0", w)
                step("d5")
            elif mn == "ldm":
                self.e("move.%s %s,d0" % (sz, self.src(v, ins, srco, w)))
                step("d4")
            else:
                self.e("move.%s %s,-(sp)" % (sz, self.src(v, ins, srco, w)))
                self.store(v, ins, dsto, "(sp)+", w)
                step("d4", "d5")
        if mn in ("stm", "ldm", "movbk"):
            self.keep_all(v, body)
            return
        lo = "(a0)" if w == 1 else "1(a0)"
        if mn == "cmpm":
            if odd:
                self.word_any(v, ins, dsto)
                self.e("cmp.w d7,d0")
                if self.live(v) & P:
                    self.e("move.w sr,-(sp)")
                    self.e("sub.b d0,d7")
                    self.e("neg.b d7")
                    self.e("move.b d7,%d(a6)" % PB_OFF)
                    self.e("move.w (sp)+,ccr")
            else:
                self.mem(v, ins, dsto, w, in_a0=True)
                self.e("cmp.%s (a0),d0" % sz)
                if self.live(v) & P:
                    self.e("move.w sr,-(sp)")
                    self.e("move.b d0,d7")
                    self.e("sub.b %s,d7" % lo)
                    self.e("move.b d7,%d(a6)" % PB_OFF)
                    self.e("move.w (sp)+,ccr")
            if live:
                self.e("move.w sr,-(sp)")
            step("d5")
            if live:
                self.e("move.w (sp)+,ccr")
            return
        if mn == "cmpbk":
            d = self.src(v, ins, dsto, w)
            self.e("move.%s %s,-(sp)" % (sz, d))
            s1 = self.src(v, ins, srco, w)
            if s1 != "d7":
                self.e("move.%s %s,d7" % (sz, s1))
            self.e("cmp.%s (sp),d7" % sz)
            if self.live(v) & P:
                self.e("move.w sr,-(sp)")
                self.e("sub.b %d(sp),d7" % (3 if w == 2 else 2))
                self.e("move.b d7,%d(a6)" % PB_OFF)
                self.e("move.w (sp)+,ccr")
            self.e("addq.l #2,sp")
            if live:
                self.e("move.w sr,-(sp)")
            step("d4", "d5")
            if live:
                self.e("move.w (sp)+,ccr")
            return
        raise Unsupported(mn)

    def emit_rep(self, v, ins, sbase, sabs):
        """REP string instructions: runtime routines (a0 = the source base, a1 = the destination base)"""
        mn, w = ins.mn, ins.w
        if ins.rep not in ("rep",) or mn not in ("stm", "movbk"):
            raise Unsupported("%s %s" % (ins.rep, mn))

        def b():
            if mn == "movbk":
                if sabs:
                    self.e("lea %s,a0" % sabs)
                else:
                    self.e("move.l %s,a0" % sbase)
            self.e("jsr v30_rep_%s%s" % (mn, "b" if w == 1 else "w"))
        self.keep_all(v, b)

    # -- multiply / divide -----------------------------------------------------------------------------------
    def emit_mul(self, v, ins):
        mn, w = ins.mn, ins.w
        live = self.live(v) & CCR
        if live & (C | V):
            raise Unsupported("mul flags")
        if mn == "imul":
            r, m, imm = ins.ops

            def b():
                s = self.src(v, ins, m, 2)
                self.e("move.w %s,d7" % s)
                self.e("muls.w #$%X,d7" % (imm[1] & 0xFFFF))
                self.e("move.w d7,%s" % REGW[r[1]])
            self.keep_all(v, b)
            return
        o = ins.ops[0]
        signed = mn == "mul"

        def b2():
            if w == 1:
                s = self.src(v, ins, o, 1)
                if signed:
                    self.e("move.b %s,d7" % s)
                    self.e("ext.w d7")
                    self.e("ext.w d0")
                    self.e("muls.w d7,d0")
                else:
                    if s != "d7":
                        self.e("moveq #0,d7")
                        self.e("move.b %s,d7" % s)
                    else:
                        self.e("and.w #$FF,d7")
                    self.e("and.w #$FF,d0")
                    self.e("mulu.w d7,d0")
                self.e("and.l #$FFFF,d0")
                return
            s = self.src(v, ins, o, 2)
            self.e("%s.w %s,d0" % ("muls" if signed else "mulu", s))
            self.e("move.l d0,d2")
            self.e("clr.w d2")
            self.e("swap d2")
            self.e("and.l #$FFFF,d0")
        self.keep_all(v, b2)

    def emit_div(self, v, ins):
        mn, w = ins.mn, ins.w
        o = ins.ops[0]
        signed = mn == "div"

        def b():
            if w == 2:
                s = self.free_d7(self.src(v, ins, o, 2))
                if s == "d7":
                    raise Unsupported("div by d7")
                self.e("move.w d2,d7")
                self.e("swap d7")
                self.e("move.w d0,d7")
                self.e("%s.w %s,d7" % ("divs" if signed else "divu", s))
                self.e("move.w d7,d0")
                self.e("swap d7")
                self.e("move.w d7,d2")
                return
            s = self.src(v, ins, o, 1)
            if s != "d7":
                self.e("move.b %s,d7" % s)
            if signed:
                self.e("ext.w d7")
                self.e("ext.l d0")
                self.e("divs.w d7,d0")
            else:
                self.e("and.w #$FF,d7")
                self.e("divu.w d7,d0")
            self.e("move.l d0,d7")                      # remainder:quotient -> AH:AL
            self.e("swap d7")
            self.e("lsl.w #8,d7")
            self.e("move.b d0,d7")
            self.e("moveq #0,d0")
            self.e("move.w d7,d0")
        self.wrap(v, 0, b, const_set=C | V)


def translate(prog):
    """-> (asm lines, report, emitter, code)"""
    code, joins = discover(prog)
    rets = function_returns(code, prog.targets)
    live_in, live_out = liveness(prog, code, rets)
    em = Emitter(prog, code, joins, live_out, rets)
    em.live_in = live_in
    em.emit_all()
    missing = sorted(v for v in em.refs if v not in code)
    lines = list(em.lines)
    lines.append("; --- referenced but not code")
    for v in missing:
        lines.append("%s:\tmove.l #$%X,d7\n\tjmp %s_badpc" % (prog.label(v), v, prog.name))
    entries = set(em.entries) | {lin_of(*r) for r in prog.roots}
    for v, s in rets.items():
        entries |= s
    entries = sorted(e for e in entries if e in code)
    report = dict(instructions=len(code), unsupported=em.unsupported, missing=["%05X" % v for v in missing],
                  stats=dict(em.stats), entries=len(entries), conflicts=len(prog.conflicts))
    return lines, report, em, code, entries


def dispatch_table(prog, entries, bits=13):
    """the dispatcher's hash table: 2^bits slots of (linear.l, label.l), slot = linear & mask, linear probing; laid
    out for a .w index centred on the table's middle (slot s at byte 8 * ((s + half) mod size))"""
    size = 1 << bits
    half = size // 2
    slots = [None] * size
    for e in entries:
        s = e & (size - 1)
        while slots[s] is not None:
            s = (s + 1) & (size - 1)
        slots[s] = e
    out = [None] * size
    for s, e in enumerate(slots):
        out[(s + half) % size] = e
    lines = ["\teven", "%s_disp_table:" % prog.name]
    for e in out:
        lines.append("\tdc.l $%X,%s" % (e, prog.label(e)) if e is not None else "\tdc.l 0,0")
    return lines
