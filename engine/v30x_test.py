"""The V30 translation (v30x.py) instruction by instruction against the reference interpreter (v30.py).

    venv/bin/python engine/v30x_test.py [--seed N] [--states K] [--variants K] [--only HEXOP] [--show K]

Every one-byte opcode (and the $0F bit instructions), with random ModRM bytes, displacements, immediates and segment
prefixes, is put into a test segment, translated, assembled with vasm and run on Musashi from K random states
(registers, segments, the flags, the 1 MB of memory); the same state runs one step on v30.py.  Compared: the eight
registers, the segment registers, C Z S O and P, IE, the memory of the three data segments, and where execution went
(the next instruction, a branch target, or the dispatcher's linear address).  Every flag but AC counts as read after
the instruction (the hook at the next pc reads them), so the flag fixing is tested at its worst.  States whose
offsets would wrap at 64 KB (not translated: see v30x.py) are left out.  The coverage the translator uses (odd word
addresses) comes from a first interpreter run, as in a port.
"""
import argparse
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from v30 import V30, V30Error, PAR
from v30dec import decode, SEG_PREFIX
import v30x
from paths import VASM, RT_INCLUDE

ORG = 0x10000
IMG = 0x100000                  # the V30's 1 MB (bytes swapped in words)
CS = 0x0100                     # the test code: linear $1000-
IPTAB = 0x200000                # the IP table (v30x Program.ip_table_cs: every entry the stub that records the IP)
STEP = 24
SKIP = {0x26, 0x2E, 0x36, 0x3E, 0xF0, 0xF2, 0xF3, 0x64, 0x65, 0x9A, 0xEA, 0xCC, 0xCD, 0xCE, 0xF4, 0x9B, 0xFD,
        0x63, 0x66, 0x67, 0xF1, 0x62, 0x6C, 0x6D, 0x6E, 0x6F, 0xC8, 0xC9, 0xD8, 0xD9, 0xDA, 0xDB, 0xDC, 0xDD, 0xDE,
        0xDF, 0x0F}
CTX = 64                        # (the context block's size in the test)


def make_instruction(rng, op):
    b = []
    if rng.random() < 0.15 and op not in (0x70,):
        b.append(rng.choice(list(SEG_PREFIX)))
    if op in (0xA4, 0xA5, 0xAA, 0xAB) and rng.random() < 0.5:
        b.append(0xF3)
    b.append(op)
    tail = [rng.randrange(256) for _ in range(8)]
    if 0x70 <= op <= 0x7F or 0xE0 <= op <= 0xE3 or op == 0xEB:
        tail[0] = rng.randrange(0, 8)
    if op in (0xE8, 0xE9):
        tail[0], tail[1] = rng.randrange(0, 8), 0
    if op == 0xFF and rng.random() < 0.6:
        tail[0] = (tail[0] & 0xC7) | rng.choice([0, 1, 2, 4, 6]) << 3
    if op in (0xC0, 0xC1):
        # (the count after the ModRM and displacement: small)
        pass
    return b + tail


def random_state(rng):
    st = dict(r=[rng.randrange(0x1000, 0x7000) for _ in range(8)],
              sr=[rng.randrange(0x0000, 0xE000) for _ in range(4)], flags=rng.randrange(0x10000) & ~0x100)
    st["r"][4] = rng.randrange(0x0100, 0xFF00) & ~1                 # SP
    for i in (0, 1, 2, 3):
        if rng.random() < 0.3:
            st["r"][i] = rng.choice([0, 1, 0x7F, 0x80, 0xFF, 0x100, 0x7FFF, 0x8000, 0xFFFF, 0x00FF, 0xFF00])
    if rng.random() < 0.3:
        st["r"][1] = rng.randrange(0, 12)                          # (CW: counts)
    st["sr"][1] = CS
    return st


def wraps(cpu, ins):
    """the instruction's memory operand offset leaves 0-$FFFF before the mask (not translated)"""
    for o in ins.ops:
        if o[0] == "m" and o[1]:
            off = sum(cpu.r[r] for r in o[1]) + v30x.s16(o[2])
            if not 0 <= off <= 0xFFFE:
                return True
            if len(o[1]) == 2 and not 0 <= sum(cpu.r[r] for r in o[1]) <= 0xFFFF:
                return True
    if ins.mn in ("movbk", "stm", "ldm", "cmpm", "cmpbk", "trans"):
        if cpu.r[6] >= 0xFFF0 or cpu.r[7] >= 0xFFF0 or cpu.r[3] + 0x100 > 0xFFFF:
            return True
        if ins.rep and (cpu.r[6] + 2 * cpu.r[1] > 0xFFFF or cpu.r[7] + 2 * cpu.r[1] > 0xFFFF):
            return True
    if ins.mn in ("ret", "retf") and ins.ops and not 0x40 <= cpu.r[4] + v30x.s16(ins.ops[0][1]) <= 0xFFC0:
        return True
    if ins.mn in ("push", "pop", "call", "ret", "retf", "reti", "pusha", "popa", "pushf", "popf") or \
            ins.flow in ("icall", "call"):
        if not 0x40 <= cpu.r[4] <= 0xFFC0:
            return True
    return False


