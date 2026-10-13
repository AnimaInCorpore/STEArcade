"""Splatterhouse's main and sub CPU programs translated to 68000 code (engine/m6809x.py).

    from gen import generate; text, report = generate()     -> build/splatter/code_main.s, code_sub.s, tables

The coverage (ref/cover.py, build/splatter/cover_*.pkl) gives the code pages and their slots, the data slots of each
access site, and where computed jumps and returns went.  The 68000 side of the virtual space (src/splatter.s):
    rom_image   the eight 64 KB program ROMs (virtual $400000-$7FFFFF: ROM i at $400000 + i * $80000, mirrored)
    vio         $2E0000-$307FFF: the palette, the tile RAM, the key custom's page, the sprite RAM, the CUS30 sound RAM,
                TRIRAM, the work RAM
    nopage      8 KB for everything else
I/O pages (through the runtime's <cpu>_io_r / _io_w): $17C (the key custom), $17E (the sprite RAM's latch byte $7F2
and flip byte $7F6, the CUS123 control registers mirrored over $2FD000-$2FDFFF).
"""
import collections
import glob
import os
import pickle
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
import m6809x
from machine import IDLE
from namcos1 import load_regions
from paths import build_dir

VIO_FIRST, VIO_LAST = 0x170, 0x183                  # virtual pages of vio ($2E0000-$307FFF)
IO_PAGES = {0x17C, 0x17E}
IRQ = {0: 0xE0DF, 1: 0xE0A1}                        # the IRQ handlers (slot 7)
# hand-written 68000 routines (src/natives.s) in place of translated code; NO_NATIVES=1 builds the translation only
NATIVES = {0: {0x7FCA57: "main_mul16", 0x7FC5D5: "main_bgclass"}, 1: {0x6EF714: "sub_sprites", 0x6EF4CF: "sub_spritelist"}}
NAMES = {0: ("main", "M"), 1: ("sub", "S")}


def page_addr(p):
    """the 68000 address (an assembler expression) of virtual page p"""
    if p >= 0x200:
        r = p * 0x2000 - 0x400000
        return "rom_image+$%X" % ((r >> 19) * 0x10000 + (r & 0xFFFF))
    if VIO_FIRST <= p <= VIO_LAST:
        return "vio+$%X" % ((p - VIO_FIRST) * 0x2000)
    return "nopage"


def rom_image(regions=None):
    main = (regions or load_regions("splatter"))["main"]
    return b"".join(bytes(main[i * 0x80000:i * 0x80000 + 0x10000]) for i in range(8))


def load_cover():
    files = sorted(glob.glob(str(build_dir("splatter") / "cover_*.pkl")))
    if not files:
        sys.exit("error: no coverage in build/splatter: python port.py cover splatter")
    exec_ = {0: collections.Counter(), 1: collections.Counter()}
    acc = {0: collections.defaultdict(set), 1: collections.defaultdict(set)}
    ioacc = {0: collections.defaultdict(set), 1: collections.defaultdict(set)}
    tg = {0: collections.defaultdict(set), 1: collections.defaultdict(set)}
    for f in files:
        d = pickle.load(open(f, "rb"))
        for i in (0, 1):
            exec_[i].update(d["exec"][i])
            for (v, slot), s in d["acc"][i].items():
                acc[i][v] |= s
            for (v, slot), s in d["targets"][i].items():
                tg[i][v] |= s
            for (v, slot), s in d.get("ioacc", {}).get(i, {}).items():
                ioacc[i][v] |= s
    return exec_, acc, tg, ioacc


TILE0 = 0x2F0000                      # the CUS123 tile RAM ($2F0000-$2F7FFF): layers 0-3 below $2F7000, the fixed above
CAP = 64                              # (ref/cover.py keeps at most this many I/O addresses per site)


