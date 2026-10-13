"""Tests of the NEC V30 interpreter (v30.py) and disassembler (v30dis.py).

    python engine/v30_test.py [--regen]

(a) hand-written instruction tests (flags, results, cycles, the prefetch queue, interrupts, REP chunks);
(b) MAME traces of R-Type's main CPU (the boot and windows of the attract mode) with every program and I/O access:
    the disassembler's text must equal MAME's for every distinct instruction, and the interpreter must reproduce
    each step (registers, flags, writes, port accesses, cycles) going on from its own state; reads are answered
    from the trace, the maskable interrupts are taken where MAME took them (the vector from the table read).
    A REP chunk runs as many iterations as MAME's did (it stops where MAME's time slice ended).  MAME logs an odd-address
    word access (memory or port) as two byte accesses.
(c) probe programs loaded into R-Type's work RAM in MAME (8 runs, ~750 cases each: every opcode, every NEC $0F
    instruction, prefixes, REP forms, ModRM forms, branches taken or not) checked the same way.
The traces are made once into build/v30/ (not in git; they hold ROM bytes) when MAME and the ROMs are there
(games/rtype/tools/prepare.py fills build/rtype/mame_roms), else (b) is skipped.
"""
import os
import random
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict, deque

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v30
from v30 import V30
import v30dis
from paths import ROOT

OUT = ROOT / "build" / "v30"
MAME_ROMS = ROOT / "build" / "rtype" / "mame_roms"
WINDOWS = [(0, 40), (400, 430), (1500, 1530)]    # traced frames: the boot, the title, the demo
FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("FAIL", msg)


# ---- (a) instruction tests ---------------------------------------------------------------------------------
class Mem:
    def __init__(self):
        self.m = bytearray(1 << 20)
        self.writes = []
        self.io = []

    def rd(self, a):
        return self.m[a]

    def wr(self, a, v):
        self.m[a] = v
        self.writes.append((a, v))

    def io_rd(self, p):
        self.io.append(("i", p))
        return 0x5A

    def io_wr(self, p, v):
        self.io.append(("o", p, v))


def cpu_with(code, at=0x10000, **regs):
    mem = Mem()
    mem.m[at:at + len(code)] = code
    c = V30(mem.rd, mem.wr, mem.io_rd, mem.io_wr, lambda: 0x20)
    c.cs, c.ip = at >> 4, at & 15
    c.ss, c.sp = 0x2000, 0x1000
    c.ds = c.es = 0x3000
    c.icount = 1 << 40
    for k, v in regs.items():
        setattr(c, k, v)
    return c, mem


def run1(code, **regs):
    c, mem = cpu_with(bytes.fromhex(code.replace(" ", "")), **regs)
    c.pf_count = 6                                    # (a full queue: no prefetch cost)
    n = c.step()
    return c, mem, n


def fl(c):
    f = c.flags
    return "".join(ch if f & b else "." for ch, b in zip("ODITSZAPC", (0x800, 0x400, 0x200, 0x100, 0x80, 0x40, 0x10, 4, 1)))


