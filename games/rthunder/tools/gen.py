"""DRAFT, never run (no coverage exists yet: see README, "Port schedule"): Rolling Thunder's two 6809 programs translated to
68000 code (engine/m6809x.py).  The spin-wait hook stubs and the runtime (src/core.s) are not written.

    from gen import generate; report = generate()  -> build/rthunder/code_main.s, code_sub.s, tables_*.s, hooks.s, gen_info.s

CPU 0 is `main` (prefix M, MAME's cpu1), CPU 1 `sub` (prefix S, cpu2).  The coverage (ref/cover.py --port, the
cover_p_*.pkl of build/rthunder) gives the code pages and their slots, the data slots of each access site, the spin waits
and where computed jumps and returns went.  Virtual pages (8 KB = address >> 13): 0-7 are the CPU's own slots (RAM and
I/O in 0-3, the ROM at $8000 in 4-7), and the banked ROM window of slot 3 ($6000-$7FFF) is page 8 + bank (main: the 32
banks of the expansion ROMs, bank = the $6800 write & $1F; sub: the 4 banks of its program ROM, $D803 & 3).
The 68000 side (src/core.s): `shared` is the 8 KB of RAM both CPUs see at different addresses: main slot 2 ($4000: its
first KB is the CUS30 mailbox, an I/O area for main) = sub slot 0 ($0000: its first KB is sub's own RAM, the direct
page 0 variables); the tile RAMs `vram0` (main slot 0 = sub slot 1) and `vram1` (main slot 1 = sub slot 2).

What does not run as translated instructions (the runtime, src/core.s):
  * the idle loops' BRA ($81BC main, $80A6 sub): `<cpu>_idle` tests the loop's queues; empty = the CPU's frame is done
  * the spin waits' backward branches (the SPIN set of the coverage): `<cpu>_spin_<pc>` branches back by yielding
  * every store to a semaphore byte ($5606 / $5607 of main, $1606 / $1607 of sub): `bsr <cpu>_sem_yield` after it
  * the I/O: main's reads of $4000-$43FF (the CUS30 mailbox), the stores to $6000-$FFFF (the bank, the PCM player, the
    interrupt acknowledges, the tile bank, the scroll registers, the back colour), sub's stores to $8000-$FFFF
"""
import collections
import glob
import json
import pickle
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
import m6809x
from machine import load_regions, RthunderPort
from paths import build_dir

NAMES = {0: ("main", "M"), 1: ("sub", "S")}
IRQ = {0: 0x8565, 1: 0x8173}
# idle loop: (the BRA, its target), the queues' test is the runtime's (src/core.s main_idle / sub_idle)
IDLE = {0: (0x81BC, 0x81B6), 1: (0x80A6, 0x80A3)}
DP = {0: 0x56, 1: 0x16}
SLOTS = {0: (2, 0), 1: (0, 1)}                       # a3_slot, a4_slot: the direct page and stack, the next most used
MAIN_BANKS, SUB_BANKS = 32, 4


def regions():
    return load_regions()


def page_bytes(cpu, r):
    rom = r["cpu1"] if cpu == 0 else r["cpu2"]

    def f(p):
        if p < 4:
            return bytes(0x2000)
        if p < 8:
            return rom[p * 0x2000:(p + 1) * 0x2000]
        if cpu == 0:
            b = p - 8
            return r["bankeddata"][b * 0x2000:(b + 1) * 0x2000] if b < MAIN_BANKS else bytes(0x2000)
        b = p - 8
        return rom[b * 0x2000:(b + 1) * 0x2000] if b < SUB_BANKS else bytes(0x2000)
    return f


def page_addr(cpu):
    """the 68000 address (an assembler expression) of virtual page p of a CPU"""
    names = {0: {0: "vram0", 1: "vram1", 2: "shared"}, 1: {0: "shared", 1: "vram0", 2: "vram1"}}[cpu]
    rom = "rom_main" if cpu == 0 else "rom_sub"
    banks = "banks_main" if cpu == 0 else "rom_sub"

    def f(p):
        if p in names:
            return names[p]
        if 4 <= p < 8:
            return "%s+$%X" % (rom, (p - 4) * 0x2000)
        if p >= 8:
            return "%s+$%X" % (banks, (p - 8) * 0x2000)
        return "nopage"
    return f


