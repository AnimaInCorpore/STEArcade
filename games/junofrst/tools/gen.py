"""Juno First's main program (KONAMI-1, ROM $A000-$FFFF and the 4 KB banks of the window $9000-$9FFF) translated to 68000
code (engine/m6809x.py).

    from gen import generate; report = generate()   -> build/junofrst/code_main.s, tables_main.s, main_info.s

Virtual pages (8 KB, ref/cover.py): 5-7 the fixed ROM ($A000-$FFFF), 8 + bank the code of bank 0-15 (the window's 4 KB
in the upper half of slot 4's 8 KB: v = page << 13 | pc & $1FFF).  The 68000 side (src/junofrst.s): the 6809's RAM,
video RAM and ROM are one 64 KB block g_mem (every context's VB is g_mem: the direct page $88xx, the stack, the work
RAM and every other data access of the program; a3 = a4 = g_mem), a context per bank (ctx_banks, a6): its slot 4 holds
that bank's page for the dispatcher and the page checks (`bank_ctx`), and main_bank_w switches a6.  The accesses the
coverage lists as I/O sites go through main_io_r / main_io_w: $8000-$80FF (palette, inputs, latch, sound, bank and
blitter registers), the window's data ($9000-$9FFF: the bank's ROM bytes, 25 sites) and the stores to the video RAM
($0000-$7FFF: the runtime keeps the picture).
"""
import collections
import os
import pickle
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
import m6809x
from m6809 import konami1_opcode
from machine import JunoPort, load, PROGRAM, BANKED
from paths import build_dir, require_coverage

RESET, IRQ = 0xA000, JunoPort.IRQ
SEEDS = [int(x) for x in os.environ.get("JF_SEEDS", "").split(",") if x] or range(1, 9)
NATIVES = {JunoPort.IDLE: "jf_idle"}
NBANKS = 16


def rom_image():
    """the ROM as the 6809 sees it at power-on ($A000-$FFFF) and the 16 banks of the window (4 KB each)"""
    mem = bytearray(0x10000)
    for n, a in PROGRAM:
        mem[a:a + 0x2000] = load(n)
    banks = b"".join(load(n) for n in BANKED) + bytes(0x4000)
    return mem, banks


def page_bytes_fn():
    mem, banks = rom_image()

    def page_bytes(p):
        if 5 <= p < 8:
            return bytes(mem[p << 13:(p + 1) << 13])
        if p >= 8:
            b = p - 8
            return bytes(0x1000) + banks[b * 0x1000:(b + 1) * 0x1000]
        return bytes(0x2000)
    return page_bytes


def page_addr(p):
    return "jf_mem+$%04X" % (p << 13) if p < 8 else "jf_mem+$%04X" % 0x8000


def bank_ctx(page, slot):
    """m6809x Program.slot_ctx: context k (ctx_banks + k * CTX_STRIDE) holds bank k's page in slot 4 for good, and
    main_bank_w makes a6 the context of the bank selected: a6 == that context <=> slot 4 holds the page"""
    if slot == 4 and page >= 8:
        return "ctx_banks+%d" % ((page - 8) * 256)
    return None


def load_cover():
    require_coverage("junofrst", ["cover%d.pkl" % s for s in SEEDS])
    exec_ = collections.Counter()
    acc = collections.defaultdict(set)
    tg = collections.defaultdict(set)
    wraps, io = set(), set()
    returns = collections.Counter()
    for s in SEEDS:
        d = pickle.loads((build_dir("junofrst") / ("cover%d.pkl" % s)).read_bytes())
        exec_.update(d["exec"])
        for v, x in d["acc"].items():
            acc[v] |= x
        for v, x in d["targets"].items():
            tg[v] |= x
        wraps |= d["wraps"]
        io |= {pc for pc, a, rw in d["io"]}
        returns.update(d.get("returns", {}))
    # the video RAM is the planar picture (no byte image): its reads go through the runtime too
    io |= {v for v, x in acc.items() if any(rw == 'r' and sl < 4 for rw, sl, pg, odd in x)}
    return exec_, acc, tg, wraps, io, returns


class JProgram(m6809x.Program):
    """m6809x.Program whose window pages read their code from the upper half of slot 4"""


def program(cover):
    exec_, acc, tg, wraps, io, returns = cover
    page_bytes = page_bytes_fn()
    slot_of = {}
    for v in exec_:
        p = v >> 13
        slot_of[p] = 4 if p >= 8 else p
    # one base for every slot: an indexed access uses a4 (slot 0) whatever slot the coverage saw
    flat = {v: {(rw, 0, 0, odd) for rw, sl, pg, odd in s} for v, s in acc.items()}
    prog = JProgram("main", "M", page_bytes, slot_of, roots=[RESET, IRQ] + sorted(NATIVES), exec_cover=set(exec_),
                    acc_cover=flat, targets=tg, page_addr=page_addr, io_sites=io, wrap_sites=wraps, dp=0x88, a3_slot=4,
                    a4_slot=0, natives=dict(NATIVES), opcode_reader=lambda rd: konami1_opcode(rd), pid_checks=True)
    prog.fixed_slots = (0, 1, 2, 3, 5, 6, 7)
    prog.slot_ctx = bank_ctx
    prog.fast_forms = True
    prog.ret_weights = dict(returns) or dict(exec_)
    prog.call_summaries = True
    return prog


def dispatch_tables(prog, code):
    """per code page a table of 8192 words, (the label - the page's base) / 2, its base the long before it: the stub
    main_pb_XX (jmp main_badpc) put before the page's first label, so 0 is a bad pc; the page list (32 longs)"""
    lines = ["\tsection data,data", "\teven", "main_page_tables:"]
    for p in range(32):
        lines.append("\tdc.l %s" % ("main_pt_%02X" % p if p in prog.slot_of else "main_bad_table"))
    for p in sorted(prog.slot_of):
        lines.append("\tdc.l main_pb_%02X" % p)
        lines.append("main_pt_%02X:" % p)
        row = []
        for off in range(0x2000):
            v = (p << 13) | off
            row.append("(%s-main_pb_%02X)/2" % (prog.label(v), p) if v in code else "0")
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
            out.append("main_pb_%02X:\tjmp main_badpc" % starts[head])
        out.append(line)
    return out


def generate():
    build = build_dir("junofrst")
    prog = program(load_cover())
    lines, rep, em, code = m6809x.translate(prog)
    seen = [u for u in rep["unsupported"] if int(u.split()[0], 16) in prog.exec_cover]
    if seen:
        raise RuntimeError("observed instructions cannot be translated: %s" % seen)
    lines = page_bases(lines, prog, code)
    head = ["; generated by games/junofrst/tools/gen.py (engine/m6809x.py): the main CPU", "\tsection text,code"]
    (build / "code_main.s").write_text("\n".join(head + lines) + "\n")
    (build / "tables_main.s").write_text("\n".join(dispatch_tables(prog, code)) + "\n")
    info = ["MAIN_RESET equ %s" % prog.label(RESET), "MAIN_IRQ equ %s" % prog.label(IRQ),
            "MAIN_IDLE_T equ %s_t" % prog.label(JunoPort.IDLE)]
    (build / "main_info.s").write_text("\n".join(info) + "\n")
    rep["pages"] = sorted("%X:%d" % (p, s) for p, s in prog.slot_of.items())
    return rep


if __name__ == "__main__":
    r = generate()
    print("instructions", r["instructions"], "unsupported", len(r["unsupported"]), "missing", len(r["missing"]),
          r["stats"], r["pages"])
    for u in r["unsupported"][:20]:
        print("   ", u)
