"""Translator bench: the emitted 68000 code (Musashi) against the reference Z80 (z80.py), for every Z80 opcode the
emitter supports and for random straight-line sequences, in the memory layouts the ports use.

    python engine/xbench.py [--layout dk|signed|long|all] [--seq N] [-n vectors] [-k text] [--a3busy] [-v]

Single instructions: every opcode (operand bytes random), every useful subset of live flags; registers, memory,
the next pc and the live flags must match.  --seq N: N random sequences of 2-12 instructions (forward jumps
inside), compiled by translate.compile_code like a whole program (flag analysis, the block pass), ending with
`push af` so the flags land in memory.  Where the alternate registers, IY and F' are kept is asked from the
emitter (Emitter.regmap), so the bench follows the register map.
"""
import argparse
import os
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import z80x
from z80x import S, Z, C, H, N, PV, swap16
from z80 import Z80
from z80dis import decode
from paths import VASM, VLINK, RT_INCLUDE
import translate
from machine68k import CPUType, Machine, Register as R

CODE = 0x10000
BLOCK = 0x40000          # 64 KB: the Z80 space as the layout maps it
TABLE = 0x80000          # the swapped dispatch table (256 KB)
STACK = 0x0F000
BASE = 0x1000            # where the tested instructions sit in the Z80 space
RAM_LO, RAM_HI = 0x6100, 0x6F00     # pointers, the stack
PTR_HI, SP_LO = 0x6C00, 0x6E40       # pointers below PTR_HI, the stack above SP_LO: a pointer (+d) never reaches
                                     # the stack words a push wrote (the merge pass does not write them: dead)
IYADDR, FSHADOW = 0x4FF0, 0x4FF2     # the block words of IY and F' (old register map), away from the tested ranges

HELPERS = open(str(RT_INCLUDE / "rtlib.s")).read() + """
z80_unsupported:\tbra.s z80_unsupported
z80_badjump:\tbra.s z80_badjump
z80_badpc:\tbra.s z80_badpc
"""

# the memory models: (a6 - BLOCK, Config kwargs); the Z80 space sits in BLOCK..BLOCK+64K as the model sees it
LAYOUTS = {
    "dk": dict(mode="signed", block=0x8000),                       # Donkey Kong: 32 KB, a6 = address 0
    "signed": dict(mode="signed", block=0x10000),                  # $8000-$FFFF below a6
    "long": dict(mode="long", block=0x10000, ram_sym="xb_ram"),    # long index, RAM through an absolute symbol
    "signed+": dict(mode="signed", block=0x10000, alt_af="upper", alt_regs="upper", iy_reg="a2"),   # the fast register map
    "long+": dict(mode="long", block=0x10000, ram_sym="xb_ram", alt_af="upper"),
    "dk+": dict(mode="signed", block=0x8000, alt_af="upper", alt_regs="upper", iy_reg="a2"),
}


def a6_of(layout):
    layout = layout.rstrip("+")             # (the + layouts: the same memory, the fast register map)
    return BLOCK + (0x8000 if layout == "signed" else 0)


def z2m(layout, a):
    """68000 address of Z80 address a"""
    layout = layout.rstrip("+")
    if layout == "signed":
        return BLOCK + 0x8000 + (a if a < 0x8000 else a - 0x10000)
    return BLOCK + a


def put_space(mem, layout, space):
    layout = layout.rstrip("+")
    if layout == "signed":
        mem.w_block(BLOCK, bytes(space[0x8000:]))
        mem.w_block(BLOCK + 0x8000, bytes(space[:0x8000]))
    else:
        mem.w_block(BLOCK, bytes(space))


def get_space(mem, layout):
    layout = layout.rstrip("+")
    b = bytes(mem.r_block(BLOCK, 0x10000))
    if layout == "signed":
        return b[0x8000:] + b[:0x8000]
    return b


