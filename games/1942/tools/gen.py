"""Generate the translated 1942 main CPU program: build/1942/code_1942.s (+ report).

    python gen.py [-o file]

One Z80 program ("signed" memory model: a6 = the Z80 address $8000 of a 64 KB block, RAM and video RAM at C000-EFFF are
the block, ROM at 0000-7FFF).  $8000-$BFFF is a window onto one of the three 16 KB ROM banks (C806): the program only
reads it as data (the only code that runs from it is the service mode, which is not translated), so the block's own window
area stays unused and the instructions that read the window go through the marker register `aW` = `g_winbase`
(the current bank's ROM copy), the way Bubble Bobble's main CPU does it; the sites are those the coverage runs and
tools/window_audit.py found.  The service mode jump ($0166) lands on a "not code" stub.
The kernel switches tasks with `ld sp,hl` / `ret` / `jp (hl)` through the dispatch table; the interrupts are delivered
by the runtime at the foreground's idle point (see machine.py run_frame_port).
Coverage from ref/cover.py (build/1942/cover_*.pkl).
"""
import argparse, glob, json, os, pickle, re, sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import z80x, z80dis, discover
from z80x import Emitter, compute_liveness, Unsupported, hx, swap16
from translate import compile_code
from machine import main_rom

from paths import build_dir, require_coverage
BUILD = str(build_dir("1942"))

WIN_LO, WIN_HI = 0x8000, 0xC000
IY_ADDR = 0xBFF0                 # unused cells of the window area of the block: IY and F'
TOKEN = 0xBFFE                   # the return address token of the interrupt entry (never a real address)
ENTRIES = 0x8000                 # code lives in 0000-7FFF
TABLE_CALLS = {0x66F7: WIN_LO, 0x66F4: WIN_LO}   # `call 66F7`: the word table of handlers follows the call (index in A, or (ix+3) at 66F4)
TABLES = ((0x05F9, 13), (0x0603, 13))           # the two tables the scheduler of the enemies indexes through $1936 (hl = table, A & 15)
SCAN_HOOK = 0x0087               # the scheduler's scan for a ready task (0087-009A): done natively (z80_hook)
IDLE_HOOK = 0x009A               # the scheduler's idle loop found no task: the runtime's schedule (z80_hook)
PV_FORCE = {0x261A}               # `or a,a` whose parity is read at 262D after an ex af,af' pair
BANK_HOOK = (0xC806, 0xC806, "g_bank_w", None)
# the kernel's entry points reached only through interrupt vectors / task tables: rst vectors are roots below


def image():
    """The program as the translator sees it: ROM at 0000-7FFF, the rest of the 64 KB halt (never code here)."""
    rom = main_rom()
    img = bytearray(b"\x76" * 0x10000)
    img[0:0x8000] = rom[0:0x8000]
    return bytes(img), bytes(rom[0x10000:0x20000])


