"""Defender's main program (MC6809E: the fixed ROM $D000-$FFFF and the 4 KB banks of the window $C000-$CFFF)
translated to 68000 code (engine/m6809x.py).

    from gen import generate; report = generate()   -> build/defender/code_main.s, tables_main.s, main_info.s

Virtual pages (8 KB, ref/cover.py): 6 the fixed ROM $D000-$DFFF (v = pc; its lower half, the window, holds no code
of page 6), 7 the fixed ROM $E000-$FFFF, 8 + view the code of the window's view 1-7 (v = page << 13 | pc & $1FFF:
the bank's 4 KB in the lower half; the upper half is the fixed ROM again, never translated there).

Slot 6 ($C000-$DFFF) is two things at once: the window below $D000 (the view: I/O, a bank, nothing) and the fixed
ROM above.  engine/m6809x.py keeps one page per slot, so here (Emitter / branch_targets patched for this program):
  * a direct target in $D000-$DFFF is page 6, whatever page the jump is in; a page check of page 6 always passes;
  * a direct target in $C000-$CFFF from window code is that code's own bank (no code changed the view while running
    in the window: ref/cover.py view_in_window = 0); from elsewhere the banks the coverage saw it go to, each checked
    against the context's page of slot 6 (8 + view), else the dispatcher;
  * the runtime's dispatcher sends $D000-$DFFF to page 6's table, the rest through the context's slot tables.
The 68000 side (src/defender.s): the 6809's memory is one 64 KB block df_mem (RAM and video RAM $0000-$BFFF, the
fixed ROM $D000-$FFFF): every VB but slot 6's is df_mem, a4 = df_mem, a3 = df_mem + $A000 (DP $A0 and the stack,
slot 5), a context per view (ctx_views, a6: its slot 6 PID is 8 + view, its slot 6 page an 8 KB copy of the view's
bank and the fixed ROM $D000-$DFFF: view_pages; view 0's is df_mem + $C000); the accesses the coverage lists as I/O sites go
through main_io_r / main_io_w: $C000-$CFFF (the I/O in view 0, the bank's bytes in 1-7) and the stores to
$D000-$DFFF (the view select).  The IRQ vector points into RAM ($A08F: JMP $DF17): the IRQ root is $DF17.
"""
import collections
import os
import pickle
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
import m6809x
from machine import load, PROGRAM, BANKED
from paths import build_dir, require_coverage

RESET, IRQ = 0xD738, 0xDF17         # (RESET: the game's start after the power-on tests, machine.DefenderPort.START)
POWER_ON = 0xF61F
IDLE = 0xE7C3                       # LDA <$5D; BEQ $E7C3: the foreground waits for the IRQ's frame count
SEEDS = [int(x) for x in os.environ.get("DF_SEEDS", "").split(",") if x] or range(1, 19)
NATIVES = {IDLE: "df_idle",
           0x1E0C2: "df_terrain",         # bank 7's $C0C2-$C127: the terrain's 152 columns (src/defender.s)
           0xF5DD: "df_cls",              # $F5D1's loop: the video RAM and $9800-$9BFF cleared with PSHU
           0xF5FF: "df_clsb",             # $F5F1's loop: the same below the scanner (y $2A-$FF of every column)
           # the sprite copiers' rectangles (src/defender.s spr_rect): their unrolled PULS / PSHU sequences
           0xD149: "nat_D149", 0xD159: "nat_D159", 0xD1A3: "nat_D1A3", 0xD131: "nat_D131", 0xD17D: "nat_D17D",
           0xD189: "nat_D189", 0xD29E: "nat_D29E", 0xD2AE: "nat_D2AE", 0xD2ED: "nat_D2ED", 0xD2F9: "nat_D2F9",
           0xD22F: "nat_D22F", 0xD26C: "nat_D26C",
           0x12CF0: "df_scan",            # bank 1's $CCF0-$CD0A: the scanner's terrain (64 columns)
           0x1E658: "df_part",            # bank 7's $C658-$C696: the particles (explosions)
           0xE621: "df_lzr", 0xE68D: "df_lzl",   # a laser's line erased (right / left)
           0xE856: "df_task",             # $E856: the task list walk
           0xF53C: "df_icopy"}            # $F53C-$F54F: $F522's image copy (even heights)
VIDEO_SITES = set()                 # (load_cover)
WINDOW_READS = set()                # (load_cover: the sites that read $C000-$CFFF)
NVIEWS = 8                          # (views 8-15 are empty: no code, read 0)
SLOT6 = 6


