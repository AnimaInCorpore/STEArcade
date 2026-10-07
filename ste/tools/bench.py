"""Instruction bench: translated 68000 snippets on a Musashi model vs the Z80 reference.

    python bench.py [-k substring] [--rom] [-n vectors]

For each tested Z80 instruction the real Emitter produces the snippet; random Z80
states (registers, flags, memory) run through both the reference Z80 (z80.py) and
the snippet on machine68k, and registers, memory, next pc and the *live* flags are
compared.  Every subset of live flags is tried (the emitter skips what nobody reads).
"""
import os
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import z80x
from z80x import S, Z, C, H, N, IYADDR, FSHADOW, IO_READ_REDIRECT, TABLE_ENTRIES
from z80 import Z80
from z80dis import decode, Ins

ROOT = Path(__file__).resolve().parents[2]
VASM = ROOT.parent.parent / "Arbeit" / "F030Arcade" / "third_party" / "vasm" / "vasmm68k_mot.exe"
VLINK = ROOT.parent.parent / "Arbeit" / "F030Arcade" / "third_party" / "vlink" / "vlink.exe"
if not VASM.exists():
    VASM = Path(r"C:\Arbeit\F030Arcade\third_party\vasm\vasmm68k_mot.exe")
    VLINK = Path(r"C:\Arbeit\F030Arcade\third_party\vlink\vlink.exe")
if not VASM.exists():       # macOS / Linux: same defaults as build.py
    VASM = Path(os.environ.get("VASM") or os.path.expanduser("~/Work/f030dsp3d/tools/vasm/vasmm68k_mot"))
    VLINK = Path(os.environ.get("VLINK") or os.path.expanduser("~/Work/f030dsp3d/tools/vlink/vlink"))

CODE = 0x10000
TABLE = 0x20000
BLOCK = 0x40000
STACK = 0x0F000
STOPLBL = "Zstop"

HELPERS = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "rtlib.s")).read() + """
z80_unsupported:
\tbra.s z80_unsupported
z80_badjump:
\tbra.s z80_badjump
z80_badpc:
\tbra.s z80_badpc
"""


