#!/usr/bin/env python3
"""Run the LZ4 stub (tools/lz4stub.s) on Musashi and compare with a plain TOS load of the program.

    python tools/lz4prg_test.py [game ...]        (default: every port in port.GAMES, from run/<game>/)

For each program: pack it (tools/lz4prg.py), load the packed program as TOS does (text + data at T = basepage +
256, its BSS cleared, the rest of the memory junk, 4(sp) the basepage), run until the stub jumps to T and check
the game's text + data (relocated) and BSS (zero) against the unpacked program loaded at T, the basepage's
segment fields, the stack, a0 = 0.  T at a long and at a word boundary.  The TOS calls are emulated (Physbase,
Getrez for low / medium / high resolution, Cconws, Setexc; d1-d2/a0-a2 scribbled), a VBL interrupt comes every
160,000 cycles: the progress bar must grow during the unpacking, end full with its frame and touch nothing else of
the screen, and the VBL vector must be TOS's again at the end.  Prints the stub's 68000 cycles (seconds
at 8 MHz, no wait states) and the memory needed (text + data + BSS + 256) before and after packing.
"""
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import lz4prg  # noqa: E402
from machine68k import CPUType, Machine, Register as R  # noqa: E402

RAM_KIB = 8192
JUNK = 0xA5


def tos_image(data, t):
    """text + data + BSS of a program as TOS loads it at t (relocated)."""
    p = lz4prg.parse_prg(data)
    img = bytearray(p["body"]) + bytes(p["blen"])
    rel = p["reloc"]
    off = struct.unpack(">I", rel[:4])[0]
    if off:
        def fix(o):
            img[o:o + 4] = struct.pack(">I", (struct.unpack(">I", img[o:o + 4])[0] + t) & 0xFFFFFFFF)
        fix(off)
        for b in rel[4:]:
            if b == 0:
                break
            if b == 1:
                off += 254
            else:
                off += b
                fix(off)
    return p, bytes(img)


SCREEN = 0x780000
TRAP1, TRAP13, TRAP14, OLD_VBL = 0x400, 0x410, 0x420, 0x430
RES = {0: (160, 96, 8), 1: (160, 96, 8), 2: (80, 192, 16)}      # bytes a line, the bar's line, its lines