class WinEmitter(Emitter):
    """Window reads: see games/bublbobl/tools/gen.py BBEmitter (the same mechanism, without banked code).

    The translator keeps A' BC' DE' HL' in a3 a0 a1 a2, so no address register is free for the window: accesses to
    it use the marker register `aW` in the lines of an instruction, and emit_ins turns that into
    pea (a0) / move.l g_winbase,a0 ... move.l (sp)+,a0 around the instruction (flag neutral).
    g_winbase = the current bank's copy + $8000 (so the Z80 address - $10000 is the offset)."""

    def __init__(self, *a, window_sites=(), bank_sites=(), video_sites=None, **k):
        super().__init__(*a, **k)
        self.video_sites = video_sites or {}      # pc -> {'fg', 'bg'}: the stores to the character / background RAM set the renderer's dirty flags
        self.window_sites = set(window_sites)
        self.bank_sites = set(bank_sites)       # stores to the bank latch that the `ld (nn),a` hook does not see

    def x_ld_i_a(self, ins):
        self.e("move.b d0,g1_ireg")

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

    def x_ldir(self, ins):
        if ins.pc in self.window_sites:
            return self.block_win(super().x_ldir, ins)
        # a1 / a2 (a2 = IY) are saved around a loop on address registers: 22 cycles a byte instead of 46
        # (kept instead of the engine's: its set-up costs more on 1942's short copies, 24407 against 24254 cycles a tick)
        l = self.new_label()
        self.e("move.w d1,d5")
        self.e("ror.w #8,d5")              # the count (0 = 65536), BC is 0 afterwards
        self.e("movem.l a1-a2,-(sp)")
        self.e("lea (a6,d3.w),a1")
        self.e("lea (a6,d2.w),a2")
        lb = self.new_label()
        done = self.new_label()
        # (a copy of an even number of longs between even addresses that cannot overlap forward is done a long at a time)
        self.e("move.w d3,d7")
        self.e("or.w d2,d7")
        self.e("btst #0,d7")
        self.e("bne.s %s" % lb)
        self.e("move.w d5,d7")
        self.e("and.w #3,d7")
        self.e("bne.s %s" % lb)
        self.e("tst.w d5")
        self.e("beq.s %s" % lb)
        self.e("move.w d2,d7")
        self.e("sub.w d3,d7")
        self.e("cmp.w d5,d7")
        self.e("blo.s %s" % lb)
        self.e("move.w d5,d7")
        self.e("lsr.w #2,d7")
        self.e("subq.w #1,d7")
        lw = self.new_label()
        self.lines.append(lw + ":")
        self.e("move.l (a1)+,(a2)+")
        self.e("dbf d7,%s" % lw)
        self.e("bra.s %s" % done)
        self.lines.append(lb + ":")
        self.e("move.w d5,d7")
        self.e("subq.w #1,d7")
        self.lines.append(l + ":")
        self.e("move.b (a1)+,(a2)+")
        self.e("dbf d7,%s" % l)
        self.lines.append(done + ":")
        self.e("movem.l (sp)+,a1-a2")
        self.e("add.w d5,d3")
        self.e("add.w d5,d2")
        self.e("clr.w d1")                  # (a word: z80x.FAST keeps BC' in the upper word)
        self.flags(0, const_clear=z80x.H | z80x.N)

    def x_ldi(self, ins): self.block_win(super().x_ldi, ins)
    def x_ldd(self, ins): self.block_win(super().x_ldd, ins)
    def x_lddr(self, ins): self.block_win(super().x_lddr, ins)
    def x_cpi(self, ins): self.block_win(super().x_cpi, ins)
    def x_cpir(self, ins): self.block_win(super().x_cpir, ins)

    def read8(self, op, io_read=True):
        pre, ea = super().read8(op, io_read)
        if op[0] == "ind" and self.cur is not None and self.cur.pc in self.window_sites:
            m = re.fullmatch(r"(-?\d+)?\(a6,(d\d)\.w\)", ea)         # (hl) / (de) / (bc) and (ix+d): a6 + disp + the signed index
            if m:
                pre = pre + self.win_check(m.group(2))
                ea = "%s(aW,%s.w)" % (m.group(1) or "", m.group(2))
        return pre, ea

    def emit_ins(self, pc, live_out_override=None, with_label=True):
        n0 = len(self.lines)
        super().emit_ins(pc, live_out_override, with_label)
        if pc in self.bank_sites:
            self.e("bsr g_bank_w")               # (the byte is stored already; the routine reads it from the block)
        for kind in sorted(self.video_sites.get(pc, ())):
            self.e("st %s_dirty" % kind)               # (Scc keeps the flags)
        self.window_wrap(n0)                  # (z80x: a0 = the window, saved only where it holds BC')


def config():
    return z80x.Config(prefix="Z", table="z80_dispatch", token_sym="z80_irq_ret", mode="signed", block=0x10000,
                       iyaddr=IY_ADDR, fshadow=IY_ADDR + 2, io_read_redirect={}, write_hooks=[BANK_HOOK],
                       nmi_token=TOKEN, table_entries=ENTRIES, rst28_tables=False,
                       pv_force=PV_FORCE, bit_s=True,
                       **z80x.FAST)      # (xprof 1100-1500: 24254 cycles a tick, alt_af="upper" alone 24306; the engine's ldir 24407)


def EXTRA_TABLE_ROOTS(img):
    out = []
    for base, n in TABLES:
        out += [img[base + 2 * i] | (img[base + 2 * i + 1] << 8) for i in range(n)]
    return out


def coverage():
    pcs, wread = set(), set()
    require_coverage("1942", ["cover_%d.pkl" % s for s in range(1, 9)])     # seeds 5-8 cover the later stages
    for f in glob.glob(os.path.join(BUILD, "cover_*.pkl")):
        d = pickle.load(open(f, "rb"))
        pcs |= d["pcs"]
        wread |= d["wread"]
    return pcs, wread


def bank_sites():
    """pcs that store to the bank latch C806 other than by `ld (nn),a` (ld (hl),n / ld (nn),hl ...): post-store hooks"""
    img, _ = image()
    out = set()
    for f in glob.glob(os.path.join(BUILD, "cover_*.pkl")):
        for pc, addr in pickle.load(open(f, "rb")).get("io_writes", ()):
            if addr == 0xC806:
                ins = z80dis.decode(img, pc)
                if not (ins.mn == "ld" and ins.ops[0] == ("ind16", 0xC806) and ins.ops[1] == ("r8", "a")):
                    out.add(pc)
    return out


