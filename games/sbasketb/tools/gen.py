"""Super Basketball: the main CPU's program (KONAMI-1, 40 KB at $6000) translated to 68000 code (engine/m6809x.py).

    from gen import generate; report = generate()   -> build/sbasketb/code_main.s, tables_main.s, main_info.s

The boot skips the self-test: the program starts at $6000 (see machine.SBasketPort).  The program is flat: virtual page = slot = address >> 13.  The opcode bytes are decrypted (m6809.konami1_opcode: the
first byte and the byte after $10 / $11), the operands are plain.  The 68000 side (src/sbasketb.s): the 6809's 64 KB
are one block, sb_mem (the RAM, the NVRAM, the video RAM and the ROM at their addresses), so every slot's VB is
sb_mem: a3 (slot 1: the direct page $20xx, the RAM and the stack at $2000-$2FFF) and a4 (slot 0) hold the same base,
and an indexed access uses a4 whatever slot it touched.  The I/O ($3C00-$3FFF: the coverage's io sites, and the unmapped
space) goes through main_io_r / main_io_w.  The idle point $60F9 (the foreground's loop head) is a native (sb_idle): it delivers the IRQ (machine.SBasketPort).
"""
import collections
import os
import pickle
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
import m6809x
from m6809 import konami1_opcode
from m6809dis import decode
from machine import SBasketPort, ROM_FILES, load
from paths import build_dir, require_coverage

RESET, IRQ = 0x6000, SBasketPort.IRQ
DP = 0x20
SEEDS = [int(x) for x in os.environ.get("SB_SEEDS", "").split(",") if x] or range(1, 22)
# the tables behind the computed jumps (JMP / JSR [A,X], [A,U], [B,X] with the table's base loaded just before, 22 sites):
# each entry is a root, so a handler that no coverage run reached (an object type the game meets later) is translated too
TABLES = [0xD6A3, 0xFE98, 0xDBCE, 0xDBF0, 0xDCA4, 0xDCB0, 0xDCCA, 0xDCDE, 0xF405, 0xF5C4, 0xF6BE, 0xFA7F, 0xFAEC, 0xFC43,
          0xFCA7, 0xFD7D, 0xFE94, 0xFEC1, 0xFF9C, 0xFFA2, 0xFFAE, 0xFF01]


def plausible(rd, ops, v, limit=24):
    """ordinary instructions (no undocumented opcode) from v up to a jump or return, at most `limit` of them"""
    pc = v
    for _ in range(limit):
        try:
            i = decode(rd, pc, DP, rd_op=ops)
        except Exception:
            return False
        if i.mn.upper().startswith("X") or i.mn.upper() in ("NOP2",) or i.flow == "halt":
            return False
        if i.flow in ("ret", "jmp", "ijmp", "rti"):
            return True
        pc += i.length
    return True


def clean(rd, ops, v, exec_, limit=600):
    """everything reachable from v (fall-through, branches, calls) before a known instruction decodes as ordinary code"""
    seen, work = set(), [v]
    while work and len(seen) < limit:
        pc = work.pop()
        while pc not in seen and pc not in exec_:
            seen.add(pc)
            if not 0x6000 <= pc < 0xFFE0:
                return False
            try:
                i = decode(rd, pc, DP, rd_op=ops)
            except Exception:
                return False
            if i.mn.upper().startswith("X") or i.mn.upper() in ("NOP2",) or i.flow in ("halt", "swi", "wait"):
                return False
            if i.target is not None and i.flow in ("jmp", "jcc", "call"):
                work.append(i.target)
            if i.flow in ("ret", "jmp", "ijmp", "rti"):
                break
            pc += i.length
    return True


def table_roots(mem):
    """the entries of TABLES: words from the base while they are plausible code addresses and before the next table"""
    rd = lambda a: mem[a & 0xFFFF]
    ops = konami1_opcode(rd)
    bases = sorted(TABLES)
    roots = set()
    for k, b in enumerate(bases):
        end = bases[k + 1] if k + 1 < len(bases) else 0xFFE0
        a = b
        while a + 1 < end:
            v = rd(a) << 8 | rd(a + 1)
            if not 0x6000 <= v < 0xFFE0:
                break
            if not plausible(rd, ops, v):
                break
            roots.add(v)
            a += 2
    return roots


