"""The 68010 program as the STE runs it: the arcade's own code, natively, patched in place.

    venv/bin/python games/gauntlet/tools/patch.py [--report]    -> build/gauntlet/{program.bin, map.i, patch.json}

The STE keeps the ROM at its arcade addresses ($000000-$04FFFF: no code address, jump table or return address
changes) and moves what the STE has no memory for: the video RAM, palette, work RAM, EEPROM, I/O and scroll register
of $800000-$93FFFF go to RAM below 4 MB (MAP).  Every place the program names such an address is rewritten to the
STE's (same instruction, same length):
  * absolute operands ($904F0C.l) and long immediates (#$904002 into an address register, compares) in the code;
  * long words in the data that point there (pointer tables);
the code being every instruction the coverage saw (build/gauntlet/cover_*.pkl) and what recursive descent finds from
them.  Some sites become calls of the runtime (SITES: a `jsr` of the same length, padded with nops): the sound
command and the sound CPU's reset bit (the runtime models the sound board), the slapstic's bank switches (the
runtime copies the selected 8 KB bank into the window $38000-$3FFFF, all four mirrors).  Everything else of the I/O
lands in RAM: the inputs and the status word the runtime keeps, the writes nobody reads (watchdog, IRQ 4
acknowledge, LEDs, EEPROM unlock).  Instructions that only the coverage can tell apart are listed in NOT_POINTERS.
"""
import json
import pickle
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from machine import main_rom
from paths import build_dir

IMAGE_END = 0x50000                       # the ROM the STE keeps at its own addresses ($0-$FFFF, $38000-$4FFFF used)
POPULATED = [(0x00000, 0x10000), (0x38000, 0x50000)]


def populated(a):
    return any(lo <= a < hi for lo, hi in POPULATED)

# arcade range -> STE address (canonical addresses only: the program uses no mirrors, the port model checks).  Only
# the high byte changes ($80 -> $3D, $90 -> $3F, $91 -> $3E, $93 -> $3C): the program keeps low words of pointers
# and rebuilds them (the EEPROM's offset from A1's low word, $44B2).  The rest of those 64 KB blocks is the
# runtime's.
MAP = [
    ("vram", 0x900000, 0x906000, 0x3F0000),     # playfield, motion objects, spare (the program's RAM, stack), alpha
    ("palette", 0x910000, 0x910800, 0x3E0000),
    ("ram", 0x800000, 0x802000, 0x3D0000),
    ("eeprom", 0x802000, 0x802400, 0x3D2000),
    ("io", 0x803000, 0x803200, 0x3D3000),       # +$000-$00F reads (inputs, status, reply), +$100-$17F writes
    ("xscroll", 0x930000, 0x930002, 0x3C0000),
]

# runtime calls: (arcade pc, instruction length, stub name); the runtime's stub does what the instruction did
SITES = [
    (0x041AE, 6, "snd_cmd_d0"),              # move.w d0,$803170.l
    (0x041E4, 6, "snd_cmd_d0"),              # move.w d0,$803170.l
    (0x04312, 8, "snd_cmd_sp10"),            # move.w ($a,a7),$803170.l (the stub sees it at ($e,a7))
    (0x04306, 6, "snd_reset_d0"),            # move.w d0,$80312e.l (Q7: the sound CPU's reset, bit 0)
    (0x04326, 6, "snd_reset_d0"),
    # the slapstic's routines (a jmp: the runtime's routine returns to their caller)
    (0x4FED4, 6, "slap_bank0"),              # move sr,d0; move #$2700,sr  (the routine: reset, $38040: bank 0)
    (0x4FEEA, 6, "slap_bank3"),              # (reset, $38070: bank 3)
    (0x4FF00, 6, "slap_a0d0"),               # move.w d0,$38000.l (then a write to (a0,d0.w): its bank)
    (0x4FF0C, 6, "slap_a0"),                 # move.w d0,$38000.l; bra $4fed0 (move.w (a0),(a1): its bank)
    (0x4FF14, 6, "slap_a0d0"),               # (unused so far: reset, $3FB2A, (a0,d0.w))
    # the playfield's writers (every one, logged on the reference board; tools/logic_test.py checks the marks): the
    # renderer compares only the columns marked since its last picture.  A 2 x 2 tile block at a2 (the maze cells),
    # three routines: the stub marks its two columns and does the add.  The clear routine ($42550: count 6(sp), address
    # 8(sp)): the stub loads them and marks every column when the range starts below the playfield's end.
    (0x41C44, 6, "pf_blk_d4"),               # addi.l #130,d4 (the block's fourth word next)
    (0x42884, 6, "pf_blk_d7"),               # addi.l #130,d7
    (0x42C88, 6, "pf_blk_d6"),               # addi.l #130,d6
    (0x42550, 8, "mem_clear"),               # move.w (6,a7),d0; movea.l (8,a7),a0 (the stub: (10,a7), (12,a7))
]

