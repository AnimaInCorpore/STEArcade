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
NATIVES = {0: {}, 1: {0x6EF714: "sub_sprites", 0x6EF4CF: "sub_spritelist"}}
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

    def after(v, ins):
        if v in marks:
            return marks[v]
        if v not in acc and ins.mode in ("ext", "idx") and (m6809x.base_mn(ins.mn).startswith("st") or m6809x.base_mn(ins.mn) in (
                "clr", "neg", "com", "inc", "dec", "asl", "lsl", "lsr", "asr", "rol", "ror")):
            return ["st tile_written", "st tile_written_fix"]
        return None
    return after


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
                          after=tile_marks(acc[cpu], ioacc[cpu]),
                          natives={} if os.environ.get("NO_NATIVES") else NATIVES[cpu],
                          io_sites={v for v, s in ioacc[cpu].items() if io_site(s)} if any(ioacc[cpu].values()) else None)
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