def tile_marks(acc, ioacc):
    """the render's writer flags (src/render.s, TILE_FLAG): (v, ins) -> the lines after a store into tile RAM.  From the
    coverage: a site that wrote tile RAM sets tile_written (layers 0-3) and / or tile_written_fix (the fixed layers);
    a store the coverage never saw sets both."""
    marks = {}
    for v, s in acc.items():
        pages = {pg for rw, slot, pg, odd in s if rw == "w" and TILE0 >> 13 <= pg <= (TILE0 >> 13) + 3}
        if not pages:
            continue
        ws = [va for rw, va in ioacc.get(v, ()) if rw == "w"]
        exact = 0 < len(ioacc.get(v, ())) < CAP
        lay = bool(pages - {(TILE0 >> 13) + 3}) or not exact or any(va < TILE0 + 0x7000 for va in ws)
        fix = (TILE0 >> 13) + 3 in pages and (not exact or any(va >= TILE0 + 0x7000 for va in ws))
        marks[v] = ["st tile_written"] * lay + ["st tile_written_fix"] * fix
        if fix:
            # the fixed layers' rows it wrote (render.s TILE_ROWS: only those are compared); not known: all
            rows = sorted({fix_row(va - TILE0) for va in ws} - {None}) if exact else None
            marks[v] += ["st tile_fix_rows+%d" % r for r in rows] if rows is not None else ["st tile_fix_all"]

    def after(v, ins):
        if v in marks:
            return marks[v]
        if v not in acc and ins.mode in ("ext", "idx") and (m6809x.base_mn(ins.mn).startswith("st") or m6809x.base_mn(ins.mn) in (
                "clr", "neg", "com", "inc", "dec", "asl", "lsl", "lsr", "asr", "rol", "ror")):
            return ["st tile_written", "st tile_written_fix", "st tile_fix_all"]
        return None
    return after


def fix_row(off):
    """a tile RAM offset -> its fixed layer row flag (28 a layer: layer 4 at $7010, layer 5 at $7810, 72 bytes a row),
    or None (not shown)"""
    for k, base in enumerate((0x7010, 0x7810)):
        if base <= off < base + 28 * 72:
            return 28 * k + (off - base) // 72
    return None


def io_site(accesses):
    """an access site that needs the runtime: the key custom, the sprite RAM's latch byte, the CUS123 control (mirrored
    over $2FD000-$2FDFFF), the C116 registers past their first copy"""
    for rw, va in accesses:
        page, off = va >> 13, va & 0x1FFF
        if page == 0x17C:
            return True
        if page == 0x17E and (off >= 0x1000 or (off == 0xFF2 and rw == "w")):
            return True
        if 0x170 <= page <= 0x173 and off >= 0x1800 and (page != 0x170 or off >= 0x1810):
            return True
    return False


def key_read(page, off):
    """a read of the key custom (CUS181, type 3) at a static address: the register is known (A4-A6 of the address)"""
    if page != 0x17C:
        return None
    op = (off & 0x70) >> 4
    if op == 3:
        return ["move.l #181,d7"]
    if op == 4:
        return ["bsr mame_rand"]
    return ["moveq #0,d7"]


def control_fold(ioacc):
    """v -> ("vio+$1D000", $1F) for the sites whose stores all go to the CUS123 control (mirrored every 32 bytes over
    $2FD000-$2FDFFF): the translation folds the address itself"""
    def fold(v):
        s = ioacc.get(v)
        if s and all(rw == "w" and 0x2FD000 <= va < 0x2FE000 for rw, va in s):
            return ("vio+$1D000", 0x1F)
        return None
    return fold


def plausible(prog, v, starts, inside):
    """a table entry could be code: a code page's straight line of instructions decodes to ordinary ones until a
    transfer or code the coverage reached (within 256), and never starts inside an instruction of that code"""
    for _ in range(256):
        if v >> 13 not in prog.slot_of or v in inside:
            return False
        if v in starts:
            return True
        rd, slot = prog.reader(v)
        ins = m6809x.decode(rd, prog.cpu_pc(v), prog.dp_at(v))
        if ins.flow in ("halt", "wait", "swi", "rti") or ins.mn[0] == "x" or ins.mn == "nop" or \
                ins.mode == "idx" and ins.arg.kind == "illegal":
            return False
        if ins.flow not in ("seq", "jcc", "call", "icall"):
            return True
        nv = m6809x.next_virtual(prog, v, ins)
        if nv is None:
            return False
        v = nv
    return False


