"""Generate the translated Bubble Bobble programs: build/bb_code.s (+ report).

    python gen.py [-o file]

Main CPU (mode "signed", a6 = the main ROM at Z80 0, the RAM at 8000-FFFF below it):
  0000-7FFF is the fixed ROM, 8000-BFFF a window onto one of four 16 KB banks (FB40 selects).
  Code in the window is translated per bank at the virtual pc 0x10000 + 0x4000 * bank + (pc - 0x8000)
  (labels Z1xxxx); a jump from fixed code to a window address goes through a stub (BKxxxx) that
  picks the bank's label; a return (`ret`, jp (hl)) goes through the dispatch table of the
  current bank (g1_dispatch0..3, a4 follows the bank).  Reads of the window as data use a2 (the
  current bank's copy minus $8000): static reads always, register indirect reads at the sites
  the coverage found reading it (checked at run time: window or not).
Sub CPU (mode "long"): the same shared RAM (g_ram) through the absolute symbol.
Coverage from ref/cover.py (build/bublbobl/bb_cover_*.pkl).
"""
import argparse, glob, os, pickle, sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import z80x, z80dis, discover
from z80x import Emitter, compute_liveness, Unsupported, hx, swap16
from translate import compile_code
from machine import load, skip_tests

from paths import build_dir
BUILD = str(build_dir("bublbobl"))

WIN_LO, WIN_HI = 0x8000, 0xC000
VBASE = 0x10000
IY_MAIN = 0xBFF0                 # unused cells of the window area of the block: IY and F' of each CPU
IY_SUB = 0xBFF8
MAIN_HOOKS = {0x0158, 0x01ED}    # the handshake with the MCU (boot turns), the idle loop
SUB_HOOKS = {0x000A}             # the sub CPU's idle loop
TOKEN = 0x7FFE                   # the return address token of the interrupt entry (the handler checks that its high byte is below $C0)
ENTRIES = 0xC002


