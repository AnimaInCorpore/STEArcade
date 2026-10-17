"""Gyruss: the sub CPU's program (KONAMI-1, 8 KB at $E000) translated to 68000 code (engine/m6809x.py).

    from gen_sub import generate; report = generate()   -> build/gyruss/code_sub.s, tables_sub.s, sub_info.s

The program is flat: virtual page = slot = address >> 13 (no MMU), code only in page 7.  The opcode bytes are
decrypted (m6809.konami1_opcode: the first byte and the byte after $10 / $11), the operands are plain.
The 68000 side (src/sub.s): the context block sub_ctx (a6), PB / VB per slot: slot 2 ($4000-$47FF RAM, the sprite RAM
at $4040) is sub_ram, slot 3 ($6000-$67FF) the main CPU's shared RAM ($A000-$A7FF in the Z80 block), slot 7 the ROM
(sub_rom); the others a zero page.  a3 = VB of slot 2 (the direct page $42xx and the stack $47xx), a4 = VB of slot 3.
Slots 0 ($0000: the beam's line) and 1 ($2000: the IRQ mask) are I/O (sub_io_r / sub_io_w).
Hooks (machine.GyrussPort): F0B6 (BRA self, the foreground's idle: back to the runtime), F0CA (the IRQ's wait for
$A701: skipped, on at F0CF).
"""
import collections
import pickle
import os
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
import m6809x
from m6809 import konami1_opcode
from machine import GyrussPort, load
from paths import build_dir, require_coverage

RESET, IRQ = 0xF000, 0xF0B8
SEEDS = [int(x) for x in os.environ.get("GY_SEEDS", "").split(",") if x] or range(1, 13)   # (GY_SEEDS: other coverage files)
HOOKS = {GyrussPort.SUB_IDLE: "sub_hook_idle", 0xF0CA: "sub_hook_F0CA"}
assert set(GyrussPort.SUB_SKIP) | {GyrussPort.SUB_IDLE} == set(HOOKS)
# after the second STD of an entry given to another object (the multiplexing, machine.GyrussPort): the bands' log
AFTER = {0xF6CA: ["bsr sub_spr_seg"], 0xF723: ["bsr sub_spr_seg"]}
# hand-written (src/sub.s): the scans of the entries for one the beam has passed
NATIVES = {0xF6A2: "native_scan_F6A2", 0xF6FB: "native_scan_F6FB",
           0xF48B: "native_copy_F48B", 0xF4E4: "native_copy_F4E4",      # the first phase's copy of the lists
           0xF273: "native_proj_F273", 0xF2DC: "native_proj_F2DC",      # the objects' projections (src/natives.s)
           0xF386: "native_proj_F386", 0xF3F1: "native_proj_F3F1"}


def page_addr(p):
    return {2: "sub_ram", 3: "g_block+$2000", 7: "sub_rom"}.get(p, "sub_null")


def load_cover():
    require_coverage("gyruss", ["cover%d.pkl" % s for s in SEEDS])
    exec_ = collections.Counter()
    acc = collections.defaultdict(set)
    tg = collections.defaultdict(set)
    wraps = set()
    for s in SEEDS:
        d = pickle.loads((build_dir("gyruss") / ("cover%d.pkl" % s)).read_bytes())["sub"]
        exec_.update(d["exec"])
        for v, x in d["acc"].items():
            acc[v] |= x
        for v, x in d["targets"].items():
            tg[v] |= x
        wraps |= d["wraps"]
    return exec_, acc, tg, wraps