# the runtime's routines: a table of `jmp routine` at RT_STUBS, entry k at RT_STUBS + 6 * k (src/gauntlet.s rt_stubs)
RT_BASE = 0x50000
RT_STUBS = RT_BASE + 0x10
STUB_ORDER = ["snd_cmd_d0", "snd_cmd_sp10", "snd_reset_d0", "slap_bank0", "slap_bank3", "slap_a0d0", "slap_a0",
              "pf_blk_d4", "pf_blk_d7", "pf_blk_d6", "mem_clear"]
HOOKS_AT = (RT_STUBS + 6 * len(STUB_ORDER) + 15) & ~15        # (src/gauntlet.s rt_hooks: checked there)

# the alphanumerics' writers (logged on the reference board in the attract mode and play; tools/logic_test.py checks
# that every change was marked): an instruction of 6 or 8 bytes before each write loop (absolute or immediate, not
# PC-relative) becomes a jsr of a generated hook (build/gauntlet/hooks.i, at HOOKS_AT, 16 bytes each): `st al_dirty`,
# the instruction itself (relocated), rts.  The renderer compares the alphanumerics only after a mark (and one row a
# picture in turn).
HOOKS = [
    (0x02F42, 6),                            # BIOS: lea $905000,a1 (a string: $2F60, $2F92)
    (0x0307C, 6),                            # BIOS: lea $905000,a1 (a character: $3082)
    (0x03090, 6),                            # BIOS: lea $905000,a1 ($30EC)
    (0x03214, 6),                            # BIOS: addi.l #$905000,d0 (the big digits: $324E)
    (0x03540, 6),                            # BIOS: lea $905000,a0 (the clear: $354E)
    (0x42F30, 6),                            # movea.l #$905000,a0 ($42F3A)
    (0x43088, 6),                            # movea.l #$905000,a0 ($43092)
    (0x430D0, 6),                            # movea.l #$905000,a0 ($430EA, $430FA, $43104)
    (0x4325C, 6),                            # addi.l #$90503a,d0 ($43276)
    (0x43664, 6),                            # addi.l #$90503e,d0 ($43694 ... $4369E)
    (0x43740, 6),                            # movea.l #$9de6,a0 (the high-score entry's rows: $4375E)
    (0x43784, 6),                            # movea.l #$9e08,a0 ($4378A)
    (0x437F4, 6),                            # movea.l #$9df6,a0 ($43808)
    (0x4B618, 6),                            # movea.l #$904b26,a0 (a list of places: $4B622)
    (0x4B678, 6),                            # movea.l #$905000,a0 ($4B684)
    (0x4B758, 6),                            # movea.l #$905522,a0 ($4B762)
    (0x4B9C2, 6),                            # movea.l #$9051ae,a0 ($4B9CC)
]
HOOK_SIZE = 16

# the STE's schedule (program_ste.bin only; tools/stemodel.py stops at the same places): where the program waits for
# the next frame, a trap: TRAP #14 (vector 46) for the main loop's `bra.s $40C22` (the counter was 0: give the frame
# to the picture, then go on at $40C22), TRAP #13 (vector 45) for `bne.s $40F80` at $40F88 (d0 nonzero: the queue is
# not empty yet: wait for the next frame, then call $4802 again; else on at $40F8A)
SCHEDULE = [(0x40C28, 0x60F8, 0x4E4E), (0x40F88, 0x66F6, 0x4E4D)]

# long values in window ranges that are numbers, not addresses: (arcade pc of the instruction)
NOT_POINTERS = {0x3202, 0x32CC}           # movea.l #$800002,a0: the alphanumerics' row and column steps ($80 by
                                          # swap, 2 by adda.w; $324E), not the work RAM

# where the data holds window addresses: (first, end) offsets scanned for longs in the MAP ranges (the reset vector's
# stack, the BIOS's self-test tables); others show up as accesses outside the STE map in tools/stemodel.py
DATA_POINTERS = [(0x0000, 0x0004), (0x01D8, 0x0600),
                 (0x9DE6, 0x9DF6),                 # 4 rows of the alphanumerics (the high-score entry, $4378A)
                 (0xD800, 0xD810)]                 # the 4 player records ($4ADC6: movea.l #$d800,a0; movea.l (a0,d0.w),a0)