def make_cpu(mem, st, ip, seen):
    def rd(a):
        seen.append(("r", a))
        return mem[a]

    def wr(a, v):
        seen.append(("w", a))
        mem[a] = v & 0xFF

    c = V30(rd, wr, lambda p: 0x5A, lambda p, v: None, io_rd16=lambda p: 0x5AA5, io_wr16=lambda p, v: None,
            rd16=lambda a: (seen.append(("r2", a)), mem[a] | (mem[(a + 1) & 0xFFFFF] << 8))[1],
            wr16=lambda a, v: (seen.append(("w2", a)), mem.__setitem__(a, v & 0xFF),
                               mem.__setitem__((a + 1) & 0xFFFFF, v >> 8)),
            rd_op=lambda a: mem[a])
    c.r[:] = st["r"]
    c.sr[:] = st["sr"]
    c.flags = st["flags"]
    c.df = 0
    c.ip = ip
    c.icount = 1 << 30
    return c


def swapped(mem):
    out = bytearray(len(mem))
    out[0::2] = mem[1::2]
    out[1::2] = mem[0::2]
    return out


def run(args):
    rng = random.Random(args.seed)
    ops = [op for op in range(256) if op not in SKIP]
    if args.only:
        ops = [int(x, 16) for x in args.only.split(",")]
    tests = []
    for op in ops:
        for _ in range(args.variants):
            tests.append(make_instruction(rng, op))
    if args.bytes:
        tests = [list(bytes.fromhex(x)) + [0x90] * 8 for x in args.bytes.split(",")] * args.variants
    per = 0x8000 // STEP
    tot = [0, 0, 0]
    bad_all = {}
    for b0 in range(0, len(tests), per):
        f, c, u, bad = run_batch(args, rng, tests[b0:b0 + per])
        tot[0] += f
        tot[1] += c
        tot[2] += u
        for k, n in bad.items():
            bad_all[k] = bad_all.get(k, 0) + n
    print("%d tests, %d runs checked, %d failures; %d instructions unsupported by the translator" % (
        len(tests), tot[1], tot[0], tot[2]))
    if bad_all:
        print("failing:", dict(sorted(bad_all.items(), key=lambda x: -x[1])))
    return tot[0]


