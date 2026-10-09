"""Z80 -> 68000 static translator (STE port of arcade Z80 programs).

Pipeline (same shape as F030CT's tools/smkx):
  1. discovery (discover.py): reachable instructions from entries/dispatch seeds
  2. flag liveness over the instruction graph
  3. emission: one 68000 snippet per Z80 instruction, labelled Z<pc>

Machine conventions of the generated code
-----------------------------------------
  d0.b  A                      a0..a2  BC' DE' HL'  (exx = exg), or free (Config.alt_regs)
  d1.w  BC                     a3.b    A'            (ex af,af' = exg d0,a3), or free (Config.alt_af)
  d2.w  DE                     a4      dispatch table (Z80 pc*4 -> 68k address)
  d3.w  HL                     a5      Z80 SP, a real pointer into the block
  d4.w  IX                     a6      Z80 memory block (32 KiB, base of $0000)
  d5    scratch 2              a7      native stack (interrupt/runtime only)
  d6.w  Z80 flags image: 68k CCR bits N=S(8) Z(4) C(1); bit5 = H, bit6 = N
        (V/PV, X, Y are not tracked)
  d7    scratch 1
  IY and F' live in the block at IYADDR / FSHADOW (little used)

The register map can be changed per program (Config, see Emitter.regmap):
  alt_af="upper":   A' in bits 16-23 of d0, F' in the upper word of d6: ex af,af' = swap d0 / swap d6,
                    and a3 is free for the computed jumps (ret, jp (hl): 50 cycles instead of 66)
  alt_regs="upper": BC' DE' HL' in the upper words of d1-d3: exx = three swaps ("signed" mode only, the
                    "long" mode needs the upper words 0); a0-a2 are free then
  iy_reg="a2":      IY in an address register (the low word) instead of the block ("signed" mode only)

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
# P/V (parity after and/or/xor) is tracked only for `jp/call/ret pe|po` that do not directly follow ldi/cpi:
# bit 7 of d6, computed by the producers where the liveness says a consumer reads it (and for Config.pv_force)
PV = 32
PV_BIT = 7
PV_PRODUCERS = {"and", "or", "xor"}
PV_PASS = {"ex af,af'", "ldi", "ldd", "ldir", "lddr", "cpi", "cpd", "cpir", "cpdr"}
CCRBIT = {S: 0x08, Z: 0x04, C: 0x01}           # 68k CCR bit for a Z80 flag
D6BIT = {H: 5, N: 6}

IYADDR = 0x7FF0
FSHADOW = 0x7FF2
IO_READ_REDIRECT = {0x7C00: 0x7E00, 0x7C80: 0x7E80, 0x7D00: 0x7F00, 0x7D80: 0x7F80}
DMA_TRIGGER = 0x7D85
NMI_TOKEN = 0x4001
TABLE_ENTRIES = 0x4002


class Config:
    """What differs between the programs the translator handles (the defaults are the
    Donkey Kong main CPU).

    prefix: of the instruction labels (Z1234); table / token_sym: the dispatch table and
    the code a token on the Z80 stack returns to (the runtime's interrupt entry).
    mode "signed": a6 is the base of the Z80 address 0 and the index is the signed word
    (addresses >= $8000 lie below a6; a 32 KB block raises for them); mode "long": the
    index is the long (upper words of the registers kept 0), static accesses to $8000 and
    up go through `ram_sym` (the RAM starts at a6 + $8000).  iyaddr / fshadow: two unused
    RAM words of the program for IY and F'.  write_hooks: (lo, hi, label, bit) - after
    `ld (nn),a` with nn in lo..hi, `bsr label` (only if bit `bit` of A is set, if given).
    """

    def __init__(self, prefix="Z", table="z80_dispatch", token_sym="z80_nmi_ret", mode="signed",
                 block=0x8000, ram_sym=None, iyaddr=IYADDR, fshadow=FSHADOW, io_read_redirect=None,
                 write_hooks=((DMA_TRIGGER, DMA_TRIGGER, "z80_dma", 0),), nmi_token=NMI_TOKEN,
                 table_entries=TABLE_ENTRIES, rst28_tables=True, iff_sym=None, hl_tables=False, pv_force=(), bit_s=False,
                 alt_af="a3", alt_regs="areg", iy_reg=None):
        self.prefix = prefix
        self.alt_af = alt_af            # "a3" | "upper" (see the module docs)
        self.alt_regs = alt_regs        # "areg" | "upper"
        self.iy_reg = iy_reg            # None (the block) | "a0".."a2"
        if mode == "long" and (alt_regs == "upper" or iy_reg):
            raise ValueError("the long mode keeps the upper words of the registers 0")
        self.bit_s = bit_s              # BIT sets S as the CPU does (the flags a task saves on its stack are exact; one more instruction)
        self.pv_force = set(pv_force)   # and/or/xor pcs whose parity must reach d6 bit 7 although the liveness does not see the reader (across ex af,af')
        self.table = table
        self.token_sym = token_sym
        self.mode = mode
        self.block = block
        self.ram_sym = ram_sym
        self.iyaddr = iyaddr
        self.fshadow = fshadow
        self.io_read_redirect = IO_READ_REDIRECT if io_read_redirect is None else io_read_redirect
        self.write_hooks = list(write_hooks)
        self.nmi_token = nmi_token
        self.table_entries = table_entries
        self.rst28_tables = rst28_tables
        self.hl_tables = hl_tables
        self.iff_sym = iff_sym          # a byte the runtime reads for the IRQ gate (ei / di)

# the fast register maps (module docs): a "signed" mode program, a "long" mode program
FAST = dict(alt_af="upper", alt_regs="upper", iy_reg="a2")
FAST_LONG = dict(alt_af="upper")

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
    """(uses, defs) over the tracked flags S Z C H N and P/V (see PV)."""
    u, d = _uses_defs(ins)
    mn = ins.mn
    if d & (S | Z) or mn in ("ldi", "ldd", "ldir", "lddr"):
        d |= PV
    if mn == "ex af,af'":
        d |= PV                  # (the swap carries d6 bit 7 along; what the consumer reads was produced earlier: pv_force)
    if mn in ("jr", "jp", "call", "ret") and ins.ops and ins.ops[0][0] == "cc" and ins.ops[0][1] in ("pe", "po"):
        u |= PV
    return u, d


def _uses_defs(ins):
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
    if mn == "ld a,i":
        return 0, S | Z | H | N
    return 0, 0


def flow_uses(ins, ijmp_flags=False):
    """Extra liveness 'uses' at control-flow boundaries (flags a callee/caller may read).  ijmp_flags: a computed jump
    (`jp (hl)`) passes the flags on too (1942: the scheduler starts a task with it and the task saves them on its stack)."""
    if ins.flow in ("call", "ccall", "ret", "cret", "rst") or (ijmp_flags and ins.flow == "ijmp"):
        return CCRF
    return 0


SP_WRITERS = {"inc sp", "dec sp", "ld sp,hl", "ld sp,ix", "ld sp,iy"}


def ret_targets(code, foreign=(), rst28_tables=True):
    """ret pc -> the return points it goes to, for the rets of well-behaved functions only (the flag liveness then
    follows the ret to them instead of taking every flag as read).  A function is the code reached from a call
    target without entering calls; it is well-behaved when its stack is balanced on every path (no pop of the
    return address, no ex (sp) of it, SP not set), and its rets are not reached from an entry other than a call
    target (`foreign`: the interrupt and reset entries, jump table targets, code addresses the program holds)."""
    rps = {}
    for pc, ins in code.items():
        if ins.flow in ("call", "ccall", "rst") and ins.target in code:
            if ins.flow == "rst" and ins.target == 0x28 and rst28_tables:
                continue
            rps.setdefault(ins.target, set()).add(pc + ins.length)

    def walk(entry):
        depth, rets, ok = {}, set(), True
        todo = [(entry, 0)]
        while todo:
            pc, dep = todo.pop()
            if pc not in code:
                ok = False
                continue
            if pc in depth:
                ok &= depth[pc] == dep
                continue
            if len(depth) > 8000:
                return rets, False
            depth[pc] = dep
            ins = code[pc]
            mn, fl, nxt = ins.mn, ins.flow, pc + ins.length
            if mn == "push":
                dep += 1
            elif mn == "pop":
                if dep == 0:
                    ok = False
                    continue
                dep -= 1
            elif mn == "ex" and ins.ops[0][0] == "ind" and dep == 0:
                ok = False
            elif mn in ("reti", "retn") or ins.text in SP_WRITERS or (mn == "ld" and ins.ops[0] == ("r16", "sp")):
                ok = False
            if fl in ("ret", "cret"):
                if mn == "ret":
                    rets.add(pc)
                    ok &= dep == 0
                if fl == "cret":
                    todo.append((nxt, dep))
                continue
            if fl in ("seq", "call", "ccall", "rst"):
                if fl == "rst" and ins.target == 0x28 and rst28_tables:
                    continue
                todo.append((nxt, dep))
            if fl in ("jmp", "jcc") and ins.target is not None:
                todo.append((ins.target, dep))
            if fl == "jcc":
                todo.append((nxt, dep))
        return rets, ok

    out, bad = {}, set()
    for tgt, points in rps.items():
        rets, ok = walk(tgt)
        for r in rets:
            if ok:
                out.setdefault(r, set()).update(points)
            else:
                bad.add(r)
    for f in foreign:
        if f in code:
            bad |= walk(f)[0]
    return {r: s for r, s in out.items() if r not in bad}


def compute_liveness(code, ccr_users=(), ijmp_flags=False, flags_at=(), ret_succ=None):
    """live_in / live_out per pc (bitmask of tracked flags).  ccr_users: conditional jumps
    that read the 68k condition codes instead of d6 (Emitter.analyze), no use of d6.  flags_at: pcs where the
    flags in d6 must be exact (a hook that delivers an interrupt, whose handler saves them).  ret_succ (from
    ret_targets): the rets whose return points are known; then a call passes the flags to its callee (no longer read
    by the call itself) and those rets to their return points."""
    succs = {}
    callee = {}
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
            if ret_succ is not None and ins.target in code and not (fl == "rst" and ins.target == 0x28):
                callee[pc] = ins.target
        elif fl == "cret":
            s = [nxt]
        if ret_succ is not None and pc in ret_succ:
            s = s + sorted(ret_succ[pc])
        succs[pc] = [x for x in s if x in code]
    uses = {}
    defs = {}
    for pc, ins in code.items():
        u, d = uses_defs(ins)
        if pc in ccr_users:
            u = 0
        fu = flow_uses(ins, ijmp_flags)
        if pc in callee or (ret_succ is not None and pc in ret_succ):
            fu = 0
        uses[pc] = u | fu | (CCRF if pc in flags_at else 0)
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
                lo &= ~(H | N | PV)      # H/N/PV are not preserved across calls
                if pc in callee:
                    lo |= live_in[callee[pc]]       # what the callee reads
            li = uses[pc] | (lo & ~defs[pc])
            if li != live_in[pc] or lo != live_out[pc]:
                live_in[pc] = li
                live_out[pc] = lo
                changed = True
    return live_in, live_out


# --------------------------------------------------------------------------
# Flags in the condition codes
#
# A flag producing instruction leaves S Z C of its result in the CCR; a conditional
# jump right behind it can branch on that instead of reloading the CCR from d6 (12
# cycles), if nothing in between destroyed the bit.  Emitter.analyze works out, per
# instruction, which Z80 flags the CCR holds at its start (a forward must-analysis over
# the code: the intersection over the predecessors, nothing at the entries, the return
# points and the targets of computed jumps).  The jumps that can read the CCR then no
# longer count as uses of d6, so a producer whose flags are only read that way stores
# nothing.  Stores can only become fewer by this, and a load of the CCR counts for
# nothing, so the analysis of the first emission holds for the final one.
# --------------------------------------------------------------------------

BCC = {"bra", "bcc", "bcs", "beq", "bne", "bpl", "bmi", "bhi", "bls", "bhs", "blo", "bge", "blt",
       "bgt", "ble", "bvc", "bvs"}
KILL_NONE = {"lea", "pea", "exg", "movem", "jmp", "rts", "nop", "movep", "dbf", "dbra", "movea",
             "adda", "suba"} | BCC
KILL_Z = {"btst", "bset", "bclr", "bchg"}
AN_DST = {"move", "add", "sub", "addq", "subq"}


def ccr_kill(line):
    """The Z80 flags (of S Z C) whose copy in the CCR a 68k instruction destroys.  Nearly
    everything sets N Z and clears C (a move too); only address register operations, the
    bit instructions (Z) and the control flow leave them alone."""
    s = line.strip()
    if not s or s.endswith(":") or s.startswith(";"):
        return 0
    mn, _, ops = s.partition(" ")
    mn = mn.split(".")[0].lower()
    ops = ops.split(";")[0].strip()
    if mn in KILL_NONE:
        return 0
    if mn in AN_DST and "," in ops:
        dst = ops.rsplit(",", 1)[1].strip().lower()
        if dst == "ccr":
            return 0            # a load from d6 (counts for nothing, kills nothing)
        if dst in ("a0", "a1", "a2", "a3", "a4", "a5", "a6", "a7", "sp"):
            return 0
    if mn == "move" and ops.startswith("sr,"):
        return 0
    if mn in KILL_Z:
        return Z
    return CCRF


import re as _re
_MOVE_B = _re.compile(r"^move\.b\s+(d[0-7]),")
_CORE = _re.compile(r"^(add|addq|addx|sub|subq|subx|and|andi|or|ori|eor|eori|neg|lsl|lsr|asl|asr|rol|ror|roxl|roxr|tst)"
                    r"\.b\s+(?:[^,]*,)?(d[0-7])$")
_REG_WRITERS = {"exg", "movem", "movep", "dbf", "dbra"}


def _dst(ops):
    """the destination operand of a 68000 line's operands"""
    depth, cut = 0, -1
    for i, ch in enumerate(ops):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            cut = i
    return ops[cut + 1:].strip().lower()


def ccr_step(line, valid, zreg):
    """(valid, zreg) after one 68000 line.  valid: the Z80 flags the CCR holds; zreg: the data register whose
    byte the Z80's S and Z describe (the result of the last flag op), whether the CCR shows them or not.  A move.b
    or tst.b of zreg sets N and Z from that byte: S and Z are in the CCR again (C is not)."""
    s = line.strip()
    if not s or s.endswith(":") or s.startswith(";"):
        return valid, zreg
    parts = s.split(None, 1)
    mn = parts[0].split(".")[0].lower()
    ops = parts[1].split(";")[0].strip() if len(parts) > 1 else ""
    k = ccr_kill(s)
    if zreg:
        if (mn == "move" or mn == "tst") and parts[0].lower().endswith(".b"):
            src = ops.split(",", 1)[0].strip().lower()
            if src == zreg and (mn == "tst" or _dst(ops) != zreg):
                return (valid & ~C) | S | Z, zreg
        if _dst(ops) == zreg or (mn in _REG_WRITERS and zreg in ops) or mn in ("bsr", "jsr"):
            zreg = None                         # (a runtime routine may change any register)
    return valid & ~k, zreg


def core_reg(line):
    """the data register an ALU line leaves its byte result in (its N and Z describe it), or None"""
    if line is None:
        return None
    s = line.strip().split(";")[0].strip()
    if s.startswith("cmp"):
        return None
    m = _CORE.match(s)
    return m.group(2) if m else None


# --------------------------------------------------------------------------
# emitter
# --------------------------------------------------------------------------

REG16 = {"bc": "d1", "de": "d2", "hl": "d3", "ix": "d4"}
# BC is kept byte-swapped (B in the low byte, C in the high one): B is the register the
# program works with (djnz, ld b,(hl), ...), the pair is rare.  That is also the order of
# the bytes on the Z80 stack, so push/pop bc are plain word moves.
HALF = {"b": ("d1", False), "c": ("d1", True), "d": ("d2", True), "e": ("d2", False),
        "h": ("d3", True), "l": ("d3", False), "ixh": ("d4", True), "ixl": ("d4", False)}
SWAPPED = {"bc"}


def swap16(v):
    return ((v & 0xFF) << 8) | ((v >> 8) & 0xFF)


def hx(v, w=4):
    return "$%0*X" % (w, v & ((1 << (4 * w)) - 1))


class Emitter:
    def __init__(self, code, live_in=None, live_out=None, leaders=None, cfg=None):
        self.code = code
        self.cfg = cfg or Config()
        self.ends = {pc + ins.length: pc for pc, ins in code.items()}   # fall-through predecessor
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
        # a3 holds A' only if the program uses ex af,af'; otherwise it is free for the
        # computed jumps
        self.alt_af_upper = self.cfg.alt_af == "upper"
        self.alt_upper = self.cfg.alt_regs == "upper"
        self.iyr = self.cfg.iy_reg
        self.a3_free = self.alt_af_upper or not any(ins.mn == "ex af,af'" for ins in code.values())
        self.after_label = {}   # pc -> label to put after its code (inc sp pairs)
        self.ccr_in = {}        # pc -> Z80 flags the CCR holds at the instruction (analyze)
        self.ccr_users = set()  # conditional jumps that branch on the CCR, no load from d6
        self.transfer = None    # collecting (keep, gen) per pc during analyze
        self.core_at = None     # where the current instruction's flag op ended, what it provided
        self.core_provided = 0
        self.joins = set()      # (analyze) pcs entered other than by the straight flow
        self.no_entry = set()   # pcs that must not be entered (merges): no table entry (z80_badpc)
        self.merged = set()     # of those, the ones whose label is not in the code (emitted as a stub)
        self.raw_af = set()     # push af / pop af pairs that keep the flags in the d6 format (pair_af)

    def regmap(self):
        """where the registers that are not plain data registers are kept (for the tests)"""
        return {"alt_af": "upper" if self.alt_af_upper else "none" if self.a3_free else "a3",
                "alt_regs": "upper" if self.alt_upper else "areg" if any(i.mn == "exx" for i in self.code.values()) else "none",
                "iy": self.iyr or "mem"}

    def free_aregs(self):
        """address registers the translated code may use as scratch"""
        out = ["a0", "a1", "a2"] if self.alt_upper or not any(i.mn == "exx" for i in self.code.values()) else []
        return [r for r in out if r != self.iyr]

    # ---- CCR validity ----------------------------------------------------
    def analyze(self, joins):
        """Compute ccr_in / ccr_users; joins: pcs where nothing is known about the CCR."""
        self.joins = set(joins)
        saved = (self.lines, self.uid, self.refs, self.unsupported, self.after_label)
        self.lines, self.refs, self.unsupported, self.after_label = [], set(), [], {}
        self.transfer = {}
        for pc in sorted(self.code):
            self.emit_ins(pc)
        transfer = self.transfer
        self.transfer = None
        self.lines, self.uid, self.refs, self.unsupported, self.after_label = saved

        preds = {pc: [] for pc in self.code}
        for pc, ins in self.code.items():
            nxt = pc + ins.length
            fl = ins.flow
            if fl == "seq" or fl == "cret":
                s = [nxt]
            elif fl in ("jmp", "call", "rst"):
                s = [ins.target]            # a callee gets the caller's flags
            elif fl in ("jcc", "ccall"):
                s = [ins.target, nxt]
            else:
                s = []
            for t in s:
                if t in preds:
                    preds[t].append(pc)
        state = {pc: (0, None) for pc in self.code}         # (valid flags, zreg) at the start
        order = sorted(self.code)
        changed = True
        while changed:
            changed = False
            for pc in order:
                if pc in joins or not preds[pc]:
                    continue
                v, z = CCRF, "?"
                for p in preds[pc]:
                    pv, pz = self.ccr_out(transfer[p], state[p])
                    v &= pv
                    z = pz if z == "?" or z == pz else None
                z = z if z != "?" else None
                if (v, z) != state[pc]:
                    state[pc] = (v, z)
                    changed = True
        self.ccr_in = {pc: s[0] for pc, s in state.items()}
        ccr_in = self.ccr_in
        self.ccr_users = set()
        for pc, ins in self.code.items():
            if ins.flow in ("jcc", "ccall", "cret") and ins.ops and ins.ops[0][0] == "cc":
                need = CC_USES.get(ins.ops[0][1])
                if need and need & ~ccr_in[pc] == 0 and pc not in self.hooks:
                    self.ccr_users.add(pc)

    def record_transfer(self, pc, start):
        """what ccr_out needs of the instruction's code: its lines, where its flag op ended, what it provided"""
        _, defs = uses_defs(self.code[pc])
        if self.core_at is None:
            self.transfer[pc] = (tuple(self.lines[start:]), False, None, 0, defs)
        else:
            core = self.lines[self.core_at - 1] if self.core_at > start else None
            self.transfer[pc] = (tuple(self.lines[self.core_at:]), True, core_reg(core), self.core_provided & CCRF, defs)

    @staticmethod
    def ccr_out(rec, st):
        """(valid, zreg) after an instruction's code, from (valid, zreg) before it"""
        lines, has_core, core, provided, defs = rec
        if lines is None:
            return 0, None                      # (an unsupported instruction)
        if has_core:                            # the flag op: what it provided, its result register
            v, z = provided, core if provided & (S | Z) else None
        else:
            v, z = st
            v &= ~(defs & CCRF)
            if defs & (S | Z):
                z = None
        for l in lines:
            v, z = ccr_step(l, v, z)
        return v, z

    # ---- small helpers -------------------------------------------------
    def new_label(self):
        self.uid += 1
        return "L%s%d" % (self.cfg.prefix.lower() if self.cfg.prefix != "Z" else "x", self.uid)

    def e(self, s):
        self.lines.append("\t" + s)

    def label_of(self, pc):
        self.refs.add(pc)
        return "%s%04X" % (self.cfg.prefix, pc)

    def half(self, n):
        if n not in HALF:
            raise Unsupported("8-bit register %s" % n)
        return HALF[n]

    def mem(self, addr, off=0, io_read=False):
        """effective address of the static Z80 address addr + off."""
        cfg = self.cfg
        a = (addr + off) & 0xFFFF
        if io_read and addr in cfg.io_read_redirect:
            a = cfg.io_read_redirect[addr]
        if a < 0x8000:
            return "%s(a6)" % hx(a)
        if cfg.mode == "long":
            return "%s+%s" % (cfg.ram_sym, hx(a - 0x8000))
        if cfg.block < 0x10000:
            raise Unsupported("address %04X outside the 32 KiB block" % a)
        return "-%s(a6)" % hx(0x10000 - a)

    def ind(self, reg, disp=0):
        """effective address of the Z80 address in a data register (the pair's natural value)."""
        x = "%s.%s" % (reg, "l" if self.cfg.mode == "long" else "w")
        return "%d(a6,%s)" % (disp, x) if disp else "(a6,%s)" % x

    def clean(self, reg):
        """lines that clear the upper word of a scratch register before it is an index."""
        return ["moveq #0,%s" % reg] if self.cfg.mode == "long" else []

    # operand access --------------------------------------------------------
    def read8(self, op, io_read=True):
        """-> (pre_lines, ea) with ea usable as a byte source operand."""
        k = op[0]
        if k == "r8":
            n = op[1]
            if n == "a":
                return [], "d0"
            if n in HALF:
                reg, hi = self.half(n)
                if hi:
                    # the high byte through the 68000 stack: the word pushed, its first byte popped (a byte
                    # move on a7 steps by 2): 16 cycles instead of 26 for move.w / lsr.w #8.  The ea must be
                    # used exactly once.
                    return ["move.w %s,-(a7)" % reg], "(a7)+"
                return [], reg
            if n in ("iyh", "iyl"):      # IY lives in the block, big-endian word
                if self.iyr:
                    return (["move.w %s,-(a7)" % self.iyr], "(a7)+") if n == "iyh" else (["move.w %s,d7" % self.iyr], "d7")
                return [], self.mem(self.cfg.iyaddr, 0 if n == "iyh" else 1)
            raise Unsupported("8-bit register %s" % n)
        if k == "imm":
            return [], "#%s" % hx(op[1], 2)
        if k == "ind":
            b, d = op[1], op[2]
            if b == "hl":
                return [], self.ind("d3")
            if b == "de":
                return [], self.ind("d2")
            if b == "bc":
                return self.clean("d7") + ["move.w d1,d7", "ror.w #8,d7"], self.ind("d7")
            if b == "ix":
                return [], self.ind("d4", d)
            if b == "iy":
                if self.iyr:
                    return [], ("%d(a6,%s.w)" % (d, self.iyr)) if d else "(a6,%s.w)" % self.iyr
                return self.clean("d5") + ["move.w %s,d5" % self.mem(self.cfg.iyaddr)], self.ind("d5", d)
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
            if n in ("iyh", "iyl"):
                if self.iyr:
                    if n == "iyl":
                        return ["move.w %s,d5" % self.iyr, "move.b %s,d5" % src_ea, "movea.w d5,%s" % self.iyr]
                    return ["move.w %s,d5" % self.iyr, "ror.w #8,d5", "move.b %s,d5" % src_ea, "ror.w #8,d5",
                            "movea.w d5,%s" % self.iyr]
                return ["move.b %s,%s" % (src_ea, self.mem(self.cfg.iyaddr, 0 if n == "iyh" else 1))]
            reg, hi = self.half(n)
            if not hi:
                return ["move.b %s,%s" % (src_ea, reg)]
            if src_ea.startswith("#"):
                v = int(src_ea[1:].replace("$", "0x"), 16) & 0xFF
                return ["andi.w #$00FF,%s" % reg] + (["ori.w #%s,%s" % (hx(v << 8), reg)] if v else [])
            if src_ea == "(a7)+":
                out.append("move.b (a7)+,d7")
                src_ea = "d7"
            # through the 68000 stack: 24 cycles from a register instead of 38 (lsl.w #8 / andi / or)
            out += ["move.w %s,-(a7)" % reg, "move.b %s,(a7)" % src_ea, "move.w (a7)+,%s" % reg]
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
        self.core_at = len(self.lines)
        self.core_provided = provided
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
                r = core_reg(self.lines[self.core_at - 1]) if self.core_at else None
                if r and need & (S | Z) and not passthru & (H | N | PV):
                    self.e("tst.b %s" % r)      # (the merge spoilt the CCR: N Z of the result again = S Z)
        for f in (H, N):
            if const_set & f and lo & f:
                self.e("ori.b #%s,d6" % hx(1 << D6BIT[f], 2))
            if const_clear & f and lo & f:
                self.e("andi.b #%s,d6" % hx(0xFF ^ (1 << D6BIT[f]), 2))
        if hcomp is not None and lo & H:
            hcomp()

    def ctoc(self, setz=False):
        """Load the CCR with X = C = the Z80 carry from d6 (and Z set, for addx / subx).  The shift of
        (d6 & 1) by one: the bit goes into X and C, the result is 0 (Z set): 16 cycles, no branch."""
        self.e("moveq #1,d7")
        self.e("and.b d6,d7")
        self.e("lsr.b #1,d7")

    def load_cc(self, cc):
        if self.cur.pc in self.ccr_users:
            return                      # the CCR still holds the flag
        self.e("move d6,ccr")

    # ---- instruction dispatch --------------------------------------------
    # ---- banked windows ---------------------------------------------------------------------------
    def window_wrap(self, n0, base="g_winbase"):
        """The lines of the instruction emitted from n0 on that use the window register `aW` (the ports with a
        banked window: Bubble Bobble, 1942, Black Tiger, 1943) get a0 for it, loaded with `base` (the current bank's
        copy + $8000) at the start of the instruction, right after its label (and hook) lines: the instruction's
        own uses of the 68000 stack (the high bytes, ldir) then nest inside.  a0 is saved around it only when the
        register map keeps a Z80 register there (BC' without z80x.FAST)."""
        new = self.lines[n0:]
        if not any("aW" in l for l in new):
            return
        start = 0
        while start < len(new) and _re.match(r"^[A-Za-z]+[0-9A-F]{4,5}(_r)?:", new[start]):
            start += 1
            if start < len(new) and new[start].strip().startswith("pea ") and new[start].strip().endswith("_r"):
                while start < len(new) and not new[start].endswith("_r:"):
                    start += 1          # (a hook: pea / move.w / jmp z80_hook, then its resume label)
        body = [l.replace("aW", "a0") for l in new[start:]]
        save = "a0" not in self.free_aregs()
        # the base is needed for static window addresses (n(aW)); a window check (lea (a6),aW ...) sets aW itself
        uses = [l.strip() for l in new[start:] if "aW" in l]
        checked = uses[0].startswith("lea (a6),aW") and not any(_re.search(r"-?\d+\(aW\)", u) for u in uses)
        self.lines[n0:] = new[:start] + (["\tpea (a0)"] if save else []) + ([] if checked else ["\tmove.l %s,a0" % base]) + \
            body + (["\tmove.l (sp)+,a0"] if save else [])

    # ---- the second pass: instructions merged over labels nothing enters ------------------------------
    #
    # Code may be merged across a Z80 instruction's label only when the program cannot arrive there other than by
    # the straight flow: not a join (entries, return points, jump table targets, code addresses held as numbers),
    # not the target of a jump or call, not a hook.  The labels inside such a merge lose their dispatch table
    # entry (no_entry: the table generators put z80_badpc there), so a jump the analysis did not see stops loudly.

    def boundaries(self):
        b = set(self.joins) | set(self.hooks)
        for pc, ins in self.code.items():
            if ins.flow in ("jmp", "jcc", "call", "ccall", "rst") and ins.target is not None:
                b.add(ins.target)
        return b

    def pair_af(self, bnd):
        """push af ... pop af in straight code that nothing between them enters, with the slot read by nothing
        else: the pair keeps the flags in the d6 format (2 moves each instead of the conversions, 112 cycles
        saved; H N P/V come back exact instead of 0, so the pop's must not be live: they are not, then)."""
        out = set()
        for pc, ins in self.code.items():
            if ins.mn != "push" or ins.ops[0] != ("r16", "af") or pc in self.hooks:
                continue
            depth, q, inner = 0, pc + ins.length, []
            while len(inner) < 64:
                i2 = self.code.get(q)
                if i2 is None or q in bnd or i2.flow != "seq" or "sp" in i2.text:
                    break
                if i2.mn == "push":
                    depth += 1
                elif i2.mn == "pop":
                    if depth == 0:
                        if i2.ops[0] == ("r16", "af") and not self.live_out[q] & (H | N | PV):
                            out |= {pc, q}
                            self.no_entry |= set(inner) | {q}
                        break
                    depth -= 1
                inner.append(q)
                q += i2.length
        return out

    def emit_copy(self, pc, push, pop):
        """push rr / pop rr': rr' = rr (the stack word below SP is dead)"""
        s, d = push.ops[0][1], pop.ops[0][1]
        self.cur = push
        self.lines.append("%s%04X:\t\t; %s / %s (merged)" % (self.cfg.prefix, pc, push.text, pop.text))
        if s == d:
            return
        src = self.nat16(s, 7)
        if d in SWAPPED:
            self.e("move.w %s,%s" % (src, REG16[d]))
            self.e("ror.w #8,%s" % REG16[d])
        elif d in REG16:
            self.e("move.w %s,%s" % (src, REG16[d]))
        elif d == "iy" and self.iyr:
            self.e("movea.w %s,%s" % (src, self.iyr))
        elif d == "iy":
            self.e("move.w %s,%s" % (src, self.mem(self.cfg.iyaddr)))
        else:
            raise Unsupported("pop %s" % d)

    def emit_all(self, order=None):
        pcs = sorted(self.code) if order is None else order
        bnd = self.boundaries()
        self.raw_af = self.pair_af(bnd)
        i = 0
        while i < len(pcs):
            pc = pcs[i]
            ins = self.code[pc]
            nxt = pc + ins.length
            n2 = self.code.get(nxt)
            step = 1
            if (ins.mn == "push" and n2 is not None and n2.mn == "pop" and nxt not in bnd and pc not in self.hooks
                    and i + 1 < len(pcs) and pcs[i + 1] == nxt and "af" not in (ins.ops[0][1], n2.ops[0][1])
                    and "sp" not in (ins.ops[0][1], n2.ops[0][1])):
                self.emit_copy(pc, ins, n2)
                self.no_entry.add(nxt)
                self.merged.add(nxt)
                ins, pc, step = n2, nxt, 2
            else:
                self.emit_ins(pc)
            if ins.flow in ("seq", "jcc", "ccall", "cret"):
                nxt = pc + ins.length
                follow = pcs[i + step] if i + step < len(pcs) else None
                if follow != nxt and not (self.lines and self.lines[-1].strip().startswith("jmp z80_unsupported")):
                    self.jmp_to(nxt)
            i += step
        # the labels of merged instructions: a stub each, for table generators that list every pc (an entry there
        # was not foreseen by the analysis: it stops loudly)
        if self.merged:
            self.lines.append("; --- merged into the instruction before: not entered")
            for pc in sorted(self.merged):
                self.lines.append("%s%04X:\tmove.w #%s,d7\n\tjmp z80_badpc" % (self.cfg.prefix, pc, hx(pc)))
        # a jump to the label right behind it; a tst.b R right before a move.b R (which sets N Z the same)
        out = []
        for k, line in enumerate(self.lines):
            s = line.strip()
            if s.startswith("bra ") and k + 1 < len(self.lines) and self.lines[k + 1].startswith(s[4:] + ":"):
                continue
            if s.startswith("tst.b d"):
                nxt = next((l.strip() for l in self.lines[k + 1:] if l.strip() and not l.strip().endswith(":")
                            and not l.strip().startswith(";") and ":" not in l.split(";")[0]), "")
                if nxt.startswith("move.b %s," % s[6:]):
                    continue
            out.append(line)
        self.lines = out

    def emit_ins(self, pc, live_out_override=None, with_label=True):
        ins = self.code[pc]
        self.cur = ins
        self.lo = self.live_out[pc] if live_out_override is None else live_out_override
        if with_label:
            self.lines.append("%s%04X:\t\t; %s" % (self.cfg.prefix, pc, ins.text))
            if pc in self.hooks:
                # the runtime's hook (d7 = pc) resumes at the label on the stack
                self.e("pea %s%04X_r" % (self.cfg.prefix, pc))
                self.e("move.w #%s,d7" % hx(pc))
                self.e("jmp z80_hook")
                self.lines.append("%s%04X_r:" % (self.cfg.prefix, pc))
        start = len(self.lines)
        self.core_at = None
        self.core_provided = 0
        try:
            fn = getattr(self, "x_" + ins.mn.replace(" ", "_").replace(",", "_").replace("'", "p"), None)
            if fn is None:
                raise Unsupported("mnemonic %s" % ins.mn)
            fn(ins)
            if self.lo & PV and ins.mn not in PV_PRODUCERS and ins.mn not in PV_PASS and uses_defs(ins)[1] & PV:
                raise Unsupported("P/V after %s" % ins.mn)
        except Unsupported as ex:
            del self.lines[start:]
            self.unsupported.append((pc, ins.text, str(ex)))
            self.e("move.w #%s,d7" % hx(pc))
            self.e("jmp z80_unsupported")
            if self.transfer is not None:
                self.transfer[pc] = (None, False, None, 0, ALLF)
            return
        if self.transfer is not None:
            self.record_transfer(pc, start)
        if pc in self.after_label:
            self.lines.append(self.after_label[pc] + ":")

    # ---- simple instructions ------------------------------------------------
    def x_nop(self, ins):
        pass

    def x_di(self, ins):
        if self.cfg.iff_sym:
            self.e("clr.b %s" % self.cfg.iff_sym)

    def x_ei(self, ins):
        if self.cfg.iff_sym:
            self.e("st %s" % self.cfg.iff_sym)

    def x_im(self, ins):
        pass

    def x_halt(self, ins):
        self.e("jsr z80_halt")           # the runtime: wait for the next interrupt

    def x_ld_a_r(self, ins):
        self.e("jsr z80_rnd")            # the runtime: a pseudo random byte in d0 (the refresh register)
        self.e("tst.b d0")
        self.flags(S | Z, const_clear=H | N)

    def x_rld(self, ins):
        pre, ea = self.read8(("ind", "hl", 0), io_read=False)
        for l in pre:
            self.e(l)
        self.e("moveq #0,d7")
        self.e("move.b %s,d7" % ea)
        self.e("lsl.w #4,d7")            # (hl) << 4: the old high nibble in bits 8-11
        self.e("move.b d0,d5")
        self.e("and.b #$0F,d5")
        self.e("or.b d5,d7")
        self.e("move.b d7,%s" % ea)      # new (hl) = old << 4 | A & 15
        self.e("lsr.w #8,d7")
        self.e("and.b #$F0,d0")
        self.e("or.b d7,d0")             # new A = A & $F0 | old (hl) >> 4
        self.flags(S | Z, const_clear=H | N)

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
                if v < 128 and not self.alt_af_upper:
                    self.e("moveq #%d,d0" % v)
                else:
                    self.e("move.b #%s,d0" % hx(v, 2))
                return
            pre, sea = self.read8(src)
            for l in pre:
                self.e(l)
            for l in self.write8(dst, sea):
                self.e(l)
            if kd == "ind16" and src == ("r8", "a"):
                for lo, hi, label, bit in self.cfg.write_hooks:
                    if lo <= dst[1] <= hi:
                        # the runtime acts on the write (e.g. the DK sprite DMA start bit)
                        if bit is None:
                            self.e("bsr %s" % label)
                        else:
                            skip = self.new_label()
                            self.e("btst #%d,d0" % bit)
                            self.e("beq %s" % skip)
                            self.e("bsr %s" % label)
                            self.lines.append(skip + ":")
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
            self.e("lea %s,a5" % self.ind(self.nat16(src[1], 7)))
            return
        raise Unsupported("ld %r,%r" % (dst, src))

    def reg16(self, name, scratch):
        """data register holding a 16-bit register (loading IY into d<scratch> if needed);
        a swapped pair comes as it is kept."""
        if name in REG16:
            return REG16[name]
        if name == "iy":
            if self.iyr:
                return self.iyr
            for l in self.clean("d%d" % scratch):
                self.e(l)
            self.e("move.w %s,d%d" % (self.mem(self.cfg.iyaddr), scratch))
            return "d%d" % scratch
        raise Unsupported("reg16 %s" % name)

    def nat16(self, name, scratch):
        """data register holding the natural value of a 16-bit register (a swapped pair is
        rotated into d<scratch>)."""
        if name in SWAPPED:
            for l in self.clean("d%d" % scratch):
                self.e(l)
            self.e("move.w %s,d%d" % (REG16[name], scratch))
            self.e("ror.w #8,d%d" % scratch)
            return "d%d" % scratch
        return self.reg16(name, scratch)

    def set16(self, name, v):
        v &= 0xFFFF
        if name in SWAPPED:
            v = swap16(v)
        if name in REG16:
            r = REG16[name]
            if v < 128 and not (self.alt_upper and r in ("d1", "d2", "d3")):
                self.e("moveq #%d,%s" % (v, r))
            else:
                self.e("move.w #%s,%s" % (hx(v), r))
        elif name == "sp":
            self.e("lea %s,a5" % self.mem(v))
        elif name == "iy":
            if self.iyr:
                self.e("movea.w #%s,%s" % (hx(v), self.iyr))
            else:
                self.e("move.w #%s,%s" % (hx(v), self.mem(self.cfg.iyaddr)))
        else:
            raise Unsupported("ld %s,imm" % name)

    def load16(self, name, addr):
        lo = self.mem(addr)
        hi = self.mem(addr, 1)
        if name in REG16:
            r = REG16[name]
            if addr % 2 == 0:
                # the little-endian pair read as a 68k word is the swapped value
                self.e("move.w %s,%s" % (lo, r))
                if name not in SWAPPED:
                    self.e("ror.w #8,%s" % r)
            elif name in SWAPPED:
                self.e("move.b %s,%s" % (lo, r))
                self.e("lsl.w #8,%s" % r)
                self.e("move.b %s,%s" % (hi, r))
            else:
                self.e("move.b %s,%s" % (hi, r))
                self.e("lsl.w #8,%s" % r)
                self.e("move.b %s,%s" % (lo, r))
        elif name == "sp":
            for l in self.clean("d7"):
                self.e(l)
            self.e("move.b %s,d7" % hi)
            self.e("lsl.w #8,d7")
            self.e("move.b %s,d7" % lo)
            self.e("lea %s,a5" % self.ind("d7"))
        elif name == "iy":
            self.e("move.b %s,d7" % hi)
            self.e("lsl.w #8,d7")
            self.e("move.b %s,d7" % lo)
            if self.iyr:
                self.e("movea.w d7,%s" % self.iyr)
            else:
                self.e("move.w d7,%s" % self.mem(self.cfg.iyaddr))
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
            if r.startswith("a"):                 # (IY in an address register: no byte moves from it)
                self.e("move.w %s,d7" % r)
                r = "d7"
        if addr % 2 == 0:
            if name in SWAPPED:
                self.e("move.w %s,%s" % (r, lo))
            else:
                if r != "d7":
                    self.e("move.w %s,d7" % r)
                self.e("ror.w #8,d7")
                self.e("move.w d7,%s" % lo)
            return
        if name in SWAPPED:
            lo, hi = hi, lo
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
            if n in SWAPPED:
                # the low half is the high byte; a carry out of the word means it wrapped
                r = REG16[n]
                l = self.new_label()
                self.e("%s.w #$0100,%s" % ("add" if isinc else "sub", r))
                self.e("bcc.s %s" % l)
                self.e("%s.b #1,%s" % (op, r))
                self.lines.append(l + ":")
            elif n in REG16:
                self.e("%s.w #1,%s" % (op, REG16[n]))
            elif n == "sp":
                nxt = self.code.get(ins.pc + ins.length)
                if ins.pc in self.after_label:
                    self.e("%s.l #1,a5" % op)       # the second of a pair, reached by a jump
                elif isinc and nxt is not None and nxt.mn == "inc" and nxt.ops[0] == ("r16", "sp"):
                    # inc sp twice (dropping a return address): the stack is word aligned
                    # before and after, not in between, and the NMI pushes a word, so it must
                    # not interrupt there: both at once, stepping over the second one.
                    l = self.new_label()
                    self.after_label[nxt.pc] = l
                    self.e("addq.l #2,a5")
                    self.e("bra.s %s" % l)
                else:
                    self.e("%s.l #1,a5" % op)
            elif n == "iy":
                self.e("%s.w #1,%s" % (op, self.iyr or self.mem(self.cfg.iyaddr)))
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
                reg, hi = self.half(n)
                if hi:
                    if not self.lo & (S | Z | H | N):
                        self.e("%s.w #$0100,%s" % ("add" if isinc else "sub", reg))     # (no flags wanted)
                        return
                    self.e("move.w %s,-(a7)" % reg)       # on the 68000 stack: the byte is its first
                    post = ["move.w (a7)+,%s" % reg]
                    ea = "(a7)"
                else:
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

    def pv_parity(self):
        """d6 bit 7 = P/V after a logic op: set when the parity of A is even (needs live or forced; clobbers d5 d7)."""
        if not (self.lo & PV or self.cur.pc in self.cfg.pv_force):
            return
        l = self.new_label()
        self.e("move.b d0,d7")
        self.e("move.b d7,d5")
        self.e("lsr.b #4,d5")
        self.e("eor.b d5,d7")
        self.e("move.b d7,d5")
        self.e("lsr.b #2,d5")
        self.e("eor.b d5,d7")
        self.e("move.b d7,d5")
        self.e("lsr.b #1,d5")
        self.e("eor.b d5,d7")               # bit 0: odd parity
        self.e("bclr #%d,d6" % PV_BIT)
        self.e("btst #0,d7")
        self.e("bne.s %s" % l)
        self.e("bset #%d,d6" % PV_BIT)
        self.lines.append(l + ":")

    def x_and(self, ins):
        pre, ea = self._alu_src(ins)
        for l in pre:
            self.e(l)
        self.e("and.b %s,d0" % ea)
        self.flags(S | Z | C, const_set=H, const_clear=N)
        self.pv_parity()

    def x_or(self, ins):
        pre, ea = self._alu_src(ins)
        for l in pre:
            self.e(l)
        self.e("or.b %s,d0" % ea)
        self.flags(S | Z | C, const_clear=H | N)
        self.pv_parity()

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
        self.pv_parity()

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
                sreg = self.nat16(sn, 5)
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
            self.e("move.w %s,d5" % (self.iyr or self.mem(self.cfg.iyaddr)))
            sreg = "d5"
        else:
            sreg = self.nat16(sn, 7 if dn == "iy" else 5)
        if dn in SWAPPED:
            raise Unsupported("add %s,rr" % dn)
        if dn == "iy":
            if sreg == "d5":
                raise Unsupported("add iy,sp/iy")
            if self.iyr and not self.lo & (C | N):
                self.e("adda.w %s,%s" % (sreg, self.iyr))     # (the low word is the sum; no flags wanted)
                return
            self.e("move.w %s,d5" % (self.iyr or self.mem(self.cfg.iyaddr)))
            self.e("add.w %s,d5" % sreg)
            self.flags(C, const_clear=N)
            if self.iyr:
                self.e("movea.w d5,%s" % self.iyr)
            else:
                self.e("move.w d5,%s" % self.mem(self.cfg.iyaddr))
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
                reg, hi = self.half(n)
                if hi:
                    self.e("move.w %s,-(a7)" % reg)       # the byte from the 68000 stack into d5 and back
                    self.e("move.b (a7),d5")
                    store = "move.b d5,(a7)"
                    post = ["move.w (a7)+,%s" % reg]
                    ea = "d5"
                else:
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
            reg, hi = self.half(n)
            return reg, (bit + 8 if hi else bit), []
        pre, ea = self.read8(tgt, io_read=False)
        return ea, bit, pre

    def x_bit(self, ins):
        bit = ins.ops[0][1]
        ea, b, pre = self._bitea(ins.ops[1], bit)
        for l in pre:
            self.e(l)
        self.e("btst #%d,%s" % (b, ea))
        exact_s = self.cfg.bit_s and self.lo & S
        if exact_s and bit == 7:
            self.e("sne d5")                  # (the CCR stays) S = the tested bit
        self.flags(Z, const_set=H, const_clear=N)
        if exact_s:                           # the real CPU sets S from bit 7 of the result: 0 for any lower bit
            if bit == 7:
                self.e("andi.b #8,d5")
                self.e("andi.b #$F7,d6")
                self.e("or.b d5,d6")
            else:
                self.e("andi.b #$F7,d6")

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
        if n == "af" and ins.pc in self.raw_af:
            self.e("move.b d0,-(a5)")
            self.e("move.b d6,-(a5)")           # (the d6 format: pair_af)
            return
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
        # the Z80 stack is always word aligned here (ld sp,nn even, 16-bit pushes and pops);
        # a word on it, read big-endian, is the swapped value
        if n in SWAPPED:
            self.e("move.w %s,-(a5)" % REG16[n])
            return
        r = self.reg16(n, 7)
        if r != "d7":
            self.e("move.w %s,d7" % r)
        self.e("ror.w #8,d7")
        self.e("move.w d7,-(a5)")

    def x_pop(self, ins):
        n = ins.ops[0][1]
        if n == "af" and ins.pc in self.raw_af:
            self.e("move.b (a5)+,d6")           # (the d6 format: pair_af)
            self.e("move.b (a5)+,d0")
            return
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
        self.e("move.w (a5)+,%s" % r)
        if n not in SWAPPED:
            self.e("ror.w #8,%s" % r)
        if n == "iy":
            self.e("movea.w d5,%s" % self.iyr if self.iyr else "move.w d5,%s" % self.mem(self.cfg.iyaddr))

    def x_ex(self, ins):
        a, b = ins.ops
        if a == ("r16", "de") and b == ("r16", "hl"):
            if self.alt_upper:                  # (the words only: DE' and HL' stay)
                self.e("move.w d2,d7")
                self.e("move.w d3,d2")
                self.e("move.w d7,d3")
            else:
                self.e("exg d2,d3")
            return
        if a[0] == "ind" and a[1] == "sp" and b[0] == "r16" and b[1] in ("hl", "ix"):
            r = REG16[b[1]]              # swap the register with the word on the stack
            self.e("move.w (a5),d7")
            self.e("ror.w #8,d7")
            self.e("move.w %s,d5" % r)
            self.e("ror.w #8,d5")
            self.e("move.w d5,(a5)")
            self.e("move.w d7,%s" % r)
            return
        raise Unsupported("ex")

    def x_ex_af_afp(self, ins):
        if self.alt_af_upper:
            self.e("swap d0")
            self.e("swap d6")
            return
        self.e("exg d0,a3")
        self.e("move.w d6,d7")
        self.e("move.w %s,d6" % self.mem(self.cfg.fshadow))
        self.e("move.w d7,%s" % self.mem(self.cfg.fshadow))

    def x_exx(self, ins):
        if self.alt_upper:
            self.e("swap d1")
            self.e("swap d2")
            self.e("swap d3")
            return
        self.e("exg d1,a0")
        self.e("exg d2,a1")
        self.e("exg d3,a2")

    # ---- block ops --------------------------------------------------------------------------
    def x_ldir(self, ins):
        """BC bytes (hl)+ -> (de)+, on two address registers: a fill (de = hl + 1) writes the byte by longs, a copy of
        the same parity that does not overlap forward goes by longs, anything else by bytes (8 a turn).  A copy
        across the ends of the 68000 block (the $8000 split of the "signed" mode, the $FFFF wrap) and BC = 0 go
        the indexed way, a byte a turn."""
        regs = self.free_aregs()
        save = len(regs) < 2
        s, d = ("a1", "a0") if save else (regs[0], regs[1])
        L = {k: self.new_label() for k in ("slow", "fin", "done", "fill", "bytes", "bytes1", "even", "tail",
                                           "lw", "b8", "b1", "bl", "fe", "fl", "ft", "ftl", "l2")}
        lab = lambda k: self.lines.append(L[k] + ":")
        e = self.e
        e("move.w d1,d5")
        e("ror.w #8,d5")                        # the count, BC is 0 afterwards
        e("beq %s" % L["slow"])                 # (0 = 65536)
        for r in ("d3", "d2"):                  # the last byte on the same side of the block's ends
            e("move.w d5,d7")
            e("subq.w #1,d7")
            e("add.w %s,d7" % r)
            e("%s %s" % ("bvs" if self.cfg.mode == "signed" else "bcs", L["slow"]))
        if save:
            e("movem.l a0-a1,-(sp)")
        e("lea %s,%s" % (self.ind("d3"), s))
        e("lea %s,%s" % (self.ind("d2"), d))
        e("move.w d5,-(a7)")                    # (the count, for the end)
        e("move.w d2,d7")
        e("sub.w d3,d7")                        # destination - source
        e("subq.w #1,d7")
        e("beq %s" % L["fill"])
        e("addq.w #1,d7")
        e("cmp.w d5,d7")
        e("blo.s %s" % L["bytes"])              # the destination inside the source's range: bytes, in order
        e("move.w d3,d7")
        e("eor.w d2,d7")
        e("btst #0,d7")
        e("bne.s %s" % L["bytes"])              # different parity: bytes
        e("btst #0,d3")
        e("beq.s %s" % L["even"])
        e("move.b (%s)+,(%s)+" % (s, d))        # both odd: a byte first
        e("subq.w #1,d5")
        e("beq %s" % L["done"])
        lab("even")
        e("move.w d5,d7")
        e("lsr.w #2,d7")
        e("beq.s %s" % L["tail"])
        e("subq.w #1,d7")
        lab("lw")
        e("move.l (%s)+,(%s)+" % (s, d))
        e("dbf d7,%s" % L["lw"])
        lab("tail")
        e("and.w #3,d5")
        e("beq.s %s" % L["done"])
        lab("bytes")                            # d5 >= 1 bytes
        e("move.w d5,d7")
        e("lsr.w #3,d7")
        e("beq.s %s" % L["b1"])
        e("subq.w #1,d7")
        lab("b8")
        for _ in range(8):
            e("move.b (%s)+,(%s)+" % (s, d))
        e("dbf d7,%s" % L["b8"])
        lab("b1")
        e("and.w #7,d5")
        e("beq.s %s" % L["done"])
        e("subq.w #1,d5")
        lab("bl")
        e("move.b (%s)+,(%s)+" % (s, d))
        e("dbf d5,%s" % L["bl"])
        e("bra.s %s" % L["done"])
        lab("fill")                             # (hl) into the count bytes at de, by longs
        e("move.b (%s),d7" % s)
        e("movea.w d5,%s" % s)                  # (the count; the source is not needed any more)
        e("move.b d7,d5")
        e("lsl.w #8,d5")
        e("move.b d7,d5")
        e("move.w d5,d7")
        e("swap d5")
        e("move.w d7,d5")                       # the byte in all four
        e("move.w %s,d7" % s)
        e("btst #0,d2")
        e("beq.s %s" % L["fe"])
        e("move.b d5,(%s)+" % d)
        e("subq.w #1,d7")
        e("beq.s %s" % L["done"])
        lab("fe")
        e("movea.w d7,%s" % s)
        e("lsr.w #2,d7")
        e("beq.s %s" % L["ft"])
        e("subq.w #1,d7")
        lab("fl")
        e("move.l d5,(%s)+" % d)
        e("dbf d7,%s" % L["fl"])
        lab("ft")
        e("move.w %s,d7" % s)
        e("and.w #3,d7")
        e("beq.s %s" % L["done"])
        e("subq.w #1,d7")
        lab("ftl")
        e("move.b d5,(%s)+" % d)
        e("dbf d7,%s" % L["ftl"])
        lab("done")
        e("move.w (a7)+,d5")
        if save:
            e("movem.l (sp)+,a0-a1")
        e("add.w d5,d3")
        e("add.w d5,d2")
        e("bra.s %s" % L["fin"])
        lab("slow")                             # the indexed way (any addresses)
        lab("l2")
        e("move.b %s,%s" % (self.ind("d3"), self.ind("d2")))
        e("addq.w #1,d3")
        e("addq.w #1,d2")
        e("subq.w #1,d5")
        e("bne.s %s" % L["l2"])
        lab("fin")
        e("clr.w d1")
        self.flags(0, const_clear=H | N)

    def x_ldi(self, ins):
        self.e("move.b %s,%s" % (self.ind("d3"), self.ind("d2")))
        self.e("addq.w #1,d3")
        self.e("addq.w #1,d2")
        l = self.new_label()                      # dec bc, swapped
        self.e("sub.w #$0100,d1")
        self.e("bcc.s %s" % l)
        self.e("subq.b #1,d1")
        self.lines.append(l + ":")
        self.flags(0, const_clear=H | N)

    def x_ldd(self, ins):
        self.e("move.b %s,%s" % (self.ind("d3"), self.ind("d2")))
        self.e("subq.w #1,d3")
        self.e("subq.w #1,d2")
        l = self.new_label()                      # dec bc, swapped
        self.e("sub.w #$0100,d1")
        self.e("bcc.s %s" % l)
        self.e("subq.b #1,d1")
        self.lines.append(l + ":")
        self.flags(0, const_clear=H | N)

    def x_lddr(self, ins):
        l = self.new_label()
        self.e("move.w d1,d7")
        self.e("ror.w #8,d7")              # the count, BC is 0 afterwards
        self.lines.append(l + ":")
        self.e("move.b %s,%s" % (self.ind("d3"), self.ind("d2")))
        self.e("subq.w #1,d3")
        self.e("subq.w #1,d2")
        self.e("subq.w #1,d7")
        self.e("bne.s %s" % l)
        self.e("clr.w d1")
        self.flags(0, const_clear=H | N)

    def x_cpi(self, ins):
        if self.lo & H:
            raise Unsupported("H after cpi")
        self.e("cmp.b %s,d0" % self.ind("d3"))
        self.flags(S | Z, const_set=N)
        self.e("addq.w #1,d3")
        l = self.new_label()                      # dec bc, swapped (P/V = BC != 0, see branch)
        self.e("sub.w #$0100,d1")
        self.e("bcc.s %s" % l)
        self.e("subq.b #1,d1")
        self.lines.append(l + ":")

    def x_cpir(self, ins):
        loop = self.new_label()
        end = self.new_label()
        self.e("move.w d1,d5")
        self.e("ror.w #8,d5")              # the count
        self.lines.append(loop + ":")
        self.e("cmp.b %s,d0" % self.ind("d3"))
        self.e("move sr,d7")
        self.e("addq.w #1,d3")
        self.e("subq.w #1,d5")
        self.e("beq.s %s" % end)
        self.e("btst #2,d7")
        self.e("beq.s %s" % loop)
        self.lines.append(end + ":")
        self.e("ror.w #8,d5")
        self.e("move.w d5,d1")
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
        self.e("bra %s" % self.label_of(pc))       # (vasm: bra.s / bra.w, or a jmp when it is out of range)

    # The return address goes on the Z80 stack as a word, which read back is the byte
    # swapped pc; a4 is the dispatch table in that order (z80_init_dispatch), 65536 entries.

    def push_ret(self, pc):
        self.e("move.w #%s,-(a5)" % hx(swap16(self.ret_value(pc))))

    def dispatch_ret(self, pc=None):
        """ret: the word on the stack is compared with the return points of the function the ret is in (up to
        MAX_RET_CANDS, see ret_candidates) and a match jumps there directly (30 cycles instead of 50); anything else
        (a token, a return address the program made itself) goes through the table."""
        self.e("moveq #0,d7")
        self.e("move.w (a5)+,d7")
        for rp in self.ret_cands().get(pc, ()):
            self.e("cmp.w #%s,d7" % hx(swap16(self.ret_value(rp))))
            self.e("beq %s" % self.label_of(rp))
        self.dispatch_d7()

    MAX_RET_CANDS = 3

    def ret_value(self, pc):
        """the Z80 pc a call to return to pc pushes (the banked ports: the real address)"""
        return pc

    def direct_ok(self, rp):
        """whether a ret may jump to the return point rp directly (not a banked address)"""
        return rp in self.code

    def ret_cands(self):
        """ret pc -> the return points it is likely to go to: the instructions after the calls of every function
        (call target) whose code, followed without entering calls, reaches the ret.  Only a guess (the ret checks the
        stack word): functions are not marked in the Z80 code, and a program may return elsewhere."""
        if getattr(self, "_ret_cands", None) is not None:
            return self._ret_cands
        code = self.code
        rps = {}
        for pc, ins in code.items():
            if ins.flow in ("call", "ccall") and ins.target in code:
                rps.setdefault(ins.target, set()).add(pc + ins.length)
        cands = {}
        for tgt, points in rps.items():
            seen, todo = set(), [tgt]
            while todo and len(seen) < 4000:
                pc = todo.pop()
                if pc in seen or pc not in code:
                    continue
                seen.add(pc)
                ins = code[pc]
                fl, nxt = ins.flow, pc + ins.length
                if ins.mn == "ret":
                    cands.setdefault(pc, set()).update(points)
                if fl in ("seq", "call", "ccall", "rst", "cret"):
                    if not (fl == "rst" and ins.target == 0x28 and self.cfg.rst28_tables):
                        todo.append(nxt)
                if fl in ("jmp", "jcc") and ins.target is not None:
                    todo.append(ins.target)
                if fl == "jcc":
                    todo.append(nxt)
        self._ret_cands = {}
        for pc, pts in cands.items():
            pts = sorted(p for p in pts if self.direct_ok(p))
            if 0 < len(pts) <= self.MAX_RET_CANDS:
                self._ret_cands[pc] = pts
        return self._ret_cands

    def dispatch_d7(self):
        """jump to the code of the swapped Z80 pc in d7 (upper word clear)."""
        self.e("lsl.l #2,d7")
        if self.a3_free:
            self.e("move.l 0(a4,d7.l),a3")
            self.e("jmp (a3)")
        else:
            self.e("move.l 0(a4,d7.l),-(a7)")
            self.e("rts")

    def x_jp(self, ins):
        ops = ins.ops
        if ops[0][0] == "ind":              # jp (hl)/(ix)/(iy)
            r = ops[0][1]
            self.e("moveq #0,d7")
            self.e("move.w %s,d7" % self.reg16(r, 5))
            if r not in SWAPPED:
                self.e("ror.w #8,d7")
            self.dispatch_d7()
            return
        if ops[0][0] == "addr":
            self.jmp_to(ops[0][1])
            return
        cc, tgt = ops[0][1], ops[1][1]
        self.branch(cc, self.label_of(tgt))

    def x_jr(self, ins):
        ops = ins.ops
        if ops[0][0] == "addr":
            self.jmp_to(ops[0][1])
            return
        cc, tgt = ops[0][1], ops[1][1]
        self.branch(cc, self.label_of(tgt))

    def branch(self, cc, label, inv=False):
        """branch to label if the Z80 condition cc holds (or does not, inv).  P/V is not
        tracked; `jp pe/po` right after ldi/ldd (P/V = BC != 0) is the one form supported."""
        if cc in ("pe", "po"):
            prev = self.ends.get(self.cur.pc)
            taken = (cc == "pe") != inv
            if prev is not None and self.code[prev].mn in ("ldi", "ldd", "cpi", "cpd"):
                self.e("tst.w d1")
                self.e("b%s %s" % ("ne" if taken else "eq", label))
                return
            self.e("btst #%d,d6" % PV_BIT)           # parity of a logic op, see pv_parity
            self.e("b%s %s" % ("ne" if taken else "eq", label))
            return
        self.load_cc(cc)
        self.e("b%s %s" % ((CC_68K_INV if inv else CC_68K)[cc], label))

    def x_djnz(self, ins):
        tgt = ins.ops[0][1]
        self.e("subq.b #1,d1")
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
        self.branch(cc, skip, inv=True)
        self.push_ret(nxt)
        self.jmp_to(tgt)
        self.lines.append(skip + ":")

    def x_ret(self, ins):
        ops = ins.ops
        if ops:
            cc = ops[0][1]
            skip = self.new_label()
            self.branch(cc, skip, inv=True)
            self.dispatch_ret(ins.pc)
            self.lines.append(skip + ":")
            return
        self.dispatch_ret(ins.pc)

    def x_retn(self, ins):
        self.dispatch_ret()

    x_reti = x_retn

    def x_rst(self, ins):
        self.push_ret(ins.pc + ins.length)
        self.jmp_to(ins.ops[0][1])
