"""Track & Field: the main CPU's program (KONAMI-1, 40 KB at $6000) translated to 68000 code (engine/m6809x.py).

    from gen import generate; report = generate()   -> build/trackfld/code_main.s, tables_main.s, main_info.s

The program is flat: virtual page = slot = address >> 13.  The opcode bytes are decrypted (m6809.konami1_opcode: the
first byte and the byte after $10 / $11), the operands are plain.  The 68000 side (src/trackfld.s): the 6809's 64 KB
are one block, tf_mem (the RAM, the NVRAM, the video RAM and the ROM at their addresses), so every slot's VB is
tf_mem: a3 (slot 1: the direct page $28xx) and a4 (slot 0: the RAM $1800-$1FFF, the stack) hold the same base, and
an indexed access uses a4 whatever slot it touched.  The I/O ($1000-$12FF: the coverage's io sites) goes through
main_io_r / main_io_w.  The idle point $6160 is a native (tf_idle): it delivers the IRQ (machine.TrackFieldPort).
"""
import collections
import os
import pickle
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
import m6809x
from m6809 import konami1_opcode
from machine import TrackFieldPort, load
from paths import build_dir, require_coverage

RESET, IRQ = 0x6000, TrackFieldPort.IRQ
SEEDS = [int(x) for x in os.environ.get("TF_SEEDS", "").split(",") if x] or range(1, 13)
NATIVES = {TrackFieldPort.IDLE: "tf_idle"}
ROM_FILES = ("a01_e01.bin", "a02_e02.bin", "a03_k03.bin", "a04_e04.bin", "a05_e05.bin")


def image():
    """the 64 KB the 6809 sees at power-on: zero but the ROM at $6000-$FFFF"""
    mem = bytearray(0x10000)
    for i, n in enumerate(ROM_FILES):
        mem[0x6000 + i * 0x2000:0x8000 + i * 0x2000] = load(n)
    return bytes(mem)


def page_addr(p):
    return "tf_mem+$%04X" % (p << 13)


def load_cover():
    require_coverage("trackfld", ["cover%d.pkl" % s for s in SEEDS])
    exec_ = collections.Counter()
    acc = collections.defaultdict(set)
    tg = collections.defaultdict(set)
    wraps, io = set(), set()
    returns = collections.Counter()
    for s in SEEDS:
        d = pickle.loads((build_dir("trackfld") / ("cover%d.pkl" % s)).read_bytes())
        exec_.update(d["exec"])
        for v, x in d["acc"].items():
            acc[v] |= x
        for v, x in d["targets"].items():
            tg[v] |= x
        wraps |= d["wraps"]
        io |= {pc for pc, a, rw in d["io"]}
        returns.update(d.get("returns", {}))
    return exec_, acc, tg, wraps, io, returns


def program(cover):
    exec_, acc, tg, wraps, io, returns = cover
    mem = image()
    # one base for every slot: an indexed access uses a4 (slot 0) whatever slot the coverage saw
    flat = {v: {(rw, 0, 0, odd) for rw, sl, pg, odd in s} for v, s in acc.items()}
    prog = m6809x.Program("main", "M", lambda p: mem[p << 13:(p + 1) << 13], {p: p for p in range(3, 8)},
                          roots=[RESET, IRQ] + sorted(NATIVES), exec_cover=set(exec_), acc_cover=flat, targets=tg,
                          page_addr=page_addr, io_sites=io, wrap_sites=wraps, dp=0x28, a3_slot=1, a4_slot=0,
                          natives={v: l for v, l in NATIVES.items()
                                   if '%04X' % v not in os.environ.get('TF_NO_NATIVES', '')},
                          opcode_reader=lambda rd: konami1_opcode(rd))
    # flat: every slot holds one page for good, so jumps, calls and returns need no page check; the 68030 forms the
    # 68000 runs too (m6809x Program.fast_forms: flags fixed through d7, returns compared most frequent first by the
    # coverage's counts of the returns to each point)
    prog.fixed_slots = tuple(range(8))
    prog.fast_forms = True
    prog.ret_weights = dict(returns) or dict(exec_)
    prog.call_summaries = True                  # (m6809x: a call's live flags from its callees' summaries)
    return prog


def dispatch_tables(prog, code):
    """per code page a table of 8192 words, (the label - the page's base) / 2, its base the long before it (the stub
    main_pb_NN: jmp main_badpc before the page's first label, so 0 is a bad pc); the slots' list (8 longs)"""
    pages = {v >> 13 for v in code}                 # (a ROM page with data only has no table)
    lines = ["\tsection data,data", "\teven", "main_page_tables:"]
    for p in range(8):
        lines.append("\tdc.l %s" % ("main_pt_%02X" % p if p in pages else "main_bad_table"))
    for p in sorted(pages):
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
    build = build_dir("trackfld")
    prog = program(load_cover())
    lines, rep, em, code = m6809x.translate(prog)
    seen = [u for u in rep["unsupported"] if int(u.split()[0], 16) in prog.exec_cover]
    if seen:
        raise RuntimeError("observed instructions cannot be translated: %s" % seen)
    lines = page_bases(lines, prog, code)
    head = ["; generated by games/trackfld/tools/gen.py (engine/m6809x.py): the main CPU", "\tsection text,code"]
    (build / "code_main.s").write_text("\n".join(head + lines) + "\n")
    (build / "tables_main.s").write_text("\n".join(dispatch_tables(prog, code)) + "\n")
    info = ["MAIN_RESET equ %s" % prog.label(RESET), "MAIN_IRQ equ %s" % prog.label(IRQ),
            "MAIN_IDLE_T equ %s_t" % prog.label(TrackFieldPort.IDLE)]
    (build / "main_info.s").write_text("\n".join(info) + "\n")
    return rep


if __name__ == "__main__":
    r = generate()
    print("instructions", r["instructions"], "unsupported", len(r["unsupported"]), "missing", len(r["missing"]),
          r["stats"])
    for u in r["unsupported"][:20]:
        print("   ", u)