def plausible_tree(prog, v, starts, inside, known, ok):
    """plausible, and so is everything v reaches in its own page (straight on, branches, jumps and calls) before code
    the coverage or the discovery reached: no instruction plausible rejects, no start inside an executed instruction"""
    page, work, seen = v >> 13, [v], set()
    while work:
        u = work.pop()
        if u in seen or u in starts or u in known:
            continue
        seen.add(u)
        if u >> 13 != page or u in inside:
            return False
        rd, slot = prog.reader(u)
        ins = m6809x.decode(rd, prog.cpu_pc(u), prog.dp_at(u))
        if ins.flow in ("halt", "wait", "swi", "rti") or ins.mn[0] == "x" or ins.mn == "nop" or \
                ins.mode == "idx" and ins.arg.kind == "illegal":
            return False
        if ins.target is not None and ins.flow in ("jmp", "jcc", "call") and ins.target >> 13 == slot:
            work.append((u & ~0x1FFF) | (ins.target & 0x1FFF))
        if ins.flow in ("seq", "jcc", "call", "icall"):
            nv = m6809x.next_virtual(prog, u, ins)
            if nv is None:
                return False
            work.append(nv)
    return ok(v)


def table_targets(prog, exec_v, tg, acc):
    """the entries of ROM tables that random play did not exhaust -> {site: set of virtual targets}.  A computed call /
    jump through memory (JSR / JMP [..]): in the ROM pages the site read its pointer from, the runs of plausible
    entries that hold at least two of the targets the coverage saw.  An entry is an address word (stride 2; its page
    the one the site's targets have in that slot, or the slot's only one) or a page word and an address word (stride 4:
    the object records of stages 3 and 5, `LDD ,X++; STD $E800; JSR [,X]`)."""
    starts, inside = set(), set()
    for v in exec_v:
        rd, slot = prog.reader(v)
        ins = m6809x.decode(rd, prog.cpu_pc(v), prog.dp_at(v))
        starts.add(v)
        inside.update(range(v + 1, v + ins.length))
    inside -= starts
    ok_cache = {}

    def ok(t):
        if t not in ok_cache:
            ok_cache[t] = plausible(prog, t, starts, inside)
        return ok_cache[t]
    out = collections.defaultdict(set)
    for v, seen in tg.items():
        if v not in starts or v >> 13 not in prog.slot_of:
            continue
        rd, slot = prog.reader(v)
        ins = m6809x.decode(rd, prog.cpu_pc(v), prog.dp_at(v))
        if ins.flow not in ("icall", "ijmp") or ins.mode != "idx" or not ins.arg.indirect:
            continue
        seen = {t for t in seen if t >> 13 in prog.slot_of}
        by_slot = collections.defaultdict(set)
        for t in seen:
            by_slot[prog.slot_of[t >> 13]].add(t >> 13)
        for pg in sorted({pg for rw, sl, pg, odd in acc.get(v, ()) if rw == "r" and pg >= 0x200}):
            data = prog.page(pg)

            def word(o):
                return (data[o] << 8) | data[o + 1]

            def entry(o, stride):
                if not 0 <= o < 0x1FFF:
                    return None
                w = word(o)
                s = w >> 13
                if stride == 4:
                    if o < 2 or prog.slot_of.get(word(o - 2)) != s:
                        return None
                    tv = (word(o - 2) << 13) | (w & 0x1FFF)
                else:
                    pages = by_slot.get(s) or prog.slot_pages.get(s, ())
                    if len(pages) != 1:
                        return None
                    tv = (next(iter(pages)) << 13) | (w & 0x1FFF)
                return tv if ok(tv) else None
            done = set()
            for o in range(0x1FFF):
                for stride in (2, 4):
                    if (o, stride) in done or entry(o, stride) not in seen:
                        continue
                    run = set()
                    for step in (stride, -stride):
                        q = o
                        for _ in range(256):
                            tv = entry(q, stride)
                            if tv is None:
                                break
                            done.add((q, stride))
                            run.add(tv)
                            q += step
                    if len(run & seen) >= 2:
                        out[v] |= run - seen
    # the code these entries reach has tables of its own that nothing ran: `LDX #table` (A / B loads and shifts
    # between) and JSR / JMP [A,X] or [B,X]: the plausible entries from the first one on; again until nothing is new.
    # Also the sites that ran with fewer than two targets seen (no run above: seed 14 stopped at $883F's entry $2A)
    simple = ("lda", "ldb", "asla", "aslb", "lsla", "lslb", "tsta", "tstb", "anda", "andb")
    static = set()
    while True:
        prog.targets = {k: set(tg.get(k, ())) | out.get(k, set()) for k in set(tg) | set(out)}
        code, joins = m6809x.discover(prog)
        prev = collections.defaultdict(list)
        for u, ins in code.items():
            nv = m6809x.next_virtual(prog, u, ins)
            if nv is not None and ins.flow in ("seq", "jcc"):
                prev[nv].append(u)
        new = False
        for v, ins in code.items():
            if v in static or ins.flow not in ("icall", "ijmp") or ins.mode != "idx":
                continue
            if v in starts and len({t for t in tg.get(v, ()) if t >> 13 in prog.slot_of}) >= 2:
                continue
            x = ins.arg
            if not x.indirect or x.reg != "x" or x.kind not in ("acc_a", "acc_b"):
                continue
            static.add(v)
            w, table = v, None
            for _ in range(4):
                if len(prev[w]) != 1:
                    break
                w = prev[w][0]
                if code[w].mn == "ldx" and code[w].mode == "imm16":
                    table = code[w].arg
                    break
                if code[w].mn not in simple:
                    break
            if table is None:
                continue
            own = prog.slot_of[v >> 13]

            def page_in(s):
                if s == own:
                    return v >> 13
                pages = prog.slot_pages.get(s, ())
                return next(iter(pages)) if len(pages) == 1 else None
            tp = page_in(table >> 13)
            if tp is None:
                continue
            data = prog.page(tp)
            for k in range(64):
                o = (table & 0x1FFF) + 2 * k
                if o + 1 >= 0x2000:
                    break
                w16 = (data[o] << 8) | data[o + 1]
                pg = page_in(w16 >> 13)
                if pg is None or not ok((pg << 13) | (w16 & 0x1FFF)):
                    break
                out[v].add((pg << 13) | (w16 & 0x1FFF))
                new = True
        # direct jumps / calls in code nothing ran into a slot of several pages (no target the coverage saw): each page
        # where the target is plausible, its branches and calls in that slot too (seed 14: $887C's JSR $D3F4 into slot
        # 6, pages 3B4 and 3FE; 3B4's $C51B is TSTA; BRA into data)
        for v, ins in code.items():
            if v in starts or ins.target is None or ins.flow not in ("jmp", "jcc", "call"):
                continue
            ts = ins.target >> 13
            if ts == prog.slot_of[v >> 13] or m6809x.branch_targets(prog, v, ins):
                continue
            for pg in sorted(prog.slot_pages.get(ts, ())):
                tv = (pg << 13) | (ins.target & 0x1FFF)
                if tv not in out[v] and ok(tv) and plausible_tree(prog, tv, starts, inside, code, ok):
                    out[v].add(tv)
                    new = True
        if not new:
            return out