NATIVES = {SBasketPort.IDLE: "sb_idle", 0x8DD8: "nat_div_8DD8", 0x64F7: "nat_list_64F7"}   # (src/natives.s)


def image():
    """the 64 KB the 6809 sees at power-on: zero but the ROM at $6000-$FFFF"""
    mem = bytearray(0x10000)
    for n, a in ROM_FILES:
        d = load(n)
        mem[a:a + len(d)] = d
    return bytes(mem)


def page_addr(p):
    return "sb_mem+$%04X" % (p << 13)


CODE_END = 0xD6A3                               # (the first table: the code is below)


def data_roots(mem, exec_):
    """code addresses that no coverage run reached, found in the ROM: words of the data ($D6A3 on) and 16-bit immediates
    of executed loads (LDD / LDX / LDY / LDU #) that point into the code, to the start of a basic block (right after an
    executed return, jump or branch-always) and that decode as ordinary code (`plausible`).  The object scripts and the
    state machines (JMP ,U) name their handlers this way; a handler no seed met is translated all the same."""
    rd = lambda a: mem[a & 0xFFFF]
    ops = konami1_opcode(rd)
    ends, pool, imm = set(), set(), set()
    for pc in exec_:
        i = decode(rd, pc, DP, rd_op=ops)
        if i.flow in ("ret", "jmp", "ijmp", "rti") or i.mn.upper() in ("BRA", "LBRA"):
            ends.add(pc + i.length)
        t = i.text.upper().replace(" ", "")
        if t[:3] in ("LDD", "LDX", "LDY", "LDU") and t[3:5] == "#$" and len(t) == 9:
            imm.add(int(t[5:], 16))
    for a in range(CODE_END, 0xFFDF):
        pool.add(rd(a) << 8 | rd(a + 1))
    ok = lambda v: 0x6000 <= v < CODE_END and v not in exec_ and plausible(rd, ops, v) and clean(rd, ops, v, exec_)
    return {v for v in pool if v in ends and ok(v)} | {v for v in imm if ok(v)}      # (an immediate may name a state inside a routine)


def load_cover():
    require_coverage("sbasketb", ["cover%d.pkl" % s for s in SEEDS])
    exec_ = collections.Counter()
    acc = collections.defaultdict(set)
    tg = collections.defaultdict(set)
    wraps, io = set(), set()
    returns = collections.Counter()
    dps = collections.defaultdict(set)
    for s in SEEDS:
        d = pickle.loads((build_dir("sbasketb") / ("cover%d.pkl" % s)).read_bytes())
        exec_.update(d["exec"])
        for v, x in d["acc"].items():
            acc[v] |= x
        for v, x in d["targets"].items():
            tg[v] |= x
        wraps |= d["wraps"]
        io |= {pc for pc, a, rw in d["io"]}
        returns.update(d.get("returns", {}))
        for v, x in d["dp"].items():
            dps[v] |= x
    return exec_, acc, tg, wraps, io, returns, dps