def load_cover():
    files = sorted(glob.glob(str(build_dir("rthunder") / "cover_p_*.pkl")))
    if not files:
        sys.exit("error: no coverage in build/rthunder: python games/rthunder/ref/cover.py SEED FRAMES --port")
    exec_ = {0: collections.Counter(), 1: collections.Counter()}
    acc = {0: collections.defaultdict(set), 1: collections.defaultdict(set)}
    ioacc = {0: collections.defaultdict(set), 1: collections.defaultdict(set)}
    tg = {0: collections.defaultdict(set), 1: collections.defaultdict(set)}
    dps = {0: collections.defaultdict(set), 1: collections.defaultdict(set)}
    wraps = {0: set(), 1: set()}
    spin = {0: set(), 1: set()}
    semw = {0: set(), 1: set()}
    for f in files:
        d = pickle.load(open(f, "rb"))
        for i in (0, 1):
            exec_[i].update(d["exec"][i])
            for (v, slot), s in d["acc"][i].items():
                acc[i][v] |= s
            for (v, slot), s in d["ioacc"][i].items():
                ioacc[i][v] |= s
            for (v, slot), s in d["targets"][i].items():
                tg[i][v] |= s
            for (v, slot), s in d["dp"][i].items():
                dps[i][v] |= s
            wraps[i] |= {v for v, slot in d["wrap"][i]}
            spin[i] |= d["spin"][i]
            semw[i] |= d["semw"][i]
    return dict(exec=exec_, acc=acc, ioacc=ioacc, tg=tg, dps=dps, wraps=wraps, spin=spin, semw=semw, files=len(files))


def io_sites(cpu, ioacc):
    """the sites that go through the runtime's <cpu>_io_r / _io_w"""
    out = set()
    for v, s in ioacc.items():
        for rw, a in s:
            if cpu == 0 and (a >= 0x6000 and rw == "w" or 0x4000 <= a < 0x4400):
                out.add(v)
            if cpu == 1 and a >= 0x6000 and rw == "w":
                out.add(v)
    return out


def program(cpu, r, cov):
    name, prefix = NAMES[cpu]
    exec_ = cov["exec"][cpu]
    slot_of = {}
    for (v, slot) in exec_:
        p = v >> 13
        if slot_of.setdefault(p, slot) != slot:
            raise RuntimeError("%s: page %X runs from slots %d and %d" % (name, p, slot_of[p], slot))
    for v, s in cov["dps"][cpu].items():
        if s != {DP[cpu]}:
            raise RuntimeError("%s: %06X runs with DP %s" % (name, v, sorted(s)))
    idle_pc, idle_head = IDLE[cpu]
    hooks = {idle_pc: "%s_idle" % name}
    hook_next = {idle_pc: idle_head}
    for pc in sorted(cov["spin"][cpu]):
        hooks[pc] = "%s_spin_%04X" % (name, pc)
        hook_next[pc] = None
    semw = cov["semw"][cpu]

    def after(v, ins):
        if v in semw:
            return ["bsr %s_sem_yield" % name]
        return None
    ios = io_sites(cpu, cov["ioacc"][cpu])
    a3, a4 = SLOTS[cpu]
    prog = m6809x.Program(name, prefix, page_bytes(cpu, r), slot_of, roots=[IRQ[cpu], idle_pc],
                          exec_cover={v for v, s in exec_}, acc_cover=cov["acc"][cpu], targets=cov["tg"][cpu],
                          hooks=hooks, page_addr=page_addr(cpu), io_sites=ios, after=after, nf_dispatch=True,
                          wrap_sites=cov["wraps"][cpu], pid_checks=True, dp=DP[cpu], a3_slot=a3, a4_slot=a4)
    prog.hook_next = {k: v for k, v in hook_next.items() if v is not None}
    prog.fast_forms = True
    prog.call_summaries = True
    prog.fixed_slots = (4, 5, 6, 7)
    return prog


def generate():
    r = regions()
    cov = load_cover()
    build = build_dir("rthunder")
    (build / "rom_main.bin").write_bytes(r["cpu1"][0x8000:0x10000])
    (build / "rom_sub.bin").write_bytes(r["cpu2"])
    (build / "banks_main.bin").write_bytes(r["bankeddata"])
    report = {}
    info = []
    for cpu in (0, 1):
        prog = program(cpu, r, cov)
        lines, rep, em, code = m6809x.translate(prog)
        name = prog.name
        head = ["; generated by games/rthunder/tools/gen.py (engine/m6809x.py): the %s CPU" % name, "\tsection text,code"]
        (build / ("code_%s.s" % name)).write_text("\n".join(head + lines) + "\n")
        info += ["%s_IRQ_LABEL equ %s" % (name.upper(), prog.label(IRQ[cpu]))]
        report[name] = rep
        report[name]["pages"] = sorted("%X:%d" % (p, s) for p, s in prog.slot_of.items())
    (build / "gen_info.s").write_text("\n".join(info) + "\n")
    report["coverage files"] = cov["files"]
    return report


if __name__ == "__main__":
    rep = generate()
    for name in ("main", "sub"):
        r = rep[name]
        print(name, "instructions", r["instructions"], "unsupported", len(r["unsupported"]), "missing", len(r["missing"]),
              r["stats"], r["pages"])
        for u in r["unsupported"][:20]:
            print("   ", u)
