"""The hand-written routines of src/natives.s against the translated Z80 code they replace (gen.py MAIN_NATIVES /
SUB_NATIVES), on Musashi with random object tables: memory, the registers and the flags the code after them reads must
match.

    python native_test.py [cases]

y_near (the sub CPU's $0849): its translation still follows its label (Y084D, after `ld iy,$E76C`).  Cases: object
counts 0-12 (0: 256 objects, the translation), IX one of the objects, fields near each other (equal +29, |+2| and +1
around 13, +30 bit 0, IX+33 bits 4/5, (IY+0) & $1D zero or not).

mcu_native (src/mcu_native.s, the MCU's VBL interrupt $F046) against the translated firmware MF046 with the runtime's
bus routines: random MCU RAM, shared RAM, DIP switches and inputs, the request bytes biased to each path (coins and
credits, lockout, the counters and their checks, the two position scans with objects near, the sequences, the
countdown, the tables, the reset request): the MCU's memory $00-$EF (its ports, $4A, its variables), the shared RAM,
p1_out / p2_out / p3_in, the main CPU's interrupt request, a reset.

z_state / y_state (the objects' state dispatch, $5C37 / $03CF): the translation from the label after the `push af`
(the push done here as z80x stores it); every combination of the tested bits of (IX+0) and (IX+33) (the others
random), random F: the handler reached, A, F, the CCR, the Z80 stack.
"""
import collections, os, random, sys
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


def test_mcu(s, sym, rnd, n_cases):
    cpu, mem = s.cpu, s.mem
    mm, mc = sym["mcu_mem"], sym["G_MCRAM"]
    mem.w_block(mm + 0xF000, (build_dir("bublbobl") / "rom_mcu.rom").read_bytes())
    frame = 0x2E8000                              # (mcu_restart: movem.l (sp)+,d0-d7/a0-a6; rts)
    glue = ["p1_out", "p2_out", "p3_in", "main_irq", "mcu_booted"]
    paths = collections.Counter()

    def pick(*vals):
        return rnd.choice(list(vals) + [rnd.getrandbits(8)])

    for case in range(n_cases):
        ram = bytearray(rnd.getrandbits(8) for _ in range(0x100))
        ram[0], ram[1], ram[5] = 0xF0, 0xFF, 0xFF
        ram[4] = rnd.choice([0, 0xFF])
        for a in (0x41, 0x43, 0x45):
            ram[a] = pick(0, 1, 2, 3)
        for a in (0x40, 0x42, 0x44):
            ram[a] = pick(0, 0x80)
        ram[0x48], ram[0x49] = rnd.randrange(4), rnd.randrange(4)
        for a in range(0x5D, 0x61):
            ram[a] = rnd.randrange(12)
        sh = bytearray(rnd.getrandbits(8) for _ in range(0x400))
        put = lambda a, v: sh.__setitem__(a - 0xC00, v)
        put(0xF98, pick(0x47, 0x47))
        put(0xF94, pick(1, 0xFF, 0))
        put(0xC1E, pick(0, 3, 8, 9))
        for cmd, val, cp in ((0xC6F, 0xC24, 0x52), (0xC70, 0xC25, 0x53)):
            put(cmd, pick(0, 1, 2, 4, 8))
            put(val, pick(0x0A, ram[cp]))
        put(0xF95, pick(0x42))
        put(0xC7E, pick(0, 1, 2, 4, 8, 0x10, 0x20, 0x40))
        x, y = rnd.getrandbits(8), rnd.getrandbits(8)
        for req, xa, ya in ((0xC5F, 0xC60, 0xC61), (0xC67, 0xC68, 0xC69)):
            put(req, pick(1, 3, 0))
            put(xa, x)
            put(ya, y)
        for k in range(7):
            put(0xC01 + 4 * k, pick(1, 0))
            put(0xC02 + 4 * k, (x + rnd.randrange(-12, 13)) & 0xFF)
            put(0xC03 + 4 * k, (y + rnd.randrange(-12, 13)) & 0xFF)
        for a in (0xC72, 0xC74, 0xC76, 0xC80):
            put(a, rnd.randrange(40))
        put(0xC7A, pick(0, 1))
        put(0xC79, pick(0, 1))
        put(0xC78, pick(0, 1))
        put(0xC71, pick(0x0D))
        ram[0x54] = pick(0x0C)
        put(0xC7C, rnd.randrange(7))
        for f, i in ((0xF88, 0xF8A), (0xF8C, 0xF8E), (0xF90, 0xF92)):
            put(f, pick(1, 1))
            put(i, rnd.randrange(5))
        put(0xF97, rnd.choice([0x4A] + [rnd.getrandbits(8)] * 30))
        inputs = bytes(rnd.getrandbits(8) for _ in range(4))
        in0 = rnd.choice([rnd.getrandbits(4) | 3, rnd.getrandbits(8)])
        g0 = [rnd.getrandbits(8), rnd.getrandbits(8), rnd.getrandbits(8), 0, 1]
        out = []
        for entry in ("MF046", "mcu_native"):
            mem.w_block(mm, bytes(ram))
            mem.w_block(mc, bytes(sh))
            mem.w_block(sym["dsw0"], inputs)
            mem.w8(sym["in0_val"], in0)
            for name, v in zip(glue, g0):
                mem.w8(sym[name], v)
            mem.w32(sym["mcu_sp0"], frame)
            mem.w32(frame + 60, STOP)
            for r in (R.D0, R.D1, R.D2, R.D3, R.D6, R.D7):
                cpu.w_reg(r, 0)
            cpu.w_reg(R.A6, mm)
            cpu.w_reg(R.A5, mm + 0x100)
            cpu.w_reg(R.A7, 0x2EF000)
            mem.w32(0x2EF000, STOP)
            cpu.w_sr(0x2700)
            cpu.w_pc(sym[entry])
            n = 0
            while cpu.r_pc() != STOP:
                cpu.execute(1)
                n += 1
                assert n < 200000, (entry, "does not return", hex(cpu.r_pc()))
            out.append((bytes(mem.r_block(mm, 0xF0)), bytes(mem.r_block(mc, 0x400)),
                        [mem.r8(sym[name]) for name in glue]))
        a, b = out
        assert a == b, (case, [("mcu %02X" % i, a[0][i], b[0][i]) for i in range(0xF0) if a[0][i] != b[0][i]][:8],
                        [("sh %03X" % (0xC00 + i), a[1][i], b[1][i]) for i in range(0x400) if a[1][i] != b[1][i]][:8],
                        a[2], b[2])
        paths["reset"] += a[2][4] == 0
        paths["main irq"] += a[2][3] != 0
        paths["scan hit"] += a[1][0x62] != sh[0x62] or a[1][0x6A] != sh[0x6A]
        paths["credits"] += a[1][0x1E] != sh[0x1E]
        paths["countdown end"] += a[1][0x7B] != sh[0x7B]
    print("mcu_native: %d cases: native = translation (MCU memory $00-$EF, shared RAM, ports, interrupt, reset); "
          "with %s" % (n_cases, ", ".join("%s %d" % kv for kv in sorted(paths.items()))))


def main():
    n_cases = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    s = Sim(str(RUN / "BUBBLE.PRG"), run_dir=RUN)
    sym = {k: v + s.base for k, v in s.symbols(MAP).items()}
    cpu, mem = s.cpu, s.mem
    test_mcu(s, sym, random.Random(3), n_cases)
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