def assemble(src):
    tmp = Path(tempfile.mkdtemp(prefix="xbench_"))
    (tmp / "t.s").write_text(src)
    r = subprocess.run([str(VASM), "-Fvobj", "-quiet", "-nowarn=2047", "-o", str(tmp / "t.o"), str(tmp / "t.s")],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("vasm: " + r.stdout + r.stderr)
    r = subprocess.run([str(VLINK), "-brawbin1", "-Ttext", hex(CODE), "-M" + str(tmp / "t.map"), "-o", str(tmp / "t.bin"),
                        str(tmp / "t.o")], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("vlink: " + r.stdout + r.stderr)
    syms = {}
    for line in (tmp / "t.map").read_text().splitlines():
        m = re.match(r"\s+0x([0-9a-f]{8})\s+(\S+?):", line)
        if m:
            syms[m.group(2)] = int(m.group(1), 16)
    return (tmp / "t.bin").read_bytes(), syms


# ---------------------------------------------------------------------------- the instructions

SKIP = {"halt", "ld a,r", "in", "out", "im", "reti", "retn", "ld i,a", "ld a,i", "ld r,a", "di", "ei"}


def all_opcodes(rnd):
    """{form: encoding} for every opcode (the operand bytes random but fixed per opcode)"""
    encs = []
    for op in range(256):
        if op in (0xCB, 0xDD, 0xED, 0xFD):
            continue
        encs.append(bytes([op, rnd.randrange(256), rnd.randrange(256)]))
    for op in range(256):
        encs.append(bytes([0xCB, op]))
        encs.append(bytes([0xED, op, rnd.randrange(256), rnd.randrange(256)]))
    for pre in (0xDD, 0xFD):
        for op in range(256):
            if op in (0xCB, 0xDD, 0xED, 0xFD):
                continue
            encs.append(bytes([pre, op, rnd.randrange(256), rnd.randrange(256)]))
        for op in range(256):
            encs.append(bytes([pre, 0xCB, rnd.randrange(256), op]))
    out = {}
    for e in encs:
        try:
            ins = decode(e + bytes(4), 0)
        except Exception:
            continue
        if ins is None or ins.mn in SKIP or ins.mn.startswith("?"):
            continue
        form = re.sub(r"\$[0-9A-F]+", "n", ins.text)
        form = re.sub(r"[+-]\d+\)", "+d)", form)
        out.setdefault(form, e[:ins.length])
    return out


def at(enc, pc):
    """the instruction of encoding enc decoded at pc"""
    buf = bytearray(0x10000)
    buf[pc:pc + len(enc)] = enc
    return decode(bytes(buf), pc)


def pointer_regs(ins):
    regs = set()
    for o in ins.ops:
        if o[0] == "ind":
            regs.add(o[1])
    if ins.mn in ("ldir", "lddr", "ldi", "ldd"):
        regs |= {"hl", "de"}
    if ins.mn in ("cpir", "cpdr", "cpi", "cpd", "rld", "rrd"):
        regs |= {"hl"}
    if ins.mn in ("push", "pop", "ex") or ins.flow in ("call", "ccall", "ret", "cret", "rst"):
        regs.add("sp")
    return regs


# ---------------------------------------------------------------------------- one case

class Case:
    """one compiled piece of code: run it from random states against the reference"""

    def __init__(self, layout, code, raw, entry, end, live=None, a3busy=False, seq=False):
        self.raw = raw                    # pc -> the encoding
        self.seq = seq
        self.layout = layout
        self.geo = layout.rstrip("+")
        # (sequences with BIT: the exact S of Config.bit_s, as F can be seen through push af / pop rr)
        bit_s = seq and any(i.mn == "bit" for i in code.values())
        cfg = z80x.Config(io_read_redirect={}, write_hooks=(), iyaddr=IYADDR, fshadow=FSHADOW, bit_s=bit_s, **LAYOUTS[layout])
        if seq:
            em = translate.compile_code(code, {entry}, cfg)
        else:
            em = z80x.Emitter(code, live_in={entry: 0}, live_out={entry: live}, cfg=cfg)
            em.emit_ins(entry, live_out_override=live)
        if a3busy:
            pass
        self.em = em
        self.unsupported = bool(em.unsupported)
        if self.unsupported:
            return
        self.code, self.entry, self.end, self.live = code, entry, end, live
        labels = set(em.refs) | {end}
        defined = {int(m.group(1), 16) for m in (re.match(r"^Z([0-9A-F]{4}):", l) for l in em.lines) if m}
        src = ["\tsection text", "\tcnop 0,2", "xb_ram\tequ $%X" % (a6_of(layout) + 0x8000)]
        src += em.lines
        src.append("\tjmp Z%04X" % end)
        src.append(HELPERS)
        self.stop_pcs = sorted(l for l in labels if l not in defined)
        for p in self.stop_pcs:
            src.append("Z%04X:\n\tnop\n\tnop" % p)
        src.append("Zdisp:\n\tnop\n\tnop")
        try:
            self.binary, self.sym = assemble("\n".join(src))
        except RuntimeError as e:
            raise RuntimeError("assembly failed for %s\n%s\n%s" % ([i.text for i in code.values()], "\n".join(em.lines), e))
        self.m = Machine(CPUType.M68000, 2048)
        self.cpu, self.mem = self.m.cpu, self.m.mem
        self.mem.w_block(CODE, self.binary)
        self.mem.w_block(TABLE, self.sym["Zdisp"].to_bytes(4, "big") * 65536)
        self.stops = {self.sym["Z%04X" % p]: p for p in self.stop_pcs}
        self.stops[self.sym["Zdisp"]] = "disp"

    # -------------------------------------------------------------- states
    def rand_state(self, rnd):
        w = lambda: rnd.randrange(0x10000)
        p = lambda: rnd.randrange(RAM_LO, PTR_HI)
        st = {"a": rnd.randrange(256), "bc": w(), "de": w(), "hl": w(), "ix": w(), "iy": w(), "sp": p() & ~1,
              "f": rnd.randrange(256) & 0xD7, "a_": rnd.randrange(256), "f_": rnd.randrange(256) & 0xD7,
              "bc_": w(), "de_": w(), "hl_": w()}
        ptr = set()
        for ins in self.code.values():
            ptr |= pointer_regs(ins)
        for r in ("bc", "de", "hl", "ix", "iy"):
            if r in ptr:
                st[r] = p()
        if "sp" in ptr or self.seq:
            st["sp"] = rnd.randrange(SP_LO, RAM_HI) & ~1
        for ins in self.code.values():
            if ins.mn in ("ldir", "lddr", "cpir", "cpdr"):
                st["bc"] = rnd.randrange(1, 40) if rnd.random() < 0.7 else rnd.randrange(1, 300)
                if ins.mn in ("ldir", "lddr"):
                    st["hl"] = rnd.randrange(RAM_LO + 0x40, RAM_LO + 0x400)
                    st["de"] = st["hl"] + rnd.choice([-3, -2, -1, 1, 2, 3, 4, 8, 0x100, -0x100]) * rnd.choice([1, 1, 4])
                    k = rnd.random()
                    if k < 0.15:                           # across the $8000 split of the signed mode
                        st["hl"] = rnd.randrange(0x7FD8, 0x7FFF)
                    elif k < 0.3:
                        st["de"] = rnd.randrange(0x7FD8, 0x7FFF)
                    elif k < 0.4:                          # across the $FFFF wrap
                        st["hl"] = rnd.randrange(0xFFE0, 0x10000)
            if ins.flow == "ijmp":
                st[ins.ops[0][1]] = rnd.randrange(0x10000)
        return st

    def f68(self, f):
        """Z80 F -> the d6 image (S bit 3, Z bit 2, C bit 0, H bit 5, N bit 6, P/V bit 7)"""
        return ((f & 0x80) >> 4) | ((f & 0x40) >> 4) | (f & 1) | ((f & 0x10) << 1) | ((f & 0x02) << 5) | ((f & 0x04) << 5)

    def apply(self, rnd, st):
        em, cpu, w = self.em, self.cpu, self.cpu.w_reg
        rm = em.regmap()
        junk = lambda: rnd.randrange(1 << 16) << 16 if self.geo != "long" else 0
        up = {}
        if rm["alt_af"] == "upper":
            up[R.D0] = st["a_"] << 16
            up[R.D6] = self.f68(st["f_"]) << 16
        if rm["alt_regs"] == "upper":
            up[R.D1] = swap16(st["bc_"]) << 16
            up[R.D2] = st["de_"] << 16
            up[R.D3] = st["hl_"] << 16
        w(R.D0, up.get(R.D0, rnd.randrange(1 << 24) << 8) & 0xFFFFFF00 | st["a"]) if rm["alt_af"] != "upper" else w(R.D0, up[R.D0] | (rnd.randrange(256) << 8) | st["a"])
        w(R.D1, up.get(R.D1, junk()) | swap16(st["bc"]))
        w(R.D2, up.get(R.D2, junk()) | st["de"])
        w(R.D3, up.get(R.D3, junk()) | st["hl"])
        w(R.D4, junk() | st["ix"])
        w(R.D5, rnd.randrange(1 << 32))
        w(R.D7, rnd.randrange(1 << 32))
        d6 = self.f68(st["f"]) | rnd.choice([0, 0x10]) | rnd.choice([0, 2])
        w(R.D6, up.get(R.D6, rnd.randrange(1 << 16) << 16) | (rnd.randrange(256) << 8) | d6)
        if rm["alt_regs"] == "areg":                # (the long mode: exx brings them in as indexes, upper words 0)
            w(R.A0, junk() | swap16(st["bc_"]))
            w(R.A1, junk() | st["de_"])
            w(R.A2, junk() | st["hl_"])
        if rm["alt_af"] == "a3":
            w(R.A3, (rnd.randrange(1 << 24) << 8) | st["a_"])
        if rm["iy"].startswith("a"):
            w(getattr(R, rm["iy"].upper()), (rnd.randrange(1 << 16) << 16 if self.geo != "long" else 0) | st["iy"])
        w(R.A4, TABLE)
        w(R.A5, z2m(self.layout, st["sp"]))
        w(R.A6, a6_of(self.layout))
        w(R.A7, STACK)
        w(R.ISP, STACK)
        self.cpu.w_sr(0x2700)

    def regs(self):
        """the Z80 registers from the 68000"""
        rm, r, mem = self.em.regmap(), self.cpu.r_reg, self.mem
        out = {"a": r(R.D0) & 0xFF, "bc": swap16(r(R.D1) & 0xFFFF), "de": r(R.D2) & 0xFFFF, "hl": r(R.D3) & 0xFFFF,
               "ix": r(R.D4) & 0xFFFF, "sp": (r(R.A5) - z2m(self.layout, 0)) & 0xFFFF}
        out["iy"] = r(getattr(R, rm["iy"].upper())) & 0xFFFF if rm["iy"].startswith("a") else \
            mem.r16(z2m(self.layout, IYADDR))
        if rm["alt_regs"] == "upper":
            out["bc_"] = swap16((r(R.D1) >> 16) & 0xFFFF)
            out["de_"] = (r(R.D2) >> 16) & 0xFFFF
            out["hl_"] = (r(R.D3) >> 16) & 0xFFFF
        elif rm["alt_regs"] == "areg":
            out["bc_"] = swap16(r(R.A0) & 0xFFFF)
            out["de_"] = r(R.A1) & 0xFFFF
            out["hl_"] = r(R.A2) & 0xFFFF
        if rm["alt_af"] == "upper":
            out["a_"] = (r(R.D0) >> 16) & 0xFF
            out["f_"] = (r(R.D6) >> 16) & 0xFF
        elif rm["alt_af"] == "a3":
            out["a_"] = r(R.A3) & 0xFF
            out["f_"] = mem.r16(z2m(self.layout, FSHADOW)) & 0xFF
        else:
            out["a_"] = None
        return out

    # -------------------------------------------------------------- run
    def run(self, rnd, nvec, check_flags=True):
        """-> list of error strings (empty: all vectors matched)"""
        rm = self.em.regmap()
        for v in range(nvec):
            space = bytearray(rnd.randbytes(0x10000))
            st = self.rand_state(rnd)
            for pc, ins in self.code.items():
                space[pc:pc + ins.length] = self.raw[pc]
            iy_mem = IYADDR
            if not rm["iy"].startswith("a"):
                space[iy_mem] = st["iy"] >> 8          # the 68000 keeps IY as a big-endian word
                space[iy_mem + 1] = st["iy"] & 0xFF
            if rm["alt_af"] == "a3":
                space[FSHADOW] = 0
                space[FSHADOW + 1] = self.f68(st["f_"])
            for ins in self.code.values():
                if ins.flow in ("ret", "cret"):
                    t = rnd.randrange(0x10000)
                    space[st["sp"]], space[st["sp"] + 1] = t & 0xFF, t >> 8
            ref_space = bytearray(space)
            hi = [False]                        # (the 32 KB layout cannot reach $8000 and up: such a vector is skipped)

            def rd(a):
                a &= 0xFFFF
                hi[0] |= a >= 0x8000 and not (self.entry <= a < self.end)
                return ref_space[a]

            def wr(a, b):
                a &= 0xFFFF
                hi[0] |= a >= 0x8000
                ref_space[a] = b & 0xFF
            z = Z80(rd, wr)
            z.afmask = 0xC1          # (push af keeps S Z C, see Emitter.x_push)
            z.a, z.f = st["a"], st["f"]
            z.bc, z.de, z.hl, z.ix, z.iy, z.sp = st["bc"], st["de"], st["hl"], st["ix"], st["iy"], st["sp"]
            z.a_, z.f_ = st["a_"], st["f_"]
            z.b_, z.c_ = st["bc_"] >> 8, st["bc_"] & 255
            z.d_, z.e_ = st["de_"] >> 8, st["de_"] & 255
            z.h_, z.l_ = st["hl_"] >> 8, st["hl_"] & 255
            z.pc = self.entry
            n = 0
            while (z.pc in self.code) and n < 200000:
                z.step()
                n += 1
            if hi[0] and self.geo == "dk":
                continue
            put_space(self.mem, self.layout, space)
            self.apply(rnd, st)
            self.cpu.w_pc(self.sym["Z%04X" % self.entry])
            steps = 0
            while True:
                self.cpu.execute(1)
                steps += 1
                pc = self.cpu.r_pc()
                if pc in self.stops:
                    break
                if steps > 200000:
                    return ["timeout"]
            errs = []
            got = self.regs()
            want = {"a": z.a, "bc": z.bc, "de": z.de, "hl": z.hl, "ix": z.ix, "iy": z.iy, "sp": z.sp,
                    "bc_": (z.b_ << 8) | z.c_, "de_": (z.d_ << 8) | z.e_, "hl_": (z.h_ << 8) | z.l_, "a_": z.a_}
            if rm["alt_af"] == "upper":
                want["f_"] = self.f68(z.f_) & 0x0D        # (S Z C: H N are computed only where read)
                got["f_"] &= 0x0D
            for k, v in want.items():
                if got.get(k) is not None and got[k] != v:
                    errs.append("%s: got %X expected %X" % (k, got[k], v))
            stop = self.stops[pc]
            if stop == "disp":
                gpc = swap16(((self.cpu.r_reg(R.D7) & 0xFFFFFFFF) >> 2) & 0xFFFF)
            else:
                gpc = stop
            if gpc != z.pc:
                errs.append("pc: got %04X expected %04X" % (gpc, z.pc))
            if check_flags and self.live is not None:
                d6 = self.cpu.r_reg(R.D6)
                for fl, zb, mb, nm in ((S, 0x80, 8, "S"), (Z, 0x40, 4, "Z"), (C, 1, 1, "C"), (H, 0x10, 0x20, "H"),
                                       (N, 2, 0x40, "N"), (PV, 4, 0x80, "P/V")):
                    if fl == S and any(i.mn == "bit" for i in self.code.values()):
                        continue
                    if self.live & fl and bool(d6 & mb) != bool(z.f & zb):
                        errs.append("flag %s: got %d expected %d" % (nm, bool(d6 & mb), bool(z.f & zb)))
            mm = get_space(self.mem, self.layout)
            skip = set()
            if not rm["iy"].startswith("a"):
                skip |= {iy_mem, iy_mem + 1}
            if rm["alt_af"] == "a3":
                skip |= {FSHADOW, FSHADOW + 1}
            skip |= set(range(z.sp - 64, z.sp))     # (popped stack words are dead: the merge pass does not write them)
            nbad = 0
            if self.geo == "dk":
                mm = mm[:0x8000] + bytes(ref_space[0x8000:])
            for a in ([] if mm == bytes(ref_space) else range(0x10000)):
                if mm[a] != ref_space[a] and a not in skip:
                    if self.geo == "dk" and a >= 0x8000:
                        continue
                    errs.append("mem[%04X]: got %02X expected %02X" % (a, mm[a], ref_space[a]))
                    nbad += 1
                    if nbad > 4:
                        break
            if errs:
                return errs
        return []


# ---------------------------------------------------------------------------- drivers

# flags the translator does not produce exactly (by design): H after ccf (the old C; only daa reads H)
KNOWN = {"ccf": H}
MASKS = [0, S | Z | C, S, Z, C, S | Z, H | N, S | Z | C | H | N, H, N, C | H | N, PV]


def single(layout, rnd, nvec, filt, verbose):
    forms = all_opcodes(random.Random(7))
    tot = bad = unsup = 0
    for form, enc in sorted(forms.items()):
        if filt and filt not in form:
            continue
        ins = at(enc, BASE)
        end = BASE + ins.length
        for mask in MASKS:
            if mask == PV and ins.mn not in z80x.PV_PRODUCERS:
                continue                    # (P/V after ldi / ldd: only for the jp pe/po right behind, see Emitter.branch)
            if ins.mn in KNOWN and mask & KNOWN[ins.mn]:
                continue
            try:
                c = Case(layout, {BASE: ins}, {BASE: enc}, BASE, end, live=mask)
            except z80x.Unsupported:
                c = None
            if c is None or c.unsupported:
                if mask == 0:
                    unsup += 1
                    if verbose:
                        print("  unsupported:", form)
                break
            tot += 1
            errs = c.run(rnd, nvec)
            if errs:
                bad += 1
                print("FAIL %-6s %-22s live=%02X  %s" % (layout, ins.text, mask, "; ".join(errs[:3])))
                if verbose:
                    print("\n".join(c.em.lines))
                break
    print("%s: %d cases, %d failed, %d forms unsupported" % (layout, tot, bad, unsup))
    return bad


SEQ_POOL = None


def sequences(layout, rnd, count, nvec, verbose):
    """random straight-line pieces (with forward jumps), compiled like a program"""
    global SEQ_POOL
    if SEQ_POOL is None:
        forms = all_opcodes(random.Random(7))
        SEQ_POOL = [e for f, e in forms.items() if not re.match(r"(jp|jr|call|ret|rst|djnz|reti|retn|ex \(sp\)|ld sp|pop|halt|ldir|lddr|cpir|cpdr|daa)", f)
                    and "sp" not in f]
    bad = 0
    for k in range(count):
        n = rnd.randrange(2, 13)
        pcs, encs = [], []
        pc = BASE
        for i in range(n):
            e = rnd.choice(SEQ_POOL)
            pcs.append(pc)
            encs.append(e)
            pc += len(e)
        if rnd.random() < 0.6:                             # a push / pop pair (the merge pass: copies, pair_af)
            regs = [(0xC5, 0xC1), (0xD5, 0xD1), (0xE5, 0xE1), (0xF5, 0xF1), (b"\xDD\xE5", b"\xDD\xE1"), (b"\xFD\xE5", b"\xFD\xE1")]
            a, b = rnd.choice(regs), rnd.choice(regs)
            i = rnd.randrange(0, len(encs) + 1)
            j = rnd.choice([i, i, rnd.randrange(i, len(encs) + 1)])
            pu = a[0] if isinstance(a[0], bytes) else bytes([a[0]])
            po = b[1] if isinstance(b[1], bytes) else bytes([b[1]])
            encs.insert(j, po)
            encs.insert(i, pu)
        # a forward jump or two: jr cc to a later instruction (or the end)
        if n > 3 and rnd.random() < 0.6:
            i = rnd.randrange(1, n - 1)
            cc = rnd.choice([0x20, 0x28, 0x30, 0x38, 0x18])
            encs.insert(i, bytes([cc, 0]))
            pcs = []
            pc = BASE
            for e in encs:
                pcs.append(pc)
                pc += len(e)
            tgt = rnd.choice(pcs[i + 1:] + [pc + 1])
            encs[i] = bytes([cc, (tgt - (pcs[i] + 2)) & 0xFF])
        encs.append(bytes([0xF5]))                         # push af: the flags into memory
        pcs = []
        pc = BASE
        for e in encs:
            pcs.append(pc)
            pc += len(e)
        end = pc
        buf = bytearray(0x10000)
        for p, e in zip(pcs, encs):
            buf[p:p + len(e)] = e
        code = {}
        for p, e in zip(pcs, encs):
            code[p] = decode(bytes(buf), p)
        if any(i.ops and i.ops[0] == ("r16", "sp") for i in code.values()):
            continue
        try:
            c = Case(layout, code, dict(zip(pcs, encs)), BASE, end, seq=True)
        except z80x.Unsupported:
            continue
        if c.unsupported:
            continue
        errs = c.run(rnd, nvec, check_flags=False)
        if errs:
            bad += 1
            print("FAIL seq %s: %s\n   %s" % (layout, " / ".join(i.text for _, i in sorted(code.items())), "; ".join(errs[:4])))
            if verbose:
                print("\n".join(c.em.lines))
    print("%s: %d sequences, %d failed" % (layout, count, bad))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--layout", default="all")
    ap.add_argument("--seq", type=int, default=0)
    ap.add_argument("-n", type=int, default=6)
    ap.add_argument("-k", default="")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("-v", action="store_true")
    ap.add_argument("--noflat", action="store_true", help="sequences only")
    a = ap.parse_args()
    rnd = random.Random(a.seed)
    bad = 0
    for lay in (LAYOUTS if a.layout == "all" else [a.layout]):
        if not a.noflat:
            bad += single(lay, rnd, a.n, a.k, a.v)
        if a.seq:
            bad += sequences(lay, rnd, a.seq, a.n, a.v)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