def rom_image():
    """the 64 KB as the 6809 sees it with view 0 ($D000-$FFFF the fixed ROM) and the 7 banks of the window (4 KB each).
    $CC00-$CFFF holds bank 2's bytes there (view 2's $CC00-$CFFF): the sprite and block copiers ($D149-$D2D6) point S
    at images there and read them with PULS, which the translation does in df_mem; only view 2 does that (play of seeds
    1, 5, 7: 1.2 million reads, all in view 2).  In view 0 these addresses are the PIAs, reached through main_io_r."""
    mem = bytearray(0x10000)
    for n, a in PROGRAM:
        d = load(n)
        mem[a:a + len(d)] = d
    banks = bytearray(0x7000)
    for n, a in BANKED:
        d = load(n)
        banks[a:a + len(d)] = d
    mem[0xCC00:0xD000] = banks[0x1C00:0x2000]
    return mem, bytes(banks)


def page_bytes_fn():
    mem, banks = rom_image()

    def page_bytes(p):
        if p in (6, 7):
            return bytes(mem[p << 13:(p + 1) << 13])
        if p >= 9:
            b = p - 9
            return banks[b * 0x1000:(b + 1) * 0x1000] + bytes(mem[0xD000:0xE000])
        return bytes(0x2000)
    return page_bytes


def page_addr(p):
    return "df_mem+$%04X" % ((p << 13) if p < 8 else 0xC000)


def view_ctx(page, slot):
    """m6809x Program.slot_ctx: context k (ctx_views + k * CTX_STRIDE) holds view k's page in slot 6 for good, and
    main_io_w's view select makes a6 that context"""
    if slot == SLOT6 and page >= 8:
        return "ctx_views+%d" % ((page - 8) * 256)
    return None


# ---- slot 6: the window and the fixed ROM in one slot -------------------------------------------------------------
_branch_targets = m6809x.branch_targets


def branch_targets(prog, v, ins):
    t = ins.target
    if 0xD000 <= t < 0xE000:
        return [t]
    if 0xC000 <= t < 0xD000:
        if v >> 13 >= 8:
            return [(v & ~0x1FFF) | (t & 0x1FFF)]
        return sorted(x for x in prog.targets.get(v, ()) if x >> 13 >= 8 and x & 0x1FFF == t & 0x1FFF)
    return _branch_targets(prog, v, ins)


m6809x.branch_targets = branch_targets
_page_cmp = m6809x.Emitter.page_cmp
_jump_to = m6809x.Emitter.jump_to


def page_cmp(self, page, slot):
    if page == 6:
        self.e("cmp.b d7,d7")                   # (Z: the fixed ROM is always there)
        return
    _page_cmp(self, page, slot)


def jump_to(self, v, target, tg, saved=False, live=True):
    """a jump into $D000-$DFFF: a branch (page 6 is always there); a jump from page 6 into the window: the original
    treats a target in its own slot as its own page"""
    if 0xD000 <= target < 0xE000 and tg == [target]:
        if saved:
            self.e("move.w d5,ccr")
        self.e("bra %s" % self.lab(target))
        return
    if not (v >> 13 == 6 and 0xC000 <= target < 0xD000):
        return _jump_to(self, v, target, tg, saved, live)
    if not saved and tg and live:
        self.e("move.w sr,d5")
        saved = True
    for t in tg:
        skip = self.new_label()
        _page_cmp(self, t >> 13, SLOT6)
        self.e("bne.s %s" % skip)
        if saved:
            self.e("move.w d5,ccr")
        self.e("bra %s" % self.lab(t))
        self.lines.append(skip + ":")
    self.stats["window dispatch"] += 1
    self.e("move.w #$%04X,d7" % target)
    if saved:
        self.e("move.w d5,ccr")
    self.dispatch_jump(live)


m6809x.Emitter.page_cmp = page_cmp
m6809x.Emitter.jump_to = jump_to


# ---- the video RAM's stores inline --------------------------------------------------------------------------------
# At the sites that only ever stored into the video RAM (VIDEO_SITES) the byte goes into df_mem and, when it changed,
# its two pixels onto the screen right there (src/defender.s vput's work: vtab, vm_tab, vv_tab), no call; an address at
# or above $9800 calls main_io_w.  d5 the byte, d7.l the address; d5-d7, a0, a1 are the translation's scratch.
_store8 = m6809x.Emitter.store8
_store16 = m6809x.Emitter.store16


