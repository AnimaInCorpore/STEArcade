"""Galaga '88's main and sub CPU programs translated to 68000 code (engine/m6809x.py).

    from gen import generate; text, report = generate()     -> build/galaga88/code_main.s, code_sub.s, tables

The coverage (ref/cover.py, build/galaga88/cover_*.pkl) gives the code pages and their slots, the data slots of each
access site, and where computed jumps and returns went.  The 68000 side of the virtual space (src/galaga88.s):
    rom_image   the eight 64 KB program ROMs (virtual $400000-$7FFFFF: ROM i at $400000 + i * $80000, mirrored)
    vio         $2E0000-$307FFF: the palette, the tile RAM, the key custom's page, the sprite RAM, the CUS30 sound RAM,
                TRIRAM, the work RAM
    nopage      8 KB for everything else
I/O pages (through the runtime's <cpu>_io_r / _io_w): $17C (the key custom: CUS153, the 32 / 16 divider; its reads
have a side effect), $17E (the sprite RAM's latch byte $7F2 and flip byte $7F6, the CUS123 control registers mirrored
over $2FD000-$2FDFFF).  DP is $40 in both programs (slot 2, the work RAM; the stacks are there too): a3 = VB[2]; a4
caches slot 3 (main) / slot 1 (sub), the next most used data slots.
"""
import collections
import glob
import os
import pickle
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
import m6809x
from machine import IDLE, IRQ, DP
from namcos1 import load_regions
from paths import build_dir

VIO_FIRST, VIO_LAST = 0x170, 0x183                  # virtual pages of vio ($2E0000-$307FFF)
IO_PAGES = {0x17C, 0x17E}
A4_SLOT = {0: 3, 1: 1}
NATIVES = {0: {}, 1: {}}
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
    main = (regions or load_regions("galaga88"))["main"]
    return b"".join(bytes(main[i * 0x80000:i * 0x80000 + 0x10000]) for i in range(8))


def load_cover():
    files = sorted(glob.glob(str(build_dir("galaga88") / "cover_*.pkl")))
    if not files:
        sys.exit("error: no coverage in build/galaga88: games/galaga88/ref/cover.py")
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


def control_fold(ioacc):
    """v -> ("vio+$1D000", $1F) for the sites whose stores all go to the CUS123 control (mirrored every 32 bytes over
    $2FD000-$2FDFFF): the translation folds the address itself"""
    def fold(v):
        s = ioacc.get(v)
        if s and all(rw == "w" and 0x2FD000 <= va < 0x2FE000 for rw, va in s):
            return ("vio+$1D000", 0x1F)
        return None
    return fold


def program(cpu, regions, cover):
    exec_, acc, tg, ioacc, dps = cover
    dp_sites = {}
    for v, s in dps[cpu].items():
        if len(s) > 1:
            raise RuntimeError("%s: the instruction at %06X runs with DP %s" % (NAMES[cpu][0], v, sorted(s)))
        if s != {DP}:
            dp_sites[v] = next(iter(s))
    name, prefix = NAMES[cpu]
    main = regions["main"]
    slot_of = {}
    for (v, slot) in exec_[cpu]:
        p = v >> 13
        if slot_of.setdefault(p, slot) != slot:
            raise RuntimeError("%s: page %X runs from slots %d and %d" % (name, p, slot_of[p], slot))

    def page_bytes(p):
        return main[p * 0x2000 - 0x400000:p * 0x2000 - 0x400000 + 0x2000]
    idle_pc, flags = IDLE[cpu]
    code7 = [p for p, s in slot_of.items() if s == 7]
    assert len(code7) == 1
    p7 = code7[0]
    idle_v = (p7 << 13) | (idle_pc & 0x1FFF)
    irq_v = (p7 << 13) | (IRQ[cpu] & 0x1FFF)
    prog = m6809x.Program(name, prefix, page_bytes, slot_of, roots=[irq_v, idle_v],
                          exec_cover={v for v, s in exec_[cpu]}, acc_cover=acc[cpu], targets=tg[cpu],
                          io_pages=IO_PAGES, hooks={idle_v: "%s_idle" % name}, page_addr=page_addr,
                          hook_next={idle_v: idle_v + 2}, inline_banks=True, dp=DP, a3_slot=DP >> 5,
                          a4_slot=A4_SLOT[cpu], dp_sites=dp_sites, dynamic_stack=True,
                          io_fold=control_fold(ioacc[cpu]), indirect_live=not os.environ.get("NO_INDIRECT_LIVE"),
                          after=tile_marks(acc[cpu], ioacc[cpu]), nf_dispatch=True,
                          natives={} if os.environ.get("NO_NATIVES") else NATIVES[cpu],
                          io_sites={v for v, s in ioacc[cpu].items() if io_site(s)} if any(ioacc[cpu].values()) else None)
    # the slots one code page runs from (in all the coverage): returns and jumps into them need no page check
    pages_in = collections.Counter(prog.slot_of.values())
    prog.fixed_slots = tuple(sorted(k for k, n in pages_in.items() if n == 1))
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
    regions = load_regions("galaga88")
    cover = load_cover()
    build = build_dir("galaga88")
    (build / "rom_image.bin").write_bytes(rom_image(regions))
    report = {}
    info = []
    for cpu in (0, 1):
        prog, irq_v, idle_v = program(cpu, regions, cover)
        lines, rep, em, code = m6809x.translate(prog)
        rep["idle_flags"] = em.live_out.get(idle_v, m6809x.NZVC)
        em.no_entry = set()
        name = prog.name
        head = ["; generated by games/galaga88/tools/gen.py (engine/m6809x.py): the %s CPU" % name, "\tsection text,code"]
        (build / ("code_%s.s" % name)).write_text("\n".join(head + lines) + "\n")
        (build / ("tables_%s.s" % name)).write_text("\n".join(dispatch_tables(prog, code, em)) + "\n")
        info += ["%s_IRQ_LABEL equ %s" % (name.upper(), prog.label(irq_v)),
                 "%s_IDLE_PC equ $%04X" % (name.upper(), prog.cpu_pc(idle_v)),
                 "%s_IDLE_NEXT equ %s" % (name.upper(), prog.label(idle_v + 2)),
                 "%s_A4SLOT equ %d" % (name.upper(), A4_SLOT[cpu])]
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