# The main CPU's instructions that write the video RAM (C000-DCFF), from ref/vsites.py (three seeds of attract and
# play): the form of their address.  Each marks the 128-byte page it wrote in vmarks (the page of the address,
# 0-511), so rf_vdiff compares only those pages with its copy ('all': the ldir that clears the whole RAM).  The CCR
# is kept around the computation (the translated code keeps flags in it).  rf_vdiff also compares one page a frame
# in turn, in case a writer is missing here; logic_test.py checks that every change is marked.
VRAM_WRITERS = {
    0x003BD: ('hl', 0), 0x003BF: 'all', 0x003EA: ('hl', 0), 0x003ED: ('hl', 0), 0x003FF: ('hl', 0),
    0x00402: ('hl', 0), 0x00AD0: ('de', 0), 0x00D50: ('hl', 0), 0x00E9D: ('de', 0), 0x00EA1: ('de', 0),
    0x00ECB: ('hl', 0), 0x00ECE: ('hl', 0), 0x00FD2: ('iy', -64), 0x00FD5: ('iy', -65), 0x00FD9: ('iy', 0),
    0x00FDC: ('iy', 1), 0x00FE0: ('iy', 64), 0x00FE3: ('iy', 65), 0x01480: ('iy', 12), 0x01483: ('iy', 13),
    0x01487: ('iy', 76), 0x0148A: ('iy', 77), 0x0148E: ('iy', 14), 0x01491: ('iy', 15), 0x01495: ('iy', 78),
    0x01498: ('iy', 79), 0x014A1: ('iy', 76), 0x014A4: ('iy', 77), 0x014A8: ('iy', 12), 0x014AB: ('iy', 13),
    0x014AF: ('iy', 78), 0x014B2: ('iy', 79), 0x014B6: ('iy', 14), 0x014B9: ('iy', 15), 0x0194E: ('hl', 0),
    0x01951: ('hl', 0), 0x01985: ('iy', 0), 0x01988: ('iy', 1), 0x019DE: ('iy', 0), 0x019E2: ('iy', 1),
    0x01A00: ('iy', 0), 0x01A04: ('iy', 1), 0x01A21: ('iy', 0), 0x01A25: ('iy', 1), 0x01A3C: ('iy', 0),
    0x01A40: ('iy', 1), 0x01A51: ('iy', 0), 0x01A55: ('iy', 1), 0x01A66: ('iy', 0), 0x01A6A: ('iy', 1),
    0x01A85: ('hl', 0), 0x01A90: ('hl', 0), 0x01ADA: ('iy', 0), 0x01ADD: ('iy', 1), 0x01AE1: ('iy', 64),
    0x01AE4: ('iy', 65), 0x02229: ('hl', 0), 0x03016: ('hl', 0), 0x03018: ('hl', 0), 0x03034: ('hl', 0),
    0x03036: ('hl', 0), 0x03054: ('hl', 0), 0x03056: ('hl', 0), 0x03072: ('hl', 0), 0x03074: ('hl', 0),
    0x03092: ('hl', 0), 0x03094: ('hl', 0), 0x030A0: ('hl', 0), 0x030A2: ('hl', 0), 0x030E0: ('abs', 0xD508),
    0x030E3: ('abs', 0xD50A), 0x030E6: ('abs', 0xD548), 0x030E9: ('abs', 0xD54A), 0x030F4: ('abs', 0xD509), 0x030F7: ('abs', 0xD50B),
    0x030FA: ('abs', 0xD549), 0x030FD: ('abs', 0xD54B), 0x0311D: ('abs', 0xD548), 0x03121: ('abs', 0xD54A), 0x03318: ('hl', 0),
    0x0331B: ('hl', 0), 0x03335: ('hl', 0), 0x03338: ('hl', 0), 0x034F9: ('hl', 0), 0x034FC: ('hl', 0),
    0x03559: ('de', 0), 0x0355C: ('de', 0), 0x03A36: ('iy', -65), 0x03A39: ('iy', 1), 0x03A3C: ('iy', 65),
    0x03CB0: ('hl', 0), 0x03CB2: ('hl', 0), 0x1A0AE: ('hl', 0), 0x1A0B0: ('hl', 0), 0x1A0D9: ('hl', 0),
    0x1A0DE: ('hl', 0), 0x1A133: ('hl', 0), 0x1A135: ('hl', 0), 0x1A13F: ('hl', 0), 0x1A141: ('hl', 0),
    0x1A181: ('hl', 0), 0x1A183: ('hl', 0), 0x1FE30: ('de', 0), 0x1FE34: ('de', 0),
}


def virt(pc, bank):
    return VBASE + bank * 0x4000 + (pc - WIN_LO)


def real(pc):
    return WIN_LO + ((pc - VBASE) & 0x3FFF) if pc >= VBASE else pc


def main_image():
    fixed, _ = skip_tests(load("a78-06-1.51"), load("a78-08.37"))
    big = load("a78-05-1.52")
    img = bytearray(0x20000)
    img[0:0x8000] = fixed
    img[WIN_LO:0x10000] = bytes([0x76]) * 0x8000     # real addresses 8000-FFFF are never code here (halt)
    for e in range(4):
        img[VBASE + e * 0x4000:VBASE + (e + 1) * 0x4000] = big[e * 0x4000:(e + 1) * 0x4000]
    return bytes(img)


DYN = set()          # virtual pcs the coverage executed (set by generate)


def decode_main(rom, pc):
    ins = z80dis.decode(rom, pc)
    if pc >= VBASE:
        base = pc & ~0x3FFF

        def fix(o):
            if o[0] == "addr" and ins.mn in ("jr", "djnz"):      # (the decoder wraps relative targets to 16 bits)
                return ("addr", (pc & ~0xFFFF) | o[1])
            if o[0] == "addr" and WIN_LO <= o[1] < WIN_HI:
                return ("addr", base + (o[1] - WIN_LO))
            return o
        ops = [fix(o) for o in ins.ops]
        tgt = ins.target
        if tgt is not None and ins.mn in ("jr", "djnz"):
            tgt = (pc & ~0xFFFF) | tgt
        elif tgt is not None and WIN_LO <= tgt < WIN_HI:
            tgt = base + (tgt - WIN_LO)
        ins = ins._replace(ops=ops, target=tgt)
    return ins