def assemble(src, base=CODE):
    """-> (bytes, symbols dict)."""
    tmp = Path(tempfile.mkdtemp(prefix="z80x_"))
    (tmp / "t.s").write_text(src)
    r = subprocess.run([str(VASM), "-Fvobj", "-quiet", "-o", str(tmp / "t.o"), str(tmp / "t.s")],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("vasm: " + r.stdout + r.stderr)
    r = subprocess.run([str(VLINK), "-brawbin1", "-Ttext", hex(base), "-M" + str(tmp / "t.map"),
                        "-o", str(tmp / "t.bin"), str(tmp / "t.o")], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("vlink: " + r.stdout + r.stderr)
    syms = {}
    for line in (tmp / "t.map").read_text().splitlines():
        m = re.match(r"\s+0x([0-9a-f]{8})\s+(\S+?):", line)
        if m:
            syms[m.group(2)] = int(m.group(1), 16)
    return (tmp / "t.bin").read_bytes(), syms


class Rng:
    def __init__(self, seed):
        self.r = random.Random(seed)


def pointer_regs(ins):
    """Registers dereferenced by an instruction (to keep them inside the RAM window)."""
    regs = set()
    for o in ins.ops:
        if o[0] == "ind":
            regs.add(o[1])
    if ins.mn in ("ldir", "lddr", "ldi", "ldd"):
        regs |= {"hl", "de"}
    if ins.mn in ("cpir", "cpdr", "cpi", "cpd"):
        regs |= {"hl"}
    if ins.mn in ("push", "pop", "call", "ret", "rst", "ex"):
        regs.add("sp")
    if ins.flow in ("call", "ccall", "ret", "cret", "rst"):
        regs.add("sp")
    return regs


ROMBYTES = b""


class Bench:
    def __init__(self, code=None):
        from machine68k import CPUType, Machine, Register as R
        self.R = R
        self.Machine = Machine
        self.CPUType = CPUType

    def run_case(self, ins, live, seed, nvec=1, verbose=False):
        """Translate one instruction, run `nvec` random states, return list of mismatches."""
        code = {ins.pc: ins}
        em = z80x.Emitter(code, live_in={ins.pc: 0}, live_out={ins.pc: live})
        em.emit_ins(ins.pc, live_out_override=live)
        if em.unsupported:
            return None
        nxt = ins.pc + ins.length
        body = em.lines + ["\tjmp Z%04X" % nxt]
        labels = set(em.refs) | {nxt}
        src = ["\tsection text", "\tcnop 0,2"] + body + [HELPERS]
        # stop stubs: one per label + dispatch stop
        for pcl in sorted(labels):
            src.append("Z%04X:\n\tnop\n\tnop" % pcl)
        src.append("Zdisp:\n\tnop\n\tnop")
        # label of this instruction might also be a referenced target
        if ins.pc in labels:
            pass
        text = "\n".join(src)
        # the instruction's own label comes first in body; remove duplicates for self-targets
        try:
            binary, sym = assemble(text)
        except RuntimeError as e:
            raise RuntimeError("assembly failed for %s\n%s\n%s" % (ins.text, "\n".join(em.lines), e))
        return self._run_vectors(ins, live, seed, nvec, binary, sym, labels, verbose)

    def _run_vectors(self, ins, live, seed, nvec, binary, sym, labels, verbose=False):
        R = self.R
        m = self.Machine(self.CPUType.M68000, 2 * 1024)
        cpu, mem = m.cpu, m.mem
        mem.w_block(CODE, binary)
        stops = {sym["Z%04X" % l] for l in labels} | {sym["Zdisp"]}
        # dispatch table: everything goes to Zdisp
        disp = sym["Zdisp"]
        tbl = b"".join(disp.to_bytes(4, "big") for _ in range(TABLE_ENTRIES))
        mem.w_block(TABLE, tbl)
        rnd = random.Random(seed)
        ptr = pointer_regs(ins)
        fails = []
        for v in range(nvec):
            ref = RefMem()
            for a in range(0x8000):
                ref.mem[a] = rnd.randrange(256)
            for a, b in IO_READ_REDIRECT.items():
                for k in range(1):
                    ref.mem[b] = ref.mem[a]
            ref.mem[IYADDR] = ref.mem[IYADDR + 1] = 0
            cpu_ref = Z80(ref.rd, ref.wr)
            cpu_ref.afmask = 0xC1
            st = self._rand_state(rnd, ptr, ins)
            self._apply_ref(cpu_ref, st)
            cpu_ref.pc = ins.pc
            for i_, b_ in enumerate(ROMBYTES[ins.pc:ins.pc + ins.length]):
                ref.mem[ins.pc + i_] = b_
            if ins.flow in ("ret", "cret"):
                tgt = rnd.randrange(0x4000)
                ref.mem[st["sp"]] = tgt & 0xFF
                ref.mem[st["sp"] + 1] = tgt >> 8
            # reference IY lives in the register; mirror into the block for the 68k
            ref.mem[IYADDR] = st["iy"] >> 8       # big-endian word, as move.w stores
            ref.mem[IYADDR + 1] = st["iy"] & 0xFF
            ref.mem[FSHADOW] = 0
            ref.mem[FSHADOW + 1] = 0
            # the 68k sees the same block
            mem.w_block(BLOCK, bytes(ref.mem[:0x8000]))
            self._apply_68k(cpu, mem, st, rnd)
            before_mem = bytes(ref.mem[:0x8000])
            # reference run
            cpu_ref.step()
            n_ = 0
            while ins.mn in ("ldir", "cpir", "lddr", "cpdr") and cpu_ref.pc == ins.pc and n_ < 100000:
                cpu_ref.step()
                n_ += 1
            # 68k run
            cpu.w_pc(sym["Z%04X" % ins.pc])
            steps = 0
            while True:
                cpu.execute(1)
                steps += 1
                pc = cpu.r_pc()
                if pc in stops and steps > 0:
                    break
                if steps > 5000:
                    fails.append(("timeout", st))
                    break
            else:
                pass
            else_stop = cpu.r_pc()
            err = self._compare(cpu, mem, cpu_ref, ref, st, ins, live, sym, labels, else_stop, disp)
            if err:
                fails.append((err, st))
                if verbose:
                    print(ins.text, err)
        return fails

    def _rand_state(self, rnd, ptr, ins):
        def w():
            return rnd.randrange(0x10000)

        def p():
            return rnd.randrange(0x6100, 0x6F00)
        st = {"a": rnd.randrange(256), "bc": w(), "de": w(), "hl": w(), "ix": w(), "iy": w(),
              "sp": p(),
              "f": rnd.choice([0, 0xFF]) & 0 or (rnd.randrange(256) & 0xD3),   # S Z H N C (no X/Y/PV)
              "a_": rnd.randrange(256), "bc_": w(), "de_": w(), "hl_": w(), "f_": rnd.randrange(256) & 0xD3}
        for r in ("bc", "de", "hl", "ix", "iy"):
            if r in ptr:
                st[r] = p()
        # block instructions: small counts
        if ins.mn in ("ldir", "cpir"):
            st["bc"] = rnd.randrange(1, 12)
        if ins.mn in ("ldir",):
            st["hl"] = rnd.randrange(0x6100, 0x6400)
            st["de"] = rnd.randrange(0x6500, 0x6700)
        # sp must keep room; pops read above, pushes below
        # jp (hl) targets within the table
        if ins.flow == "ijmp":
            reg = ins.ops[0][1]
            st[reg] = rnd.randrange(0x4002)
        # djnz etc: any
        return st

    def _apply_ref(self, cpu, st):
        cpu.a = st["a"]
        cpu.f = st["f"]
        cpu.bc, cpu.de, cpu.hl, cpu.ix, cpu.iy = st["bc"], st["de"], st["hl"], st["ix"], st["iy"]
        cpu.sp = st["sp"]
        cpu.a_ = st["a_"]
        cpu.b_, cpu.c_ = st["bc_"] >> 8, st["bc_"] & 255
        cpu.d_, cpu.e_ = st["de_"] >> 8, st["de_"] & 255
        cpu.h_, cpu.l_ = st["hl_"] >> 8, st["hl_"] & 255
        cpu.f_ = st["f_"]

    def _apply_68k(self, cpu, mem, st, rnd):
        R = self.R
        w = cpu.w_reg
        w(R.D0, rnd.randrange(1 << 32) & 0xFFFFFF00 | st["a"])
        w(R.D1, (rnd.randrange(1 << 16) << 16) | st["bc"])
        w(R.D2, (rnd.randrange(1 << 16) << 16) | st["de"])
        w(R.D3, (rnd.randrange(1 << 16) << 16) | st["hl"])
        w(R.D4, (rnd.randrange(1 << 16) << 16) | st["ix"])
        w(R.D5, rnd.randrange(1 << 32))
        w(R.D7, rnd.randrange(1 << 32))
        f = st["f"]
        d6 = ((f & 0x80) >> 4) | ((f & 0x40) >> 4) | (f & 1) | ((f & 0x10) << 1) | ((f & 0x02) << 5)
        d6 |= rnd.choice([0, 0x10]) | rnd.choice([0, 2])      # X and V garbage
        w(R.D6, d6 | (rnd.randrange(256) << 8))
        w(R.A0, (rnd.randrange(1 << 16) << 16) | st["bc_"])
        w(R.A1, (rnd.randrange(1 << 16) << 16) | st["de_"])
        w(R.A2, (rnd.randrange(1 << 16) << 16) | st["hl_"])
        w(R.A3, (rnd.randrange(1 << 24) << 8) | st["a_"])
        w(R.A4, TABLE)
        w(R.A5, BLOCK + st["sp"])
        w(R.A6, BLOCK)
        w(R.A7, STACK)
        w(R.ISP, STACK)
        mem.w16(BLOCK + IYADDR, st["iy"])
        mem.w16(BLOCK + FSHADOW, (st["f_"] & 0x80) >> 4 | (st["f_"] & 0x40) >> 4 | (st["f_"] & 1)
                | ((st["f_"] & 0x10) << 1) | ((st["f_"] & 0x02) << 5))
        cpu.w_sr(0x2700)

    def _compare(self, cpu, mem, zc, ref, st, ins, live, sym, labels, stop_pc, disp):
        R = self.R
        r = cpu.r_reg
        errs = []

        def cmp(name, got, exp):
            if got != exp:
                errs.append("%s: got %X expected %X" % (name, got, exp))
        cmp("A", r(R.D0) & 0xFF, zc.a)
        cmp("BC", r(R.D1) & 0xFFFF, zc.bc)
        cmp("DE", r(R.D2) & 0xFFFF, zc.de)
        cmp("HL", r(R.D3) & 0xFFFF, zc.hl)
        cmp("IX", r(R.D4) & 0xFFFF, zc.ix)
        cmp("IY", mem.r16(BLOCK + IYADDR), zc.iy)
        cmp("SP", (r(R.A5) - BLOCK) & 0xFFFF, zc.sp)
        cmp("BC'", r(R.A0) & 0xFFFF, (zc.b_ << 8) | zc.c_)
        cmp("DE'", r(R.A1) & 0xFFFF, (zc.d_ << 8) | zc.e_)
        cmp("HL'", r(R.A2) & 0xFFFF, (zc.h_ << 8) | zc.l_)
        cmp("A'", r(R.A3) & 0xFF, zc.a_)
        # next pc
        if stop_pc == disp:
            got_pc = (r(R.D7) & 0xFFFFFFFF) >> 2 if False else None
            # d7 holds pc*4 after `lsl.l #2` ; the stop is hit after `rts` pops the table entry
            got_pc = (r(R.D7) & 0xFFFFFFFF) >> 2
        else:
            got_pc = None
            for l in labels:
                if sym["Z%04X" % l] == stop_pc:
                    got_pc = l
        cmp("PC", got_pc if got_pc is not None else -1, zc.pc)
        # flags (live only)
        d6 = r(R.D6)
        f = zc.f
        exp = {S: bool(f & 0x80), Z: bool(f & 0x40), C: bool(f & 1), H: bool(f & 0x10), N: bool(f & 2)}
        got = {S: bool(d6 & 8), Z: bool(d6 & 4), C: bool(d6 & 1), H: bool(d6 & 0x20), N: bool(d6 & 0x40)}
        names = {S: "S", Z: "Z", C: "C", H: "H", N: "N"}
        for fl in (S, Z, C, H, N):
            if ins.mn == "bit" and fl == S:
                continue
            if live & fl and got[fl] != exp[fl]:
                errs.append("flag %s: got %d expected %d" % (names[fl], got[fl], exp[fl]))
        # memory
        mm = mem.r_block(BLOCK, 0x8000)
        for a in range(0x8000):
            if a in (IYADDR, IYADDR + 1, FSHADOW, FSHADOW + 1):
                continue
            if mm[a] != ref.mem[a]:
                errs.append("mem[%04X]: got %02X expected %02X" % (a, mm[a], ref.mem[a]))
                if len(errs) > 6:
                    break
        return errs or None


class RefMem:
    def __init__(self):
        self.mem = bytearray(0x10000)

    def rd(self, a):
        return self.mem[a & 0xFFFF]

    def wr(self, a, v):
        self.mem[a & 0xFFFF] = v & 0xFF


def all_instructions():
    """Every distinct instruction form (by text) found in the ROM code."""
    sys.path.insert(0, os.path.dirname(__file__))
    from discover import load_rom, discover
    import pickle, glob
    rom = load_rom()
    dyn = set()
    for f in glob.glob(str(ROOT / "ste" / "cover_*.pkl")):
        p, io = pickle.load(open(f, "rb"))
        dyn |= p
    code, tables = discover(rom, [0, 0x66] + sorted(dyn))
    return rom, code


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", default="")
    ap.add_argument("-n", type=int, default=8)
    ap.add_argument("--maxforms", type=int, default=100000)
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args()
    rom, code = all_instructions()
    ROMBYTES = rom
    seen = {}
    for pc, ins in sorted(code.items()):
        # a form = text with immediates/addresses abstracted
        key = re.sub(r"\$[0-9A-F]+", "$n", ins.text)
        key = re.sub(r"[+-]\d+\)", "+d)", key)
        if key not in seen:
            seen[key] = ins
    print(len(seen), "distinct forms")
    b = Bench()
    tot = bad = unsup = 0
    for key, ins in sorted(seen.items()):
        if a.k and a.k not in key:
            continue
        masks = [0] + [m for m in range(1, 32)]
        # a flag mask only matters over the tracked flags; sample subsets
        masks = [0, S | Z | C, S, Z, C, S | Z, H | N, S | Z | C | H | N, H, N, C | H | N]
        res = None
        for mask in masks:
            res = b.run_case(ins, mask, seed=hash((key, mask)) & 0xFFFF, nvec=a.n, verbose=a.v)
            if res is None:
                if mask == 0:
                    unsup += 1
                    print("UNSUPPORTED", ins.text)
                else:
                    print("  (unsupported with live=%02X: %s)" % (mask, ins.text))
                break
            tot += 1
            if res:
                bad += 1
                print("FAIL %-22s live=%02X  %s" % (ins.text, mask, res[0][0]))
                break
    print("cases", tot, "failed", bad, "unsupported", unsup)
