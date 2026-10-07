"""Static code discovery for the DK main CPU ROM (recursive descent)."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from z80dis import decode

ROMSIZE = 0x4000


def load_rom():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return open(os.path.join(root, "assets", "roms", "extracted", "cpu.rom"), "rb").read()


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


def discover(rom, roots, extra_code=(), rst28_counts=None, verbose=False, known=()):
    """Recursive descent.  Returns (code: dict pc->Ins, tables: dict site->list of targets)."""
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
                pc = nxt
                continue
            if fl == "rst":
                if ins.target == 0x28:
                    tbl = [t for t in table_after_rst28(rom, nxt, known) if t]
                    if rst28_counts and nxt in rst28_counts:
                        tbl = tbl[:rst28_counts[nxt]]
                    tables[pc] = (nxt, tbl)
                    work.extend(tbl)
                    break  # code after the table is not a fall-through
                work.append(ins.target)
                pc = nxt
                continue
            if fl in ("ret", "ijmp", "halt"):
                break
            if fl == "cret":
                pc = nxt
                continue
            break
    return code, tables
