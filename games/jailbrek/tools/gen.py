"""Jail Break: the main CPU's program (KONAMI-1, 32 KB at $8000) translated to 68000 code (engine/m6809x.py).

    from gen import generate; report = generate()   -> build/jailbrek/code_main.s, tables_main.s, main_info.s

The program is flat: virtual page = slot = address >> 13.  The opcode bytes are decrypted (m6809.konami1_opcode: the
first byte and the byte after $10 / $11), the operands are plain.  The 68000 side (src/jailbrek.s): the 6809's 64 KB
are one block, jb_mem (the colour and video RAM, the sprite RAM, the RAM, the scroll RAM and the ROM at their
addresses), so every slot's VB is jb_mem: a3 (slot 0: the direct page $15xx and the stack $17xx) and a4 (slot 1) hold
the same base, and an indexed access uses a4 whatever slot it touched.  The control registers ($2040-$2047), the I/O
($3000-$6000) and the stores to the colour and video RAM (the coverage's io sites) go through main_io_r / main_io_w.
The idle point $8073 is a native (jb_idle): it delivers the NMIs and the IRQ (machine.JailBreakPort).
"""
import collections
import os
import re
import pickle
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
import m6809x
from m6809 import konami1_opcode
from machine import JailBreakPort, load
from paths import build_dir, require_coverage

RESET, IRQ, NMI = 0x81A6, JailBreakPort.IRQ, JailBreakPort.NMI
SEEDS = [int(x) for x in os.environ.get("JB_SEEDS", "").split(",") if x] or range(1, 14)
NATIVES = {JailBreakPort.IDLE: "jb_idle",
           0xAF96: "nat_sn_AF96",                     # the SN76489A write (src/sound.s)
           0x9272: "nat_9272"}                        # the sprite RAM from the objects (src/natives.s)
# a read-modify-write of the video RAM (m6809x cannot send one through the runtime): `dec $0830` runs on the memory and
# lists the cell (the video RAM's $0830 is cell $030) itself afterwards
RMW_VIDEO = {0x907B: 0x0830}
# the jump tables of the indirect JSR / JMP [A|B,X|Y|U] sites (found in the translation): every entry is code the coverage
# may not have run (a state the random play did not reach crashed Hatari at arcade frame 3176: $AA2A); the entries
# (words >= $8100 from each table's start, up to 24, until one is not a code address) are roots too
JUMP_TABLES = (0xc1be, 0xc244, 0xc24c, 0xc3f6, 0xc400, 0xc412, 0xe7ac, 0xe67b, 0xe7b2, 0xe832, 0xe9b2, 0xeb98, 0xebe5,
               0xeba0, 0xec27, 0xec31, 0xec75, 0xf955, 0xfd25)
ROM_FILES = ("507p03.11d", "507p02.9d")


def image():
    """the 64 KB the 6809 sees at power-on: zero but the ROM at $8000-$FFFF"""
    mem = bytearray(0x10000)
    for i, n in enumerate(ROM_FILES):
        mem[0x8000 + i * 0x4000:0xC000 + i * 0x4000] = load(n)
    return bytes(mem)


def table_roots(mem):
    """the jump tables' entries that decode to code the translator accepts (a few instructions' worth of flow from each:
    tables run into data, and junk raises m6809x.Unsupported)"""
    rd = lambda a: mem[a & 0xFFFF]
    rd_op = konami1_opcode(rd)

    def ok(root):
        seen, work = set(), [root]
        while work and len(seen) < 400:
            v = work.pop()
            while v not in seen:
                if not 0x8000 <= v < 0x10000:
                    return False
                seen.add(v)
                try:
                    ins = m6809x.decode(rd, v, 0x15, rd_op=rd_op)
                    m6809x.defs_uses(ins)
                except Exception:
                    return False
                if ins.target is not None and ins.flow in ('jmp', 'jcc', 'call'):
                    work.append(ins.target)
                if ins.flow in ('seq', 'jcc', 'call', 'icall'):
                    v += ins.length
                    continue
                break
        return True

    roots = set()
    for b in JUMP_TABLES:
        for i in range(24):
            w = mem[b + 2 * i] << 8 | mem[b + 2 * i + 1]
            if not 0x8100 <= w < 0xFFE0:
                break
            roots.add(w)
    return sorted(r for r in roots if ok(r))


