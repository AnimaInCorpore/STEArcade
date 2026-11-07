"""Generate the translated Super Xevious programs: build/xevious/xevious_code.s (+ report).

    python gen.py [-o file]

Three programs with their own labels and dispatch tables (xevious.s is the machine):
  CPU1 (main, 16 KB): labels Z, table g1_dispatch, mode "signed" over a 64 KB block (a6 = its ROM, the shared RAM
       $8000-$FFFF lies 32 KB below it)
  CPU2 (sub, 8 KB):   labels Y, table g2_dispatch, mode "long" (a6 = its ROM, the shared RAM at a6 + $8000 = g_ram)
  CPU3 (sound, 4 KB): labels X, table g3_dispatch, mode "long" over its own block (a6 = g3_block: its ROM, its I/O
       cells, its RAM g3_ram at + $8000); the shared bytes it uses are copied in and out around its NMI handlers
The work RAM $7800-$7FFF is below $8000: CPU1 sees it in its own half of the block, CPU2 in its half; the part both use
($7900-$7FFF) is copied between the halves at every change of CPU (xevious.s sync_share).
Hooks (the runtime's z80_hook, d7 = the pc): the idle loops and boot spin loops (the frame's stops), CPU2's background
ROM read ($04DA: the BB0 / BB1 bytes of MAME's xevious_bb_r from the BS latches).  After the scroll latch writes
($D000-$D07F, static or through hl) `bsr g_vhlatch` (d7 = the address, d0 = the value); after the instructions that
write the tile RAMs ($B000-$CFFF) the blocks of 32 bytes they wrote are marked in vblocks (the renderer compares only
those): stores mark the block of their address, block instructions the blocks from DE before to DE after.
Coverage from ref/cover.py (xevious_cover_*.pkl: executed pcs per CPU, the instructions that write the tile RAM and the
scroll latch).
"""
import argparse, glob, os, pickle, sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import z80x
from translate import generate_program
from paths import build_dir, require_coverage
BUILD = str(build_dir("xevious"))
from machine import load, skip_ram_test, ste_rom

ROMS = [("cpu_3p.rom", "cpu_3m.rom", "xv3_3.2m", "xv3_4.2l"), ("xv3_5.3f", "xv3_6.3j"), ("xvi_7.2c",)]
IY = [0xAFF0, 0xAFF4, 0xAFF8]          # unused RAM words of the map for IY and F' per CPU
TOKEN = 0x4001
ENTRIES = 0x4002
SEEDS = (1, 2, 3, 4, 5, 6, 7, 8, 9)


def configs():
    hooks1 = [(0x7100, 0x7100, "g_ctrl06", None), (0x7000, 0x70FF, "g_data06", None)]
    return [
        z80x.Config(prefix="Z", table="g1_dispatch", token_sym="g1_ret", mode="signed", block=0x10000,
                    iyaddr=IY[0], fshadow=IY[0] + 2, io_read_redirect={}, write_hooks=hooks1,
                    nmi_token=TOKEN, table_entries=ENTRIES, rst28_tables=False, iff_sym="g1_iff", hl_tables=True,
                    **z80x.FAST),
        z80x.Config(prefix="Y", table="g2_dispatch", token_sym="g2_ret", mode="long", block=0x10000,
                    ram_sym="g_ram", iyaddr=IY[1], fshadow=IY[1] + 2, io_read_redirect={}, write_hooks=[],
                    nmi_token=TOKEN, table_entries=ENTRIES, rst28_tables=False, iff_sym="g2_iff", hl_tables=True,
                    **z80x.FAST_LONG),
        z80x.Config(prefix="X", table="g3_dispatch", token_sym="g3_ret", mode="long", block=0x10000,
                    ram_sym="g3_ram", iyaddr=IY[2], fshadow=IY[2] + 2, io_read_redirect={}, write_hooks=[],
                    nmi_token=TOKEN, table_entries=ENTRIES, rst28_tables=False, **z80x.FAST_LONG),
    ]


LDI06 = [0x0067, None, None]      # the main CPU's NMI handler (the 06XX transfers): its ldi
ROOTS = [[0, 0x38, 0x66], [0, 0x38, 0x66], [0, 0x66]]
# the frame's stops: CPU1's idle loop ($044C waits for the flag $8000 its IRQ handler sets) and the boot's spin loops
# ($02AD / $0310 wait for the 06XX's first read, $8018 bit 7); CPU2's idle loop ($0356, flag $8002) and its background
# ROM read ($04DA); CPU3's idle loop ($0098)
YIELDS = [{0x044C, 0x02AD, 0x0310}, {0x0356, 0x04DA}, {0x0098}]


BLOCK_OPS = ("ldir", "lddr", "ldi", "ldd")