def unit_tests():
    n0 = len(FAILS)
    c, _, n = run1("04 01", ax=0x7F)                   # ADD AL,1: V S A
    check(c.al == 0x80 and fl(c) == "O...S.A.." and n == 4, "add al: %02X %s %d" % (c.al, fl(c), n))
    c, _, n = run1("2C 01", ax=0x00)                   # SUB AL,1: S A P C
    check(c.al == 0xFF and fl(c) == "....S.APC", "sub al: %s" % fl(c))
    c, _, n = run1("F6 D8", ax=0x00)                   # NEG AL of 0: CY 0, no V/AC update (MAME)
    check(fl(c) == ".....Z.P." and n == 2, "neg 0: %s" % fl(c))
    c, _, n = run1("27", ax=0x9A)                      # ADJ4A
    check(c.al == 0x00 and fl(c) == ".....ZAPC", "adj4a: %02X %s" % (c.al, fl(c)))
    c, _, n = run1("37", ax=0x00FA)                    # ADJBA: AL+6 = $00 -> AH += 1 (AL > $F9 tested after)
    check(c.ax == 0x0100 and n == 7, "adjba: %04X" % c.ax)
    c, _, n = run1("F7 E3", ax=0x8000, bx=2)           # MULU: $10000
    check((c.ax, c.dx) == (0, 1) and fl(c)[0] == "O" and n == 30, "mulu: %04X %04X %d" % (c.ax, c.dx, n))
    c, _, n = run1("F7 FB", ax=0xFFF9, dx=0xFFFF, bx=2)  # DIV -7/2: -3 r -1
    check((c.ax, c.dx) == (0xFFFD, 0xFFFF) and n == 43, "div: %04X %04X" % (c.ax, c.dx))
    c, _, n = run1("D3 E0", ax=0x8001, cx=1)           # SHL AW,CL
    check(c.ax == 2 and fl(c)[-1] == "C" and n == 7 + 1, "shl cl: %04X %s %d" % (c.ax, fl(c), n))
    c, _, n = run1("D0 C8", ax=0x01)                   # ROR AL,1: $80, CY, V
    check(c.al == 0x80 and fl(c).startswith("O") and fl(c).endswith("C"), "ror: %02X %s" % (c.al, fl(c)))
    c, _, n = run1("0F 1C C0 07", ax=0)                # SET1 AL,7
    check(c.al == 0x80 and n == 5, "set1: %02X %d" % (c.al, n))
    c, _, n = run1("0F 18 C0 07", ax=0x80, flags=0xF002)   # TEST1: bit set -> Z clear
    check(fl(c)[5] == "." and n == 4, "test1: %s" % fl(c))
    c, _, n = run1("0F 28 C3", ax=0x0005, bx=0x12)     # ROL4 BL: BL=$25, AL=$01
    check(c.bl == 0x25 and c.al == 0x01, "rol4: %02X %02X" % (c.bl, c.al))
    c, mem = cpu_with(bytes.fromhex("0F 20"), cx=4, si=0, di=0x10)   # ADD4S 4 digits: 1234 + 0999 = 2233
    mem.m[0x30000:0x30002] = b"\x34\x12"
    mem.m[0x30010:0x30012] = b"\x99\x09"
    n = c.step()
    check(bytes(mem.m[0x30010:0x30012]) == b"\x33\x22" and n == 7 + 2 * 19, "add4s: %s %d" % (mem.m[0x30010:0x30012].hex(), n))
    # cycles: odd/even word operands, prefetch
    for code, regs, exp in (("8B 07", {"bx": 0}, 11), ("8B 07", {"bx": 1}, 15), ("89 07", {"bx": 1}, 13), ("01 07", {"bx": 0}, 16),
                            ("50", {}, 8), ("68 34 12", {}, 8), ("68 34 12", {"sp": 0x1001}, 12), ("E8 00 00", {}, 24),
                            ("C3", {}, 19), ("CF", {}, 47), ("CD 10", {}, 58), ("9C", {}, 8), ("60", {}, 35), ("61", {}, 43),
                            ("74 05", {"flags": 0xF042}, 10), ("74 05", {"flags": 0xF002}, 4), ("EB 05", {}, 12),
                            ("E2 05", {"cx": 2}, 13), ("E2 05", {"cx": 1}, 5), ("F6 E3", {}, 30), ("F7 F3", {"bx": 1}, 25),
                            ("C8 04 00 00", {}, 23), ("C9", {}, 8), ("FF 37", {"bx": 0}, 4), ("8F 07", {}, 21)):
        c, _, n = run1(code, **regs)
        check(n == exp, "cycles %s %s: %d (MAME %d)" % (code, regs, n, exp))
    # prefetch: empty queue after a jump; 2 cycles per byte not covered by the instruction's own time
    c, mem = cpu_with(bytes.fromhex("EA 00 01 00 10") + bytes(0xFB) + bytes.fromhex("FA B9 FF FF E2 FE"))
    ns = [c.step() for _ in range(4)]
    check(ns == [27, 4, 6, 13], "prefetch: %s" % ns)
    # interrupts: the IRQ is taken before the next instruction, vector from inta, 8 cycles (PUSHF's)
    c, mem = cpu_with(bytes.fromhex("90 90"), flags=0xF202)
    mem.m[0x80:0x84] = b"\x34\x12\x00\x50"
    mem.m[0x51234] = 0x90
    c.irq_line = True
    n = c.step()
    check(c.cs == 0x5000 and c.ip == 0x1235 and n == 8 + 3 and not c.irq_line and c.flags & 0x200 == 0,
          "irq: %04X:%04X %d" % (c.cs, c.ip, n))
    check(bytes(mem.m[0x20FFA:0x21000]) == bytes.fromhex("0000 0010 02F2"), "irq frame %s" % mem.m[0x20FFA:0x21000].hex())
    c, mem = cpu_with(bytes.fromhex("8E D8 90"), flags=0xF202, ax=0x1234)   # no interrupt right after MOV sreg
    c.step()
    c.irq_line = True
    c.step()
    check(c.cs == 0x1000 and c.ip == 3, "irq held after mov sreg")
    c.step()
    check(c.cs == 0, "irq after it")
    # REP chunks: stopped by icount, continued from the prefix
    c, mem = cpu_with(bytes.fromhex("F3 AB 90"), cx=5, di=0, ax=0xBEEF)
    c.icount = 9
    c.step()
    check(c.cx == 3 and c.ip == 0 and c.rep_params, "rep chunk: cx %d ip %d" % (c.cx, c.ip))
    c.icount = 1 << 40
    c.step()
    check(c.cx == 0 and c.ip == 2 and bytes(mem.m[0x30000:0x3000A]) == bytes.fromhex("EFBE") * 5, "rep done")
    # disassembler
    for code, text in (("EA0008003F", "br      3F00h:800h"), ("F3AB", "rep     stmw"), ("C606052F1C", "mov     byte ptr [2F05h],1Ch"),
                       ("26C7060000FFFF", "mov     word ptr ds1:[0h],0FFFFh"), ("2E8B4702", "mov     aw,ps:[bw+2h]"),
                       ("6A80", "push    -80h"), ("0F1CC007", "set1    al,7"), ("D1E0", "shl     aw,1"), ("E2FE", "dbnz    3F804h")):
        b = bytes.fromhex(code) + bytes(8)
        ins = v30dis.decode(lambda a: b[a - 0x3F804], 0x3F804)
        check(ins.text.rstrip() == text and ins.length == len(code) // 2, "decode %s: %r %d" % (code, ins.text, ins.length))
    print("unit tests: %d failures" % (len(FAILS) - n0))


# ---- (b) MAME traces ------------------------------------------------------------------------------------------
TRACELOG = ('{tracelog "%d %04X %04X %04X %04X %04X %04X %04X %04X %04X %04X %04X %04X %04X %04X ",'
            'totalcycles,aw,cw,dw,bw,sp,bp,ix,iy,ds1,ps,ss,ds0,psw,pc}')
WPS = ['wpset 0,100000,r,1,{tracelog "R %05X %X\\n",wpaddr,wpdata; g}',
       'wpset 0,100000,w,1,{tracelog "W %05X %X\\n",wpaddr,wpdata; g}',
       'wpiset 0,10000,r,1,{tracelog "I %05X %X\\n",wpaddr,wpdata; g}',
       'wpiset 0,10000,w,1,{tracelog "O %05X %X\\n",wpaddr,wpdata; g}']
KIND = {"R": 0, "W": 1, "I": 2, "O": 3}


def lua_quote(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def trace_script(windows):
    lines = ["local dbg = manager.machine.debugger", "local frame = 0", "local function on(i)",
             "  dbg:command('focus maincpu')",
             "  dbg:command(" + lua_quote("trace w") + " .. i .. " + lua_quote(".txt,maincpu,noloop,%s" % TRACELOG) + ")"]
    lines += ["  dbg:command(%s)" % lua_quote(w) for w in WPS]
    lines += ["end", "local function off()", "  dbg:command('wpclear')", "  dbg:command('wpiclear')",
              "  dbg:command('trace off,maincpu')", "end", "sub = emu.register_frame_done(function()", "  frame = frame + 1"]
    for i, (a, b) in enumerate(windows):
        if a > 0:
            lines.append("  if frame == %d then on(%d) end" % (a, i))
        lines.append("  if frame == %d then off() end" % b)
    lines += ["end)"]
    if windows[0][0] == 0:
        lines.append("on(0)")
    lines.append("dbg:command('go')")
    return "\n".join(lines) + "\n"


def mame_cmd(script, seconds):
    return ["mame", "rtype", "-rompath", str(MAME_ROMS), "-debug", "-debugger", "none", "-autoboot_script", script, "-window",
            "-video", "none", "-sound", "none", "-nothrottle", "-seconds_to_run", str(seconds), "-skip_gameinfo"]


def parse_trace(path):
    """MAME trace text -> arrays: cyc, regs (14: aw..ds0 psw ip), pc (linear), text index, accesses (kind addr data)."""
    cyc, regs, pcs, tix, acc, off = [], [], [], [], [], []
    texts = {}
    with open(path) as f:
        for line in f:
            if len(line) > 2 and line[1] == " " and line[0] in KIND:
                k, a, d = line.split()
                acc.append((KIND[k] << 40) | (int(a, 16) << 16) | int(d, 16))
                continue
            if not line.strip() or line.startswith("   ("):
                continue                     # (MAME's notes: interrupts, loops)
            p = line.split(" ", 16)
            cyc.append(int(p[0]))
            regs.append([int(q, 16) for q in p[1:15]])
            pcs.append(int(p[15].rstrip(":"), 16))
            off.append(len(acc))
            tix.append(texts.setdefault(p[16].rstrip(), len(texts)))
    off.append(len(acc))
    return dict(cyc=np.array(cyc, np.int64), regs=np.array(regs, np.uint16), pc=np.array(pcs, np.int32),
                tix=np.array(tix, np.int32), acc=np.array(acc, np.uint64), off=np.array(off, np.int64),
                texts=np.array(sorted(texts, key=texts.get), dtype=object))


def have_mame():
    return shutil.which("mame") is not None and (MAME_ROMS / "rtype").is_dir()


def make_trace():
    """Runs MAME once (a few minutes) and packs the windows into OUT/rtype_maincpu.npz."""
    OUT.mkdir(parents=True, exist_ok=True)
    d = OUT / "run_rtype"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir()
    (d / "t.lua").write_text(trace_script(WINDOWS))
    with open(d / "mame.log", "w") as log:
        subprocess.run(mame_cmd("t.lua", WINDOWS[-1][1] // 55 + 2), cwd=d, stdout=log, stderr=subprocess.STDOUT)
    parts = [parse_trace(d / ("w%d.txt" % i)) for i in range(len(WINDOWS)) if (d / ("w%d.txt" % i)).exists()]
    parts = [p for p in parts if len(p["cyc"])]
    if not parts:
        print("no trace (see %s)" % (d / "mame.log"))
        return
    np.savez_compressed(OUT / "rtype_maincpu.npz", **{"%s_%d" % (k, i): v for i, part in enumerate(parts) for k, v in part.items()})
    shutil.rmtree(d)
    print("trace: %d instructions" % sum(len(p["cyc"]) for p in parts))


def load_trace(path):
    z = np.load(path, allow_pickle=True)
    parts = []
    i = 0
    while "cyc_%d" % i in z:
        parts.append({k: z["%s_%d" % (k, i)] for k in ("cyc", "regs", "pc", "tix", "acc", "off", "texts")})
        i += 1
    return parts


def irq_vector(accs):
    """The interrupt MAME took after a step: [W flags] [R n*4] [R n*4+2] among its accesses; n or None."""
    for j in range(1, len(accs) - 1):
        k, a, _ = accs[j]
        if k == 0 and a < 0x400 and not a & 3 and accs[j - 1][0] == 1 and accs[j + 1][:2] == (0, a + 2):
            return a >> 2
    return None


def replay(part, stats, opcount, rom):
    cyc, regs, pcs, acc, off, tix, texts = (part[k] for k in ("cyc", "regs", "pc", "acc", "off", "tix", "texts"))
    reads = defaultdict(deque)
    ins = defaultdict(deque)
    mine = []
    missing = []

    def pop(q, a, what):
        x = q.get(a)
        if x:
            return x.popleft()
        missing.append((what, a))
        return 0

    def rd(a):
        return pop(reads, a, "R") & 0xFF

    def rd16(a):
        if a & 1:                                       # (unaligned: two bus words)
            return (pop(reads, a, "R") & 0xFF) | ((pop(reads, (a + 1) & 0xFFFFF, "R") & 0xFF) << 8)
        return pop(reads, a, "R")

    def wr(a, v):
        mine.append((1, a, v))

    def wr16(a, v):
        if a & 1:
            mine.append((1, a, v & 0xFF))
            mine.append((1, (a + 1) & 0xFFFFF, v >> 8))
        else:
            mine.append((1, a, v))

    def io_rd(p):
        return pop(ins, p, "I") & 0xFF

    def io_rd16(p):
        if p & 1:                                       # (unaligned: two bus words, logged as bytes)
            return (pop(ins, p, "I") & 0xFF) | ((pop(ins, (p + 1) & 0xFFFF, "I") & 0xFF) << 8)
        return pop(ins, p, "I")

    def io_wr(p, v):
        mine.append((3, p, v))

    def io_wr16(p, v):
        if p & 1:
            mine.append((3, p, v & 0xFF))
            mine.append((3, (p + 1) & 0xFFFF, v >> 8))
        else:
            mine.append((3, p, v))

    vec = [None]
    c = V30(rd, wr, io_rd, io_wr, lambda: vec[0], rd16, wr16, io_rd16, io_wr16)
    c.icount = 1 << 60
    regsl = regs.tolist()
    accl = acc.tolist()
    offl = off.tolist()
    cycl = cyc.tolist()
    pcl = pcs.tolist()
    seen = set()
    bad = 0
    synced = False
    c.flushed = False

    def load(r):
        c.r[:] = r[0:8]
        c.sr[:] = r[8:12]
        c.expand(r[12])
        c.ip = r[13]
    load(regsl[0])
    for i in range(len(regsl) - 1):
        r = regsl[i]
        pc = pcl[i]
        text = texts[tix[i]]
        reads.clear()
        ins.clear()
        del mine[:]
        del missing[:]
        logw = []
        accs = []
        for v in accl[offl[i]:offl[i + 1]]:
            k, a, d = v >> 40, (v >> 16) & 0xFFFFF, v & 0xFFFF
            accs.append((k, a, d))
            if k == 0:
                reads[a].append(d)
                if a < 0x40000:
                    rom[a] = d & 0xFF
                    if not a & 1 and d > 0xFF:
                        rom[a + 1] = d >> 8
            elif k == 2:
                ins[a].append(d)
            else:
                logw.append((k, a, d))
        if pc not in seen and all(a in rom for a in range(pc, pc + 2)):
            seen.add(pc)
            try:
                t = v30dis.decode(lambda a: rom.get(a, 0), pc)
                opcount[t.op] += 1
                t = t.text.rstrip()
            except Exception as e:
                t = "<%s>" % e
            stats["dis"] += 1
            if t != text and "escape" not in t:        # (no 8087 forms: FPU escapes are "escape")
                stats["dis_bad"] += 1
                if stats["dis_bad"] <= 10:
                    print("  dis %05X: %r, MAME %r" % (pc, t, text))
        nr = regsl[i + 1]
        c.rep_limit = None
        if text.startswith("rep"):
            k = (r[1] - nr[1]) & 0xFFFF
            c.rep_limit = k or None
        n = 0
        try:
            n = c.step()
            v = irq_vector(accs)
            if v is not None and any(reads.values()):
                vec[0] = v
                c.irq_line = True
                n += c.dispatch()
                stats["ints"] += 1
                stats["int%02X" % v] += 1
        except v30.V30Error as e:
            print("  ", e)
        if c.flushed or cycl[0] == 0:
            synced = True                               # (the queue is known after the first jump)
        ok = list(c.state()) == nr and mine == logw and not missing and not any(reads.values()) and not any(ins.values())
        if ok and synced and n != cycl[i + 1] - cycl[i]:
            ok = False
            stats["bad_cycles"] += 1
            stats["cyc %s mine %d MAME %d" % (" ".join(text.split()[:1]), n, cycl[i + 1] - cycl[i])] += 1
        stats["steps"] += 1
        if not ok:
            bad += 1
            stats["bad"] += 1
            if bad <= 12:
                print("  step #%d %05X %s:\n    mine %s cyc %d writes %s missing %s left %s\n    MAME %s cyc %d writes %s" % (
                    i, pc, text, " ".join("%04X" % x for x in c.state()), n, mine[:6], missing[:4],
                    [(hex(a), list(q)) for a, q in reads.items() if q][:3], " ".join("%04X" % x for x in nr),
                    cycl[i + 1] - cycl[i], logw[:6]))
            load(nr)
    return bad


def trace_tests():
    files = [OUT / "rtype_maincpu.npz"] + [OUT / ("probe%d.npz" % k) for k in range(PROBES)]
    total = Counter()
    for f in files:
        if not f.exists():
            continue
        t = time.time()
        stats = Counter()
        opcount = Counter()
        rom = {}
        z = np.load(f, allow_pickle=True)
        if "code" in z:
            rom.update((PROBE_AT + a, int(b)) for a, b in enumerate(z["code"]))
        for part in load_trace(f):
            replay(part, stats, opcount, rom)
        dt = time.time() - t
        print("%-14s %8d steps checked, %d mismatches (%d cycles only), %d interrupts (%s); %d distinct instructions,"
              " %d text mismatches (%.1f s, %.0f steps/s)" % (
                  f.stem, stats["steps"], stats["bad"], stats["bad_cycles"], stats["ints"],
                  " ".join("%s %d" % (k[3:], v) for k, v in sorted(stats.items()) if k.startswith("int") and k != "ints"),
                  stats["dis"], stats["dis_bad"], dt, stats["steps"] / dt))
        for k, v in sorted(stats.items(), key=lambda kv: -kv[1]):
            if k.startswith("cyc "):
                print("   %6d %s" % (v, k))
        print("  opcodes: %s" % " ".join("%02X" % o for o in sorted(opcount)))
        check(stats["bad"] == 0 and stats["dis_bad"] == 0, "trace %s" % f.stem)
        total.update(opcount)
    if total:
        print("opcodes not seen: %s" % " ".join("%02X" % o for o in range(256) if o not in total))


# ---- (c) the probe program ----------------------------------------------------------------------------------
# Loaded into R-Type's work RAM after the boot (frame 200: the CPU waits for the vblank there; IE is cleared): code at
# $40000 (PS $4000), data at $43000 (DS0 = DS1 = SS = $4300, so every operand address is $43000-$52FFF: work RAM
# above the code, then unmapped space).  Every case loads some registers and the flags (PUSH imm, POPF; IE and BRK
# clear), then runs one instruction; cases are simulated with v30.py first and kept when the control flow stays in
# the case, no interrupt is taken, nothing is written into the code and OUT only reaches unused ports.
PROBE_AT, DATA, CODE_END = 0x40000, 0x43000, 0x42F00
SEG = 0x4300
SAFE_PORTS = list(range(0x88, 0x100)) + list(range(0x1000, 0x1100))
SKIP = {0xCC, 0xCD, 0xCE, 0xF4, 0xFB, 0x9D, 0xCF}                 # (INT, HALT, EI; POPF/RETI: built below)
STRING = [0x6C, 0x6D, 0x6E, 0x6F, 0xA4, 0xA5, 0xA6, 0xA7, 0xAA, 0xAB, 0xAC, 0xAD, 0xAE, 0xAF]
NEC_0F = list(range(0x10, 0x20)) + [0x20, 0x22, 0x26, 0x28, 0x2A, 0x31, 0x33, 0x39, 0x3B, 0xE0, 0xF0]


class ProbeReject(Exception):
    pass


class ProbeGen:
    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.mem = bytearray(1 << 20)
        for a in range(DATA, 0x44000):
            self.mem[a] = self.rng.randrange(256)
        self.at = PROBE_AT
        self.cpu = V30(self._rd, self._wr, lambda p: self.rng.randrange(256), self._io_wr)
        self.cpu.interrupt = self._int
        self.cpu.icount = 1 << 60
        self.cpu.ps, self.cpu.ip = PROBE_AT >> 4, 0
        self.cases = 0
        self.code = bytearray()
        self.emit(bytes.fromhex("EA 05 00 00 40"), check=False)                 # (BR far: the queue is known)
        self.emit(self.segs(), check=False)

    def _rd(self, a):
        return self.mem[a] if a < 0x44000 else 0         # (unmapped: 0)

    def _wr(self, a, v):
        if a < DATA:
            raise ProbeReject("write %05X" % a)
        if a < 0x44000:
            self.mem[a] = v

    def _io_wr(self, p, v):
        if p not in SAFE_PORTS:
            raise ProbeReject("out %04X" % p)

    def _int(self, *a):
        raise ProbeReject("interrupt")

    def segs(self):
        return bytes.fromhex("B8 00 43 8E D8 8E C0 8E D0")                 # DS0 DS1 SS = $4300

    def emit(self, code, check=True):
        """Simulates code at self.at; keeps it when it runs to its end; returns success."""
        c = self.cpu
        end = self.at + len(code)
        if end > CODE_END:
            return False
        snap = (bytes(self.mem[DATA:0x53000]), c.state(), c.pf_count)
        self.mem[self.at:end] = code
        try:
            for _ in range(200):
                if c.pc == end and not c.rep_params:
                    break
                c.step()
                if c.halted or not self.at <= c.pc <= end or c.sr[1] != 0x4000:
                    raise ProbeReject("pc %05X" % c.pc)
            else:
                raise ProbeReject("no end")
            if c.tf or c.ie or c.mf != 1:
                raise ProbeReject("flags")
        except (ProbeReject, v30.V30Error, ZeroDivisionError) as e:
            if not check:
                raise
            self.mem[DATA:0x53000] = snap[0]
            self.mem[self.at:end] = bytes(len(code))
            st = snap[1]
            c.r[:] = st[0:8]
            c.sr[:] = st[8:12]
            c.expand(st[12])
            c.ip = st[13]
            c.rep_params = c.halted = 0
            c.pf_count = snap[2]
            return False
        self.at = end
        if tuple(c.sr) != (SEG, 0x4000, SEG, SEG):
            self.emit(self.segs(), check=False)
        return True

    def setup(self, force=None):
        r = self.rng
        v = {}
        for i in range(8):
            if r.random() < 0.3:
                v[i] = r.randrange(0x10000) if r.random() < 0.5 else r.randrange(0x100)
        if 4 in v or r.random() < 0.2:
            v[4] = r.randrange(0x300, 0xF00)            # (the stack stays in the work RAM)
        v.update(force or {})
        code = []
        for i, x in sorted(v.items()):
            code += [0xB8 + i, x & 0xFF, x >> 8]
        f = r.randrange(0x10000) & ~0x0300
        code += [0x68, f & 0xFF, f >> 8, 0x9D]
        return code

    def rnd_ins(self, pre):
        """pre (opcode bytes) + random ModRM/operands, cut to MAME's decoded length."""
        r = self.rng
        tail = [r.randrange(256) for _ in range(8)]
        if r.random() < 0.4:
            tail[0] |= 0xC0
        b = bytes(pre + tail)
        n = v30dis.decode(lambda a: b[a - PROBE_AT] if a - PROBE_AT < len(b) else 0, PROBE_AT).length
        return list(b[:n])

    def grp_tail(self, o, k):
        """ModRM (BW or [bw]) with reg field k, then the operands MAME decodes."""
        r = self.rng
        m = (k << 3) | r.choice((0xC3, 0xC3, 0x07, 0x47))
        b = bytes([o, m] + [r.randrange(256) for _ in range(6)])
        n = v30dis.decode(lambda a: b[a - PROBE_AT] if a - PROBE_AT < len(b) else 0, PROBE_AT).length
        return list(b[1:n])

    def case(self, build, tries=40):
        for _ in range(tries):
            if self.emit(bytes(build())):
                self.cases += 1
                return True
            if self.at + 64 > CODE_END:
                return False
        return False

    def generate(self):
        r = self.rng
        plain = [o for o in range(256) if o not in SKIP and not 0x70 <= o <= 0x7F and o not in
                 (0x0F, 0x26, 0x2E, 0x36, 0x3E, 0x64, 0x65, 0xF2, 0xF3, 0xE0, 0xE1, 0xE2, 0xE3, 0xE8, 0xE9, 0xEA, 0xEB,
                  0x9A, 0xC2, 0xC3, 0xCA, 0xCB, 0xE6, 0xE7, 0xEE, 0xEF, 0x6E, 0x6F, 0x62, 0xFF, 0xC8)]
        builders = []
        for o in plain:
            builders.append(lambda o=o: self.setup() + self.rnd_ins([o]))
        for sub in NEC_0F:
            builders.append(lambda sub=sub: self.setup({1: r.randrange(0x20)}) + self.rnd_ins([0x0F, sub]))
        for o in plain[:: 3]:
            builders.append(lambda o=o: self.setup() + [r.choice((0x26, 0x2E, 0x36, 0x3E))] + self.rnd_ins([o]))
        for rep in (0xF2, 0xF3, 0x64, 0x65):
            for o in STRING:
                builders.append(lambda rep=rep, o=o: self.setup({1: r.randrange(7), 2: r.choice(SAFE_PORTS)})
                                + [rep] + ([r.choice((0x26, 0x2E, 0x36, 0x3E))] if r.random() < 0.3 else []) + [o])
        for o in (0x6E, 0x6F, 0xEE, 0xEF):
            builders.append(lambda o=o: self.setup({2: r.choice(SAFE_PORTS)}) + [o])
        for o in (0xE6, 0xE7):
            builders.append(lambda o=o: self.setup() + [o, r.randrange(0x88, 0x100)])
        for o in list(range(0x70, 0x80)) + [0xE0, 0xE1, 0xE2, 0xE3, 0xEB]:
            def br(o=o):
                k = r.randrange(4)
                return self.setup({1: r.randrange(3)} if o >= 0xE0 else None) + [o, k] + [0x90] * k
            builders.append(br)
        builders.append(lambda: self.setup() + [0xE9, 2, 0, 0x90, 0x90])

        def near(o):                                    # CALL/BR near, RET / RET imm to the next instruction
            def b():
                base = self.setup()
                at = self.at + len(base)
                if o == 0xE8:
                    return base + [0xE8, 1, 0, 0x90]
                if o in (0xC3, 0xC2):
                    nxt = at - PROBE_AT + 3 + 1 + (3 if o == 0xC2 else 1)
                    tail = [0xC2, r.randrange(0, 8) * 2, 0] if o == 0xC2 else [0xC3]
                    return base + [0xB8, nxt & 0xFF, nxt >> 8, 0x50] + tail
                if o in (0xCB, 0xCA, 0xCF):             # RETF / RETF imm / RETI: frame pushed first
                    n_tail = 3 if o == 0xCA else 1
                    nxt = at - PROBE_AT + 3 + 3 + (3 if o == 0xCF else 0) + n_tail
                    f = r.randrange(0x10000) & ~0x0300
                    frame = ([0x68, f & 0xFF, f >> 8] if o == 0xCF else []) + [0x68, 0, 0x40, 0x68, nxt & 0xFF, nxt >> 8]
                    return base + frame + ([0xCA, r.randrange(0, 8) * 2, 0] if o == 0xCA else [o])
                if o == 0x9A:
                    nxt = at - PROBE_AT + 5
                    return base + [0x9A, nxt & 0xFF, nxt >> 8, 0, 0x40]
                if o == 0xEA:
                    nxt = at - PROBE_AT + 5
                    return base + [0xEA, nxt & 0xFF, nxt >> 8, 0, 0x40]
                if o == 0x9D:
                    f = r.randrange(0x10000) & ~0x0300
                    return base + [0x68, f & 0xFF, f >> 8, 0x9D]
            return b
        for o in (0xE8, 0xC3, 0xC2, 0xCB, 0xCA, 0xCF, 0x9A, 0xEA, 0x9D):
            builders.append(near(o))

        def ff():                                       # FF group: INC DEC CALL CALLF BR BRF PUSH via a register or memory
            base = self.setup({3: r.randrange(0x100) * 2, 6: r.randrange(0x100) * 2})
            k = r.randrange(7)
            if k in (0, 1, 6):
                return base + self.rnd_ins([0xFF, (k << 3) | r.choice((0xC0, 0x00, 0x40)) | r.randrange(8)])
            # target: the instruction after, via AW (register forms) or the word at [bw+ix] (and the segment after it)
            at = self.at + len(base)
            mem = r.random() < 0.6 and k in (2, 3, 4, 5) or k in (3, 5)
            ins = [0xFF, (k << 3) | (0x00 if mem else 0xC0)]
            if mem:                                     # MOV word ptr [bw+ix],nxt; MOV word ptr [bw+ix+2],$4000
                nxt = at - PROBE_AT + 9 + 2
                return base + [0xC7, 0x00, nxt & 0xFF, nxt >> 8, 0xC7, 0x40, 0x02, 0x00, 0x40] + ins
            nxt = at - PROBE_AT + 3 + 2
            return base + [0xB8, nxt & 0xFF, nxt >> 8] + ins
        builders += [ff] * 8

        def enter():
            return self.setup({4: r.randrange(0x400, 0xF00), 5: r.randrange(0x400, 0xF00)}) + \
                [0xC8, r.randrange(0x20), r.randrange(2), r.randrange(4)] + ([0xC9] if r.random() < 0.7 else [])
        builders += [enter] * 3

        def chkind():
            base = self.setup()
            lo, hi = sorted((r.randrange(0x10000), r.randrange(0x10000)))
            return base + [0xC7, 0x00, lo & 0xFF, lo >> 8, 0xC7, 0x40, 0x02, hi & 0xFF, hi >> 8, 0x62, 0x00 | (r.randrange(8) << 3)]
        builders += [chkind] * 3
        for o in (0xF6, 0xF7, 0xD0, 0xD1, 0xD2, 0xD3, 0xC0, 0xC1, 0xFE, 0x80, 0x81, 0x83):
            for k in range(8):                          # every group member; DIV with operands that fit
                def grp(o=o, k=k):
                    force = {2: r.randrange(0x10), 0: r.randrange(0x10000), 3: r.randrange(0x40, 0x10000) | 1,
                             1: r.randrange(0x20)} if k >= 6 else {1: r.randrange(0x20)}
                    return self.setup(force) + [o] + self.grp_tail(o, k)
                builders.append(grp)
        while self.at + 64 < CODE_END:
            r.shuffle(builders)
            for b in builders:
                if not self.case(b):
                    if self.at + 64 >= CODE_END:
                        break
        self.mem[self.at:self.at + 2] = b"\xEB\xFE"     # BR $
        return self.at


def probe_script(end):
    lines = ["local dbg = manager.machine.debugger", "local cpu = manager.machine.devices[':maincpu']",
             "local space = cpu.spaces['program']", "local frame = 0", "sub = emu.register_frame_done(function()",
             "  frame = frame + 1", "  if frame == 200 then",
             "    local f = io.open('probe.bin', 'rb'); local data = f:read('*a'); f:close()",
             "    for i = 1, #data do space:write_u8(0x%X + i - 1, data:byte(i)) end" % PROBE_AT,
             "    cpu.state['PSW'].value = 0xF002", "    cpu.state['PS'].value = 0x%X" % (PROBE_AT >> 4),
             "    cpu.state['PC'].value = 0", "    dbg:command('focus maincpu')",
             "    dbg:command(" + lua_quote("trace probe.txt,maincpu,noloop,%s" % TRACELOG) + ")"]
    lines += ["    dbg:command(%s)" % lua_quote(w) for w in WPS]
    lines += ["    dbg:command(%s)" % lua_quote("bpset %X,1,{trace off,maincpu; wpclear; wpiclear; bpclear; g}" % end),
              "  end", "  if frame == 204 then dbg:command('trace off,maincpu') dbg:command('wpclear') dbg:command('wpiclear') end",
              "end)", "dbg:command('go')"]
    return "\n".join(lines) + "\n"


PROBES = 8


def make_probes():
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = []
    for k in range(PROBES):
        d = OUT / ("run_probe%d" % k)
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir()
        g = ProbeGen(30 + k)
        end = g.generate()
        print("probe %d: %d cases, %d bytes" % (k, g.cases, end - PROBE_AT))
        (d / "probe.bin").write_bytes(bytes(g.mem[PROBE_AT:0x44000]))
        (d / "t.lua").write_text(probe_script(end))
        log = open(d / "mame.log", "w")
        jobs.append((k, d, subprocess.Popen(mame_cmd("t.lua", 6), cwd=d, stdout=log, stderr=subprocess.STDOUT)))
    for k, d, p in jobs:
        p.wait()
        f = d / "probe.txt"
        if not f.exists():
            print("no probe trace (see %s)" % (d / "mame.log"))
            continue
        part = parse_trace(f)
        code = np.frombuffer((d / "probe.bin").read_bytes()[:CODE_END - PROBE_AT], np.uint8)
        np.savez_compressed(OUT / ("probe%d.npz" % k), code=code, **{"%s_0" % k2: v for k2, v in part.items()})
        shutil.rmtree(d)
        print("probe %d: %d instructions traced" % (k, len(part["cyc"])))


def main():
    args = sys.argv[1:]
    unit_tests()
    regen = "--regen" in args
    if regen or not (OUT / "rtype_maincpu.npz").exists() or not (OUT / "probe0.npz").exists():
        if have_mame():
            if regen or not (OUT / "probe0.npz").exists():
                make_probes()
            if regen or not (OUT / "rtype_maincpu.npz").exists():
                make_trace()
        else:
            print("MAME traces: skipped (no mame or build/rtype/mame_roms)")
    trace_tests()
    print("v30: %s" % ("OK" if not FAILS else "%d FAILED" % len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