def program(cpu, regions, cover):
    exec_, acc, tg, ioacc = cover
    name, prefix = NAMES[cpu]
    main = regions["main"]
    slot_of = {}
    for (v, slot) in exec_[cpu]:
        p = v >> 13
        if slot_of.setdefault(p, slot) != slot:
            raise RuntimeError("%s: page %X runs from slots %d and %d" % (name, p, slot_of[p], slot))

    def page_bytes(p):
        return main[p * 0x2000 - 0x400000:p * 0x2000 - 0x400000 + 0x2000]
    idle_pc, flag = IDLE[cpu]
    idle_v = (0x3FF << 13) | (idle_pc & 0x1FFF) if cpu == 0 else (0x377 << 13) | (idle_pc & 0x1FFF)
    code7 = [p for p, s in slot_of.items() if s == 7]
    assert len(code7) == 1
    p7 = code7[0]
    idle_v = (p7 << 13) | (idle_pc & 0x1FFF)
    irq_v = (p7 << 13) | (IRQ[cpu] & 0x1FFF)
    prog = m6809x.Program(name, prefix, page_bytes, slot_of, roots=[irq_v, idle_v],
                          exec_cover={v for v, s in exec_[cpu]}, acc_cover=acc[cpu], targets=tg[cpu],
                          io_pages=IO_PAGES, hooks={idle_v: "%s_idle" % name}, page_addr=page_addr,
                          hook_next={idle_v: idle_v + 3}, static_read=key_read, inline_banks=True,
                          io_fold=control_fold(ioacc[cpu]), indirect_live=not os.environ.get("NO_INDIRECT_LIVE"),
                          after=tile_marks(acc[cpu], ioacc[cpu]), nf_dispatch=True, pid_checks=True,
                          natives={} if os.environ.get("NO_NATIVES") else NATIVES[cpu],
                          io_sites={v for v, s in ioacc[cpu].items() if io_site(s)} if any(ioacc[cpu].values()) else None)
    # the slots one code page runs from (in all the coverage): returns and jumps into them need no page check
    pages_in = collections.Counter(prog.slot_of.values())
    prog.fixed_slots = tuple(sorted(k for k, n in pages_in.items() if n == 1))
    # table entries random play did not take (stage-select seeds 11, 13, 17 stopped at them in lock-step)
    extra = {} if os.environ.get("NO_TABLES") else table_targets(prog, prog.exec_cover, tg[cpu], acc[cpu])
    prog.targets = {v: set(tg[cpu].get(v, ())) | extra.get(v, set()) for v in set(tg[cpu]) | set(extra)}
    prog.table_extra = sum(len(s) for s in extra.values())
    return prog, irq_v, idle_v


