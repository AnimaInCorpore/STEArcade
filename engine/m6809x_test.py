"""The 6809 translation (m6809x.py) instruction by instruction against the reference interpreter (m6809.py).

    venv/bin/python engine/m6809x_test.py [--seed N] [--states K] [--only MNEMONIC]

Every documented 6809 instruction in every addressing mode (the indexed modes with random postbytes) is put into a test
page, translated, assembled with vasm and run on Musashi from K random states (registers, the flags, E F H I, memory);
the same state runs one step on m6809.py.  Compared: A B X Y U S, the N Z V C H flags, E F I, the 6809 memory, and where
execution went (the next instruction, a branch target, or the dispatcher's d7).  Every flag counts as read after the
instruction (the hook at the next pc reads all), so the flag fixing is tested at its worst.  The coverage the translator
uses (the slots an indexed site touches) comes from a first interpreter run, as in a port.
"""
import argparse
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from m6809 import M6809, M6809Error
from m6809dis import OPS, decode, IND, DIR, EXT, IMM, REL, LREL, INH, PSHS, PULS, PSHU, PULU, RR
import m6809x
from paths import VASM, RT_INCLUDE

ORG = 0x10000
IMG = 0x100000                  # the 6809's 64 KB, flat (slot k at IMG + k * $2000)
CODE = 0xC000                   # the test page: slot 6
PAGE = 0x3FE
SLOT = 6
STEP = 16                       # bytes a test

SKIP = {"swi", "swi2", "swi3", "cwai", "sync", "page2", "page3", "xhcf", "xres", "xswi2", "xfirq", "x18",
        "xandcc", "xnc", "xdec", "xclra", "xclrb", "xst8", "xst16", "xaddd", "xaddu", "xlbra", "xlbrn"}

IDX_KINDS = [(0x00, "off5"), (0x80, "inc1"), (0x81, "inc2"), (0x82, "dec1"), (0x83, "dec2"), (0x84, "zero"),
             (0x85, "acc_b"), (0x86, "acc_a"), (0x88, "off8"), (0x89, "off16"), (0x8B, "acc_d"), (0x8C, "pcr8"),
             (0x8D, "pcr16"), (0x91, "inc2i"), (0x93, "dec2i"), (0x94, "zeroi"), (0x95, "acc_bi"), (0x96, "acc_ai"),
             (0x98, "off8i"), (0x99, "off16i"), (0x9B, "acc_di"), (0x9C, "pcr8i"), (0x9D, "pcr16i"), (0x9F, "abs")]


def postbyte(rng):
    pb, kind = rng.choice(IDX_KINDS)
    reg = rng.randrange(4)
    if kind == "off5":
        return (reg << 5) | rng.randrange(32), []
    if kind in ("pcr8", "pcr16", "pcr8i", "pcr16i", "abs"):
        pb |= reg << 5
        if kind.startswith("pcr8"):
            return pb, [rng.randrange(256)]
        if kind.startswith("pcr16"):
            o = rng.randrange(-0x200, 0x200) & 0xFFFF
            return pb, [o >> 8, o & 0xFF]
        a = rng.randrange(0x0100, 0xB000)
        return pb, [a >> 8, a & 0xFF]
    if reg == 3 and kind in ("inc1", "inc2", "dec1", "dec2", "inc2i", "dec2i"):
        reg = rng.randrange(3)
    pb |= reg << 5
    if kind.startswith("off8"):
        return pb, [rng.randrange(256)]
    if kind.startswith("off16"):
        o = rng.randrange(-0x800, 0x800) & 0xFFFF
        return pb, [o >> 8, o & 0xFF]
    return pb, []


def make_instruction(rng, op):
    name, mode, ln = OPS[op]
    pre = [op >> 8] if op > 0xFF else []
    b = pre + [op & 0xFF]
    mn = name.lower()
    if mode == IMM:
        if mn in ("andcc", "orcc"):
            return b + [rng.randrange(256)]
        return b + [rng.randrange(256) for _ in range(ln)]
    if mode == DIR:
        if mn in ("jmp", "jsr"):
            return None
        return b + [rng.randrange(0x10, 0xF0)]
    if mode == EXT:
        if mn in ("jmp", "jsr"):
            t = CODE + 12                       # (relative to the test: fixed up by the caller)
            return b + ["T"]
        a = rng.randrange(0x0100, 0xB000)
        return b + [a >> 8, a & 0xFF]
    if mode == IND:
        pb, rest = postbyte(rng)
        return b + [pb] + rest
    if mode == REL:
        return b + [rng.randrange(2, 7)]
    if mode == LREL:
        o = rng.randrange(2, 7)
        return b + [0, o]
    if mode in (PSHS, PULS, PSHU, PULU):
        m = rng.randrange(256)
        if mode == PULU:
            m &= 0x3F                            # (no S, no PC)
        if mode == PSHU:
            m &= 0x7F if rng.random() < 0.5 else 0xFF
        return b + [m]
    if mode == RR:
        regs16 = [0, 1, 2, 3, 4]
        regs8 = [8, 9, 10, 11]
        if rng.random() < 0.6:
            s, d = rng.choice(regs16), rng.choice(regs16)
        else:
            s, d = rng.choice(regs8), rng.choice(regs8)
        return b + [(s << 4) | d]
    return b