class BBEmitter(Emitter):
    """The main CPU: banked window, stubs, window reads.

    The translator keeps A' BC' DE' HL' in a3 a0 a1 a2, so no address register is free for the
    window: accesses to it use the marker register `aW` in the lines of an instruction, and
    emit_ins turns that into  pea (a0) / move.l g_winbase,a0 ... move.l (sp)+,a0  around the
    instruction (flag neutral: pea and movea leave the CCR alone).  g_winbase = the current
    bank's copy + $8000 (the Z80 address - $10000 is the offset)."""

    def __init__(self, *a, window_sites=(), **k):
        super().__init__(*a, **k)
        self.window_sites = set(window_sites)
        self.stubs = set()

    def x_ld_i_a(self, ins):                  # the interrupt vector page (the program checks it)
        self.e("move.b d0,g1_ireg")

    def x_ld_a_i(self, ins):
        self.e("move.b g1_ireg,d0")
        self.e("tst.b d0")
        self.flags(z80x.S | z80x.Z, const_clear=z80x.H | z80x.N)

    def label_of(self, pc):
        if WIN_LO <= pc < WIN_HI:             # a window address from fixed code: the bank decides
            self.stubs.add(pc)
            return "BK%04X" % pc
        return super().label_of(pc)

    def ret_value(self, pc):
        return real(pc)

    def direct_ok(self, rp):                  # (a return point in the window: which bank it is in, the ret cannot tell)
        return rp in self.code and not (WIN_LO <= rp < WIN_HI) and real(rp) == rp

    def mem(self, addr, off=0, io_read=False):
        a = (addr + off) & 0xFFFF
        if WIN_LO <= a < 0xBFE0:
            return "%d(aW)" % (a - 0x10000)
        return super().mem(addr, off, io_read)

    win_src = None

    def ind(self, reg, disp=0):
        if self.win_src == reg:              # a block instruction reading the window
            return "%d(aW,%s.w)" % (disp, reg) if disp else "(aW,%s.w)" % reg
        return super().ind(reg, disp)

    def win_check(self, reg):
        """lines: aW = the window's base if the address in reg is in 8000-BFFF, else a6"""
        l = self.new_label()
        return ["lea (a6),aW", "cmp.w #$8000,%s" % reg, "blo.s %s" % l, "cmp.w #$C000,%s" % reg, "bhs.s %s" % l,
                "move.l g_winbase,aW", l + ":"]

    def block_win(self, fn, ins):
        """a block instruction at a site that read the window: aW = the base of the source (hl)"""
        if ins.pc in self.window_sites:
            for line in self.win_check("d3"):
                self.lines.append(line) if line.endswith(":") else self.e(line)
            self.win_src = "d3"
        try:
            fn(ins)
        finally:
            self.win_src = None

    def x_ldir(self, ins): self.block_win(super().x_ldir, ins)     # (z80x: on address registers, by longs where it can)
    def x_ldi(self, ins): self.block_win(super().x_ldi, ins)
    def x_ldd(self, ins): self.block_win(super().x_ldd, ins)
    def x_lddr(self, ins): self.block_win(super().x_lddr, ins)
    def x_cpi(self, ins): self.block_win(super().x_cpi, ins)
    def x_cpir(self, ins): self.block_win(super().x_cpir, ins)

    def read8(self, op, io_read=True):
        pre, ea = super().read8(op, io_read)
        if op[0] == "ind" and self.cur is not None and self.cur.pc in self.window_sites and ea.startswith("(a6,"):
            reg = ea[len("(a6,"):-1]                 # e.g. d3.w
            pre = pre + self.win_check(reg.split(".")[0])
            ea = "(aW,%s)" % reg
        return pre, ea

    def emit_ins(self, pc, live_out_override=None, with_label=True):
        n0 = len(self.lines)
        super().emit_ins(pc, live_out_override, with_label)
        self.window_wrap(n0)                  # (z80x: a0 = the window, saved only where it holds BC')
        form = VRAM_WRITERS.get(pc)
        if form == 'all':
            self.e('st vmark_all')
        elif form and form[0] == 'abs':
            self.e('st vmarks+%d' % (form[1] >> 7))
        elif form:
            self.e('move sr,-(sp)')
            self.e('move.w %s,d7' % {'hl': 'd3', 'de': 'd2', 'iy': 'a2'}[form[0]])
            if form[1]:
                self.e('add.w #%d,d7' % form[1])
            self.e('lsr.w #7,d7')
            self.e('lea vmarks,a0')
            self.e('st (a0,d7.w)')
            self.e('move (sp)+,ccr')


