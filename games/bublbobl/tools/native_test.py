"""The hand-written routines of src/natives.s against the translated Z80 code they replace (gen.py MAIN_NATIVES /
SUB_NATIVES), on Musashi with random object tables: memory, the registers and the flags the code after them reads must
match.

    python native_test.py [cases]

y_near (the sub CPU's $0849): its translation still follows its label (Y084D, after `ld iy,$E76C`).  Cases: object
counts 0-12 (0: 256 objects, the translation), IX one of the objects, fields near each other (equal +29, |+2| and +1
around 13, +30 bit 0, IX+33 bits 4/5, (IY+0) & $1D zero or not).

z_state / y_state (the objects' state dispatch, $5C37 / $03CF): the translation from the label after the `push af`
(the push done here as z80x stores it); every combination of the tested bits of (IX+0) and (IX+33) (the others
random), random F: the handler reached, A, F, the CCR, the Z80 stack.
"""
import os, random, sys
sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
from sim import Sim
from machine68k import Register as R
from paths import ROOT, build_dir

RUN = ROOT / "run" / "bublbobl_sim"
MAP = build_dir("bublbobl") / "bublbobl_sim.map"
TABLE, STACK, STOP, RET_PC = 0x200000, 0x2E0000, 0x2F0000, 0x0406
IY_SUB = 0xBFF8
OBJ, COUNT = 0xE76C, 0xE76B
LO, HI = 0xE700, 0x10000                 # (the memory compared: the objects and what follows)
REGS = [R.D0, R.D1, R.D2, R.D3, R.D4, R.A0, R.A1, R.A2, R.A5]


# (label, the translation after the push, base symbol, IX register width, the handlers, the bits tested of +0 / +33)
STATES = [("z_state", "Z5C38", "G_ROM1", "w", ["Z5CE8", "Z5C78", "Z6559", "Z5D57", "Z5D96", "Z5E10", "Z5EB1", "Z5F0B",
                                                "Z663D", "Z66CA", "Z5F96", "Z6D8B"], 0xFF, 0xE0),
          ("y_state", "Y03D0", "g_block", "l", ["Y03FC", "Y0433", "Y047E", "Y04B5", "Y04EC", "Y05FE", "Y05C7", "Y0635"],
           0x3D, 0x60)]


def test_states(s, sym, rnd):
    cpu, mem = s.cpu, s.mem
    for label, after, base, width, handlers, bits0, bits33 in STATES:
        a6 = sym[base]
        stops = {sym[h]: h for h in handlers}
        reached = set()
        tested = [b for b in range(8) if bits0 >> b & 1] + [8 + b for b in range(8) if bits33 >> b & 1]
        cases = 0
        for combo in range(1 << len(tested)):
            for _ in range(3):
                b0, b33 = rnd.getrandbits(8) & ~bits0, rnd.getrandbits(8) & ~bits33
                for i, b in enumerate(tested):
                    if combo >> i & 1:
                        if b < 8:
                            b0 |= 1 << b
                        else:
                            b33 |= 1 << (b - 8)
                ix = OBJ + 40 * rnd.randrange(12)
                off = ix - 0x10000 if width == "w" else ix
                d0, d6 = rnd.getrandbits(32), rnd.getrandbits(32)
                out = []
                for entry in ("translated", "native"):
                    mem.w8(a6 + off, b0)
                    mem.w8(a6 + off + 33, b33)
                    mem.w_block(STACK - 16, bytes(18))
                    cpu.w_reg(R.D0, d0)
                    cpu.w_reg(R.D4, ix)
                    cpu.w_reg(R.D6, d6)
                    cpu.w_reg(R.A6, a6)
                    cpu.w_reg(R.A5, STACK)
                    cpu.w_reg(R.A7, 0x2EF000)
                    cpu.w_sr(0x2700)
                    if entry == "translated":           # (push af: A, then F = S Z (d6 bits 3, 2) at 7, 6 and C)
                        mem.w8(STACK - 1, d0 & 0xFF)
                        mem.w8(STACK - 2, ((d6 & 0x0C) << 4) & 0xFF | d6 & 1)
                        cpu.w_reg(R.A5, STACK - 2)
                        cpu.w_pc(sym[after])
                    else:
                        cpu.w_pc(sym[label])
                    n = 0
                    while cpu.r_pc() not in stops:
                        cpu.execute(1)
                        n += 1
                        assert n < 10000, (label, "no handler reached")
                    out.append((stops[cpu.r_pc()], cpu.r_reg(R.D0), cpu.r_reg(R.D6), cpu.r_sr() & 0x1F,
                                cpu.r_reg(R.A5), bytes(mem.r_block(STACK - 16, 18))))
                assert out[0] == out[1], (label, hex(b0), hex(b33), out)
                reached.add(out[0][0])
                cases += 1
        assert reached == set(handlers), (label, "handlers not reached", set(handlers) - reached)
        print("%s: %d cases (every combination of the %d bits tested): native = translation (the handler, A, F, CCR, "
              "the Z80 stack), all %d handlers reached" % (label, cases, len(tested), len(handlers)))