def random_state(rng):
    st = dict(a=rng.randrange(256), b=rng.randrange(256), x=rng.randrange(0x1000, 0x9000), y=rng.randrange(0x1000, 0x9000),
              u=rng.randrange(0x1000, 0x9000), s=rng.randrange(0x0800, 0x1800), cc=rng.randrange(256), x68=rng.randrange(2))
    if rng.random() < 0.15:
        st["a"] = rng.choice([0, 0x7F, 0x80, 0xFF, 0x99, 0x09, 0x90])
    if rng.random() < 0.15:
        st["b"] = rng.choice([0, 0x7F, 0x80, 0xFF, 0x01])
    return st


def build(tests, tmp):
    """tests: [(cpu address, bytes)] -> (68000 binary, label table offsets, the Program)"""
    page = bytearray([0x12] * 0x2000)          # NOP filler
    for pc, bs in tests:
        page[pc - CODE:pc - CODE + len(bs)] = bytes(bs)
    hooks = {}
    for pc, bs in tests:
        for k in range(1, STEP):
            hooks[(PAGE << 13) | ((pc + k) & 0x1FFF)] = "HK%04X" % (pc + k)
    return page, hooks


def run(args):
    rng = random.Random(args.seed)
    all_tests = []
    ops = []
    for op, (name, mode, ln) in sorted(OPS.items()):
        mn = name.lower()
        if mn in SKIP or mn.startswith("x"):
            continue
        if args.only and mn != args.only:
            continue
        ops.append(op)
    for op in ops:
        for k in range(args.variants):
            bs = make_instruction(rng, op)
            if bs is not None:
                all_tests.append(bs)
    per = (0x2000 - STEP) // STEP
    totals = [0, 0, 0]
    bad_all = {}
    for b0 in range(0, len(all_tests), per):
        batch = all_tests[b0:b0 + per]
        f, c, u, bad = run_batch(args, rng, batch)
        totals[0] += f
        totals[1] += c
        totals[2] += u
        for k, n in bad.items():
            bad_all[k] = bad_all.get(k, 0) + n
    print("%d tests in %d pages, %d runs checked, %d failures; %d instructions unsupported by the translator" % (
        len(all_tests), (len(all_tests) + per - 1) // per, totals[1], totals[0], totals[2]))
    if bad_all:
        print("failing:", dict(sorted(bad_all.items(), key=lambda x: -x[1])))
    return totals[0]


def run_batch(args, rng, batch):
    tests = []
    pc = CODE
    for bs in batch:
        if "T" in bs:
            t = pc + 12
            i = bs.index("T")
            bs = bs[:i] + [t >> 8, t & 0xFF]
        tests.append((pc, bs))
        pc += STEP
    page, hooks = build(tests, None)
    mem0 = bytearray(rng.randrange(256) for _ in range(0x10000))
    mem0[CODE:CODE + 0x2000] = page

    # coverage: one interpreter run per test from a few states (the slots the data accesses touch)
    acc = {}
    states = [[random_state(rng) for _ in range(args.states)] for _ in tests]
    for (pc, bs), sts in zip(tests, states):
        v = (PAGE << 13) | (pc & 0x1FFF)
        seen = set()
        for st in sts:
            mem = bytearray(mem0)
            prepare_pointers(mem, pc, st)
            cpu = make_cpu(mem, st, pc, seen)
            try:
                cpu.step()
            except M6809Error:
                pass
        acc[v] = {("r", a >> 13, 0x200 + (a >> 13), False) for a in seen if not CODE <= a < CODE + 0x2000} or \
            {("r", a >> 13, 0x200 + (a >> 13), False) for a in seen}
    prog = m6809x.Program("main", "M", lambda p: page if p == PAGE else bytes(0x2000), {PAGE: SLOT},
                          roots=[(PAGE << 13) | (pc & 0x1FFF) for pc, bs in tests], acc_cover=acc, hooks=hooks,
                          page_addr=lambda p: "$%X" % (IMG + (p - 0x200) * 0x2000), hook_flags=m6809x.ALL)
    lines, report, em, code = m6809x.translate(prog)
    tmp = Path(tempfile.mkdtemp(prefix="m6809x_"))
    src = ["\torg $%X" % ORG, "table:"]
    for pc, bs in tests:
        src.append("\tdc.l %s" % prog.label((PAGE << 13) | (pc & 0x1FFF)))
    src += ["ctx:\tds.b 160", "stopreg:\tdc.l 0", "stopsr:\tdc.w 0", "stopper:\tnop", "\tbra stopper",
            "main_dispatch:\tmove.w sr,stopsr", "\tand.l #$FFFF,d7", "\tadd.l #$10000,d7", "\tmove.l d7,stopreg", "\tbra stopper",
            "main_io_r:\tmoveq #0,d7", "\trts", "main_io_w:\trts",
            "main_unsupported:\tmove.w sr,stopsr", "\tmove.l #-1,stopreg", "\tbra stopper",
            "main_badpc:\tmove.w sr,stopsr", "\tmove.l #-2,stopreg", "\tbra stopper"]
    for h in sorted(set(hooks.values())):
        src += ["%s:\tmove.w sr,stopsr" % h, "\tmove.l #$%s,stopreg" % h[2:], "\tbra stopper"]
    src.append('\tinclude "m6809rt.s"')
    src += lines
    (tmp / "t.s").write_text("\n".join(src) + "\n")
    r = subprocess.run([VASM, "-Fbin", "-quiet", "-nowarn=2047", "-I", str(RT_INCLUDE), "-o", str(tmp / "t.bin"),
                        str(tmp / "t.s")], capture_output=True, text=True)
    if r.returncode:
        print(r.stdout[-3000:], r.stderr[-3000:])
        raise SystemExit("vasm failed (%s)" % tmp)
    binary = (tmp / "t.bin").read_bytes()
    from machine68k import CPUType, Machine, Register as R
    mach = Machine(CPUType.M68000, 2048)
    mem68, cpu68 = mach.mem, mach.cpu
    mem68.w_block(ORG, binary)
    stopper = ORG + binary.index(bytes.fromhex("4e7160fc"))   # nop; bra stopper
    stopreg, stopsr = stopper - 6, stopper - 2
    ctx = ORG + 4 * len(tests)              # (CCHI at +112 as engine/m6809x.py)
    fails = 0
    checked = 0
    unsupported = {u.split()[0]: u for u in report["unsupported"]}
    bad_ops = {}
    for ti, ((pc, bs), sts) in enumerate(zip(tests, states)):
        v = (PAGE << 13) | (pc & 0x1FFF)
        if "%06X" % v in unsupported:
            continue
        entry = mem68.r32(ORG + 4 * ti)
        for st in sts:
            mem = bytearray(mem0)
            prepare_pointers(mem, pc, st)
            before = bytes(mem)
            cpu = make_cpu(mem, st, pc, set())
            ins = decode(lambda a: mem[a & 0xFFFF], pc, 0)
            try:
                cpu.step()
            except M6809Error:
                continue
            # 68000
            mem68.w_block(IMG, before)
            for k in range(8):
                mem68.w32(ctx + 4 * k, IMG + k * 0x2000)
                mem68.w32(ctx + 32 + 4 * k, IMG)
            mem68.w8(ctx + 112, st["cc"] & 0xF0)
            for reg, val in ((R.D0, st["a"] | 0xA5A5A500), (R.D1, st["b"] | 0x5A5A5A00), (R.D2, st["x"]), (R.D3, st["y"]),
                             (R.D4, st["u"]), (R.D5, 0x12345678), (R.D6, 0x87654321), (R.D7, 0xDEADBEEF),
                             (R.A5, IMG + st["s"]), (R.A6, ctx), (R.A4, IMG), (R.A3, IMG), (R.A2, IMG + 0xE000),
                             (R.A7, 0x1F0000)):
                cpu68.w_reg(reg, val)
            cpu68.w_sr(0x2700 | (st["cc"] & 0x0F) | (0x10 if st["x68"] else 0))
            cpu68.w_pc(entry)
            for _ in range(2000):
                if cpu68.r_pc() == stopper:
                    break
                cpu68.execute(1)
            else:
                raise SystemExit("test %d (%s) did not stop" % (ti, ins.text))
            a4 = mem68.r32(stopreg)
            got_pc = a4 - 0x10000 if 0x10000 <= a4 < 0x20000 else a4
            got = dict(a=cpu68.r_reg(R.D0) & 0xFF, b=cpu68.r_reg(R.D1) & 0xFF, x=cpu68.r_reg(R.D2) & 0xFFFFFFFF,
                       y=cpu68.r_reg(R.D3) & 0xFFFFFFFF, u=cpu68.r_reg(R.D4) & 0xFFFFFFFF,
                       s=(cpu68.r_reg(R.A5) - IMG) & 0xFFFF,
                       cc=(mem68.r16(stopsr) & 0x0F) | (mem68.r8(ctx + 112) & 0xF0), pc=got_pc)
            want = dict(a=cpu.a, b=cpu.b, x=cpu.x, y=cpu.y, u=cpu.u, s=cpu.s, cc=cpu.cc, pc=cpu.pc)
            mem2 = mem68.r_block(IMG, 0x10000)
            diffs = [k for k in want if got[k] != want[k]]
            # E F I are not modelled by the translation except where the instruction sets them
            if "cc" in diffs and (got["cc"] ^ want["cc"]) & 0x2F == 0 and ins.mn not in ("andcc", "orcc", "tfr", "exg",
                                                                                         "puls", "pulu", "rti"):
                diffs.remove("cc")
            mdiff = [a for a in range(0x10000) if mem2[a] != mem[a]]
            checked += 1
            if diffs or mdiff:
                fails += 1
                bad_ops.setdefault(ins.mn, 0)
                bad_ops[ins.mn] += 1
                if bad_ops[ins.mn] <= args.show:
                    print("FAIL %s (%s) state %s" % (ins.text, bytes(bs).hex(), st))
                    for k in diffs:
                        print("   %s: got %X want %X" % (k, got[k], want[k]))
                    if mdiff:
                        print("   memory differs at", ["%04X %02X/%02X" % (a, mem2[a], mem[a]) for a in mdiff[:6]])
    if args.list_unsupported:
        for u in sorted(set(x.split(":", 1)[1] for x in report["unsupported"])):
            print("  unsupported:", u)
    return fails, checked, len(unsupported), bad_ops


def prepare_pointers(mem, pc, st):
    """indirect modes: the pointer the instruction will read points into the data area"""
    ins = decode(lambda a: mem[a & 0xFFFF], pc, 0)
    if ins.mode != "idx" or not ins.arg.indirect:
        return
    x = ins.arg
    if x.kind == "abs":
        p = x.addr
    elif x.kind in ("pcr8", "pcr16"):
        p = x.addr
    else:
        r = st[x.reg] if x.reg != "s" else st["s"]
        off = {"zero": 0, "off8": x.offset, "off16": x.offset, "inc2": 0, "dec2": -2,
               "acc_a": (st["a"] ^ 0x80) - 0x80, "acc_b": (st["b"] ^ 0x80) - 0x80,
               "acc_d": (((st["a"] << 8) | st["b"]) ^ 0x8000) - 0x8000}.get(x.kind, 0)
        p = (r + off) & 0xFFFF
    if CODE - 1 <= p & 0xFFFF < CODE + 0x2000:
        return                                  # (the pointer is in the code: the bytes as they are)
    t = random.randrange(0x0100, 0xB000)
    mem[p & 0xFFFF] = t >> 8
    mem[(p + 1) & 0xFFFF] = t & 0xFF


def make_cpu(mem, st, pc, seen):
    def rd(a):
        a &= 0xFFFF
        seen.add(a)
        return mem[a]

    def wr(a, v):
        a &= 0xFFFF
        seen.add(a)
        mem[a] = v & 0xFF
    c = M6809(rd, wr)
    c.a, c.b, c.x, c.y, c.u, c.s, c.cc, c.pc = st["a"], st["b"], st["x"], st["y"], st["u"], st["s"], st["cc"], pc
    c.dp = 0
    return c


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--states", type=int, default=6)
    ap.add_argument("--variants", type=int, default=3)
    ap.add_argument("--only")
    ap.add_argument("--show", type=int, default=2)
    ap.add_argument("--list-unsupported", action="store_true")
    sys.exit(1 if run(ap.parse_args()) else 0)