def page_addr(p):
    return "jb_mem+$%04X" % (p << 13)


def load_cover():
    require_coverage("jailbrek", ["cover%d.pkl" % s for s in SEEDS])
    exec_ = collections.Counter()
    acc = collections.defaultdict(set)
    tg = collections.defaultdict(set)
    wraps, io = set(), set()
    returns = collections.Counter()
    for s in SEEDS:
        d = pickle.loads((build_dir("jailbrek") / ("cover%d.pkl" % s)).read_bytes())
        exec_.update(d["exec"])
        for v, x in d["acc"].items():
            acc[v] |= x
        for v, x in d["targets"].items():
            tg[v] |= x
        wraps |= d["wraps"]
        io |= {pc for pc, a, rw in d["io"]}
        w = int(os.environ.get("JB_RET_PLAY", "20")) if s == 13 else 1     # (the recorded play's returns count more: the attract's must not order the chains)
        for k, v in d.get("returns", {}).items():
            returns[k] += v * w
    return exec_, acc, tg, wraps, io, returns


def rmw_after(v, ins):
    a = RMW_VIDEO.get(v)
    if a is None:
        return None
    n = 'jb_rmw_%04X' % v
    return ['	move.w sr,-(sp)', '	moveq #0,d7', '	move.w #$%03X,d7' % (a & 0x7FF), '	lea cell_dirty,a0', '	tst.b (a0,d7.w)',
            '	bne.s %s' % n, '	st (a0,d7.w)', '	move.l cell_ptr,a0', '	move.w d7,(a0)+', '	move.l a0,cell_ptr',
            '%s:' % n, '	move.w (sp)+,ccr']


def program(cover):
    exec_, acc, tg, wraps, io, returns = cover
    io = set(io) - set(RMW_VIDEO)
    mem = image()
    # one base for every slot: an indexed access uses a4 (slot 0) whatever slot the coverage saw
    flat = {v: {(rw, 1, 1, odd) for rw, sl, pg, odd in s} for v, s in acc.items()}
    prog = m6809x.Program("main", "M", lambda p: mem[p << 13:(p + 1) << 13], {p: p for p in range(4, 8)},
                          roots=[RESET, IRQ, NMI] + sorted(NATIVES) + ([] if os.environ.get('JB_NO_TABLE_ROOTS') else table_roots(mem)), exec_cover=set(exec_), acc_cover=flat, targets=tg,
                          page_addr=page_addr, io_sites=io, wrap_sites=wraps, dp=0x15, a3_slot=0, a4_slot=1,
                          natives={v: l for v, l in NATIVES.items()
                                   if '%04X' % v not in os.environ.get('JB_NO_NATIVES', '')},
                          opcode_reader=lambda rd: konami1_opcode(rd), after=rmw_after,
                          inline_calls={} if os.environ.get('JB_NO_INLINE') else {0xAF96: ('nat_sn_AF96_i', 0x15)})
    # flat: every slot holds one page for good, so jumps, calls and returns need no page check; the 68030 forms the
    # 68000 runs too (m6809x Program.fast_forms: flags fixed through d7, returns compared most frequent first by the
    # coverage's counts of the returns to each point)
    prog.fixed_slots = tuple(range(8))
    prog.fast_forms = True
    prog.ret_weights = dict(returns) or dict(exec_)
    prog.call_summaries = True                  # (m6809x: a call's live flags from its callees' summaries)
    prog.video_inline = (0x0000, 0x1000, set(io))   # (m6809x: video RAM byte stores inline, main_io_w outside)
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


SITE_MIN = int(os.environ.get("JB_SITE_MIN", "20000"))     # (a site's returns in the recorded play's 60,000 ticks: ~ 1 every 3 frames)


