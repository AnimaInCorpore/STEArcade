"""Recursive-descent listing of the Bubble Bobble MCU ROM (a78-01.17, MC6801, mapped at $F000).

usage: python mcudis.py [out.txt]
Prints coverage and on-chip register accesses; writes a listing with xref labels.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import m6801

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
ROM = open(os.path.join(ROOT, "assets", "roms", "extracted_bublbobl", "a78-01.17"), "rb").read()
BASE = 0xF000


def rd(a):
    a &= 0xFFFF
    return ROM[a - BASE] if BASE <= a < BASE + len(ROM) else 0


def walk(seeds):
    seen = {}
    stack = list(seeds)
    while stack:
        pc = stack.pop()
        while pc not in seen and BASE <= pc < BASE + len(ROM):
            n, text, tgt, m = m6801.disasm(rd, pc)
            seen[pc] = (n, text, tgt, m)
            if tgt is not None and BASE <= tgt < BASE + len(ROM):
                stack.append(tgt)
            if m in ("bra", "jmp", "rts", "rti", "db"):
                break
            pc += n
    return seen


def main():
    vec = {n: (rd(a) << 8) | rd(a + 1) for n, a in
           (("sci", 0xFFF0), ("tof", 0xFFF2), ("ocf", 0xFFF4), ("icf", 0xFFF6), ("irq", 0xFFF8),
            ("swi", 0xFFFA), ("nmi", 0xFFFC), ("reset", 0xFFFE))}
    seeds = [v for v in vec.values() if BASE <= v < BASE + len(ROM)]
    seen = walk(seeds)
    labels = {}
    for pc, (n, text, tgt, m) in seen.items():
        if tgt is not None:
            labels.setdefault(tgt, []).append(pc)
    nbytes = sum(n for n, *_ in seen.values())
    print("vectors:", {k: "%04X" % v for k, v in vec.items()})
    print("instructions: %d, code bytes: %d of %d" % (len(seen), nbytes, len(ROM)))
    out = []
    pc = BASE
    while pc < BASE + len(ROM):
        if pc in seen:
            n, text, tgt, m = seen[pc]
            if pc in labels or pc in vec.values():
                out.append("L%04X:" % pc)
            out.append("  %04X  %-10s %s" % (pc, " ".join("%02X" % rd(pc + i) for i in range(n)), text))
            pc += n
        else:
            run = pc
            while run < BASE + len(ROM) and run not in seen:
                run += 1
            out.append("  %04X  data %d bytes" % (pc, run - pc))
            pc = run
    if len(sys.argv) > 1:
        open(sys.argv[1], "w").write("\n".join(out) + "\n")
    return seen, out


if __name__ == "__main__":
    main()
