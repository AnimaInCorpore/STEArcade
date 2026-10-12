"""Tests of the KONAMI-1 (an MC6809 with encrypted opcodes) in m6809.py and m6809dis.py.

    python engine/konami1_test.py [--regen] [--only <game>_<cpu>]

(a) konami1_opcode: the keys of MAME's konami1.cpp ($22 $82 $28 $88 by address bits 1 and 3), the boundary;
(b) MAME traces of Track & Field's and Hyper Sports' main CPU and Gyruss's sub CPU (the boot and 2 s of the attract
    mode, every bus read and write), replayed as engine/m6809_test.py does: the disassembler's text (MAME prints the
    decrypted opcodes) must equal MAME's, and the interpreter with rd_op = konami1_opcode(rd) must reproduce every
    step (registers, writes, cycles).  The opcode fetches appear in the trace as the raw (encrypted) bytes.
The traces are made once into build/m6809/ (not in git; they hold ROM bytes) when MAME and the ROMs are there.
"""
import os
import shutil
import subprocess
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import m6809
import m6809dis
import m6809_test as T
from paths import ROMS

# fixture: (MAME set, CPU tag, encryption boundary)
FIXTURES = {"trackfld_maincpu": ("trackfld", "maincpu", 0),
            "hyperspt_maincpu": ("hyperspt", "maincpu", 0),
            "gyruss_sub": ("gyruss", "sub", 0)}
FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("FAIL", msg)


def unit_tests():
    keys = {0x0: 0x22, 0x2: 0x82, 0x8: 0x28, 0xA: 0x88}
    for a in range(0x10000):
        if m6809.konami1_xor(a) != keys[a & 0xA]:
            check(False, "konami1_xor %04X" % a)
            break
    mem = bytes(range(256)) * 256
    rd = mem.__getitem__
    k0 = m6809.konami1_opcode(rd)
    kb = m6809.konami1_opcode(rd, 0x6000)
    check(all(k0(a) == mem[a] ^ keys[a & 0xA] for a in range(0, 0x10000, 7)), "konami1_opcode")
    check(all(kb(a) == (mem[a] ^ keys[a & 0xA] if a >= 0x6000 else mem[a]) for a in range(0, 0x10000, 7)),
          "konami1_opcode boundary")
    # LDA #$12 / LDB #$34 / page 2 LDY #$5678 / NOP, encrypted at $8000: operands are plain
    plain = [(0x86, 0x12), (0xC6, 0x34), (0x10, 0x8E, 0x56, 0x78), (0x12,)]
    m = bytearray(0x10000)
    a = 0x8000
    for ins in plain:
        for i, b in enumerate(ins):
            ophead = i == 0 or (ins[0] == 0x10 and i == 1)
            m[a] = b ^ keys[a & 0xA] if ophead else b
            a += 1
    m[0xFFFE:0x10000] = b"\x80\x00"
    c = m6809.M6809(m.__getitem__, m.__setitem__, m6809.konami1_opcode(m.__getitem__, 0x6000))
    c.reset()
    for _ in range(4):
        c.step()
    check((c.a, c.b, c.y, c.pc) == (0x12, 0x34, 0x5678, 0x8009), "KONAMI-1 run: %s" % (c.state(),))
    texts = []
    a = 0x8000
    for _ in range(4):
        ins = m6809dis.decode(m.__getitem__, a, rd_op=m6809.konami1_opcode(m.__getitem__, 0x6000))
        texts.append(ins.text)
        a += ins.length
    check(texts == ["LDA    #$12", "LDB    #$34", "LDY    #$5678", "NOP"], "KONAMI-1 text: %s" % texts)
    print("unit tests: %d failures" % len(FAILS))


def have_mame():
    return shutil.which("mame") is not None and all((ROMS / (g + ".zip")).exists() for g, _, _ in FIXTURES.values())


def make_traces(names):
    """MAME (in parallel, fresh directories: no nvram/cfg) for the named fixtures -> build/m6809/<name>.npz."""
    T.OUT.mkdir(parents=True, exist_ok=True)
    seconds = T.WINDOWS[-1][1] // 60 + 2
    jobs = []
    for name in names:
        game, cpu, _ = FIXTURES[name]
        d = T.OUT / ("run_" + name)
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir()
        (d / "t.lua").write_text(T.trace_script(cpu, T.WINDOWS))
        log = open(d / "mame.log", "w")
        jobs.append((name, d, subprocess.Popen(T.mame_cmd(game, "t.lua", seconds), cwd=d, stdout=log,
                                               stderr=subprocess.STDOUT)))
    for name, d, p in jobs:
        p.wait()
        T.pack(name, d)


def trace_tests(names):
    opcount = Counter()
    for name in names:
        f = T.OUT / (name + ".npz")
        if not f.exists():
            check(False, "no trace %s" % name)
            continue
        t = time.time()
        stats = Counter()
        parts, skip = T.load_trace(f)
        for part in parts:
            T.replay(part, stats, opcount, name, skip, False, boundary=FIXTURES[name][2])
        dt = time.time() - t
        print("%-18s %8d steps checked, %d mismatches, %4d interrupts, %3d waits; %5d distinct instructions, %d text "
              "mismatches (%.1f s)" % (name, stats["steps"], stats["bad"], stats["ints"], stats["waits"], stats["dis"],
                                       stats["dis_bad"], dt))
        check(stats["steps"] > 0 and stats["bad"] == 0 and stats["dis_bad"] == 0, "trace %s" % name)
    ops = set(opcount)
    print("opcode coverage: %d distinct opcodes (%d page 2, %d page 3)" % (
        len(ops), sum(1 for o in ops if o >> 8 == 0x10), sum(1 for o in ops if o >> 8 == 0x11)))


def main():
    args = sys.argv[1:]
    names = [args[args.index("--only") + 1]] if "--only" in args else list(FIXTURES)
    unit_tests()
    missing = [n for n in names if "--regen" in args or not (T.OUT / (n + ".npz")).exists()]
    if missing:
        if have_mame():
            make_traces(missing)
        else:
            print("MAME traces: skipped (no mame or ROMs)")
            names = [n for n in names if n not in missing]
    trace_tests(names)
    print("konami1: %s" % ("OK" if not FAILS else "%d FAILED" % len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
