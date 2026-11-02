"""Mr. HELI's main CPU program (V30) translated to 68000 code (engine/v30x.py), R-Type's way (games/rtype/tools/gen.py).

    from gen import generate; report = generate()     -> build/mrheli/code_main.s, tables_main.s, gen_info.s, rom_image.bin

The coverage (ref/cover.py, build/mrheli/cover_*.pkl) gives the code (each address with its CS), the odd word sites, the
I/O sites and where computed jumps, calls and returns went.  What random play misses is taken from the program, as for
R-Type: jump tables in ROM (table_targets), the object handlers it stores into [reg + d] for CALL [reg + d]
(stored_handlers), every code address it stores as an immediate word, the C7 46 00 idiom's bytes and the code right
after a RET or a jump that nothing refers to: translated as roots, known to the dispatcher.  Leaf calls and inlining
(engine/v30x.py) are on; no natives yet (NATIVES / LEAF_CALLS: Mr. HELI's own, from tools/profile.py).
The 68000 side (src/core.s): v30_image, the V30's 1 MB with the bytes of each word swapped (rom_image.bin is the ROM
$00000-$7FFFF in that order, copied in at the start; the work RAM at $A0000, the MCU's dual-port RAM at $B0000); the
ports: in_ports (IN0, IN1, DSW: words, active low), m72_scroll (FG y, FG x, BG y, BG x), m72_raster, m72_port02, the
two sound latches (ports $00 and $C0) and the sprite DMA through runtime routines.  The boot (the ROM and RAM tests,
the code the MCU puts into the dual-port RAM) is not translated: the port starts from the reference's state
(tools/machine.py START); the code at B000:xxxx (outside the ROM) is left out by code_limit.
"""
import collections
import glob
import json
import os
import pickle
import sys
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
import v30x
from m72board import load_regions
from machine import IDLE, VBL_VECTOR, RASTER_VECTOR
from paths import build_dir

GAME = "mrheli"
NAME, PREFIX = "main", "R"
ROM_END = 0x80000
MCU_CODE = (0xB0000, 0x0C3F, 31)  # (the MCU's command $10 copies its ROM $0C3F-$0C5D to the dual-port RAM's start; the
#                                   main CPU calls it at B000:0000 from 0040:1ED9 a frame later: translated as code
#                                   there - docs/mcu-interface.md)
NATIVES = {}                      # (hand-written replacements, src/natives.s: none yet)
LEAF_CALLS = {}                   # (CALLs to these: a JSR; none yet)
# LAHF sites whose AH the program reads only in its C bit (bit 0): 0040:28E4 (AH = PSW; ROLC; NOT AH; SAHF; ROLC;
# AND AW,3), 0040:C707 / C713 (AH = PSW; XOR AH,AL; XCH; AND AW,1) - the liveness asks C of the code before, not AC
FLAG_USES = {0x02CE4: v30x.C, 0x0CB07: v30x.C, 0x0CB13: v30x.C}
ANY_PARITY = (0, 0)               # (linear: code whose computed addresses take either parity - load_cover)
NEAR = 0x1000                     # (jump table entries this far from the seen ones count: tools/gen.py table_targets)


def load_cover():
    files = sorted(glob.glob(str(build_dir(GAME) / "cover_*.pkl")))
    if not files:
        sys.exit("error: no coverage in build/mrheli: python games/mrheli/ref/cover.py SEED FRAMES")
    exec_ = collections.Counter()
    acc = collections.defaultdict(set)
    tg = collections.defaultdict(set)
    io = collections.defaultdict(set)
    segs = collections.defaultdict(set)
    bpar = collections.defaultdict(set)
    complete = True
    for f in files:
        d = pickle.load(open(f, "rb"))
        exec_.update(d["exec"])
        for (cs, ip), s in d["acc"].items():
            acc[v30x.lin_of(cs, ip)] |= s
        for (cs, ip), s in d["targets"].items():
            tg[v30x.lin_of(cs, ip)] |= s
        for (cs, ip), s in d["io"].items():
            io[v30x.lin_of(cs, ip)] |= s
        for (cs, ip), s in d["segs"].items():
            segs[v30x.lin_of(cs, ip)] |= s
        for (cs, ip), s in d.get("bpar", {}).items():
            bpar[v30x.lin_of(cs, ip)] |= s
        complete = complete and "bpar" in d
    # (the byte parities only when every coverage file has them: one without could have seen the other parity)
    bpar = bpar if complete else {}
    # the ranking and name entry (ANY_PARITY): the byte accesses' parity tested at run time (any_parity)
    for lin in [l for l in bpar if ANY_PARITY[0] <= l < ANY_PARITY[1]]:
        bpar.pop(lin)
    return exec_, acc, tg, io, segs, bpar


