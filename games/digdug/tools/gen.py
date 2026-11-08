"""Generate the translated Dig Dug programs: build/digdug/digdug_code.s (+ report).

    python gen.py [-o file]

Three programs with their own labels and dispatch tables (digdug.s is the machine):
  CPU1 (main, 16 KB): labels Z, table g1_dispatch, mode "signed" over a 64 KB block
       (a6 = its ROM, the shared RAM lies 32 KB below it); hooks: the 06XX writes, the sub CPU's IRQ enable
  CPU2 (sub, 8 KB):   labels Y, table g2_dispatch, mode "long" (a6 = its ROM, the shared
       RAM at a6 + $8000 = g_ram); hooks: the EAROM control; its foreground function $1DDC (the EAROM commands) is a root
  CPU3 (sound, 4 KB): labels X, table g3_dispatch, mode "long" over its own block (a6 = g3_block: its ROM, its I/O
       cells, its RAM g3_ram at + $8000); its boot is done natively, its NMI handler runs twice a frame with the
       shared areas copied in and out (digdug.s g_sound_frame)
All three run the patched ROMs of machine.patch_tests (the boot self-tests skipped).
Coverage from ref/cover.py (digdug_cover_*.pkl: executed pcs per CPU, the instructions that write the EAROM window).
"""
import argparse, glob, os, pickle, sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import z80x
from translate import generate_program
from paths import build_dir, require_coverage
BUILD = str(build_dir("digdug"))
from machine import load, patch_tests

ROMS = [("dd1a.1", "dd1a.2", "dd1a.3", "dd1a.4"), ("dd1a.5", "dd1a.6"), ("dd1.7",)]
IY = [0x9FF0, 0x9FF4, 0x9FF8]          # unused RAM words of the map for IY and F' per CPU
TOKEN = 0x4001
# calls of leaf functions of up to INLINE instructions (z80x Config.inline_leaves; DIGDUG_NO_INLINE=1: none, the old build) are
# emitted in place, rst helpers ($08 / $10 / $18 of the sound CPU) and jumps inside them too: a call and a ret cost ~70 cycles.
# The ROMs are fixed code (inline_limit = the ROM's size).
INLINE = 0 if os.environ.get("DIGDUG_NO_INLINE") else int(os.environ.get("DIGDUG_INLINE", 32))
ENTRIES = 0x4002
SEEDS = (1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15, 16)


def configs():
    hooks1 = [(0x7100, 0x7100, "g_ctrl06", None), (0x7000, 0x70FF, "g_data06", None),
              (0x6821, 0x6821, "g1_latch1", None)]
    hooks2 = [(0xB840, 0xB840, "g_earom_ctl", None)]
    return [
        z80x.Config(prefix="Z", table="g1_dispatch", token_sym="g1_ret", mode="signed", block=0x10000,
                    iyaddr=IY[0], fshadow=IY[0] + 2, io_read_redirect={}, write_hooks=hooks1,
                    nmi_token=TOKEN, table_entries=ENTRIES, rst28_tables=False, iff_sym="g1_iff", hl_tables=True,
                    inline_leaves=INLINE, inline_limit=0x4000, inline_rst=True, inline_jumps=True, **z80x.FAST),
        z80x.Config(prefix="Y", table="g2_dispatch", token_sym="g2_ret", mode="long", block=0x10000,
                    ram_sym="g_ram", iyaddr=IY[1], fshadow=IY[1] + 2, io_read_redirect={}, write_hooks=hooks2,
                    nmi_token=TOKEN, table_entries=ENTRIES, rst28_tables=False, iff_sym="g2_iff", hl_tables=True,
                    inline_leaves=INLINE, inline_limit=0x2000, inline_rst=True, inline_jumps=True, **z80x.FAST_LONG),
        z80x.Config(prefix="X", table="g3_dispatch", token_sym="g3_ret", mode="long", block=0x10000,
                    ram_sym="g3_ram", iyaddr=IY[2], fshadow=IY[2] + 2, io_read_redirect={}, write_hooks=[],
                    nmi_token=TOKEN, table_entries=ENTRIES, rst28_tables=False,
                    inline_leaves=INLINE, inline_limit=0x1000, inline_rst=True, inline_jumps=True, **z80x.FAST_LONG),
    ]


ROOTS = [[0, 0x38, 0x66], [0, 0x38, 0x1DDC], [0, 0x66]]
# the sound CPU's sound routines: $0391 looks the id in $9B34 up in a table of 21 routine pointers at $040D (rst $08,
# jp (hl) at $0390); coverage only sees the sounds a play brings, the id 6 of the scripted game (frame ~4930) ended at
# z80_badpc in the simulator and Hatari: every word of the table is a root
SOUND_TABLE = range(0x040D, 0x040D + 2 * 21, 2)     # (21 routines: the sound ids 0-20; the words at $0700 are sequence data)
# the boot handshake's spin loops (CPU1 waits for the self-test results of CPU2 and CPU3 at $3973 / $3980, they wait for
# CPU1 to clear the flags: CPU2 at $1F25), CPU2's main loop ($0078: the boot is done): the runtime's scheduler (z80_hook)
YIELDS = [{0x3973, 0x3980}, {0x1F25, 0x0078}, set()]