def load_sites():
    """the recorded play's {site pc: {target: count}} of its returns, RTIs and indirect jumps (cover13.pkl), or {}"""
    f = build_dir("jailbrek") / "cover13.pkl"
    if not f.exists():
        return {}
    return pickle.loads(f.read_bytes()).get("sites", {})


def site_chains(lines, sites):
    """The returns, RTIs and indirect jumps of the recorded play (ref/cover.py seed 13, SiteCover): each site whose
    translation ends in the dispatcher (`jmp main_dispatch`, d7 = the target) compares its common targets inline first
    (the translator's chains are by the targets' counts overall, the same for every RTS; a miss costs ~100 cycles in the
    dispatcher, a hit here ~25).  The flags are in d5 where the translation restores them just before the jump: restored
    there too.  The targets that are labels of the translation, the most common first, up to 5 a site."""
    text = "\n".join(lines)
    labels = set(re.findall(r"^(M00[0-9A-F]{4}):", text, re.M))
    done = 0
    for pc, tg in sorted(sites.items(), key=lambda kv: -sum(kv[1].values())):
        if sum(tg.values()) < SITE_MIN:
            break
        lab = "M00%04X:" % pc
        i = text.find("\n" + lab)
        if i < 0:
            continue
        i += 1
        nxt = re.search(r"^M00[0-9A-F]{4}:", text[i + 1:], re.M)
        end = i + 1 + nxt.start() if nxt else len(text)
        block = text[i:end]
        k = block.rfind("\tjmp main_dispatch")
        if k < 0:
            continue
        flags = block[:k].endswith("\tmove.w d5,ccr\n")
        at = i + (k - len("\tmove.w d5,ccr\n") if flags else k)
        add = ""
        n = 0
        for t, c in sorted(tg.items(), key=lambda kv: -kv[1]):
            if n == 5 or c < SITE_MIN // 10:
                break
            if "M00%04X" % t not in labels or ("#$%04X,d7" % t) in block:
                continue
            n += 1
            if flags:
                add += "\tcmp.w #$%04X,d7\n\tbne.s Ls%04X_%d\n\tmove.w d5,ccr\n\tjmp M00%04X\nLs%04X_%d:\n" % (t, pc, n, t, pc, n)
            else:
                add += "\tcmp.w #$%04X,d7\n\tbeq M00%04X\n" % (t, t)
        if add:
            text = text[:at] + add + text[at:]
            done += 1
    return text.split("\n"), done


def generate():
    build = build_dir("jailbrek")
    prog = program(load_cover())
    lines, rep, em, code = m6809x.translate(prog)
    seen = [u for u in rep["unsupported"] if int(u.split()[0], 16) in prog.exec_cover]
    if seen:
        raise RuntimeError("observed instructions cannot be translated: %s" % seen)
    lines = page_bases(lines, prog, code)
    if not os.environ.get("JB_NO_SITE_CHAINS"):
        lines, n = site_chains(lines, load_sites())
        print("site chains: %d sites" % n)
    head = ["; generated by games/jailbrek/tools/gen.py (engine/m6809x.py): the main CPU", "\tsection text,code"]
    (build / "code_main.s").write_text("\n".join(head + lines) + "\n")
    (build / "tables_main.s").write_text("\n".join(dispatch_tables(prog, code)) + "\n")
    info = ["MAIN_RESET equ %s" % prog.label(RESET), "MAIN_IRQ equ %s" % prog.label(IRQ), "MAIN_NMI equ %s" % prog.label(NMI),
            "MAIN_IDLE_T equ %s_t" % prog.label(JailBreakPort.IDLE)]
    (build / "main_info.s").write_text("\n".join(info) + "\n")
    return rep


if __name__ == "__main__":
    r = generate()
    print("instructions", r["instructions"], "unsupported", len(r["unsupported"]), "missing", len(r["missing"]),
          r["stats"])
    for u in r["unsupported"][:20]:
        print("   ", u)