def any_parity(acc):
    """the access coverage for the translator's parity choices: the ranking and name entry (0040:1000-1B40, records of
    11 bytes from 2F51h) take a rank's words at either parity, and the coverage saw only some ranks (a word store at an
    odd address: an address error on the STE, 2026-11-01) - every word access there, seen or not, may be odd (the
    store marks keep the coverage as it is)"""
    out = dict(acc)
    for lin in range(*ANY_PARITY):
        out[lin] = set(acc.get(lin, ())) | {("r", 2, "ram", False), ("r", 2, "ram", True)}
    return out


def code_limit(lin):
    """the program's code: the ROM and the MCU's protection check at B000:0000 (not the boot's code there)"""
    return lin < ROM_END or MCU_CODE[0] <= lin < MCU_CODE[0] + MCU_CODE[2]


def with_mcu_code(regions):
    """the main CPU's view for the translator: the ROM, and the MCU's code at $B0000"""
    main = bytearray(regions["main"])
    a, src, n = MCU_CODE
    main[a:a + n] = regions["mcu"][src:src + n]
    return dict(regions, main=bytes(main))


def vector(rom, n):
    return rom[4 * n + 2] | (rom[4 * n + 3] << 8), rom[4 * n] | (rom[4 * n + 1] << 8)


def port_in(p, w):
    """IN with an immediate port: IN0 IN1 DSW from the runtime's words"""
    if p < 6:
        if w == 2 and not p & 1:
            return ["move.w in_ports+%d,d0" % p]
        if w == 1:
            return ["move.b in_ports+%d,d0" % (p ^ 1)]
    return None


def port_out(p, w):
    """OUT with an immediate port: the scroll registers and the raster line as words, the rest through routines"""
    if p == 0xC0 and w == 1:
        return ["jsr m72_sound_latch2"]
    if p == 0x00 and w == 1:
        return ["jsr m72_sound_latch"]
    if w != 2 or p & 1:
        return None
    if 0x80 <= p <= 0x86:
        return ["move.w d0,m72_scroll+%d" % (p - 0x80)]
    if p == 0x06:
        return ["move.w d0,m72_raster"]
    if p == 0x02:
        return ["move.w d0,m72_port02"]
    if p == 0x04:
        return ["jsr m72_sprite_dma"]
    if p == 0x00:
        return ["jsr m72_sound_latch"]
    if p in (0x40, 0x42):
        return []                                   # (the uPD71059: the port delivers the interrupts itself)
    return None


MARKS = ("v30_image+$C8000", 0x18000, "v30_vmarks", 6)  # (the palettes and the video RAMs: 64-byte blocks, as
#                                                           R-Type's)
WATCHED = ("fg", "bg", "pal")


def store_marks(acc):
    """the stores the renderer must see (src/video.s): the sites the coverage saw writing the video RAMs or the
    palettes, and every store site the coverage never saw (its target is unknown)"""
    sites = {lin for lin, s in acc.items() if any(rw == "w" and reg in WATCHED for rw, w, reg, odd in s)}

    def pred(lin, ins):
        return lin in sites or lin not in acc
    return (pred,) + MARKS


def rom_image(regions=None):
    """the ROM ($00000-$7FFFF) with the bytes of each word swapped: as the 68000 reads words"""
    rom = (regions or load_regions(GAME))["main"][:ROM_END]
    out = bytearray(len(rom))
    out[0::2] = rom[1::2]
    out[1::2] = rom[0::2]
    return bytes(out)


TRUSTED = {"starts": set(), "inside": set()}       # (the code the coverage reaches: plausible() checks against it)
ODD_OPS = {"invalid", "halt", "int", "into", "brkem", "chkind", "buslock", "poll", "prepare", "dispose", "adjba",
           "adjbs", "salc", "inm", "outm", "lahf", "sahf", "pushf", "popf"}