class Emitter(z80x.Emitter):
    """z80x.Emitter + after the instructions that write the tile RAMs (B000-CFFF), the blocks of 32 bytes they wrote
    marked in vblocks (256 bytes: the renderer compares only those, scan_cells), and after the scroll latch writes
    (D000-D07F) a call of g_vhlatch.  The CCR is kept (the flag analysis may keep flags in it)."""
    def __init__(self, *a, vwriters=(), lwriters=(), ldi06=None, **k):
        super().__init__(*a, **k)
        self.vwriters = set(vwriters)
        self.lwriters = set(lwriters)
        self.ldi06 = ldi06

    def emit_ins(self, pc, *a, **k):
        super().emit_ins(pc, *a, **k)
        ins = self.code[pc]
        if pc == self.ldi06:                                # the 06XX handler's ldi: the byte it wrote to the port
            self.e("move sr,-(sp)")
            self.e("move.w d2,d7")
            self.e("subq.w #1,d7")
            self.e("move.b (a6,d7.w),n06_last")
            self.e("move (sp)+,ccr")
        if ins.mn == "ld" and ins.ops[0][0] == "ind16" and ins.ops[1] == ("r8", "a"):
            a = ins.ops[0][1]
            if 0x6820 <= a <= 0x6827:                      # the misc latch: any CPU writes it, the runtime keeps the state
                self.latch_call(ins, "g_latchw")
            elif 0xD000 <= a <= 0xD07F:
                self.latch_call(ins, "g_vhlatch")
        elif pc in self.lwriters:                           # (ld (hl),a to the scroll latch: the coverage's sites)
            self.latch_call(ins, "g_vhlatch")
        if pc not in self.vwriters:
            return
        if ins.mn in BLOCK_OPS:
            self.e("bsr vblock_range")
        elif ins.mn == "ld":
            self.vblock_mark(ins.ops[0])
        else:
            self.e("st vblock_all")

    def block(self, fn, ins):
        if ins.pc in self.vwriters:
            self.e("move sr,-(sp)")
            self.e("move.w d2,vblock_de")         # (DE before)
            self.e("move (sp)+,ccr")
        fn(ins)

    def x_ldir(self, ins): self.block(super().x_ldir, ins)
    def x_lddr(self, ins): self.block(super().x_lddr, ins)
    def x_ldi(self, ins): self.block(super().x_ldi, ins)
    def x_ldd(self, ins): self.block(super().x_ldd, ins)

    def latch_call(self, ins, handler):
        dst = ins.ops[0]
        self.e("move sr,-(sp)")
        if dst[0] == "ind16":
            self.e("move.w #%d,d7" % dst[1])
        elif dst[0] == "ind" and dst[1] == "hl":
            self.e("move.w d3,d7")
        else:
            raise z80x.Unsupported("scroll latch writer %r" % (dst,))
        self.e("bsr %s" % handler)
        self.e("move (sp)+,ccr")

    def vblock_mark(self, dst):
        if dst[0] == "ind16":                       # (ld (nn),r / rr: both bytes' blocks)
            for a in sorted({(dst[1] >> 5) & 255, ((dst[1] + 1) >> 5) & 255}):
                self.e("st vblocks+%d" % a)        # (Scc leaves the CCR alone)
            return
        if dst[0] != "ind" or dst[1] not in ("hl", "de", "bc", "ix", "iy"):
            raise z80x.Unsupported("tile RAM writer %r" % (dst,))
        if dst[1] == "iy" and not self.iyr:
            raise z80x.Unsupported("tile RAM writer through IY in memory")
        assert "a0" in self.free_aregs()
        self.e("move sr,d5")
        self.e("move.w %s,d7" % (self.iyr if dst[1] == "iy" else z80x.REG16[dst[1]]))
        if dst[1] == "bc":
            self.e("ror.w #8,d7")                  # (BC is kept byte swapped)
        if len(dst) > 2 and dst[2]:
            self.e("add.w #%d,d7" % dst[2])
        self.e("lsr.w #5,d7")
        self.e("and.w #255,d7")                    # (B000 / 32 = $580: the block mod 256)
        self.e("lea vblocks,a0")
        self.e("st (a0,d7.w)")
        self.e("move d5,ccr")


def coverage_files():
    return sorted(glob.glob(os.path.join(BUILD, "xevious_cover_*.pkl")))


def sites():
    """per CPU: the instructions the coverage saw writing the tile RAMs and the scroll latch"""
    v, l = [set(), set(), set()], [set(), set(), set()]
    for f in coverage_files():
        d = pickle.load(open(f, "rb"))
        for n in range(3):
            v[n] |= d["vwrites"][n]
            l[n] |= d["sites"]["latch"][n]
    return v, l


def coverage():
    require_coverage("xevious", ["xevious_cover_%d.pkl" % s for s in (1,)])
    dyn = [set(), set(), set()]
    for f in coverage_files():
        d = pickle.load(open(f, "rb"))
        for n in range(3):
            dyn[n] |= d["pcs"][n]
    return dyn


def generate(hooks=((), (), ()), skip_tests=True, invincible=False):
    roms = [b"".join(load(f) for f in files) for files in ROMS]
    roms[0] = ste_rom(roms[0], skip_tests, invincible)
    dyn = coverage()
    vw, lw = sites()
    lines = ["; generated by gen.py -- Super Xevious CPU1, CPU2, CPU3, Z80 -> 68000", "\tsection text,code"]
    tables = ["\tsection data,data", "\tcnop 0,4", "TABLE_ENTRIES = %d" % ENTRIES]
    reports = []
    ems = []
    for n, cfg in enumerate(configs()):
        code_lines, table, rep, em = generate_program(roms[n], ROOTS[n], dyn[n] & set(range(len(roms[n]))), cfg,
                                                      set(hooks[n]) | YIELDS[n], emitter=Emitter, vwriters=vw[n],
                                                      lwriters=lw[n], ldi06=LDI06[n])
        lines.append("; ---------------- CPU%d" % (n + 1))
        lines += code_lines
        tables += table
        reports.append(rep)
        ems.append(em)
    return "\n".join(lines + tables) + "\n", reports, ems


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", default=os.path.join(BUILD, "xevious_code.s"))
    a = ap.parse_args()
    text, reps, ems = generate()
    os.makedirs(os.path.dirname(a.o), exist_ok=True)
    open(a.o, "w").write(text)
    for n, rep in enumerate(reps):
        print("CPU%d: instructions %d, unsupported %d, missing targets %s" % (
            n + 1, rep["instructions"], len(rep["unsupported"]), rep["missing_targets"][:8]))
        for u in rep["unsupported"][:30]:
            print("   %04X %-24s %s" % u)
    print("lines:", len(text.splitlines()))
