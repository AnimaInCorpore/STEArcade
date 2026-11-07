"""Dragon Spirit's main and sub CPU programs translated to 68000 code (engine/m6809x.py; from games/galaga88/tools/gen.py).

    from gen import generate; report = generate()     -> build/dspirit/code_main.s, code_sub.s, tables

The coverage (ref/cover.py, build/dspirit/cover_*.pkl) gives the code pages and their slots, the data slots of each
access site, and where computed jumps and returns went.  The 68000 side of the virtual space (src/dspirit.s):
    rom_image   the eight 64 KB program ROMs (virtual $400000-$7FFFFF: ROM i at $400000 + i * $80000, mirrored)
    vio         $2E0000-$307FFF: the palette, the tile RAM, the key custom's page, the sprite RAM, the CUS30 sound RAM,
                TRIRAM, the work RAM
    nopage      8 KB for everything else
I/O pages (through the runtime's <cpu>_io_r / _io_w): $17C (the key custom: CUS136, the 16 / 8 divider), $17E (the
sprite RAM's latch byte $7F2 and flip byte $7F6, the CUS123 control registers mirrored over $2FD000-$2FDFFF).  DP is $40
in the main program (slot 2, the work RAM), $20 in the sub program (slot 1, the scratch RAM); a3 = VB[DP's slot]; a4
caches the most used other data slot of the coverage (A4_SLOT).
"""
import collections
import glob
import os
import pickle
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
import m6809x
from machine import IDLE, IRQ, DP, IDLE_LEN
from namcos1 import load_regions
from paths import build_dir

VIO_FIRST, VIO_LAST = 0x170, 0x183                  # virtual pages of vio ($2E0000-$307FFF)
IO_PAGES = {0x17C, 0x17E}
A4_SLOT = {}                                        # (program(): from the coverage)
NATIVES = {0: {}, 1: {}}
NAMES = {0: ("main", "M"), 1: ("sub", "S")}


# main page $334 runs from slots 5 and 6: slot 6's copy is page $30C (ref/cover.py PAGE_ALIAS; its own 68000 copy of the
# bytes, alias_page in core.s, so the translation's page checks by address tell the two apart)
PAGE_ALIAS = {0: {6: {0x334: 0x30C}}, 1: {}}
ALIAS_PAGE = 0x30C


def page_addr(p):
    """the 68000 address (an assembler expression) of virtual page p"""
    if p == ALIAS_PAGE:
        return "alias_page"
    if p >= 0x200:
        r = p * 0x2000 - 0x400000
        return "rom_image+$%X" % ((r >> 19) * 0x10000 + (r & 0xFFFF))
    if VIO_FIRST <= p <= VIO_LAST:
        return "vio+$%X" % ((p - VIO_FIRST) * 0x2000)
    return "nopage"


def rom_image(regions=None):
    main = (regions or load_regions("dspirit"))["main"]
    return b"".join(bytes(main[i * 0x80000:i * 0x80000 + 0x10000]) for i in range(8))


def load_cover():
    files = sorted(glob.glob(str(build_dir("dspirit") / "cover_*.pkl")))
    if not files:
        sys.exit("error: no coverage in build/dspirit: games/dspirit/ref/cover.py")
    exec_ = {0: collections.Counter(), 1: collections.Counter()}
    acc = {0: collections.defaultdict(set), 1: collections.defaultdict(set)}
    ioacc = {0: collections.defaultdict(set), 1: collections.defaultdict(set)}
    tg = {0: collections.defaultdict(set), 1: collections.defaultdict(set)}
    dps = {0: collections.defaultdict(set), 1: collections.defaultdict(set)}
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
            if "dpsite" not in d:
                sys.exit("error: %s has no DP per site (an old ref/cover.py): run it again" % f)
            for (v, slot), s in d["dpsite"][i].items():
                dps[i][v] |= s
    return exec_, acc, tg, ioacc, dps


CAP = 64                              # (ref/cover.py keeps at most this many I/O addresses per site)


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


def control_fold(ioacc):
    """v -> ("vio+$1D000", $1F) for the sites whose stores all go to the CUS123 control (mirrored every 32 bytes over
    $2FD000-$2FDFFF): the translation folds the address itself"""
    def fold(v):
        s = ioacc.get(v)
        if s and all(rw == "w" and 0x2FD000 <= va < 0x2FE000 for rw, va in s):
            return ("vio+$1D000", 0x1F)
        return None
    return fold


