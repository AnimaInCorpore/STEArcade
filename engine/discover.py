"""Static code discovery for the DK main CPU ROM (recursive descent)."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from z80dis import decode

ROMSIZE = 0x4000


def load_rom():
    from paths import EXTRACTED
    return open(EXTRACTED / "dkong" / "cpu.rom", "rb").read()


def table_after_rst28(rom, pc_after, known=()):
    """Entries of the word table after `rst $28` (ends where code starts: at the
    smallest entry, or at a known instruction address; 0 entries are unused slots)."""
    out = []
    a = pc_after
    min_t = 0x10000
    while a + 1 < ROMSIZE:
        if a >= min_t or a in known:
            break
        v = rom[a] | (rom[a + 1] << 8)
        if v == 0:
            out.append(0)
        elif 0x100 <= v < ROMSIZE:
            out.append(v)
            min_t = min(min_t, v)
        else:
            break
        a += 2
    return out


def word_table(rom, start, known=(), limit=None):
    """Entries of a word table of code addresses at `start` (ends where code starts: at
    the smallest entry at or after the table, at a known instruction address, at an entry
    outside the ROM, or after `limit` entries)."""
    out = []
    a = start
    min_t = 0x10000
    while a + 1 < ROMSIZE and (limit is None or len(out) < limit):
        if a >= min_t or a in known:
            break
        v = rom[a] | (rom[a + 1] << 8)
        if not v < ROMSIZE:
            break
        out.append(v)
        if v >= start:
            min_t = min(min_t, v)
        a += 2
    return out


def discover(rom, roots, extra_code=(), rst28_counts=None, verbose=False, known=(), rst28_tables=True,
             hl_tables=False, table_calls=(), rst_data=None):
    # table_calls: call targets that are followed by a word table (a dict maps the target to the highest code address)
    # rst_data: {rst target: k} the restart reads k inline bytes and returns past them (the code goes on at the rst + 1
    # + k), or {rst target: "table"} a word table of jump targets follows it (indexed by A; no fall-through) - Pac-Man
    """Recursive descent.  Returns (code: dict pc->Ins, tables: dict site->list of targets).
    rst28_tables: `rst $28` is followed by a table of jump targets (Donkey Kong).
    hl_tables: `ld hl,T; rst $08|$10; ld a,(hl); inc hl; ld h,(hl); ld l,a; jp (hl)` (or
    `ld e,(hl)..ld d,(hl); ex de,hl`, or the index added to l inline) is a jump through
    the word table T indexed by A (rst $08 / inline: words, rst $10: bytes; an `and a,N`
    before it bounds the index) - Galaga; `call`/`jp` to a `jp (hl)` (or to a routine that does the double read
    before its `jp (hl)`, callee_jphl) counts as the jump, so does `ex (sp),hl; ret` (Galaga's sub CPU 091E)."""
    global ROMSIZE
    ROMSIZE = len(rom)
    code = {}
    work = list(roots) + list(extra_code)
    tables = {}
    while work:
        pc = work.pop()
        while 0 <= pc < ROMSIZE:
            if pc in code:
                break
            ins = decode(rom, pc)
            code[pc] = ins
            nxt = pc + ins.length
            fl = ins.flow
            if fl == "seq":
                pc = nxt
                continue
            if fl == "jmp":
                work.append(ins.target)
                break
            if fl == "jcc":
                work.append(ins.target)
                pc = nxt
                continue
            if fl in ("call", "ccall"):
                work.append(ins.target)
                if fl == "call" and ins.target in table_calls:
                    # `call T` with a word table of jump targets right behind it (T pops the return address and
                    # jumps through it, 1942 $66F7): the table is data, the entries are code
                    lim = table_calls[ins.target] if isinstance(table_calls, dict) else ROMSIZE
                    tbl = [t for t in word_table(rom, nxt, known) if 0x100 <= t < lim]
                    tables[pc] = (nxt, tbl)
                    work.extend(tbl)
                    break
                pc = nxt
                continue
            if fl == "rst":
                skip = (rst_data or {}).get(ins.target)
                if skip == "table":
                    tbl = word_table(rom, nxt, known)
                    tables[pc] = (nxt, tbl)
                    work.append(ins.target)
                    work.extend(tbl)
                    break
                if skip:
                    work.append(ins.target)
                    pc = nxt + skip
                    continue
                if ins.target == 0x28 and rst28_tables:
                    tbl = [t for t in table_after_rst28(rom, nxt, known) if t]
                    if rst28_counts and nxt in rst28_counts:
                        tbl = tbl[:rst28_counts[nxt]]
                    tables[pc] = (nxt, tbl)
                    work.extend(tbl)
                    break  # code after the table is not a fall-through
                work.append(ins.target)
                pc = nxt
                continue
            if fl in ("ret", "ijmp"):
                break
            if fl == "cret":
                pc = nxt
                continue
            break
    if hl_tables:
        new_targets = hl_jump_tables(rom, code, tables, known, verbose)
        if new_targets:
            return discover(rom, list(roots) + new_targets, extra_code, rst28_counts, verbose, known,
                            rst28_tables, hl_tables, table_calls, rst_data)
    return code, tables


def hl_jump_tables(rom, code, tables, known=(), verbose=False):
    """The hl_tables idiom (see discover): for every `jp (hl)` site (or call/jp to one)
    walk the linear predecessors back to the `ld hl,T`.  Adds to `tables`; returns the
    targets that are not code yet."""
    prev = {}
    for pc, ins in code.items():
        if ins.flow in ("seq", "rst", "call", "ccall", "jcc", "cret"):
            prev[pc + ins.length] = pc
    new = []
    for pc, ins in sorted(code.items()):
        if pc in tables:
            continue
        reads = set()                   # the double read: (hl) into a / e, then h / d
        is_jphl = ins.text == "jp (hl)" or (ins.flow in ("jmp", "call") and ins.target < ROMSIZE
                                           and callee_jphl(rom, ins.target, reads)) \
            or ins.text == "ret" and prev.get(pc) in code and code[prev[pc]].text == "ex (sp),hl"
        if not is_jphl:
            continue
        ldhl = rst_idx = mask = None
        p = pc
        for _ in range(12):
            p = prev.get(p)
            if p is None:
                break
            i = code[p]
            if i.mn == "ld" and i.ops[0] == ("r16", "hl"):
                if i.ops[1][0] == "imm":
                    ldhl = i.ops[1][1]
                break
            if i.mn == "ld" and len(i.ops) == 2 and i.ops[1] == ("ind", "hl", 0) and i.ops[0][0] == "r8":
                reads.add(i.ops[0][1])
            if i.flow == "rst" and i.target in (0x08, 0x10):
                rst_idx = 1 if i.target == 0x08 else 2        # bytes of index per entry
        if ldhl is None or not (rst_idx or reads & {"a", "e"} and reads & {"h", "d"}):
            continue
        if not rst_idx:
            rst_idx = 1
        limit = (mask // rst_idx) + 1 if mask is not None else None
        tbl = word_table(rom, ldhl, known, limit)
        tables[pc] = (ldhl, tbl)
        if verbose:
            print("hl table at %04X (jump at %04X, limit %s): %s" % (ldhl, pc, limit, ["%04X" % t for t in tbl]))
        new += [t for t in tbl if t not in code]
    return new


def callee_jphl(rom, target, reads):
    """Whether the straight code at `target` is a `jp (hl)` within a few instructions, the double read of the
    table entry allowed in it (Galaga 3118: `ld a,(hl); inc hl; ld h,(hl); ld l,a; jp (hl)`, called with HL on the
    entry): its (hl) reads go into `reads`."""
    pc, found = target, set()
    for _ in range(6):
        if not 0 <= pc < ROMSIZE:
            return False
        i = decode(rom, pc)
        if i.text == "jp (hl)":
            reads |= found
            return True
        if i.mn == "ld" and len(i.ops) == 2 and i.ops[1] == ("ind", "hl", 0) and i.ops[0][0] == "r8":
            found.add(i.ops[0][1])
        elif i.flow != "seq" or i.text not in ("inc hl", "ld l,a", "ld h,a", "ex de,hl") and i.mn != "ld":
            return False
        pc += i.length
    return False


def skip_offsets(rom, target, inside, cache):
    """The return offsets of a function that returns past its caller's next bytes: `pop hl`, k x `inc hl` (on a
    straight path, across `jr` / `jp`), `jp (hl)`, on a path from `target` (calls stepped over).  Capcom's object
    allocators return to the call + 3 + 3 on success (1943 06EC); the compares of 8 / 4 bytes (1943 03C0, Black Tiger
    03B2, Gun.Smoke 0365) return to the call + 3 when less, + 3 + 2 (or 3) when equal, + 3 + 4 (6) when greater, where
    the caller has a `jr` (`jp`) for each.  inside(pc): the addresses that hold code (a banked port's virtual ones)."""
    if target in cache:
        return cache[target]
    found, seen, work = set(), set(), [target]
    while work and len(seen) < 400:
        pc = work.pop()
        while pc not in seen and inside(pc):
            seen.add(pc)
            ins = decode(rom, pc)
            if ins.mn == 'pop' and ins.ops == [('r16', 'hl')]:
                k, q = 0, pc + ins.length
                for _ in range(16):
                    i2 = decode(rom, q)
                    if i2.text == 'inc hl':
                        k += 1
                    elif i2.mn in ('jp', 'jr') and len(i2.ops) == 1 and i2.target is not None:
                        q = i2.target
                        continue
                    elif i2.text == 'jp (hl)':
                        if k:
                            found.add(k)
                        break
                    else:
                        break
                    q += i2.length
            nxt = pc + ins.length
            if ins.mn in ('ret', 'reti', 'retn') and not ins.ops or ins.mn == 'jp' and ins.ops and ins.ops[0][0] == 'ind':
                break
            if ins.mn in ('jp', 'jr') and len(ins.ops) == 1 and ins.target is not None:
                pc = ins.target
                continue
            if ins.mn in ('jp', 'jr', 'djnz') and ins.target is not None:
                work.append(ins.target)
            pc = nxt
    cache[target] = found
    return found


def skip_returns(rom, code, inside=lambda pc: True, cache=None):
    """The continuations after the calls of such functions (see skip_offsets): add them as roots and discover again
    until none is missing."""
    cache = {} if cache is None else cache
    out = set()
    for pc, ins in code.items():
        if ins.mn == 'call' and ins.target is not None:
            for k in skip_offsets(rom, ins.target, inside, cache):
                out.add(pc + ins.length + k)
    return out
