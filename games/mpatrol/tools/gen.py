"""Moon Patrol: the main Z80 program (16 KB, flat) translated to 68000 code.

    python gen.py   ->  build/mpatrol/code_mpatrol.s (+ translation.json)

Coverage: build/mpatrol/cover<seed>.pkl (ref/cover.py, the port's schedule).  The runtime (src/mpatrol.s) delivers
the IRQ (RST 38) at the idle hooks (machine.MoonPatrolPort.HOOKS) and waits inside the handler at its IRQ_WAITS: a
hook calls z80_hook (d7 = pc), which returns to go on, or delivers the IRQ with TOKEN as its return address, or (an
IRQ wait) waits for the next arcade frame and returns.

The memory-mapped I/O lives in the Z80 block, so static and indirect reads need nothing: the runtime keeps IN0, IN1,
IN2, DSW1, DSW2 at $D000-$D004 (the program reads $D000-$D004 only, also through (de) and (hl)), and the protection
byte at $8800 (computed when port $40 is written).  The three stores to the latches (`ld ($D000),a`: the sound
command, `ld ($D001),a`: the flip latch) are followed by `bsr mp_sound` / `bsr mp_flip` (config write hooks), which
take A and put the input byte back.  The sprite RAM ($C800-$C8FF, filled by ldir) is plain memory: the program never
reads it.  The I/O ports (`out ($C0),a`, `out (c),a`, `outi`): mp_out_* routines store the byte into io_regs by
port >> 5 (0 the text scroll, 2 / 3 background 1 x / y, 4 / 5 background 2 x / y, 6 the control); they keep the
registers and the flags, but outi, whose flags come from B as the Z80's.  The stores to the text RAM ($8000-$87FF,
the coverage's write sites) are plain too; the renderer will compare the RAM with its copy (or get marks, later).
"""
from pathlib import Path
import sys
import pickle
import json
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
import z80x
import discover
from translate import compile_code
from paths import build_dir, require_coverage
from machine import MoonPatrolPort, load

BUILD = build_dir("mpatrol")
HOOKS = sorted(set(MoonPatrolPort.HOOKS) | set(MoonPatrolPort.IRQ_WAITS))
TOKEN = MoonPatrolPort.TOKEN
SEEDS = range(1, 10)
SERVICE = range(0x3300, 0x3A00)        # the service mode (DSW2 bit 7): not translated (z80_badpc)
# The jump tables of the three computed jumps (the porting guide: every entry of a translated `jp (hl)`'s table), as
# (table, first entry, entries); the coverage did not run them all:
#   020C  rst $28 at 01FF, the object types ((ix+0) - 1): 49 words up to the code at 026E (22-26 never ran);
#   02D3  the work loop's task queue (02C1: (ix+0) * 2): 1-11 (0 is never taken: 0298 sla c; jr nz; 12 is $0000, the end;
#         2-8, the text tasks, never ran);
#   08F5  08EC (indexed by c): 24 words up to the code at 0925 (19 never ran).
TABLES = [(0x020C, 0, 49), (0x02D3, 1, 11), (0x08F5, 0, 24)]


def image():
    rom = b"".join(load(n) for n in ("mpa-1.3m", "mpa-2.3l", "mpa-3.3k", "mpa-4.3j"))
    return rom + bytes(0x10000 - len(rom))


def coverage():
    require_coverage("mpatrol", ["cover%d.pkl" % s for s in SEEDS])
    pcs, jumps, writes, io = set(), set(), set(), set()
    for s in SEEDS:
        d = pickle.loads((BUILD / ("cover%d.pkl" % s)).read_bytes())
        pcs |= d["pcs"]
        jumps |= d["jumps"]
        writes |= d["writes"]
        io |= d["io"]
    return pcs, jumps, writes, io


