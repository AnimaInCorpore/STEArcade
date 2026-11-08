"""Yie Ar Kung-Fu: the main CPU's program (a plain MC6809E, 32 KB at $8000) translated to 68000 code (engine/m6809x.py).

    from gen import generate; report = generate()   -> build/yiear/code_main.s, tables_main.s, main_info.s, start_info.s, vlm_tab.s

The program is flat: virtual page = slot = address >> 13.  The 68000 side (src/yiear.s): the 6809's 64 KB are one
block, ya_mem (the RAM $5000-$5FFF, the video RAM in it, and the ROM at its addresses), so every slot's VB is ya_mem:
a3 (slot 2: the direct page $51xx and the stack) and a4 (slot 0) hold the same base, and an indexed access uses a4
whatever slot it touched.  The I/O ($0000, $4000-$4FFF: the coverage's io sites) goes through main_io_r / main_io_w.
The program starts at $8000 with the registers and RAM the self-test leaves (the image is the reference's state
there: machine.YieArPort.boot).  The idle point $807C is a native (ya_idle): it delivers the eight NMIs and the IRQ
(machine.YieArPort).
"""
import collections
import os
import pickle
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
import m6809x
import m6809dis
from machine import YieArPort, load
from paths import build_dir, require_coverage

RESET, IRQ, NMI = YieArPort.ENTRY, YieArPort.IRQ, YieArPort.NMI
SEEDS = [int(x) for x in os.environ.get("YA_SEEDS", "").split(",") if x] or range(1, 29)
NATIVES = {YieArPort.IDLE: "ya_idle", 0x8B30: "nat_8B30"}
ROM_FILES = ("407_i08.10d", "407_i07.8d")


# the video RAM writers that store the same text every frame (a score / credit line, $598C-$59B1): they mark vram_n, which
# render.s answers with a scan of $5980-$59BF; every other writer marks vram_w (a scan of all 2 KB).  logic_test.py checks
# every change against its marks.
NOISY = {0xA695, 0xA6D3, 0xA6F4, 0xA6AC, 0xA6BC, 0xA6EB, 0xA6B3}

STATIC_WRITE = {0x4000: "main_w4000", 0x4800: "main_w4800", 0x4900: "main_w4900"}      # (m6809x static_write: the sound's and the control latch's stores go straight to their routines)

DIPS = ()                       # (DSW1, DSW2, DSW3) of a build with other DIP switches (build.py --dsw2 / --dsw3): the
                                # self-test leaves RAM that depends on them


def image():
    """the 64 KB at the entry: the reference's memory after the self-test (the RAM as it leaves it, the ROM); the
    registers are in start_regs()"""
    m = YieArPort(*DIPS)
    m.boot()
    return bytes(m.mem), m.cpu


def start_regs():
    m = YieArPort(*DIPS)
    m.boot()
    c = m.cpu
    return dict(a=c.a, b=c.b, x=c.x, y=c.y, u=c.u, s=c.s, cc=c.cc, dp=c.dp)


def page_addr(p):
    return "ya_mem+$%04X" % (p << 13)


def load_cover():
    require_coverage("yiear", ["cover%d.pkl" % s for s in SEEDS])
    exec_ = collections.Counter()
    acc = collections.defaultdict(set)
    tg = collections.defaultdict(set)
    wraps, io = set(), set()
    returns = collections.Counter()
    vsites = set()
    for s in SEEDS:
        d = pickle.loads((build_dir("yiear") / ("cover%d.pkl" % s)).read_bytes())
        exec_.update(d["exec"])
        for v, x in d["acc"].items():
            acc[v] |= x
        for v, x in d["targets"].items():
            tg[v] |= x
        wraps |= d["wraps"]
        io |= {pc for pc, a, rw in d["io"]}
        returns.update(d.get("returns", {}))
        vsites |= d.get("vsites", set())
    return exec_, acc, tg, wraps, io, returns, vsites


def program(cover):
    exec_, acc, tg, wraps, io, returns, vsites = cover
    mem, _ = image()
    # one base for every slot: an indexed access uses a4 (slot 0) whatever slot the coverage saw
    flat = {v: {(rw, 0, 0, odd) for rw, sl, pg, odd in s} for v, s in acc.items()}
    prog = m6809x.Program("main", "M", lambda p: mem[p << 13:(p + 1) << 13], {p: p for p in range(4, 8)},
                          roots=[RESET, IRQ, NMI] + sorted(NATIVES), exec_cover=set(exec_), acc_cover=flat, targets=tg,
                          page_addr=page_addr, io_sites=io, wrap_sites=wraps, dp=0x51, a3_slot=2, a4_slot=0,
                          natives={v: l for v, l in NATIVES.items()
                                   if '%04X' % v not in os.environ.get('YA_NO_NATIVES', '')},
                          static_write=STATIC_WRITE, opcode_reader=None, after=lambda v, ins: [("st vram_n" if v in NOISY else "st vram_w")] if v in vsites else None)
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