def video_put(em):
    """the byte in d5 to the video RAM address in d7.l (upper word 0).  The screen byte goes to a0 with vtab's top byte
    (the position * 4) in it: the 68000's 24-bit bus ignores it; the four masks are the longs before vtab."""
    slow, done = em.new_label(), em.new_label()
    e = em.e
    e("cmp.w #$9800,d7")
    e("bhs.s %s" % slow)
    e("cmp.b (a4,d7.l),d5")
    e("beq.s %s" % done)                    # (the byte is there already)
    e("move.b d5,(a4,d7.l)")
    e("add.l d7,d7")
    e("add.l d7,d7")
    e("lea vtab,a1")
    e("move.l (a1,d7.l),d6")                # the screen byte | position * 4 << 24, or 0
    e("beq.s %s" % done)
    e("move.l d6,a0")
    e("move.b (a1,d7.l),d7")
    e("and.w #$C,d7")                       # position * 4
    e("and.w #$FF,d5")
    e("lsl.w #4,d5")
    e("or.w d7,d5")                         # byte * 16 + position * 4
    e("movep.l 0(a0),d6")
    e("and.l -16(a1,d7.w),d6")              # (vtab_vm: the other pixels' bits)
    e("lea vv_tab,a1")
    e("or.l (a1,d5.w),d6")
    e("movep.l d6,0(a0)")
    e("bra.s %s" % done)
    em.lines.append(slow + ":")
    e("bsr main_io_w")
    em.lines.append(done + ":")
    em._a0 = None


def video_addr(em, v, ins, off=0):
    a = em.static_addr(ins)
    if a is not None:
        em.e("moveq #0,d7")
        em.e("move.w #$%04X,d7" % ((a + off) & 0xFFFF))
    else:
        em.ea_to_d7(v, ins)
        if off:
            em.e("addq.w #%d,d7" % off)


def store8(self, v, ins, src, off=0):
    if v in VIDEO_SITES and self.io_site(v, ins) and src in ("d0", "d1", "d2", "d3", "d4"):
        self.stats["video store inline"] += 1
        video_addr(self, v, ins, off)
        self.e("move.b %s,d5" % src)
        video_put(self)
        self.e("tst.b %s" % src)
        return
    return _store8(self, v, ins, src, off)


def store16(self, v, ins, src):
    if v in VIDEO_SITES and self.io_site(v, ins) and src in ("d0", "d1", "d2", "d3", "d4"):
        self.stats["video store inline"] += 2
        video_addr(self, v, ins)
        self.e("move.w d7,-(sp)")
        self.e("move.w %s,d5" % src)
        self.e("lsr.w #8,d5")
        video_put(self)
        self.e("moveq #0,d7")
        self.e("move.w (sp)+,d7")
        self.e("addq.w #1,d7")
        self.e("move.b %s,d5" % src)
        video_put(self)
        self.e("tst.w %s" % src)
        return
    return _store16(self, v, ins, src)


m6809x.Emitter.store8 = store8
m6809x.Emitter.store16 = store16


def load_cover():
    require_coverage("defender", ["cover%d.pkl" % s for s in SEEDS])
    exec_ = collections.Counter()
    acc = collections.defaultdict(set)
    tg = collections.defaultdict(set)
    wraps, io = set(), set()
    returns = collections.Counter()
    for s in SEEDS:
        d = pickle.loads((build_dir("defender") / ("cover%d.pkl" % s)).read_bytes())
        exec_.update(d["exec"])
        for v, x in d["acc"].items():
            acc[v] |= x
        for v, x in d["targets"].items():
            tg[v] |= x
        wraps |= d["wraps"]
        # the window and the I/O, and the stores into the video RAM (main_io_w: the screen too; its reads are memory)
        io |= {pc for pc, a, rw in d["io"] if a >= 0xC000 or (a < 0x9800 and rw == 'w')}
        returns.update(d.get("returns", {}))
    for v in [v for v in exec_ if v < 0xC000]:
        del exec_[v]                                                # ($A08F: the IRQ vector's JMP $DF17 in RAM)
    # the sites whose stores the coverage saw only in the video RAM: df_vstore (no I/O decoding; other addresses go on
    # to main_io_w)
    wr = collections.defaultdict(set)
    for s in SEEDS:
        d = pickle.loads((build_dir("defender") / ("cover%d.pkl" % s)).read_bytes())
        for pc, a, rw in d["io"]:
            if rw == 'w':
                wr[pc].add(a < 0x9800)
    global VIDEO_SITES, WINDOW_READS
    VIDEO_SITES = {pc for pc, k in wr.items() if k == {True}}
    WINDOW_READS = set()
    kinds, views = collections.defaultdict(set), collections.defaultdict(set)
    for s in SEEDS:
        d = pickle.loads((build_dir("defender") / ("cover%d.pkl" % s)).read_bytes())
        WINDOW_READS |= {pc for pc, a, rw in d["io"] if rw == 'r' and 0xC000 <= a < 0xD000}
        for pc, a, rw in d["io"]:
            kinds[pc].add((rw, 0xC000 <= a < 0xD000))
        for (pc, view), n in d["views"].items():
            views[pc].add(view)
    # the sites that only read the window and only in a bank's view (1-7): memory reads through slot 6's page (the
    # context's: the view's bank), not main_io_r; a pull through S stays (S is a flat pointer, a5 = df_mem + S)
    pb = page_bytes_fn()
    BANK_READS = {pc for pc, k in kinds.items() if k == {('r', True)} and 0 not in views[pc]
                  and pb(pc >> 13)[pc & 0x1FFF] not in (0x35, 0x37)}       # (PULS / PULU: the stack ops' own path)
    io -= BANK_READS
    return exec_, acc, tg, wraps, io, returns