def plausible(rd, cs, ip, n=4):
    """an IP in a table or after a RET could be code: inside the program, its straight line of instructions
    decodes to ordinary ones until a transfer or code the coverage reached (within 256), and never starts inside an
    instruction of that code (n: unused, kept for the callers)"""
    from v30dec import decode
    for _ in range(256):
        lin = v30x.lin_of(cs, ip)
        if not 0x400 <= lin < ROM_END or lin in TRUSTED["inside"]:
            return False
        if lin in TRUSTED["starts"]:
            return True
        ins = decode(rd, cs, ip)
        if ins.mn in ODD_OPS or ins.mn == "nop" and ins.op != 0x90 or ins.flow in ("halt", "int"):
            return False
        if ins.mn in ("in", "out") and ins.ops[1][0] != "i":
            return False
        if ins.flow not in ("seq", "jcc", "call", "icall"):
            return True
        ip = (ip + ins.length) & 0xFFFF
    return False


def table_targets(rom, sites, tg, known, segs, masks):
    """jump tables the random play did not exhaust -> {linear: set of (cs, ip)}.  A computed call / jump through
    memory (one register + a displacement, its segment the one value the coverage saw): the table at segment * 16 +
    displacement: its slots (as many as an AND of the index register before allows, else up to 16 beyond the last one
    the coverage saw) that hold known code or a plausible entry.  Through a register loaded from ROM just before: the ROM's runs of plausible words that hold at least two
    of the targets seen."""
    rd = lambda a: rom[a & 0xFFFFF]
    w = lambda q: rom[q] | (rom[q + 1] << 8)
    out = collections.defaultdict(set)
    cache = {}

    def ok(cs, ip):
        if (cs, ip) in known:
            return True
        if (cs, ip) not in cache:
            cache[(cs, ip)] = plausible(rd, cs, ip, 6)
        return cache[(cs, ip)]
    where = collections.defaultdict(list)
    for p in range(0, ROM_END - 1):
        where[w(p)].append(p)
    for lin, (cs, o, segreg) in sites.items():
        seen = {ip for c, ip in tg.get(lin, ()) if c == cs}
        if not seen:
            continue
        if o is not None:
            vals = {sv[segreg] for sv in segs.get(lin, ())} if segreg is not None else {cs}
            if len(vals) != 1:
                continue
            base = (next(iter(vals)) << 4) + o[2]
            slots = [k for k in range(256) if base + 2 * k + 1 < ROM_END and w(base + 2 * k) in seen]
            if not slots:
                continue
            size = masks.get(lin)
            for k in range(size if size else max(slots) + 16):
                q = base + 2 * k
                if q + 1 >= ROM_END:
                    break
                if ok(cs, w(q)):
                    out[lin].add((cs, w(q)))
                elif k > max(slots):
                    break
            continue
        for tip in seen:
            for p in where.get(tip, ())[:16]:
                run = []
                for step in (2, -2):
                    q = p + (step if step < 0 else 0)
                    for _ in range(128):
                        if not 0 <= q < ROM_END - 1 or not ok(cs, w(q)):
                            break
                        run.append(w(q))
                        q += step
                if len(seen & set(run)) >= 2:
                    out[lin] |= {(cs, x) for x in run}
    return out


def stored_handlers(rom, code_ins, icall_sites):
    """object handlers: a computed call / jump through RAM ([reg + d]) goes where the program stores immediates into
    [reg' + d] (MOV word ptr [bp+0h], imm: the object's next state) -> {linear: set of (cs, ip)}"""
    rd = lambda a: rom[a & 0xFFFFF]
    by_disp = collections.defaultdict(set)
    for lin, ins in code_ins.items():
        if ins.mn == "mov" and ins.w == 2 and ins.ops[0][0] == "m" and ins.ops[0][1] and ins.ops[1][0] == "i":
            by_disp[ins.ops[0][2]].add((ins.cs, ins.ops[1][1]))
    out = collections.defaultdict(set)
    for lin, (cs, o) in icall_sites.items():
        for c, ip in by_disp.get(o[2], ()):
            if c == cs and plausible(rd, cs, ip, 6):
                out[lin].add((cs, ip))
    return out