def program(cover):
    exec_, acc, tg, wraps, io, returns, dps = cover
    mem = image()
    rd = lambda a: mem[a & 0xFFFF]
    dp_sites = {}
    for v, x in dps.items():                     # (TFR A,DP: the code runs with $20, the player routines with $24)
        if len(x) > 1:
            # a routine called with either: fine when the instruction addresses nothing through DP (99FA-9A0F)
            if decode(rd, v, DP, rd_op=konami1_opcode(rd)).mode == "dir":
                raise RuntimeError("the instruction at %04X runs with DP %s" % (v, sorted(x)))
            x = {DP}
        if x != {DP}:
            dp_sites[v] = next(iter(x))
    # one base for every slot: an indexed access uses a4 (slot 0) whatever slot the coverage saw
    flat = {v: {(rw, 0, 0, odd) for rw, sl, pg, odd in s} for v, s in acc.items()}
    prog = m6809x.Program("main", "M", lambda p: mem[p << 13:(p + 1) << 13], {p: p for p in range(3, 8)},
                          roots=[RESET, IRQ] + sorted(NATIVES) + sorted(table_roots(mem)) + sorted(data_roots(mem, exec_)), exec_cover=set(exec_), acc_cover=flat, targets=tg,
                          page_addr=page_addr, io_sites=io, wrap_sites=wraps, dp=0x20, a3_slot=1, a4_slot=0, dp_sites=dp_sites,
                          natives={v: l for v, l in NATIVES.items()
                                   if '%04X' % v not in os.environ.get('SB_NO_NATIVES', '')},
                          opcode_reader=lambda rd: konami1_opcode(rd))
    # flat: every slot holds one page for good, so jumps, calls and returns need no page check; the 68030 forms the
    # 68000 runs too (m6809x Program.fast_forms: flags fixed through d7, returns compared most frequent first by the
    # coverage's counts of the returns to each point)
    prog.fixed_slots = tuple(range(8))
    prog.fast_forms = True
    prog.ret_weights = dict(returns) or dict(exec_)
    prog.call_summaries = True                  # (m6809x: a call's live flags from its callees' summaries)
    prog.video_inline = (0x3000, 0x3800, set(io))   # (m6809x: video RAM byte stores inline, main_io_w outside)
    return prog


def dispatch_tables(prog, code):
    """per code page a table of 8192 words, (the label - the page's base) / 2, its base the long before it (the stub
    main_pb_NN: jmp main_badpc before the page's first label, so 0 is a bad pc); the slots' list (8 longs)"""
    pages = {v >> 13 for v in code}                 # (a ROM page with data only has no table)
    lines = ["\tsection data,data", "\teven", "main_page_tables:"]
    for p in range(8):
        lines.append("\tdc.l %s" % ("main_pt_%02X" % p if p in pages else "main_bad_table"))
    for p in sorted(pages):
        lines.append("\tdc.l main_pb_%02X" % p)
        lines.append("main_pt_%02X:" % p)
        row = []
        for off in range(0x2000):
            v = (p << 13) | off
            row.append("(%s-main_pb_%02X)/2" % (prog.label(v), p) if v in code else "0")
            if len(row) == 16:
                lines.append("\tdc.w " + ",".join(row))
                row = []
    return lines


def page_bases(lines, prog, code):
    first = {}
    for v in sorted(code):
        first.setdefault(v >> 13, prog.label(v))
    starts = {lab + ":": p for p, lab in first.items()}
    out = []
    for line in lines:
        head = line.split("\t", 1)[0]
        if head in starts:
            out.append("main_pb_%02X:\tjmp main_badpc" % starts[head])
        out.append(line)
    return out


def generate():
    build = build_dir("sbasketb")
    prog = program(load_cover())
    lines, rep, em, code = m6809x.translate(prog)
    seen = [u for u in rep["unsupported"] if int(u.split()[0], 16) in prog.exec_cover]
    if seen:
        raise RuntimeError("observed instructions cannot be translated: %s" % seen)
    lines = page_bases(lines, prog, code)
    head = ["; generated by games/sbasketb/tools/gen.py (engine/m6809x.py): the main CPU", "\tsection text,code"]
    (build / "code_main.s").write_text("\n".join(head + lines) + "\n")
    (build / "tables_main.s").write_text("\n".join(dispatch_tables(prog, code)) + "\n")
    info = ["MAIN_RESET equ %s" % prog.label(RESET), "MAIN_IRQ equ %s" % prog.label(IRQ),
            "MAIN_IDLE_T equ %s_t" % prog.label(SBasketPort.IDLE)]
    (build / "main_info.s").write_text("\n".join(info) + "\n")
    return rep


if __name__ == "__main__":
    r = generate()
    print("instructions", r["instructions"], "unsupported", len(r["unsupported"]), "missing", len(r["missing"]),
          r["stats"])
    for u in r["unsupported"][:20]:
        print("   ", u)
