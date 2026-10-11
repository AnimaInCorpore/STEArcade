"""Generate the translated Galaga programs: build/galaga_code.s (+ report).

    python gen.py [-o file]

Three programs with their own labels and dispatch tables (galaga.s is the machine):
  CPU1 (main, 16 KB): labels Z, table g1_dispatch, mode "signed" over a 64 KB block
       (a6 = its ROM, the shared RAM lies 32 KB below it); hooks: the 06XX writes
  CPU2 (sub, 4 KB):   labels Y, table g2_dispatch, mode "long" (a6 = its ROM, the shared
       RAM at a6 + $8000 = g_ram)
  CPU3 (sound, 4 KB): labels X, table g3_dispatch, mode "long" over its own block (a6 = g3_block: its ROM, its I/O
       cells, its RAM g3_ram at + $8000); its boot is done natively, its NMI handler runs twice a frame with the
       shared page $9A00-$9AFF (and $9211) copied in and out (galaga.s g_sound)
Coverage from ref/cover.py (galaga_cover_*.pkl: executed pcs per CPU, the instructions that write the video RAM: each
marks the blocks of 32 bytes it wrote, so the renderer compares only those with its copy, Emitter / scan_cells).
"""
import argparse, glob, os, pickle, sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import z80x
from translate import generate_program
from paths import build_dir, require_coverage
BUILD = str(build_dir("galaga"))
from machine import load, skip_ram_test

ROMS = [("gg1_1b.3p", "gg1_2b.3m", "gg1_3.2m", "gg1_4b.2l"), ("gg1_5b.3f",), ("gg1_7b.2c",)]
IY = [0x9FF0, 0x9FF4, 0x9FF8]          # unused RAM words of the map for IY and F' per CPU
TOKEN = 0x4001
ENTRIES = 0x4002


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


ROOTS = [[0, 0x38, 0x66], [0, 0x38], [0, 0x66]]
# the boot handshake's spin loops and CPU2's idle loop: the runtime's scheduler (z80_hook); $134C: a task of the main
# CPU's IRQ handler waits for the sub CPU's count of the attacking enemies ($9287) to become 0 (g_spin_wait)
YIELDS = [{0x3589, 0x359C, 0x134C}, {0x057F, 0x0596, 0x05B1}, set()]


BLOCK_OPS = ("ldir", "lddr", "ldi", "ldd")


class Emitter(z80x.Emitter):
    """z80x.Emitter + after the instructions that write the video RAM (8000-87FF), the blocks of 32 bytes they wrote
    marked in vblocks (64 bytes: the renderer compares only those, scan_cells).  Stores mark the block of their address,
    block instructions the blocks from DE before (vblock_de) to DE after (vblock_range); others (push / call with SP in
    the video RAM: a clear) set vblock_all.  The CCR is kept (the flag analysis may keep flags in it)."""
    def __init__(self, *a, vwriters=(), **k):
        super().__init__(*a, **k)
        self.vwriters = set(vwriters)

    def emit_ins(self, pc, *a, **k):
        super().emit_ins(pc, *a, **k)
        if pc not in self.vwriters:
            return
        ins = self.code[pc]
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

    def vblock_mark(self, dst):
        if dst[0] == "ind16":                       # (ld (nn),r / rr: both bytes' blocks)
            for a in sorted({(dst[1] >> 5) & 63, ((dst[1] + 1) >> 5) & 63}):
                self.e("st vblocks+%d" % a)        # (Scc leaves the CCR alone)
            return
        if dst[0] != "ind" or dst[1] not in ("hl", "de", "bc", "ix", "iy"):
            raise z80x.Unsupported("video RAM writer %r" % (dst,))
        if dst[1] == "iy" and not self.iyr:
            raise z80x.Unsupported("video RAM writer through IY in memory")
        assert "a0" in self.free_aregs()
        self.e("move sr,d5")
        self.e("move.w %s,d7" % (self.iyr if dst[1] == "iy" else z80x.REG16[dst[1]]))
        if dst[1] == "bc":
            self.e("ror.w #8,d7")                  # (BC is kept byte swapped)
        if len(dst) > 2 and dst[2]:
            self.e("add.w #%d,d7" % dst[2])
        self.e("lsr.w #5,d7")
        self.e("and.w #63,d7")                     # (8000 / 32 = $400: the block)
        self.e("lea vblocks,a0")
        self.e("st (a0,d7.w)")
        self.e("move d5,ccr")


def vwriters():
    """per CPU: the instructions the coverage saw writing the video RAM (8000-87FF)"""
    out = [set(), set(), set()]
    for f in glob.glob(os.path.join(BUILD, "galaga_cover_*.pkl")):
        d = pickle.load(open(f, "rb"))
        if "vwrites" not in d:
            sys.exit("gen.py: %s has no video RAM writers (an old coverage run): python port.py cover galaga" % f)
        for n in range(3):
            out[n] |= d["vwrites"][n]
    return out


def coverage():
    require_coverage("galaga", ["galaga_cover_%d.pkl" % s for s in (1, 2, 3)])
    dyn = [set(), set(), set()]
    for f in glob.glob(os.path.join(BUILD, "galaga_cover_*.pkl")):
        d = pickle.load(open(f, "rb"))
        for n in range(3):
            dyn[n] |= d["pcs"][n]
    return dyn


def generate(hooks=((), (), ()), skip_tests=True):
    roms = [b"".join(load(f) for f in files) for files in ROMS]
    if skip_tests:
        roms[0] = skip_ram_test(roms[0])
    dyn = coverage()
    vw = vwriters()
    lines = ["; generated by gen.py -- Galaga CPU1, CPU2, CPU3, Z80 -> 68000", "\tsection text,code"]
    tables = ["\tsection data,data", "\tcnop 0,4", "TABLE_ENTRIES = %d" % ENTRIES]
    reports = []
    ems = []
    for n, cfg in enumerate(configs()):
        code_lines, table, rep, em = generate_program(roms[n], ROOTS[n], dyn[n] & set(range(len(roms[n]))), cfg,
                                                      set(hooks[n]) | YIELDS[n], emitter=Emitter, vwriters=vw[n])
        lines.append("; ---------------- CPU%d" % (n + 1))
        lines += code_lines
        tables += table
        reports.append(rep)
        ems.append(em)
    return "\n".join(lines + tables) + "\n", reports, ems


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", default=os.path.join(BUILD, "galaga_code.s"))
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