def coverage():
    main, sub = set(), set()
    wread = set()
    for f in glob.glob(os.path.join(BUILD, "bb_cover_*.pkl")):
        d = pickle.load(open(f, "rb"))
        main |= {virt(pc % 0x4000 + WIN_LO, pc // 0x4000 - 4) if False else pc for pc in d["pcs"][0]}
        sub |= d["pcs"][1]
        wread |= d["wread"]
    return main, sub, wread


def vpc_of_cover(pc):
    """bb_cover.py records window pcs as pc + 0x4000 * entry (8000..BFFF + e*4000)"""
    if pc < WIN_LO:
        return pc
    e, off = divmod(pc - WIN_LO, 0x4000)
    return VBASE + e * 0x4000 + off


def configs():
    hooks = [(0xFB40, 0xFB40, "bb_bank", None)]
    main = z80x.Config(prefix="Z", table="g1_dispatch", token_sym="g1_ret", mode="signed", block=0x10000,
                       iyaddr=IY_MAIN, fshadow=IY_MAIN + 2, io_read_redirect={}, write_hooks=hooks,
                       nmi_token=TOKEN, table_entries=ENTRIES, rst28_tables=False, iff_sym="g1_iff", **z80x.FAST)
    sub = z80x.Config(prefix="Y", table="g2_dispatch", token_sym="g2_ret", mode="long", block=0x10000,
                      ram_sym="g_ram", iyaddr=IY_SUB, fshadow=IY_SUB + 2, io_read_redirect={}, write_hooks=[],
                      nmi_token=TOKEN, table_entries=ENTRIES, rst28_tables=False, iff_sym="g2_iff", **z80x.FAST_LONG)
    return main, sub


def translate(rom, roots, dyn, cfg, emitter_cls=Emitter, decode=None, hooks=(), **kw):
    """-> (code lines, report, emitter)"""
    saved = discover.decode
    if decode:
        discover.decode = decode
    try:
        code, tables = discover.discover(rom, list(roots) + sorted(dyn), known=dyn, rst28_tables=cfg.rst28_tables,
                                         hl_tables=cfg.hl_tables)
    finally:
        discover.decode = saved
    # (bank entry 1 holds data only: what a static walk finds there is not code)
    code = {pc: i for pc, i in code.items() if not (WIN_LO <= pc < 0x10000) and not (virt(WIN_LO, 1) <= pc < virt(WIN_LO, 2) and cfg.prefix == "Z")}
    joins = set(roots) | set(hooks)
    for nxt, targets in tables.values():
        joins |= set(targets)
    em = compile_code(code, joins, cfg, hooks, emitter=emitter_cls, **kw)
    return code, tables, em


def generate():
    main_dyn, sub_dyn, wread = coverage_all()
    img = main_image()
    sub_rom = skip_tests(load("a78-06-1.51"), load("a78-08.37"))[1]
    cfg_main, cfg_sub = configs()
    out = ["; generated by gen.py -- Bubble Bobble main CPU (banked) and sub CPU, Z80 -> 68000", "\tsection text,code"]
    reports = []

    # ---- main CPU
    wsites = {vpc_of_cover(pc) for pc, bank in wread}
    for f in glob.glob(os.path.join(BUILD, "bb_wsites_audit_*.pkl")):      # tools/window_audit.py
        wsites |= {int(name[1:], 16) for name in pickle.load(open(f, "rb"))}
    DYN.clear()
    DYN.update(vpc_of_cover(p) for p in main_dyn)
    code, tables, em = translate(img, [0, 0x38, 0x66], DYN, cfg_main,
                                 BBEmitter, decode_main, hooks=MAIN_HOOKS, window_sites=wsites)
    for ins in code.values():
        pass
    out.append("; ---------------- main CPU")
    out += em.lines
    missing = sorted(p for p in em.refs if p not in code and not (WIN_LO <= p < WIN_HI))
    out.append("; --- targets that are not code")
    for p in missing:
        out.append("Z%04X:\tmove.w #$%04X,d7\n\tjmp z80_badpc" % (p, p & 0xFFFF))
    # stubs: a fixed-code jump to a window address picks the bank's label
    out.append("; --- window stubs")
    for pc in sorted(em.stubs):
        out.append("BK%04X:\tmove.w g_bank4,d7\n\tmove.l BKT%04X(pc,d7.w),a3\n\tjmp (a3)" % (pc, pc))
        row = []
        for e in range(4):
            v = virt(pc, e)
            row.append("Z%04X" % v if v in code else "z80_badpc")
        out.append("BKT%04X:\tdc.l %s" % (pc, ",".join(row)))
    # the dispatch tables are built at start from these lists (pc, label): fixed code, each bank's window code
    tables_out = ["\tsection data,data", "\tcnop 0,2"]

    def entries(name, pcs, prefix, labelof):
        tables_out.append("%s:" % name)
        for p in pcs:
            tables_out.append("\tdc.w $%04X\n\tdc.l %s%04X" % (p, prefix, labelof(p)))

    entries("g1_entries_fixed", [p for p in sorted(code) if p < WIN_LO and p not in em.no_entry], "Z", lambda p: p)
    tables_out.append("\tdc.w $%04X\n\tdc.l %s\n\tdc.w $FFFF" % (TOKEN, cfg_main.token_sym))
    for e in range(4):
        pcs = [p for p in range(WIN_LO, WIN_HI) if virt(p, e) in code and virt(p, e) not in em.no_entry]
        entries("g1_entries_bank%d" % e, pcs, "Z", lambda p, e=e: virt(p, e))
        tables_out.append("\tdc.w $FFFF")
    reports.append({"instructions": len(code), "unsupported": em.unsupported, "stubs": len(em.stubs),
                    "window_sites": len(wsites)})

    # ---- sub CPU
    scode, stables, sem = translate(sub_rom + bytes(0x10000 - len(sub_rom)), [0, 0x38, 0x66],
                                    {p for p in sub_dyn}, cfg_sub, hooks=SUB_HOOKS)
    out.append("; ---------------- sub CPU")
    out += sem.lines
    missing = sorted(p for p in sem.refs if p not in scode)
    out.append("; --- targets that are not code")
    for p in missing:
        out.append("Y%04X:\tmove.w #$%04X,d7\n\tjmp z80_badpc" % (p, p))
    tables_out.append("g2_entries:")
    for p in sorted(scode):
        if p not in sem.no_entry:
            tables_out.append("\tdc.w $%04X\n\tdc.l Y%04X" % (p, p))
    tables_out.append("\tdc.w $%04X\n\tdc.l %s\n\tdc.w $FFFF" % (TOKEN, cfg_sub.token_sym))
    reports.append({"instructions": len(scode), "unsupported": sem.unsupported})
    return "\n".join(out + tables_out) + "\n", reports


def coverage_all():
    main, sub, wread = set(), set(), set()
    for f in glob.glob(os.path.join(BUILD, "bb_cover_*.pkl")):
        d = pickle.load(open(f, "rb"))
        main |= d["pcs"][0]
        sub |= d["pcs"][1]
        wread |= d["wread"]
    return main, sub, wread


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", default=os.path.join(BUILD, "bb_code.s"))
    a = ap.parse_args()
    text, reps = generate()
    os.makedirs(os.path.dirname(a.o), exist_ok=True)
    open(a.o, "w").write(text)
    for n, rep in enumerate(reps):
        print("CPU%d: instructions %d, unsupported %d %s" % (n + 1, rep["instructions"], len(rep["unsupported"]),
                                                              {k: v for k, v in rep.items() if k not in ("instructions", "unsupported")}))
        for u in rep["unsupported"][:40]:
            print("   %04X %-24s %s" % u)
    print("lines:", len(text.splitlines()))