def program(regions, cover):
    exec_, acc, tg, io, segs, bpar = cover
    rom = regions["main"]
    rd = lambda a: rom[a & 0xFFFFF]
    from v30dec import decode
    sites = {}
    masks = {}
    prev = {}
    for (cs, ip) in exec_:
        ins = decode(rd, cs, ip)
        prev[v30x.next_lin(ins)] = (v30x.lin_of(cs, ip), ins)
    rom_read = lambda lin: any(rw == "r" and reg == "rom" for rw, w, reg, odd in acc.get(lin, ()))
    for (cs, ip) in exec_:
        lin = v30x.lin_of(cs, ip)
        ins = decode(rd, cs, ip)
        if not code_limit(lin) or ins.flow not in ("ijmp", "icall"):
            continue
        # a table in ROM: the target read from ROM here, or loaded into the register from ROM just before
        o = ins.ops[0]
        if o[0] == "m" and rom_read(lin) and len(o[1]) <= 1:
            seg = o[3]
            sites[lin] = (cs, o, {0: 1, 2: 2, 3: 0}.get(seg) if seg != 1 else None)
            u = lin
            for _ in range(4):                          # (AND reg, imm before: the table's size)
                if u not in prev:
                    break
                u, pi = prev[u]
                if o[1] and pi.mn == "and" and pi.ops[0] == ("r", o[1][0], 2) and pi.ops[1][0] == "i":
                    masks[lin] = (pi.ops[1][1] & 0xFFFE) // 2 + 1
                    break
        elif o[0] == "r" and lin in prev:
            u, pi = prev[lin]
            if pi.mn == "mov" and pi.ops[0] == ("r", o[1], 2) and pi.ops[1][0] == "m" and rom_read(u):
                sites[lin] = (cs, None, None)
    trusted = v30x.discover(v30x.Program(NAME, PREFIX, rd, roots=[vector(rom, VBL_VECTOR), vector(rom, RASTER_VECTOR),
                                                                  IDLE],
                                         exec_cover={k for k in exec_ if code_limit(v30x.lin_of(*k))}, targets=tg,
                                         code_limit=code_limit))[0]
    TRUSTED["starts"] = set(trusted)
    TRUSTED["inside"] = {lin + k for lin, ins in trusted.items() for k in range(1, ins.length)} - set(trusted)
    extra = table_targets(rom, sites, tg, set(exec_), segs, masks)
    seen = tg
    tg = {k: set(v) for k, v in tg.items()}
    for k, v in extra.items():
        tg.setdefault(k, set()).update(v)
    # computed calls through RAM: the handlers the program stores (a first discovery finds the stores)
    probe = v30x.Program(NAME, PREFIX, rd, roots=[vector(rom, VBL_VECTOR), vector(rom, RASTER_VECTOR), IDLE],
                         exec_cover={k for k in exec_ if code_limit(v30x.lin_of(*k))}, targets=tg,
                         code_limit=code_limit)
    found = v30x.discover(probe)[0]
    ram_sites = {lin: (ins.cs, ins.ops[0]) for lin, ins in found.items()
                 if ins.flow in ("icall", "ijmp") and ins.ops[0][0] == "m" and ins.ops[0][1] and not rom_read(lin)}
    for k, v in stored_handlers(rom, found, ram_sites).items():
        tg.setdefault(k, set()).update(v)
    # any code address the program stores as an immediate word (a handler copied around before it is called):
    # translated and known to the dispatcher (roots), without bearing on the liveness
    stored = {(ins.cs, ins.ops[1][1]) for ins in found.values() if ins.mn == "mov" and ins.w == 2
              and ins.ops[0][0] == "m" and ins.ops[1][0] == "i" and ins.cs == 0x0040
              and plausible(rd, ins.cs, ins.ops[1][1], 6) and (ins.cs, ins.ops[1][1]) not in exec_}
    # the object handler idiom anywhere in the main segment's bytes (code discovery has not reached yet):
    # MOV word ptr [bp+0h], imm  (C7 46 00 lo hi)
    for a in range(0x400, 0x10400 - 4):
        if rom[a] == 0xC7 and rom[a + 1] == 0x46 and rom[a + 2] == 0:
            ip = rom[a + 3] | (rom[a + 4] << 8)
            if (0x0040, ip) not in exec_ and plausible(rd, 0x0040, ip, 6):
                stored.add((0x0040, ip))
    # functions nothing in the program refers to directly (their address in a ROM table copied around): code that
    # starts right after a RET or an unconditional jump, a few rounds
    for _ in range(3):
        probe.roots = probe.roots + sorted(stored)
        found = v30x.discover(probe)[0]
        more = set()
        for lin, ins in found.items():
            if ins.flow in ("ret", "jmp", "iret", "retf") and ins.cs == 0x0040:
                ip = (ins.ip + ins.length) & 0xFFFF
                if v30x.lin_of(ins.cs, ip) not in found and code_limit(v30x.lin_of(ins.cs, ip)) and \
                        plausible(rd, ins.cs, ip, 6):
                    more.add((ins.cs, ip))
        if not more - stored:
            break
        stored |= more
    vbl, raster = vector(rom, VBL_VECTOR), vector(rom, RASTER_VECTOR)
    idle_lin = v30x.lin_of(*IDLE)
    roots = [vbl, raster, IDLE] + ([] if os.environ.get("NO_STORED_ROOTS") else sorted(stored))
    prog = v30x.Program(NAME, PREFIX, rd, roots=roots,
                        exec_cover={k for k in exec_ if code_limit(v30x.lin_of(*k))},
                        acc_cover=any_parity(acc), targets=tg, targets_seen=seen, io_cover=io, ip_table_cs=0x0040,
                        exec_counts={v30x.lin_of(*k): n for k, n in exec_.items()}, hooks={idle_lin: "main_idle"},
                        natives={} if os.environ.get("NO_NATIVES") else NATIVES,
                        leaf_calls={} if os.environ.get("NO_NATIVES") else LEAF_CALLS,
                        inline_calls=not os.environ.get("NO_INLINE"),
                        byte_parity={} if os.environ.get("NO_BYTE_PARITY") else bpar,
                        hook_next={idle_lin: idle_lin}, port_in=port_in, port_out=port_out, code_limit=code_limit,
                        store_marks=None if os.environ.get("NO_MARKS") else store_marks(acc),
                        flag_uses=FLAG_USES,
                        pal_sites={lin for lin, a in acc.items() if any(rw == "r" and reg == "pal"
                                                                       for rw, w, reg, odd in a)})
    return prog, vbl, raster, idle_lin