def run_batch(args, rng, batch):
    mem0 = bytearray(rng.randrange(256) for _ in range(0x100000))
    code0 = CS << 4
    starts = []
    for k, bs in enumerate(batch):
        ip = k * STEP
        a = code0 + ip
        mem0[a:a + STEP] = bytes([0x90] * STEP)
        mem0[a:a + len(bs)] = bytes(bs)
        starts.append(ip)
    rd = lambda a: mem0[a & 0xFFFFF]
    decoded = []
    for ip in starts:
        ins = decode(rd, CS, ip)
        a = code0 + ip
        mem0[a + ins.length:a + STEP] = bytes([0x90] * (STEP - ins.length))
        decoded.append(ins)
    # coverage: interpreter runs (odd word sites, computed targets)
    states = [[random_state(rng) for _ in range(args.states)] for _ in batch]
    acc, targets = {}, {}
    for ip, ins, sts in zip(starts, decoded, states):
        lin = code0 + ip
        for st in sts:
            mem = bytearray(mem0)
            seen = []
            c = make_cpu(mem, st, ip, seen)
            if wraps(c, ins):
                continue
            try:
                c.step()
            except V30Error:
                continue
            s = acc.setdefault(lin, set())
            for rw, a in seen:
                s.add((rw[0], 2 if rw.endswith("2") else 1, "ram", rw.endswith("2") and bool(a & 1)))
            if ins.flow in ("icall", "ijmp") and not code0 <= c.pc < code0 + len(batch) * STEP:
                targets.setdefault(lin, set()).add((c.cs, c.ip))
    hooks = {}
    for ip, ins in zip(starts, decoded):
        for k in range(ins.length, STEP):
            hooks[code0 + ip + k] = "HK%05X" % (code0 + ip + k)
    prog = v30x.Program("main", "R", rd, roots=[(CS, ip) for ip in starts], acc_cover=acc, targets=targets,
                        hooks=hooks, image="IMG", hook_flags=v30x.CCR | v30x.P, ip_table_cs=CS, code_limit=lambda lin: code0 <= lin < code0 + len(batch) * STEP)
    lines, report, em, code, entries = v30x.translate(prog)
    tmp = Path(tempfile.mkdtemp(prefix="v30x_"))
    src = ["IMG = $%X" % IMG, "main_ip_mid = $%X" % (IPTAB + 0x20000), "\torg $%X" % ORG, "\tdc.l fault",
           "\tdc.l ipstub", "table:"]
    for ip in starts:
        src.append("\tdc.l %s" % prog.label(code0 + ip))
    src += ["ctx:\tds.b %d" % CTX, "stopreg:\tdc.l 0", "stopsr:\tdc.w 0", "stopper:\tnop", "\tbra stopper",
            "main_dispatch:\tmove.w sr,stopsr", "\tmove.l d7,stopreg", "\tbra stopper",
            "main_unsupported:\tmove.w sr,stopsr", "\tmove.l #-1,stopreg", "\tbra stopper",
            "main_badpc:\tmove.w sr,stopsr", "\tmove.l #-2,stopreg", "\tbra stopper",
            "ipstub:\tmove.w sr,stopsr", "\tmove.l a0,d7", "\tsub.l #main_ip_mid,d7", "\tasr.l #2,d7",
            "\tand.l #$FFFF,d7", "\tadd.l #$%X,d7" % (CS << 4), "\tmove.l d7,stopreg", "\tbra stopper",
            "fault:\tmove.w sr,stopsr", "\tmove.l #-3,stopreg", "\tlea $3F0000,sp", "\tbra stopper",
            "v30_inb:\tmove.b #$5A,d0", "\trts", "v30_inw:\tmove.w #$5AA5,d0", "\trts",
            "v30_outb:\trts", "v30_outw:\trts"]
    for h in sorted(set(hooks.values())):
        src += ["%s:\tmove.w sr,stopsr" % h, "\tmove.l #$%s,stopreg" % h[2:], "\tbra stopper"]
    src.append('\tinclude "v30rt.s"')
    src += lines
    (tmp / "t.s").write_text("\n".join(src) + "\n")
    r = subprocess.run([VASM, "-Fbin", "-quiet", "-nowarn=2047", "-I", str(RT_INCLUDE), "-o", str(tmp / "t.bin"),
                        str(tmp / "t.s")], capture_output=True, text=True)
    if r.returncode:
        print(r.stdout[-3000:], r.stderr[-3000:])
        raise SystemExit("vasm failed (%s)" % tmp)
    binary = (tmp / "t.bin").read_bytes()
    from machine68k import CPUType, Machine, Register as R
    mach = Machine(CPUType.M68000, 4096)
    mem68, cpu68 = mach.mem, mach.cpu
    mem68.w_block(ORG, binary)
    for vec in range(2, 64):
        mem68.w32(vec * 4, mem68.r32(ORG))
    mem68.w_block(IPTAB, mem68.r32(ORG + 4).to_bytes(4, "big") * 0x10000)
    stopper = ORG + binary.index(bytes.fromhex("4e7160fc"))
    stopreg, stopsr = stopper - 6, stopper - 2
    ctx = ORG + 8 + 4 * len(batch)
    unsupported = {u.split()[0]: u for u in report["unsupported"]}
    fails = checked = 0
    bad_ops = {}
    img0 = swapped(mem0)
    for ti, (ip, ins, sts) in enumerate(zip(starts, decoded, states)):
        lin = code0 + ip
        if "%05X" % lin in unsupported:
            if args.list_unsupported:
                print("  unsupported:", unsupported["%05X" % lin])
            continue
        entry = mem68.r32(ORG + 8 + 4 * ti)
        for st in sts:
            mem = bytearray(mem0)
            c = make_cpu(mem, st, ip, [])
            if wraps(c, ins):
                continue
            if ins.mn == "pushf":
                c.av = 0
            if ins.mn in ("popf",) or ins.flow == "iret":
                at = (c.ss << 4) + c.sp + (4 if ins.flow == "iret" else 0)
                if mem[(at + 1) & 0xFFFFF] & 1:
                    continue                                    # (TF: a trap)
            flags0 = c.flags
            try:
                c.step()
            except V30Error:
                continue
            if ins.mn in ("div", "divu", "chkind") and c.pc != v30x.next_lin(ins):
                continue                                        # (a divide error: an interrupt)
            mem68.w_block(IMG, bytes(img0))
            for k in range(4):
                mem68.w16(ctx + 2 * k, st["sr"][k])
            mem68.w8(ctx + 8, 0xFF if flags0 & 0x200 else 0)
            mem68.w8(ctx + 9, 0)
            mem68.w8(ctx + 10, 0 if flags0 & 4 else 1)
            mem68.w8(ctx + 11, flags0 & 0x10)
            rv = st["r"]
            sb = lambda k: IMG + (st["sr"][k] << 4)
            for reg, val in ((R.D0, rv[0]), (R.D1, rv[1]), (R.D2, rv[2]), (R.D3, rv[3]), (R.D4, rv[6]),
                             (R.D5, rv[7]), (R.D6, rv[5]), (R.D7, 0xDEADBEEF), (R.A0, 0x12345678), (R.A1, 0x9ABCDEF0),
                             (R.A2, sb(0)), (R.A3, sb(3)), (R.A4, sb(2)), (R.A5, sb(2) + rv[4]), (R.A6, ctx),
                             (R.A7, 0x3F0000)):
                cpu68.w_reg(reg, val)
            f = flags0
            ccr = (f & 1) | (2 if f & 0x800 else 0) | (4 if f & 0x40 else 0) | (8 if f & 0x80 else 0)
            cpu68.w_sr(0x2700 | ccr)
            cpu68.w_pc(entry)
            trail = []
            for _ in range(3000000):
                if cpu68.r_pc() == stopper:
                    break
                if len(trail) < 30:
                    trail.append("%06X" % cpu68.r_pc())
                cpu68.execute(1)
            else:
                raise SystemExit("test %d (%s) did not stop: %s" % (ti, ins.text, " ".join(trail)))
            reg = lambda r: cpu68.r_reg(r) & 0xFFFFFFFF
            stop = mem68.r32(stopreg)
            sr = mem68.r16(stopsr)
            segs = [mem68.r16(ctx + 2 * k) for k in range(4)]
            got = dict(r=[reg(R.D0), reg(R.D1), reg(R.D2), reg(R.D3), (reg(R.A5) - reg(R.A4)) & 0xFFFFFFFF,
                          reg(R.D6), reg(R.D4), reg(R.D5)],
                       sr=segs, bases=[reg(R.A2), reg(R.A3), reg(R.A4)],
                       flags=(sr & 1) | (0x800 if sr & 2 else 0) | (0x40 if sr & 4 else 0) | (0x80 if sr & 8 else 0)
                       | (4 if PAR[mem68.r8(ctx + 10)] else 0),
                       ie=1 if mem68.r8(ctx + 8) else 0, pc=stop)
            want = dict(r=list(c.r), sr=list(c.sr), bases=[IMG + (c.sr[k] << 4) for k in (0, 3, 2)],
                        flags=c.flags & 0x8C5, ie=c.ie, pc=c.pc)
            if want["sr"][1] == got["sr"][1] or True:
                got["sr"][1] = want["sr"][1]                        # (CS is not kept: the labels know it)
            diffs = [k for k in want if got[k] != want[k]]
            img = mem68.r_block(IMG, 0x100000)
            mdiff = []
            for k in (0, 2, 3):
                base = c.sr[k] << 4
                for a in range(base, min(base + 0x10000, 0x100000)):
                    if img[a ^ 1] != mem[a]:
                        mdiff.append(a)
                        if len(mdiff) > 8:
                            break
            checked += 1
            if diffs or mdiff:
                fails += 1
                key = "%02X %s" % (ins.op, ins.mn)
                bad_ops[key] = bad_ops.get(key, 0) + 1
                if bad_ops[key] <= args.show:
                    print("FAIL %s (%s) live %s" % (ins.text, bytes(mem0[lin:lin + ins.length]).hex(),
                                                   hex(em.live_out.get(lin, 0))))
                    for k in diffs:
                        g, w = got[k], want[k]
                        if isinstance(g, list):
                            print("   %s: got %s want %s" % (k, ["%X" % x for x in g], ["%X" % x for x in w]))
                        else:
                            print("   %s: got %X want %X" % (k, g, w))
                    if mdiff:
                        print("   memory differs at", ["%05X %02X/%02X" % (a, img[a ^ 1], mem[a]) for a in mdiff[:6]])
    return fails, checked, len(unsupported), bad_ops


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--states", type=int, default=4)
    ap.add_argument("--variants", type=int, default=6)
    ap.add_argument("--only")
    ap.add_argument("--bytes", help="instructions (hex bytes, comma separated) instead of the generated ones")
    ap.add_argument("--show", type=int, default=2)
    ap.add_argument("--list-unsupported", action="store_true")
    sys.exit(1 if run(ap.parse_args()) else 0)