def video_sites():
    """pc -> kinds of the stores to the character ('fg') / background ('bg') RAM the coverage runs saw"""
    out = {}
    for f in glob.glob(os.path.join(BUILD, "cover_*.pkl")):
        for pc, kind in pickle.load(open(f, "rb")).get("video_writes", ()):
            out.setdefault(pc, set()).add(kind)
    return out


def window_sites():
    """the pcs whose indirect accesses get the window guard: the coverage's window-read sites and the audit's
    (logic_test.py --audit), kept in docs/window-sites.json (read from there when no coverage file is present;
    W_GUARD_ALL=1: every pc)"""
    sites_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "window-sites.json")
    if os.environ.get("W_GUARD_ALL"):
        return set(range(0x20000))
    if not glob.glob(os.path.join(BUILD, "cover_*.pkl")) and os.path.exists(sites_file):
        return set(json.load(open(sites_file)))
    pcs, wread = coverage()
    sites = {pc for pc, bank in wread}
    for f in glob.glob(os.path.join(BUILD, "wsites_audit_*.pkl")):      # logic_test.py --audit
        sites |= set(pickle.load(open(f, "rb")))
    with open(sites_file, "w") as f:
        json.dump(sorted(sites), f)
        f.write("\n")
    return sites


def generate(hooks=(), extra_roots=()):
    img, banks = image()
    dyn, _ = coverage()
    wsites = window_sites()
    cfg = config()
    hooks = set(hooks) | {IDLE_HOOK, SCAN_HOOK}
    roots = [0, 0x08, 0x10, 0x18, 0x20, 0x28, 0x30, 0x38] + list(extra_roots)
    code, tables = discover.discover(img, roots + sorted(dyn) + EXTRA_TABLE_ROOTS(img), known=dyn, rst28_tables=False,
                                     hl_tables=False, table_calls=TABLE_CALLS)
    code = {pc: i for pc, i in code.items() if pc < WIN_LO}
    joins = set(roots) | set(hooks)
    for nxt, targets in tables.values():
        joins |= set(targets)
    em = compile_code(code, joins, cfg, hooks, emitter=WinEmitter, ijmp_flags=True, flags_at=hooks,
                      window_sites=wsites, bank_sites=bank_sites(), video_sites=video_sites())
    out = ["; generated by gen.py -- 1942 main CPU, Z80 -> 68000", "\tsection text,code"]
    out += em.lines
    missing = sorted(p for p in em.refs if p not in code)
    out.append("; --- targets that are not code")
    for p in missing:
        out.append("Z%04X:\tmove.w #$%04X,d7\n\tjmp z80_badpc" % (p, p & 0xFFFF))
    # The dispatch table, built here as data (it was filled at the start from a list of (pc, label), 86 KB): a long per
    # Z80 address in byte swapped order (the index is a return address read from the Z80 stack as a word), the entries
    # and the interrupt token at their label, everything else (merged instructions included) at z80_badpc.
    labels = {p: "Z%04X" % p for p in code if p not in em.no_entry}      # (merged with the instruction before: z80_badpc)
    labels[TOKEN] = "z80_irq_ret"
    out += ["\tsection data,data", "\tcnop 0,4", "z80_dispatch_sw:"]
    run = 0
    for i in range(0x10000):
        lab = labels.get(swap16(i))
        if lab is None:
            run += 1
            continue
        if run:
            out.append("\tdcb.l %d,z80_badpc" % run)
            run = 0
        out.append("\tdc.l %s" % lab)
    if run:
        out.append("\tdcb.l %d,z80_badpc" % run)
    rep = {"instructions": len(code), "unsupported": em.unsupported, "window_sites": len(wsites),
           "missing_targets": ["%04X" % p for p in missing], "bank_size": len(banks)}
    return "\n".join(out) + "\n", rep, em, code


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", default=os.path.join(BUILD, "code_1942.s"))
    a = ap.parse_args()
    text, rep, em, code = generate()
    os.makedirs(os.path.dirname(a.o), exist_ok=True)
    open(a.o, "w").write(text)
    print("instructions:", rep["instructions"], " window sites:", rep["window_sites"], " lines:", len(text.splitlines()))
    print("unsupported:", len(rep["unsupported"]))
    for u in rep["unsupported"][:60]:
        print("   %04X %-24s %s" % u)
    print("missing targets:", rep["missing_targets"])