def main():
    n_cases = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    s = Sim(str(RUN / "BUBBLE.PRG"), run_dir=RUN)
    sym = {k: v + s.base for k, v in s.symbols(MAP).items()}
    cpu, mem = s.cpu, s.mem
    test_states(s, sym, random.Random(2))
    a6 = sym["g_block"]
    mem.w32(TABLE + 4 * RET_PC, STOP)            # (the ret: the dispatch table's entry of the return point)
    mem.w16(STOP, 0x4E71)
    rnd = random.Random(1)
    low = bytes(mem.r_block(a6, 0x2840))         # (256 objects wrap past $FFFF to here: restored before each run)

    def run(entry, image, regs):
        mem.w_block(a6 + LO, bytes(image))
        mem.w_block(a6, low)
        mem.w16(a6 + IY_SUB, rnd.getrandbits(16))
        for r, v in zip(REGS, regs):
            cpu.w_reg(r, v)
        mem.w16(STACK, RET_PC)
        cpu.w_reg(R.A5, STACK)
        cpu.w_reg(R.A4, TABLE)
        cpu.w_reg(R.A6, a6)
        cpu.w_reg(R.D6, regs[-1])
        cpu.w_reg(R.A7, 0x2EF000)
        cpu.w_sr(0x2700)
        if entry == "translated":
            mem.w16(a6 + IY_SUB, OBJ)            # (ld iy,$E76C)
            cpu.w_pc(sym["Y084D"])
        else:
            cpu.w_pc(sym["Y0849"])
        n = 0
        while cpu.r_pc() != STOP:
            cpu.execute(1)
            n += 1
            assert n < 2000000, "routine stopped"
        return (bytes(mem.r_block(a6 + LO, HI - LO)) + bytes(mem.r_block(a6, len(low))), mem.r16(a6 + IY_SUB),
                [cpu.r_reg(r) for r in REGS], cpu.r_reg(R.D6) & 0x0D)

    counts = {"near": 0, "twice": 0, "all": 0, "fallback": 0}
    for case in range(n_cases):
        count = rnd.choice([0] + list(range(1, 13)) * 20)
        image = bytearray(rnd.getrandbits(8) for _ in range(HI - LO))
        image[COUNT - LO] = count
        base = rnd.randrange(count or 12)
        ix = OBJ + 40 * base
        x, y, k = rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)
        for i in range(min(count or 12, 12)):
            o = OBJ + 40 * i - LO
            if o + 40 > len(image):
                break
            image[o + 0] = rnd.choice([0, 0x02, 0xE2, rnd.getrandbits(8)])
            image[o + 1] = (y + rnd.randrange(-16, 17)) & 0xFF
            image[o + 2] = (x + rnd.randrange(-16, 17)) & 0xFF
            image[o + 29] = rnd.choice([k, k ^ 1, rnd.getrandbits(8)])
            image[o + 30] = rnd.getrandbits(8)
            image[o + 33] = rnd.choice([0, 0x10, 0x20, 0x30, rnd.getrandbits(8) & 0xCF, rnd.getrandbits(8)])
        regs = [rnd.getrandbits(32) for _ in REGS] + [rnd.getrandbits(8)]
        regs[4] = ix                                  # IX (long offsets)
        before = bytes(image)
        want = run("translated", image, regs)
        got = run("native", image, regs)
        assert got == want, (case, count, base, [(hex(LO + i), want[0][i], got[0][i]) for i in range(len(want[0])) if want[0][i] != got[0][i]][:8],
                             hex(want[1]), hex(got[1]), [hex(v) for v in want[2]], [hex(v) for v in got[2]], want[3], got[3])
        changed = sum(a != b for a, b in zip(before, want[0]))
        counts["near"] += changed > 0
        counts["twice"] += any((b - a) & 0xFF == 2 for a, b in zip(before, want[0]))
        counts["all"] += bool(image[ix - LO + 33] & 0x30)
        counts["fallback"] += count == 0
    print("y_near: %d cases: native = translation (memory, IY, registers, S Z C); with a near object %d, counted twice %d, "
          "IX+33 bit 4/5 %d, 256 objects (translated) %d" % (n_cases, counts["near"], counts["twice"], counts["all"], counts["fallback"]))


if __name__ == "__main__":
    main()
