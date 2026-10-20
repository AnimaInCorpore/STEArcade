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
]

# the runtime's routines: a table of `jmp routine` at RT_STUBS, entry k at RT_STUBS + 6 * k (src/gauntlet.s rt_stubs)
RT_BASE = 0x50000
RT_STUBS = RT_BASE + 0x10
STUB_ORDER = ["snd_cmd_d0", "snd_cmd_sp10", "snd_reset_d0", "slap_bank0", "slap_bank3", "slap_a0d0", "slap_a0"]

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