def static_io_sites(code, io):
    """the translated instructions with a static address in the I/O ($0000-$4FFF) or the unmapped space ($6000-$7FFF)
    that the coverage's io sites lack (a path no run took: $8A47's coin counter store): they must go through main_io_r
    / main_io_w too"""
    mem = image()[0]
    out = set()
    for pc in code:
        ins = m6809dis.decode(lambda a: mem[a], pc, 0x51)
        if ins.mode in ("ext", "dir") and ins.arg is not None:
            a = ins.arg if ins.mode == "ext" else 0x5100 | ins.arg
            if (a < 0x5000 or 0x6000 <= a < 0x8000) and pc not in io:
                out.add(pc)
    return out


def keep_flags_at_dispatch(lines):
    """`move.w #pc,d7` before `jmp main_dispatch` sets the 68000's flags, which main_dispatch then saves as the 6809's:
    where the code runs on into the next 8 KB page (the instruction before the boundary: Yie Ar's `CMPU #$5110` at
    $BFFF, then `BEQ`), a compare's Z was lost (lock-step seed 23, frame 13,728).  The flags are kept around the load.
    (d5 is scratch between instructions.)  engine/m6809x.py's page-crossing fall-through has the same flaw."""
    out = []
    n = 0
    for i, line in enumerate(lines):
        if line.strip() == "jmp main_dispatch" and out and out[-1].strip().startswith("move.w #$") and                 out[-1].strip().endswith(",d7"):
            load = out.pop()
            out += ["	move.w sr,d5", load, "	move.w d5,ccr"]
            n += 1
        out.append(line)
    print("flags kept at %d page-crossing dispatches" % n)
    return out


def generate():
    build = build_dir("yiear")
    cover = load_cover()
    prog = program(cover)
    lines, rep, em, code = m6809x.translate(prog)
    extra = static_io_sites(code, cover[4])
    if extra:
        print("static I/O sites the coverage did not take: %s" % " ".join("%04X" % pc for pc in sorted(extra)))
        cover[4].update(extra)
        prog = program(cover)
        lines, rep, em, code = m6809x.translate(prog)
    seen = [u for u in rep["unsupported"] if int(u.split()[0], 16) in prog.exec_cover]
    if seen:
        raise RuntimeError("observed instructions cannot be translated: %s" % seen)
    lines = page_bases(lines, prog, code)
    lines = keep_flags_at_dispatch(lines)
    head = ["; generated by games/yiear/tools/gen.py (engine/m6809x.py): the main CPU", "\tsection text,code"]
    (build / "code_main.s").write_text("\n".join(head + lines) + "\n")
    (build / "tables_main.s").write_text("\n".join(dispatch_tables(prog, code)) + "\n")
    info = ["MAIN_RESET equ %s" % prog.label(RESET), "MAIN_IRQ equ %s" % prog.label(IRQ), "MAIN_NMI equ %s" % prog.label(NMI),
            "MAIN_IDLE_T equ %s_t" % prog.label(YieArPort.IDLE)]
    (build / "main_info.s").write_text("\n".join(info) + "\n")
    r = start_regs()
    (build / "start_info.s").write_text("\n".join([
        "START_A equ $%02X" % r["a"], "START_B equ $%02X" % r["b"], "START_X equ $%04X" % r["x"],
        "START_Y equ $%04X" % r["y"], "START_U equ $%04X" % r["u"], "START_S equ $%04X" % r["s"],
        "START_CCHI equ $%02X" % (r["cc"] & 0xF0), "START_CCR equ $%02X" % (r["cc"] & 0x0F)]) + "\n")
    import vlm_frames
    vf = vlm_frames.frames()
    (build / "vlm_tab.s").write_text("\n".join(["\tsection data,data", "ya_vlmf:"] + [
        "\tdc.b " + ",".join(str(x) for x in vf[i:i + 16]) for i in range(0, 256, 16)] + ["\teven"]) + "\n")
    return rep


if __name__ == "__main__":
    r = generate()
    print("instructions", r["instructions"], "unsupported", len(r["unsupported"]), "missing", len(r["missing"]),
          r["stats"])
    for u in r["unsupported"][:20]:
        print("   ", u)