def generate():
    regions = load_regions(GAME)
    cover = load_cover()
    build = build_dir(GAME)
    (build / "rom_image.bin").write_bytes(rom_image(regions))
    prog, vbl, raster, idle_lin = program(with_mcu_code(regions), cover)
    lines, rep, em, code, entries = v30x.translate(prog)
    head = ["; generated by games/mrheli/tools/gen.py (engine/v30x.py): the main CPU", "\tsection text,code"]
    if os.environ.get("NO_NATIVES"):        # the natives' fallbacks (src/natives.s jumps to them) are the translation
        head += ["R%05X_t\tequ\tR%05X" % (a, a) for a in sorted(set(NATIVES) | {k if isinstance(k, int) else k[0] for k in LEAF_CALLS})]
    (build / "code_main.s").write_text("\n".join(head + lines) + "\n")
    tab = ["\tsection data,data"] + v30x.dispatch_table(prog, entries)
    ips = [e for e in entries if code[e].cs == 0x0040]
    tab += ["\teven", "main_ip_entries:\tdc.w %d" % len(ips)]
    tab += ["\tdc.w $%04X\n\tdc.l %s" % ((e - 0x400) & 0xFFFF, prog.label(e)) for e in ips]
    (build / "tables_main.s").write_text("\n".join(tab) + "\n")
    idle_flags = em.live_in.get(idle_lin, v30x.ALLF)
    info = ["VBL_LABEL equ %s" % prog.label(v30x.lin_of(*vbl)),
            "RASTER_LABEL equ %s" % prog.label(v30x.lin_of(*raster)),
            "IDLE_CONT equ %s_t" % prog.label(idle_lin),
            "IDLE_CS equ $%04X" % IDLE[0], "IDLE_IP equ $%04X" % IDLE[1]]
    (build / "gen_info.s").write_text("\n".join(info) + "\n")
    (build / "gen_info.json").write_text(json.dumps({"idle_flags": idle_flags}))
    rep["idle_flags"] = idle_flags
    return rep


if __name__ == "__main__":
    r = generate()
    print("instructions", r["instructions"], "entries", r["entries"], "unsupported", len(r["unsupported"]),
          "missing", len(r["missing"]), r["stats"])
    for u in r["unsupported"]:
        print("   ", u)