def program(cover):
    exec_, acc, tg, wraps = cover
    rom = bytearray(0x2000)
    rom[:] = load("gyrussk.9")

    def page_bytes(p):
        return bytes(rom) if p == 7 else bytes(0x2000)
    io = {v for v, s in acc.items() if any(pg in (0, 1) for rw, sl, pg, odd in s)}
    # indirect operands through a static pointer ([$4200], [$4211]: the sort lists in the shared RAM): the target's
    # slot is the one the coverage saw besides the pointer's (the lock-step tests check it)
    from m6809dis import decode
    rd = lambda a: rom[a - 0xE000] if a >= 0xE000 else 0
    ind = {}
    for v in exec_:
        ins = decode(rd, v, 0x42, rd_op=konami1_opcode(rd))
        x = ins.arg if ins.mode == 'idx' else None
        if x is not None and x.indirect and x.kind == 'abs':
            slots = {sl for rw, sl, pg, odd in acc.get(v, ())} - {x.addr >> 13}
            if len(slots) == 1:
                ind[v] = next(iter(slots))
    prog = m6809x.Program("sub", "S", page_bytes, {7: 7}, roots=[RESET, IRQ] + sorted(HOOKS),
                          exec_cover=set(exec_), acc_cover=acc, targets=tg, hooks=HOOKS, page_addr=page_addr,
                          io_sites=io, wrap_sites=wraps, dp=0x42, a3_slot=2, a4_slot=3,
                          after=lambda v, ins: AFTER.get(v), indirect_slots=ind,
                          natives={v: l for v, l in NATIVES.items() if '%04X' % v not in os.environ.get('GY_NO_NATIVES', '')},
                          opcode_reader=lambda rd: konami1_opcode(rd))
    return prog


def dispatch_tables(prog, code):
    """the code page's table of 8192 words, (the label - the page's base) / 2, its base the long before it (the stub
    sub_pb_07: jmp sub_badpc before the page's first label, so 0 is a bad pc); the slots' list (8 longs)"""
    lines = ["\tsection data,data", "\teven", "sub_page_tables:"]
    for p in range(8):
        lines.append("\tdc.l %s" % ("sub_pt_%02X" % p if p in prog.slot_of else "sub_bad_table"))
    for p in sorted(prog.slot_of):
        lines.append("\tdc.l sub_pb_%02X" % p)
        lines.append("sub_pt_%02X:" % p)
        row = []
        for off in range(0x2000):
            v = (p << 13) | off
            row.append("(%s-sub_pb_%02X)/2" % (prog.label(v), p) if v in code else "0")
            if len(row) == 16:
                lines.append("\tdc.w " + ",".join(row))
                row = []
    return lines


def page_bases(lines, prog, code):
    first = {}
    for v in sorted(code):
        first.setdefault(v >> 13, prog.label(v))
    starts = {lab + ":": p for p, lab in first.items()}
    out = []
    for line in lines:
        head = line.split("\t", 1)[0]
        if head in starts:
            out.append("sub_pb_%02X:\tjmp sub_badpc" % starts[head])
        out.append(line)
    return out


def generate():
    build = build_dir("gyruss")
    prog = program(load_cover())
    lines, rep, em, code = m6809x.translate(prog)
    seen = [u for u in rep["unsupported"] if int(u.split()[0], 16) in prog.exec_cover]
    if seen:
        raise RuntimeError("observed sub CPU instructions cannot be translated: %s" % seen)
    lines = page_bases(lines, prog, code)
    head = ["; generated by games/gyruss/tools/gen_sub.py (engine/m6809x.py): the sub CPU", "\tsection text,code"]
    (build / "code_sub.s").write_text("\n".join(head + lines) + "\n")
    (build / "tables_sub.s").write_text("\n".join(dispatch_tables(prog, code)) + "\n")
    info = ["SUB_RESET equ %s" % prog.label(RESET), "SUB_IRQ equ %s" % prog.label(IRQ),
            "SUB_F0CF equ %s" % prog.label(0xF0CF)]
    info += ["SUB_%04X equ %s" % (a, prog.label(a)) for a in (0xF6B1, 0xF6B2, 0xF70A, 0xF70B, 0xF4C5, 0xF51E,
                                                         0xF2DB, 0xF3F0, 0xF367, 0xF48A)]
    (build / "sub_info.s").write_text("\n".join(info) + "\n")
    return rep


if __name__ == "__main__":
    r = generate()
    print("instructions", r["instructions"], "unsupported", len(r["unsupported"]), "missing", len(r["missing"]),
          r["stats"])
    for u in r["unsupported"][:20]:
        print("   ", u)
