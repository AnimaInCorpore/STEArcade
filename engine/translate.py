"""Whole-program translation of one Z80 program: discovery, flag liveness, CCR analysis, emission.

generate_program() is shared by every port; the games' gen.py supply the ROM, the entry points, the
coverage (pcs seen executing, from games/<game>/ref/*cover*.py) and the z80x.Config.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from z80x import Emitter, compute_liveness, ret_targets
from discover import discover


def compile_code(code, joins, cfg, hooks=(), emitter=Emitter, ijmp_flags=False, flags_at=(), precise_rets=True, **kw):
    """Emit the 68000 code of `code` (pc -> Ins).  joins: pcs entered from outside the straight flow (entries,
    hooks, jump table targets); return points and code addresses held as numbers are added here.  emitter / kw:
    the Emitter class and its extra arguments; ijmp_flags / flags_at: see compute_liveness.  precise_rets: the flag
    liveness follows calls into their callees and rets back to their return points (ret_targets).  -> the Emitter
    (em.lines)."""
    foreign = set(joins)
    for pc, ins in code.items():
        for op in ins.ops:
            if op[0] == "imm" and op[1] in code:
                foreign.add(op[1])
    ret_succ = ret_targets(code, foreign, cfg.rst28_tables) if precise_rets else None
    live = dict(ijmp_flags=ijmp_flags, flags_at=flags_at, ret_succ=ret_succ)
    live_in, live_out = compute_liveness(code, **live)
    em = emitter(code, live_in, live_out, cfg=cfg, **kw)
    em.hooks = set(hooks)
    # where the flags in the CCR are unknown: entries, return points, targets of computed
    # jumps (the jump tables, any code address the program holds as a number), hooks
    joins = set(foreign)
    for pc, ins in code.items():
        if ins.flow in ("call", "ccall", "rst"):
            joins.add(pc + ins.length)
    em.analyze(joins)
    em.live_in, em.live_out = compute_liveness(code, em.ccr_users, **live)
    em.ret_succ = ret_succ
    em.emit_all()
    return em


def generate_program(rom, roots, dyn, cfg, hooks=(), extra_roots=()):
    """-> (code lines, table lines, report, emitter) of one program.  roots: entry pcs;
    dyn: pcs seen executing (coverage), seeds for the discovery and known code."""
    code, tables = discover(rom, list(roots) + sorted(dyn) + list(extra_roots), known=dyn,
                            rst28_tables=cfg.rst28_tables, hl_tables=cfg.hl_tables)
    joins = set(roots) | set(hooks)
    for nxt, targets in tables.values():
        joins |= set(targets)
    em = compile_code(code, joins, cfg, hooks)
    lines = list(em.lines)
    # stubs for labels that are referenced but not translated
    missing = sorted(p for p in em.refs if p not in code)
    lines.append("; --- targets that are not code")
    for p in missing:
        lines.append("%s%04X:\tmove.w #$%04X,d7\n\tjmp z80_badpc" % (cfg.prefix, p, p))
    table = ["%s:" % cfg.table]
    row = []
    for p in range(cfg.table_entries):
        if p in code and p not in em.no_entry:
            row.append("%s%04X" % (cfg.prefix, p))
        elif p == cfg.nmi_token:
            row.append(cfg.token_sym)
        else:
            row.append("z80_badpc")
        if len(row) == 8:
            table.append("\tdc.l " + ",".join(row))
            row = []
    if row:
        table.append("\tdc.l " + ",".join(row))
    report = {
        "instructions": len(code),
        "unsupported": em.unsupported,
        "missing_targets": [hex(p) for p in missing],
        "tables": {hex(k): [hex(x) for x in v[1]] for k, v in tables.items()},
    }
    return lines, table, report, em