def ste_addr(a):
    for name, lo, hi, ste in MAP:
        if lo <= a < hi:
            return ste + (a - lo)
    return None


def window(a):
    return 0x800000 <= a < 0x940000


def load_coverage():
    execd = set()
    regions = {}
    files = sorted(build_dir("gauntlet").glob("cover_*.pkl"))
    if not files:
        sys.exit("no coverage in build/gauntlet: venv/bin/python games/gauntlet/ref/cover.py SEED FRAMES")
    for p in files:
        d = pickle.loads(p.read_bytes())
        execd |= d["exec"]
        for k, v in d["regions"].items():
            regions[k] = regions.get(k, 0) | v
    return execd, regions


class Disassembler:
    def __init__(self, rom):
        import machine68k as mk
        self.m = mk.Machine(mk.CPUType.M68010, 1024)
        self.m.mem.w_block(0, rom)

    def __call__(self, pc):
        size, text = self.m.cpu.disassemble(pc)
        return size, text


JUMP_TABLE = re.compile(r"^jmp\s+\(\$2,PC,D\d\.w\)$")   # move.w ($k,PC,Dn.w),Dn; jmp ($2,PC,Dn.w); dc.w ...
FLOW_END = ("rts", "rte", "rtr", "jmp", "bra", "illegal")
BRANCH = re.compile(r"^(b(?:ra|sr|hi|ls|cc|cs|ne|eq|vc|vs|pl|mi|ge|lt|gt|le)|db\w+|jsr|jmp)\s+(?:.*,\s*)?\$([0-9a-f]+)(\.[lw])?$")


def discover(rom, seeds, dis):
    """recursive descent from the executed instructions: {pc: (size, text)}"""
    code = {}
    todo = sorted(seeds)
    while todo:
        pc = todo.pop()
        while pc not in code and populated(pc):
            size, text = dis(pc)
            if text.startswith("dc.w") or "ILLEGAL" in text.upper():
                break
            code[pc] = (size, text)
            mn = text.split()[0]
            m = BRANCH.match(text)
            if m:
                t = int(m.group(2), 16)
                if populated(t):
                    todo.append(t)
            if JUMP_TABLE.match(text):                 # (a jump table: the word offsets from the jmp's d8 base,
                base, end = pc + 4, None              #  up to the first case: every case is code; the base:
                                                      #  the extension word's address + 2)
                off = base
                while end is None or off < end:
                    w = struct.unpack(">h", rom[off:off + 2])[0]
                    t = base + w
                    if w <= 0 or t & 1 or not populated(t):
                        break
                    todo.append(t)
                    end = t if end is None else min(end, t)
                    off += 2
            if mn in FLOW_END:
                break
            pc += size
    return code


def relocations(rom, code):
    """(offset, old long, new long, pc, text) for every long operand / immediate of the code that names a window"""
    out = []
    for pc, (size, text) in sorted(code.items()):
        for off in range(pc + 2, pc + size - 3, 2):
            v = struct.unpack(">I", rom[off:off + 4])[0]
            if window(v) and ("$%x" % v) in text:
                out.append((off, v, pc, text))
    return out


def data_pointers(rom, code):
    """long words of DATA_POINTERS outside the code (even addresses) that hold a window address"""
    covered = bytearray(IMAGE_END)
    for pc, (size, _) in code.items():
        covered[pc:pc + size] = b"\x01" * size
    out = []
    for lo, hi in DATA_POINTERS:
        for off in range(lo, hi - 3, 2):
            if covered[off] or covered[off + 3]:
                continue
            v = struct.unpack(">I", rom[off:off + 4])[0]
            if ste_addr(v) is not None:
                out.append((off, v))
    return out