def run(data, packed, bp, rez):
    t = bp + 256
    m = Machine(CPUType.M68000, RAM_KIB)
    cpu, mem = m.cpu, m.mem
    q = lz4prg.parse_prg(packed)
    s, pl, bl = q["tlen"], q["dlen"], q["blen"]
    mem.w_block(0, bytes([JUNK]) * (RAM_KIB * 1024))
    top = RAM_KIB * 1024 - 0x1000
    assert t + s + pl + bl < SCREEN, "the test's memory is too small"
    mem.w_block(SCREEN, bytes(32000))
    for vec, adr in ((0x84, TRAP1), (0xB4, TRAP13), (0xB8, TRAP14), (0x70, OLD_VBL)):
        mem.w32(vec, adr)
    mem.w16(OLD_VBL, 0x4E73)                            # (TOS's VBL handler: rte)
    mem.w_block(t, q["body"])
    mem.w_block(t + s + pl, bytes(bl))                  # TOS clears the BSS
    bpage = struct.pack(">IIIIIIII", bp, top, t, s, t + s, pl, t + s + pl, bl)
    mem.w_block(bp, bpage + bytes(256 - len(bpage)))
    sp = top - 64
    mem.w32(sp + 4, bp)
    mem.w32(sp, 0xDEADBEEF)                             # (the return address: unused)
    cpu.w_sr(0x2300)                                    # (supervisor, IPL 3: Musashi keeps one A7 here)
    cpu.w_reg(R.A7, sp)
    cpu.w_pc(t)

    bpl, y, h = RES[rez]
    w = bpl - 32
    bar = SCREEN + y * bpl + 16
    shown = []                                          # the bar's bytes at each VBL
    cycles, next_vbl = 0, 160000
    step = cpu.execute
    while True:                                         # (instruction by instruction: stop exactly at the jump)
        pc = cpu.r_pc()
        if pc in (TRAP1, TRAP13, TRAP14):
            a7 = cpu.r_reg(R.A7)
            sr, ret, fn = mem.r16(a7), mem.r32(a7 + 2), mem.r16(a7 + 6)
            d0 = 0
            if pc == TRAP14 and fn == 2:
                d0 = SCREEN
            elif pc == TRAP14 and fn == 4:
                d0 = rez
            elif pc == TRAP13 and fn == 5:
                vec, new = mem.r16(a7 + 8), mem.r32(a7 + 10)
                d0 = mem.r32(vec * 4)
                if new != 0xFFFFFFFF:
                    mem.w32(vec * 4, new)
            elif not (pc == TRAP1 and fn == 9):
                raise RuntimeError("TOS call %x/%d" % (pc, fn))
            for r in (R.D1, R.D2, R.A0, R.A1, R.A2):
                cpu.w_reg(r, 0xA5A5A5A5)
            cpu.w_reg(R.D0, d0)
            cpu.w_reg(R.A7, a7 + 6)
            cpu.w_sr(sr)
            cpu.w_pc(ret)
            continue
        if cycles >= next_vbl and cpu.r_sr() & 0x700 < 0x400:
            next_vbl += 160000
            a7 = cpu.r_reg(R.A7) - 6
            mem.w16(a7, cpu.r_sr())
            mem.w32(a7 + 2, pc)
            cpu.w_reg(R.A7, a7)
            cpu.w_sr((cpu.r_sr() & 0xF8FF) | 0x2400)
            cpu.w_pc(mem.r32(0x70))
            shown.append(sum(1 for b in mem.r_block(bar, w) if b == 0xFF))
            continue
        cycles += step(1).cycles
        if cpu.r_pc() == t:
            break
        if cycles > 8_000_000 * 60:
            raise RuntimeError("no jump to the game after 60 s")

    p, want = tos_image(data, t)
    got = bytes(mem.r_block(t, len(want)))
    errs = []
    if got != want:
        i = next(k for k in range(len(want)) if got[k] != want[k])
        errs.append("memory differs at T+%06x (of %06x): %02x, want %02x" % (i, len(want), got[i], want[i]))
    want_bp = (t, p["tlen"], t + p["tlen"], p["dlen"], t + p["tlen"] + p["dlen"], p["blen"])
    got_bp = struct.unpack(">IIIIII", bytes(mem.r_block(bp + 8, 24)))
    if got_bp != want_bp:
        errs.append("basepage %s, want %s" % (got_bp, want_bp))
    if cpu.r_reg(R.A7) != sp or mem.r32(sp + 4) != bp:
        errs.append("stack moved or 4(sp) changed")
    if cpu.r_reg(R.A0) != 0:
        errs.append("a0 not 0")
    if mem.r32(0x70) != OLD_VBL:
        errs.append("the VBL vector not restored")
    screen = bytearray(32000)
    for line in list(range(y, y + h)) + [y - 2, y + h + 1]:
        screen[line * bpl + 16:line * bpl + 16 + w] = b"\xff" * w
    if bytes(mem.r_block(SCREEN, 32000)) != bytes(screen):
        errs.append("the screen is not the full bar and its frame")
    mid = [n for n in shown if 0 < n < w]
    if shown != sorted(shown) or len(set(mid)) < 3:
        errs.append("the bar did not grow (%s)" % shown)
    return errs, cycles


def main():
    src = (ROOT / "port.py").read_text()
    games = eval(re.search(r"GAMES = (\{.*?\})", src, re.S).group(1))
    names = sys.argv[1:] or list(games)
    bad = 0
    for g in names:
        data = (ROOT / "run" / g / games[g]).read_bytes()
        packed, info = lz4prg.pack(data)
        res = []
        for bp, rez in ((0x12000, 0), (0x12002, 1), (0x12000, 2)):    # T at a long and a word boundary
            res.append(run(data, packed, bp, rez))
        errs = [e for r in res for e in r[0]]
        bad += bool(errs)
        print("%-9s %8d -> %7d bytes  memory %8d -> %8d  unpack %5.2f s  %s" % (
            g, info["file"], info["packed"], info["load"], info["packed_load"], res[0][1] / 8e6,
            "ok" if not errs else "; ".join(errs)), flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