BLOCK_OPS = ("ldir", "lddr", "ldi", "ldd")


class Emitter(z80x.Emitter):
    """z80x.Emitter + after the instructions that write the EAROM window ($B800-$B83F: the address and data of the
    chip, the low 6 bits of the address), the address in earom_addr: stores through HL / DE / BC / IX / IY, `ld (nn),r`
    and block instructions (the destination DE before).  The CCR is kept (the flag analysis may keep flags in it)."""
    def __init__(self, *a, ewriters=(), **k):
        super().__init__(*a, **k)
        self.ewriters = set(ewriters)

    def emit_ins(self, pc, *a, **k):
        super().emit_ins(pc, *a, **k)
        if pc not in self.ewriters:
            return
        ins = self.code[pc]
        if ins.mn in BLOCK_OPS:
            self.e("move sr,d5")
            self.e("move.w earom_de,d7")
            self.e("and.w #$3F,d7")
            self.e("move.b d7,earom_addr")
            self.e("move d5,ccr")
        elif ins.mn == "ld":
            self.earom_mark(ins.ops[0])
        else:
            raise z80x.Unsupported("EAROM writer %s" % ins.text)

    def block(self, fn, ins):
        if ins.pc in self.ewriters:
            self.e("move sr,-(sp)")
            self.e("move.w d2,earom_de")         # (DE before)
            self.e("move (sp)+,ccr")
        fn(ins)

    def x_ldir(self, ins): self.block(super().x_ldir, ins)
    def x_lddr(self, ins): self.block(super().x_lddr, ins)
    def x_ldi(self, ins): self.block(super().x_ldi, ins)
    def x_ldd(self, ins): self.block(super().x_ldd, ins)

    def earom_mark(self, dst):
        if dst[0] == "ind16":
            self.e("move.b #%d,earom_addr" % (dst[1] & 0x3F))
            return
        if dst[0] != "ind" or dst[1] not in ("hl", "de", "bc", "ix", "iy"):
            raise z80x.Unsupported("EAROM writer %r" % (dst,))
        if dst[1] == "iy" and not self.iyr:
            raise z80x.Unsupported("EAROM writer through IY in memory")
        self.e("move sr,d5")
        self.e("move.w %s,d7" % (self.iyr if dst[1] == "iy" else z80x.REG16[dst[1]]))
        if dst[1] == "bc":
            self.e("ror.w #8,d7")                  # (BC is kept byte swapped)
        if len(dst) > 2 and dst[2]:
            self.e("add.w #%d,d7" % dst[2])
        self.e("and.w #$3F,d7")
        self.e("move.b d7,earom_addr")
        self.e("move d5,ccr")


def ewriters():
    """per CPU: the instructions the coverage saw writing the EAROM window"""
    out = [set(), set(), set()]
    for f in glob.glob(os.path.join(BUILD, "digdug_cover_*.pkl")):
        d = pickle.load(open(f, "rb"))
        if "ewrites" not in d:
            continue
        for n in range(3):
            out[n] |= d["ewrites"][n]
    return out


def coverage():
    require_coverage("digdug", ["digdug_cover_%d.pkl" % s for s in SEEDS])
    dyn = [set(), set(), set()]
    for f in glob.glob(os.path.join(BUILD, "digdug_cover_*.pkl")):
        d = pickle.load(open(f, "rb"))
        for n in range(3):
            dyn[n] |= d["pcs"][n]
    return dyn


def generate(hooks=((), (), ()), skip_tests=True):
    roms = [b"".join(load(f) for f in files) for files in ROMS]
    if skip_tests:
        roms = list(patch_tests(roms))
    dyn = coverage()
    ew = ewriters()
    roms3 = roms[2]
    roots = [list(r) for r in ROOTS]
    roots[2] += sorted({roms3[a] | roms3[a + 1] << 8 for a in SOUND_TABLE if 0x40 <= (roms3[a] | roms3[a + 1] << 8) < len(roms3)})
    lines = ["; generated by gen.py -- Dig Dug CPU1, CPU2, CPU3, Z80 -> 68000", "\tsection text,code"]
    tables = ["\tsection data,data", "\tcnop 0,4", "TABLE_ENTRIES = %d" % ENTRIES]
    reports = []
    ems = []
    for n, cfg in enumerate(configs()):
        code_lines, table, rep, em = generate_program(roms[n], roots[n], dyn[n] & set(range(len(roms[n]))), cfg,
                                                      set(hooks[n]) | YIELDS[n], emitter=Emitter, ewriters=ew[n])
        lines.append("; ---------------- CPU%d" % (n + 1))
        lines += code_lines
        tables += table
        reports.append(rep)
        ems.append(em)
    return "\n".join(lines + tables) + "\n", reports, ems


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", default=os.path.join(BUILD, "digdug_code.s"))
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
