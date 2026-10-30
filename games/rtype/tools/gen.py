"""R-Type's main CPU program (V30) translated to 68000 code (engine/v30x.py).

    from gen import generate; report = generate()     -> build/rtype/code_main.s, tables_main.s, gen_info.s, rom_image.bin

The coverage (ref/cover.py, build/rtype/cover_*.pkl) gives the code (each address with its CS), the odd word sites, the
I/O sites and where computed jumps, calls and returns went.  What random play misses is taken from the program: jump
tables in ROM (table_targets), the object handlers it stores into [reg + d] for CALL [reg + d] (stored_handlers), every
code address it stores as an immediate word and the code right after a RET or a jump that nothing refers to (functions
reached through ROM tables copied to RAM): translated as roots, known to the dispatcher.  The 68000 side (src/core.s): v30_image, the V30's 1 MB
with the bytes of each word swapped (rom_image.bin is the ROM in that order, copied in at the start); the ports:
in_ports (IN0, IN1, DSW: words, active low), m72_scroll (FG y, FG x, BG y, BG x), m72_raster, m72_port02, the sound
latch and the sprite DMA through runtime routines.  The boot (the ROM and RAM tests, the sound CPU's program) is not
translated (code_limit leaves out the $3F000 segment): the port starts from the reference's state (tools/machine.py
START).
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

NAME, PREFIX = "main", "R"
# hand-written replacements (src/natives.s): linear address -> label
NATIVES = {0x05784: "nat_fade_a", 0x05836: "nat_fade_b",          # the palette fade's inner loop (FADE_SNAP)
           0x01FCC: "nat_emit1", 0x0201B: "nat_emit2", 0x020A6: "nat_emit3",    # the sprite emitters
           0x01FE9: "nat_emit1f",                                   # (one entry into a fixed slot)
           0x00A53: "nat_fill",                                     # (the unused slots blanked)
           0x0F960: "nat_coll24", 0x0F948: "nat_coll3",             # the collision scans
           0x0226C: "nat_fgtile", 0x022B5: "nat_bgtile",            # the tiles under an object
           0x05CB0: "nat_glow", 0x1000A: "nat_blink"}               # (STAGE: the colour animations off)
NEAR = 0x1000                     # (jump table entries this far from the seen ones count: tools/gen.py table_targets)


def load_cover():
    files = sorted(glob.glob(str(build_dir("rtype") / "cover_*.pkl")))
    if not files:
        sys.exit("error: no coverage in build/rtype: python games/rtype/ref/cover.py SEED FRAMES")
    exec_ = collections.Counter()
    acc = collections.defaultdict(set)
    tg = collections.defaultdict(set)
    io = collections.defaultdict(set)
    segs = collections.defaultdict(set)
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
    return exec_, acc, tg, io, segs


def code_limit(lin):
    """the program's code: the ROM without the boot segment ($3F000-$3FFFF: the tests, the sound CPU's upload)"""
    return lin < 0x3F000


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


MARKS = ("v30_image+$C8000", 0x18000, "v30_vmarks")     # (the palettes and the video RAMs: 256-byte blocks)
WATCHED = ("fg", "bg", "pal")


def store_marks(acc):
    """the stores the renderer must see (src/video.s): the sites the coverage saw writing the video RAMs or the
    palettes, and every store site the coverage never saw (its target is unknown)"""
    sites = {lin for lin, s in acc.items() if any(rw == "w" and reg in WATCHED for rw, w, reg, odd in s)}

    def pred(lin, ins):
        return lin in sites or lin not in acc
    return (pred,) + MARKS


def rom_image(regions=None):
    """the ROM ($00000-$3FFFF) with the bytes of each word swapped: as the 68000 reads words"""
    rom = (regions or load_regions("rtype"))["main"][:0x40000]
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
        if not 0x400 <= lin < 0x3F000 or lin in TRUSTED["inside"]:
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
    for p in range(0, 0x3F000 - 1):
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
            slots = [k for k in range(256) if base + 2 * k + 1 < 0x3F000 and w(base + 2 * k) in seen]
            if not slots:
                continue
            size = masks.get(lin)
            for k in range(size if size else max(slots) + 16):
                q = base + 2 * k
                if q + 1 >= 0x3F000:
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
                        if not 0 <= q < 0x3F000 - 1 or not ok(cs, w(q)):
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
    exec_, acc, tg, io, segs = cover
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
                        acc_cover=acc, targets=tg, targets_seen=seen, io_cover=io, ip_table_cs=0x0040,
                        exec_counts={v30x.lin_of(*k): n for k, n in exec_.items()}, hooks={idle_lin: "main_idle"},
                        natives={} if os.environ.get("NO_NATIVES") else NATIVES,
                        hook_next={idle_lin: idle_lin}, port_in=port_in, port_out=port_out, code_limit=code_limit,
                        store_marks=None if os.environ.get("NO_MARKS") else store_marks(acc))
    return prog, vbl, raster, idle_lin


def generate():
    regions = load_regions("rtype")
    cover = load_cover()
    build = build_dir("rtype")
    (build / "rom_image.bin").write_bytes(rom_image(regions))
    prog, vbl, raster, idle_lin = program(regions, cover)
    lines, rep, em, code, entries = v30x.translate(prog)
    head = ["; generated by games/rtype/tools/gen.py (engine/v30x.py): the main CPU", "\tsection text,code"]
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