def dp_free(main, v):
    """the instruction at virtual pc v neither addresses the direct page nor reads DP (TFR / EXG from DP, PSHS DP)"""
    from m6809dis import decode
    base = (v >> 13) * 0x2000 - 0x400000
    ins = decode(lambda a: main[base + (a & 0x1FFF)], v & 0x1FFF)
    mn = ins.mn.lower()
    if ins.mode == "dir" or (ins.mode == "idx" and ins.arg.reg is None):
        return False
    if ins.mode == "regs" and (mn == "exg" or (ins.arg >> 4) == 0xB):
        return False
    if ins.mode == "stack" and mn.startswith("psh") and ins.arg & 0x08:
        return False
    return True


# The protection check (main $B65C-$B672): slot 0 gets page $173 (the C116's last plane), the program patches the byte
# at $0004 from the bytes at $0001 / $0003 and calls JSR $0002: the code there is PSHU (no registers); RTS when the
# check passes.  The port does not run code from RAM: core.s main_prot checks those bytes and goes on after the JSR.
PROT = {0: 0xB66F}
PROT_NEXT = {}
TABLE_ROOTS = {}                       # cpu -> {jump site: the targets table_targets added} (the report)
TABLE_MAX = 64                         # (entries read at most per table)


def table_targets(cpu, main, exec_, targets, slot_of):
    """The entries of the jump tables the coverage did not reach (random play misses later stages and phases): per
    computed jump or call the coverage saw (JMP [A,U], JMP $2000,U after LDU A,U, JMP D,X after LDD A,X ...), the
    table's base from an immediate load (LDU #t, LEAX t,PCR) on an executed path just before it, then its entries
    while they stay in the slot the seen targets lie in, outside the table and the executed code after it, and decode
    as legal instructions.  -> {virtual jump site: set of virtual targets not seen}"""
    from m6809dis import decode
    executed = {v for v, s in exec_}

    def rd_page(p):
        base = p * 0x2000 - 0x400000
        return lambda a: main[base + (a & 0x1FFF)]

    def legal(rd, pc):
        for _ in range(4):
            ins = decode(rd, pc)
            if ins.mn.startswith("x") or ins.flow == "halt" or ins.mn in ("page2", "page3"):
                return False
            if ins.flow in ("jmp", "ret", "ijmp", "rti"):
                return True
            pc = (pc + ins.length) & 0xFFFF
        return True

    inside = set()                      # (the bytes inside the executed instructions: an entry there is no table entry)
    for v in executed:
        if v >> 13 >= 0x200 and v >> 13 in slot_of:
            n = decode(rd_page(v >> 13), (slot_of[v >> 13] << 13) | (v & 0x1FFF)).length
            inside.update(range(v + 1, v + n))

    out = {}
    for v, seen in targets.items():
        p = v >> 13
        if p < 0x200 or p not in slot_of:
            continue
        slot = slot_of[p]
        rd = rd_page(p)
        pc = (slot << 13) | (v & 0x1FFF)
        site = decode(rd, pc)
        if site.flow not in ("ijmp", "icall") or site.mode != "idx" or site.arg.reg not in ("x", "y", "u"):
            continue
        x, r = site.arg, site.arg.reg
        tpages = {t >> 13 for t in seen}
        if len(tpages) != 1:
            continue
        tp = next(iter(tpages))
        ts = slot_of.get(tp)
        if ts is None:
            continue
        # the closest executed path into the site: the immediate load of r and an entry load (LDr acc,r / LDD acc,r)
        best = None
        for k in range(2, 32):
            start = pc - k
            if (p << 13) | (start & 0x1FFF) not in executed:
                continue
            a, seq = start, []
            while a < pc:
                ins = decode(rd, a)
                seq.append(ins)
                a += ins.length
            if a != pc:
                continue
            base, entry_load = None, None
            for ins in seq:
                mn = ins.mn.lower()
                if mn == "ld" + r and ins.mode == "imm16":
                    base, entry_load = ins.arg, None
                elif mn == "lea" + r and ins.mode == "idx" and ins.arg.kind in ("pcr8", "pcr16") and not ins.arg.indirect:
                    base, entry_load = ins.arg.addr, None
                elif base is not None and ins.mode == "idx" and ins.arg.reg == r and ins.arg.kind in ("acc_a", "acc_b", "acc_d") \
                        and mn in ("ld" + r, "ldd"):
                    entry_load = mn
                elif base is not None and mn in ("ld" + r, "lea" + r, "tfr", "exg", "pul" + "s", "pulu"):
                    base = None                 # (r changed otherwise: no table known)
            if base is not None:
                best = (base, entry_load)
                break
        if best is None:
            continue
        base, entry_load = best
        if base >> 13 == slot:
            trd = rd
        elif base >> 13 == ts:
            trd = rd_page(tp)
        else:
            continue
        if x.indirect and entry_load is None and x.kind in ("acc_a", "acc_b", "acc_d"):
            target_of = lambda e: e                                   # JMP [A,U]: a table of pointers
        elif not x.indirect and entry_load == "ld" + r and x.kind in ("off5", "off8", "off16", "zero"):
            target_of = lambda e, o=x.offset if x.kind != "zero" else 0: (e + o) & 0xFFFF    # JMP $2000,U
        elif not x.indirect and entry_load == "ldd" and x.kind == "acc_d":
            target_of = lambda e, b=base: (b + e) & 0xFFFF            # JMP D,X: offsets from the table
        else:
            continue
        stop = min((t & 0x1FFF) | (ts << 13) for t in seen)
        new = set()
        for i in range(TABLE_MAX):
            a = (base + 2 * i) & 0xFFFF
            if i and ((p << 13) | (a & 0x1FFF) in executed or (base >> 13 == ts and a >= stop > base)):
                break
            e = (trd(a) << 8) | trd(a + 1)
            t = target_of(e)
            if t >> 13 != ts or base <= t < base + 2 * (i + 1):
                break
            tv = (tp << 13) | (t & 0x1FFF)
            if tv in inside or not legal(rd_page(tp), t):
                break
            if tv not in seen:
                new.add(tv)
        if new:
            out[v] = new
    return out