class MEmitter(z80x.Emitter):
    def x_out(self, ins):
        dst, src = ins.ops
        if src != ("r8", "a"):
            raise z80x.Unsupported("out " + ins.text)
        if dst[0] == "port":
            self.e("bsr mp_out_%02x" % ((dst[1] & 0xFF) >> 5 << 5))     # (A in d0; keeps the flags)
        elif dst == ("ind", "bc", 0):
            self.e("bsr mp_out_c")                                       # (the port is C: d1's high byte)
        else:
            raise z80x.Unsupported("out " + ins.text)

    def x_outi(self, ins):
        """(hl) to port C, hl + 1, b - 1, the flags as MAME's Z80: S and Z from b, N set, C the carry of (hl) + l
        (the new l)"""
        if self.lo & ~(z80x.S | z80x.Z | z80x.C | z80x.N):
            raise z80x.Unsupported("flags after outi: %02X" % self.lo)
        self.e("bsr mp_outi")                 # (returns with N, Z of b - 1 and C of (hl) + l in the CCR)
        self.flags(z80x.S | z80x.Z | z80x.C, const_set=z80x.N)

    def x_in(self, ins):
        raise z80x.Unsupported("in " + ins.text)   # (the M52 has no input ports)


def generate():
    rom = image()
    pcs, jumps, writes, io = coverage()
    pcs = {p for p in pcs if p not in SERVICE}
    roots = {0, 0x38} | set(HOOKS) | jumps
    for t, first, n in TABLES:
        roots |= {rom[t + 2 * k] | rom[t + 2 * k + 1] << 8 for k in range(first, first + n)}
    cache = {}
    while True:
        code, tables = discover.discover(rom, sorted(roots | pcs), known=pcs, rst28_tables=False, hl_tables=True)
        code = {pc: ins for pc, ins in code.items() if pc < 0x4000 and pc not in SERVICE}
        missing = discover.skip_returns(rom, code, lambda pc: pc < 0x4000 and pc not in SERVICE, cache) - set(code)
        if not missing:
            break
        roots |= missing
    cfg = z80x.Config(mode="signed", block=0x10000, table_entries=0x10000, iyaddr=0xF7F0, fshadow=0xF7F2,
                      io_read_redirect={},
                      write_hooks=[(0xD000, 0xD000, "mp_sound", None), (0xD001, 0xD001, "mp_flip", None)],
                      nmi_token=TOKEN, token_sym="z80_irq_ret", rst28_tables=False, bit_s=True, **z80x.FAST)
    joins = set(roots)
    for nxt, targets in tables.values():
        joins |= set(targets)
    em = compile_code(code, joins, cfg, set(HOOKS), emitter=MEmitter, ijmp_flags=True, flags_at=set(HOOKS))
    seen = [u for u in em.unsupported if u[0] in pcs]
    if seen:
        raise RuntimeError("observed instructions cannot be translated: %s" % seen)
    out = ["; generated: Moon Patrol main Z80 -> 68000 (games/mpatrol/tools/gen.py)", "\tsection text,code"]
    out += em.lines
    missing = sorted(p for p in em.refs if p not in code)
    for p in missing:
        out += ["Z%04X:\tmove.w #$%04X,d7" % (p, p), "\tjmp z80_badpc"]
    out += ["\tsection data,data"] + dispatch_table(code, em)
    report = {"instructions": len(code), "unsupported": em.unsupported, "missing": ["%04X" % p for p in missing],
              "tables": {"%04X" % k: ["%04X" % t for t in v[1]] for k, v in tables.items()},
              "jumps": len(jumps), "io": sorted(io)}
    return "\n".join(out) + "\n", report, code


def dispatch_table(code, em):
    """a long per Z80 address in byte-swapped order (the word a ret reads from the Z80 stack): the translated label,
    z80_irq_ret for TOKEN, else z80_badpc (Kung-Fu Master's layout)"""
    labels = {p: "Z%04X" % p for p in code if p not in em.no_entry}
    labels[TOKEN] = "z80_irq_ret"
    rows, run = ["\tcnop 0,4", "z80_dispatch_sw:"], 0
    for swapped in range(65536):
        label = labels.get(((swapped & 255) << 8) | (swapped >> 8))
        if label is None:
            run += 1
            continue
        if run:
            rows.append("\tdcb.l %d,z80_badpc" % run)
            run = 0
        rows.append("\tdc.l %s" % label)
    if run:
        rows.append("\tdcb.l %d,z80_badpc" % run)
    return rows


if __name__ == "__main__":
    text, report, _ = generate()
    (BUILD / "code_mpatrol.s").write_text(text)
    (BUILD / "translation.json").write_text(json.dumps(report, indent=1) + "\n")
    print({k: v for k, v in report.items() if k not in ("unsupported", "tables", "io")}, len(report["unsupported"]),
          "unsupported")