def program(cover):
    exec_, acc, tg, wraps, io, returns = cover
    page_bytes = page_bytes_fn()
    slot_of = {}
    for v in exec_:
        p = v >> 13
        slot_of[p] = SLOT6 if p >= 8 else p
    slot_of.setdefault(6, 6)
    # one base for every slot but 6: an indexed access uses a4 (slot 0) unless the coverage saw it in the window, where
    # the view's page is the context's slot 6 (its bank, then the fixed ROM: a U-based PULU reads bank 1's lists there)
    flat = {v: {(rw, 6, 6, odd) if sl == 6 else (rw, 0, 0, odd) for rw, sl, pg, odd in s} for v, s in acc.items()}
    prog = m6809x.Program("main", "M", page_bytes, slot_of, roots=[RESET, POWER_ON, IRQ] + sorted(NATIVES), exec_cover=set(exec_),
                          acc_cover=flat, targets=tg, page_addr=page_addr, io_sites=io, wrap_sites=wraps, dp=0xA0,
                          a3_slot=5, a4_slot=0, natives=dict(NATIVES), pid_checks=True)
    prog.io_w_alt = {v: 'df_vstore' for v in VIDEO_SITES if v in io}
    prog.video_push = (0, 0x9800)               # (PSHU into the video RAM: main_vlist puts the bytes on the screen)
    prog.indirect_io = WINDOW_READS & io                     # (JSR [A,Y] with the table in the window's data: through main_io_r)
    prog.flat_ptr = ("a4", {6})                 # (every slot's VB but 6's is df_mem: a pointer outside the window at a4)
    prog.dp_data = True                         # (DP is a data byte in the block copies and fills: PSHU / PULS DP)
    prog.a3_pb = True                           # (DP $A0 and the stack in slot 5: a3 = df_mem + $A000)
    prog.fixed_slots = (0, 1, 2, 3, 4, 5, 7)
    prog.slot_ctx = view_ctx
    prog.fast_forms = 'DF_NO_FAST' not in os.environ
    prog.ret_weights = dict(returns) or dict(exec_)
    prog.call_summaries = True
    return prog


def dispatch_tables(prog, code):
    """per code page a table of 8192 longs: the label of each 6809 address, main_badpc where there is none (a long a
    pc: 192 KB for the 6 pages, the dispatcher one move.l, no base); the page list (32 longs)"""
    lines = ["	section data,data", "	even", "main_page_tables:"]
    for p in range(32):
        lines.append("	dc.l %s" % ("main_pt_%02X" % p if p in prog.slot_of else "main_bad_table"))
    for p in sorted(prog.slot_of):
        lines.append("main_pt_%02X:" % p)
        row = []
        for off in range(0x2000):
            v = (p << 13) | off
            row.append(prog.label(v) if v in code else "main_badpc")
            if len(row) == 8:
                lines.append("	dc.l " + ",".join(row))
                row = []
    return lines


def generate():
    build = build_dir("defender")
    prog = program(load_cover())
    lines, rep, em, code = m6809x.translate(prog)
    seen = [u for u in rep["unsupported"] if int(u.split()[0], 16) in prog.exec_cover]
    if seen:
        raise RuntimeError("observed instructions cannot be translated: %s" % seen)
    bad = sorted(hex(v) for v in code if v >> 13 >= 8 and v & 0x1FFF >= 0x1000)
    if bad:
        raise RuntimeError("fixed ROM code translated in a window page: %s" % bad[:10])
    head = ["; generated by games/defender/tools/gen.py (engine/m6809x.py): the main CPU", "\tsection text,code"]
    (build / "code_main.s").write_text("\n".join(head + lines) + "\n")
    (build / "tables_main.s").write_text("\n".join(dispatch_tables(prog, code)) + "\n")
    info = ["MAIN_RESET equ %s" % prog.label(RESET), "MAIN_IRQ equ %s" % prog.label(IRQ),
            "MAIN_IDLE_T equ %s_t" % prog.label(IDLE)]
    (build / "main_info.s").write_text("\n".join(info) + "\n")
    rep["pages"] = sorted("%X:%d" % (p, s) for p, s in prog.slot_of.items())
    return rep


if __name__ == "__main__":
    r = generate()
    print("instructions", r["instructions"], "unsupported", len(r["unsupported"]), "missing", len(r["missing"]),
          r["stats"], r["pages"])
    for u in r["unsupported"][:20]:
        print("   ", u)
    print("missing", r["missing"][:30])