def rom_writes(acc):
    """the sites that stored into a ROM page outside slot 7 (slot 7: the MMU's registers): main $AC00-$AC1A STA $6000 /
    $6200 / $6400 / $6600 into slot 3's ROM.  The arcade ignores them; through the runtime (core.s io_w drops stores
    into ROM pages) they cannot change the port's copy of the ROM"""
    return {v for v, s in acc.items() if any(rw == "w" and pg >= 0x200 and slot != 7 for rw, slot, pg, odd in s)}


def program(cpu, regions, cover):
    exec_, acc, tg, ioacc, dps = cover
    dp_sites = {}
    for v, s in dps[cpu].items():
        if len(s) > 1:
            # (main $A22A-$A233, $A241-$A274 in page $334: the bank routines use DP as a scratch register - TFR B,DP -
            # and their shared instructions run with several; allowed where the instruction neither addresses the
            # direct page nor reads DP)
            if not dp_free(regions["main"], v):
                raise RuntimeError("%s: the instruction at %06X runs with DP %s" % (NAMES[cpu][0], v, sorted(s)))
            if DP[cpu] in s:
                continue
            s = {min(s)}
        if s != {DP[cpu]}:
            dp_sites[v] = next(iter(s))
    name, prefix = NAMES[cpu]
    main = regions["main"]
    slot_of = {}
    for (v, slot) in exec_[cpu]:
        p = v >> 13
        if p < 0x200:                           # (the coverage saw a couple of "instructions" outside the ROM: the boot)
            continue
        if slot_of.setdefault(p, slot) != slot:
            raise RuntimeError("%s: page %X runs from slots %d and %d" % (name, p, slot_of[p], slot))

    def page_bytes(p):
        return main[p * 0x2000 - 0x400000:p * 0x2000 - 0x400000 + 0x2000]

    def virt(pc):
        pages = [p for p, s in slot_of.items() if s == pc >> 13 and ((p << 13) | (pc & 0x1FFF), s) in exec_[cpu]]
        if len(pages) != 1:
            raise RuntimeError("%s: slot %d runs pages %s" % (name, pc >> 13, [hex(p) for p in pages]))
        return (pages[0] << 13) | (pc & 0x1FFF)
    idle_v, irq_v = virt(IDLE[cpu]), virt(IRQ[cpu])
    hooks, hook_next = {idle_v: "%s_idle" % name}, {idle_v: idle_v + IDLE_LEN}
    if cpu in PROT:
        prot_v = virt(PROT[cpu])
        hooks[prot_v], hook_next[prot_v] = "%s_prot" % name, prot_v + 3
        PROT_NEXT[cpu] = prot_v + 3
    a3 = DP[cpu] >> 5
    if cpu not in A4_SLOT:
        use = collections.Counter()
        for v, accs in acc[cpu].items():
            for rw, slot, pg, odd in accs:
                if slot <= 3 and slot != a3:
                    use[slot] += exec_[cpu].get((v, slot_of.get(v >> 13, 0)), 0) or 1
        A4_SLOT[cpu] = use.most_common(1)[0][0] if use else (2 if a3 != 2 else 1)
    extra = table_targets(cpu, main, exec_[cpu], tg[cpu], slot_of)
    for v, ts in extra.items():
        tg[cpu][v] |= ts                       # (the jump's targets: what they read is live at the jump)
    roots = [irq_v, idle_v] + sorted(set().union(*extra.values())) if extra else [irq_v, idle_v]
    TABLE_ROOTS[cpu] = extra
    prog = m6809x.Program(name, prefix, page_bytes, slot_of, roots=roots,
                          exec_cover={v for v, s in exec_[cpu] if v >> 13 >= 0x200}, acc_cover=acc[cpu], targets=tg[cpu],
                          io_pages=IO_PAGES, hooks=hooks, page_addr=page_addr,
                          hook_next=hook_next, inline_banks=True, dp=DP[cpu], a3_slot=a3,
                          a4_slot=A4_SLOT[cpu], dp_sites=dp_sites, dynamic_stack=True,
                          io_fold=control_fold(ioacc[cpu]), indirect_live=not os.environ.get("NO_INDIRECT_LIVE"),
                          nf_dispatch=True,
                          natives={} if os.environ.get("NO_NATIVES") else NATIVES[cpu],
                          io_sites={v for v, s in ioacc[cpu].items() if io_site(s)} | rom_writes(acc[cpu]))
    # the slots one code page runs from (in all the coverage): returns and jumps into them need no page check
    pages_in = collections.Counter(prog.slot_of.values())
    prog.fixed_slots = tuple(sorted(k for k, n in pages_in.items() if n == 1))
    prog.fast_forms = True                      # (m6809x Program.fast_forms: flags fixed through d7, returns compared)
    prog.call_summaries = True                  # (m6809x: a call's live flags from its callees' summaries)
    prog.page_alias = PAGE_ALIAS[cpu]
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
    regions = load_regions("dspirit")
    cover = load_cover()
    build = build_dir("dspirit")
    (build / "rom_image.bin").write_bytes(rom_image(regions))
    a = ALIAS_PAGE * 0x2000 - 0x400000
    (build / "alias_page.bin").write_bytes(bytes(regions["main"][a:a + 0x2000]))
    report = {}
    info = []
    for cpu in (0, 1):
        prog, irq_v, idle_v = program(cpu, regions, cover)
        lines, rep, em, code = m6809x.translate(prog)
        rep["idle_flags"] = em.live_out.get(idle_v, m6809x.NZVC)
        em.no_entry = set()
        name = prog.name
        head = ["; generated by games/dspirit/tools/gen.py (engine/m6809x.py): the %s CPU" % name, "\tsection text,code"]
        (build / ("code_%s.s" % name)).write_text("\n".join(head + lines) + "\n")
        (build / ("tables_%s.s" % name)).write_text("\n".join(dispatch_tables(prog, code, em)) + "\n")
        info += ["%s_IRQ_LABEL equ %s" % (name.upper(), prog.label(irq_v)),
                 "%s_IDLE_PC equ $%04X" % (name.upper(), prog.cpu_pc(idle_v)),
                 "%s_IDLE_NEXT equ %s" % (name.upper(), prog.label(idle_v + IDLE_LEN)),
                 "%s_A4SLOT equ %d" % (name.upper(), A4_SLOT[cpu]),
                 "%s_DP equ $%02X" % (name.upper(), DP[cpu])]
        if cpu in PROT_NEXT:
            info.append("%s_PROT_NEXT equ %s" % (name.upper(), prog.label(PROT_NEXT[cpu])))
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
    for cpu, ex in TABLE_ROOTS.items():
        for v, ts in sorted(ex.items()):
            print("table %s %06X: + %s" % (NAMES[cpu][0], v, " ".join("%06X" % t for t in sorted(ts))))