def build(report=False):
    rom = bytearray(main_rom()[:IMAGE_END])
    dis = Disassembler(bytes(rom))
    execd, regions = load_coverage()
    code = discover(rom, execd, dis)
    rel = relocations(rom, code)
    data = data_pointers(rom, code)
    problems = []
    applied = []
    site_pcs = {pc for pc, _, _ in SITES}
    for off, v, pc, text in rel:
        if pc in site_pcs or pc in NOT_POINTERS:
            continue
        s = ste_addr(v)
        if s is None:
            problems.append("%06X %s: $%06X has no STE address" % (pc, text, v))
            continue
        rom[off:off + 4] = struct.pack(">I", s)
        applied.append((off, v, s, "%06X %s" % (pc, text)))
    for off, v in data:
        rom[off:off + 4] = struct.pack(">I", ste_addr(v))
        applied.append((off, v, ste_addr(v), "data"))
    stubs = []
    for pc, n, name in SITES:
        a, texts = pc, []
        while a < pc + n and a in code:               # (a site may span instructions: their boundaries must match)
            texts.append(code[a][1])
            a += code[a][0]
        if a != pc + n:
            problems.append("%06X: site length %d does not end on an instruction (%s)" % (pc, n, "; ".join(texts)))
        stubs.append((pc, n, name, "; ".join(texts)))
    for pc, n, name, _ in stubs:
        k = STUB_ORDER.index(name)
        op = 0x4EF9 if name.startswith("slap") else 0x4EB9          # (the slapstic's routines: replaced whole)
        words = [op, (RT_STUBS + 6 * k) >> 16, (RT_STUBS + 6 * k) & 0xFFFF] + [0x4E71] * ((n - 6) // 2)
        rom[pc:pc + n] = b"".join(struct.pack(">H", w) for w in words)
    out = build_dir("gauntlet")
    hooks = []
    for k, (pc, n) in enumerate(HOOKS):
        a, texts = pc, []
        while a < pc + n and a in code:
            texts.append(code[a][1])
            a += code[a][0]
        if a != pc + n or any("pc" in t for t in texts):
            sys.exit("%06X: hook length %d does not end on an instruction or is PC-relative (%s)" % (
                pc, n, "; ".join(texts)))
        words = struct.unpack(">%dH" % (n // 2), rom[pc:pc + n])            # (relocated)
        hooks.append((pc, n, "; ".join(texts), words))
        target = HOOKS_AT + HOOK_SIZE * k
        rom[pc:pc + n] = b"".join(struct.pack(">H", w) for w in [0x4EB9, target >> 16, target & 0xFFFF] +
                                  [0x4E71] * ((n - 6) // 2))
    with open(out / "hooks.i", "w") as f:
        f.write("; generated by games/gauntlet/tools/patch.py: the alphanumerics' writers' hooks (HOOKS)\n")
        f.write("HOOKS_AT = $%06X\n" % HOOKS_AT)
        for k, (pc, n, text, words) in enumerate(hooks):
            f.write("hook_%d:\t\t\t\t; $%05X %s\n\tst\tal_dirty\n\tdc.w\t%s\n\trts\n\tcnop\t0,%d\n" % (
                k, pc, text, ",".join("$%04x" % w for w in words), HOOK_SIZE))
    (out / "hooks.json").write_text(json.dumps([[pc, n, list(w)] for pc, n, _, w in hooks]))
    (out / "program.bin").write_bytes(bytes(rom))
    ste = bytearray(rom)
    for pc, old, new in SCHEDULE:
        assert struct.unpack(">H", ste[pc:pc + 2])[0] == old, hex(pc)
        ste[pc:pc + 2] = struct.pack(">H", new)
    (out / "program_ste.bin").write_bytes(bytes(ste))
    (out / "patch.json").write_text(json.dumps(dict(
        relocations=[[o, v, s, t] for o, v, s, t in applied], sites=stubs, problems=problems,
        code=len(code), executed=len(execd)), indent=0))
    write_map(out)
    print("%d instructions (%d executed), %d relocations in the code, %d data pointers, %d sites, %d problems" % (
        len(code), len(execd), len(rel), len(data), len(SITES), len(problems)))
    for p in problems:
        print("  problem:", p)
    if report:
        for o, v, s, t in applied:
            print("  %06X: $%06X -> $%06X  %s" % (o, v, s, t))
    return rom, stubs


def write_map(out):
    """The renderer harness needs the fixed map, independently of code coverage."""
    with open(out / "map.i", "w") as f:
        f.write("; generated by games/gauntlet/tools/patch.py: the arcade's windows in the STE's memory\n")
        for name, lo, hi, ste in MAP:
            f.write("ARC_%s = $%06X\t\t; $%06X-$%06X\n" % (name.upper(), ste, lo, hi - 1))
        f.write("IMAGE_END = $%06X\n" % IMAGE_END)
        f.write("RT_BASE = $%06X\n" % RT_BASE)


if __name__ == "__main__":
    build("--report" in sys.argv)