def dispatch_tables(prog, code, em):
    """per code page a table of 8192 longs (the labels; <cpu>_badpc elsewhere), and the page list"""
    lines = ["\tsection data,data", "%s_page_tables:" % prog.name]
    pages = sorted(prog.slot_of)
    table_of = {}
    for p in range(0x400):
        lines.append("\tdc.l %s" % ("%s_pt_%03X" % (prog.name, p) if p in prog.slot_of else "bad_table"))
    for p in pages:
        lines.append("%s_pt_%03X:" % (prog.name, p))
        row = []
        for off in range(0x2000):
            v = (p << 13) | off
            row.append(prog.label(v) if v in code and v not in em.no_entry else "%s_badpc" % prog.name)
            if len(row) == 8:
                lines.append("\tdc.l " + ",".join(row))
                row = []
    return lines


def generate():
    regions = load_regions("splatter")
    cover = load_cover()
    build = build_dir("splatter")
    (build / "rom_image.bin").write_bytes(rom_image(regions))
    report = {}
    info = []
    for cpu in (0, 1):
        prog, irq_v, idle_v = program(cpu, regions, cover)
        lines, rep, em, code = m6809x.translate(prog)
        rep["idle_flags"] = em.live_out.get(idle_v, m6809x.NZVC)
        rep["stats"]["table entries"] = prog.table_extra
        em.no_entry = set()
        name = prog.name
        head = ["; generated by games/splatter/tools/gen.py (engine/m6809x.py): the %s CPU" % name, "\tsection text,code"]
        (build / ("code_%s.s" % name)).write_text("\n".join(head + lines) + "\n")
        (build / ("tables_%s.s" % name)).write_text("\n".join(dispatch_tables(prog, code, em)) + "\n")
        info += ["%s_IRQ_LABEL equ %s" % (name.upper(), prog.label(irq_v)),
                 "%s_IDLE_PC equ $%04X" % (name.upper(), prog.cpu_pc(idle_v)),
                 "%s_IDLE_NEXT equ %s" % (name.upper(), prog.label(idle_v + 3)),
                 "%s_FLAG equ $%02X" % (name.upper(), IDLE[cpu][1])]
        report[name] = rep
    (build / "gen_info.s").write_text("\n".join(info) + "\n")
    import json
    (build / "gen_info.json").write_text(json.dumps({k: {"idle_flags": v["idle_flags"]} for k, v in report.items()}))
    return report


if __name__ == "__main__":
    rep = generate()
    for name, r in rep.items():
        print(name, "instructions", r["instructions"], "unsupported", len(r["unsupported"]), "missing", len(r["missing"]),
              r["stats"])
        for u in r["unsupported"][:20]:
            print("   ", u)
