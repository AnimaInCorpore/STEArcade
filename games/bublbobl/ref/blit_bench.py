"""Blitter against CPU for the Bubble Bobble tile renderer, measured on Musashi with the STE blitter model.

    python blit_bench.py

Assembles ref/blit_bench.s, then for each kind of draw runs the renderer's CPU loop and a Blitter version on
identical screens and requires identical results.  Cycles are CPU cycles (executed instruction by instruction) plus
the Blitter's bus cycles (4 a word: source reads, destination reads where a mask is partial, writes; the HOG mode
of the real chip halts the CPU meanwhile, so the two add).  The register setup a renderer does once per tile / run
is added as a fixed estimate (SETUP_*), listed below; a real frame-rate measurement needs Hatari.
Not modelled: the blitter's own start-up time, and the bus time the CPU gets back in non-HOG mode.
"""
import random
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE / ".." / ".." / ".." / "engine")]
from machine68k import Register as R       # noqa: E402
from paths import VASM, VLINK, build_dir   # noqa: E402
from sprite_blit_test import Harness       # noqa: E402

STRIDE = 160
SCR_CPU, SCR_BLT, FRONT = 0x300000, 0x310000, 0x320000
ENTRY, BDATA, MASKS = 0x330000, 0x330100, 0x330200
# per-tile / per-run register writes the renderer would do on top of the row loops (68000 cycles):
SETUP_TILE = 28 + 28 + 20 + 24          # SRC (move.l #,abs.l), DST, skew byte, X count
SETUP_RUN = 28 + 28 + 24 + 24 + 20      # SRC/DST, X count, Y count, control (run blits)
SETUP_CPU_SHIFT = 110                   # draw_tile's set-up of the two cells, MH table lookup (render.s .u_go)


class BHarness(Harness):
    """the engine's harness with any X count (a run of groups is up to 4 x 8 words wide); same bus accounting"""

    def on_access(self, mode, width, addr, value):
        if mode != 'W' or (addr & 0xffffff) < 0xff8000:
            return
        off = (addr & 0xffffff) - 0xff8000
        n = (1, 2, 4)[width]
        self.io[off:off + n] = value.to_bytes(n, 'big')
        if off <= 0xa3c < off + n and self.io[0xa3c] & 0x80:
            b = self.blitter
            x, y = b.reg16(0xa36) or 65536, b.reg16(0xa38) or 65536
            if x == 1:
                masks = [b.reg16(0xa28)]
            else:
                masks = [b.reg16(0xa28)] + [b.reg16(0xa2a)] * (x - 2) + [b.reg16(0xa2c)]
            reads = x - bool(self.io[0xa3d] & 0x40)
            if self.io[0xa3a] < 2:
                reads = 0
            self.bus_cycles += 4 * y * (reads + x + sum(m != 0xffff for m in masks))
            self.blits += 1
            self.words += x * y
            self.mem.set_trace_mode(False)
            try:
                b.run()
                self.mem.w_block(0xff8000, bytes(self.io))
            finally:
                self.mem.set_trace_mode(True)


def build():
    b = build_dir("bublbobl")
    obj, prg, mp = b / "blit_bench.o", b / "blit_bench.prg", b / "blit_bench.map"
    for step in ([VASM, "-Fvobj", "-quiet", "-nowarn=2047", "-o", str(obj), "blit_bench.s"],
                 [VLINK, "-b", "ataritos", "-s", "-o", str(prg), "-M" + str(mp), str(obj)]):
        r = subprocess.run(step, cwd=HERE, capture_output=True, text=True)
        sys.stdout.write(r.stdout + r.stderr)
        if r.returncode:
            sys.exit(r.returncode)
    return str(prg), str(mp)


def cell_addr(base, c):
    return base + (c >> 1) * 8 + (c & 1)


class Bench:
    def __init__(self):
        prg, mp = build()
        self.h = BHarness(prg, mp)
        self.rng = random.Random(7)

    def routine(self, name):
        return self.h.addr(name)

    def fill_screens(self):
        data = bytes(self.rng.randrange(256) for _ in range(STRIDE * 64))
        for s in (SCR_CPU, SCR_BLT, FRONT):
            self.h.mem.w_block(s, data)
        # the front screen differs, for the copy tests
        self.h.mem.w_block(FRONT, bytes(self.rng.randrange(256) for _ in range(STRIDE * 64)))

    def same(self, a, b):
        return bytes(self.h.mem.r_block(a, STRIDE * 64)) == bytes(self.h.mem.r_block(b, STRIDE * 64))

    def measure(self, fn):
        h = self.h
        bus0 = h.bus_cycles
        cyc = fn()
        return cyc + (h.bus_cycles - bus0)

    # ---- tiles -------------------------------------------------------
    def make_tile(self, opaque):
        rows = []
        for _ in range(8):
            t = 0 if opaque else self.rng.choice([0x00, 0xFF, 0x0F, 0xF0, 0x3C, self.rng.randrange(256)])
            planes = [self.rng.randrange(256) & ~t & 0xFF for _ in range(4)]
            rows.append((planes, t))
        return rows

    def tile_case(self, cx0, s, opaque):
        h = self.h
        rows = self.make_tile(opaque)
        entry = bytearray(8) + bytearray()
        for planes, t in rows:
            entry += ((planes[0] << 24) | (planes[1] << 16) | (planes[2] << 8) | planes[3]).to_bytes(4, "big")
            entry += (t * 0x01010101).to_bytes(4, "big")
        h.mem.w_block(ENTRY, bytes(entry))
        self.fill_screens()
        y0 = 4
        X = 8 * cx0 + s
        # --- CPU
        cpu = h.cpu
        for r_ in (R.A0, R.A1, R.A3, R.A4, R.D1, R.D2, R.D3, R.D4, R.D6):
            cpu.w_reg(r_, 0)
        if s == 0:
            cpu.w_reg(R.A1, ENTRY + 8)
            cpu.w_reg(R.A3, cell_addr(SCR_CPU, cx0) + y0 * STRIDE)
            cpu.w_reg(R.D1, 7)
            name = "cpu_opaque" if opaque else "cpu_aligned"
        else:
            mh = ((0xFF << (8 - s)) & 0xFF) * 0x01010101
            cpu.w_reg(R.A0, ENTRY)
            cpu.w_reg(R.A3, cell_addr(SCR_CPU, cx0) + y0 * STRIDE)
            cpu.w_reg(R.A4, cell_addr(SCR_CPU, cx0 + 1) + y0 * STRIDE)
            cpu.w_reg(R.D6, s)
            cpu.w_reg(R.D2, mh)
            cpu.w_reg(R.D3, ~mh & 0xFFFFFFFF)
            cpu.w_reg(R.D4, 8 - s)
            name = "cpu_shift"
        cpu_cycles = self.measure(lambda: h.call(self.routine(name)))
        if name == "cpu_shift":
            cpu_cycles += SETUP_CPU_SHIFT
        # --- Blitter
        b = X & 15
        W = X >> 4
        two = b > 8
        src = bytearray()
        masks = bytearray()
        for planes, t in rows:
            for p in range(4):
                src += (planes[p] << 8).to_bytes(2, "big")
            M = (~t & 0xFF) << 8
            masks += ((M >> b) & 0xFFFF).to_bytes(2, "big")
            if two:
                masks += ((M << (16 - b)) & 0xFFFF).to_bytes(2, "big")
        h.mem.w_block(BDATA, bytes(src))
        h.mem.w_block(MASKS, bytes(masks))
        h.hw(0x20, 2); h.hw(0x22, 2); h.hw(0x2a, 0xFFFF)
        h.hw(0x2e, 8 if two else 2); h.hw(0x30, (-6 if two else 2) & 0xFFFF)
        h.hw(0x24, BDATA, 4)
        h.hw(0x32, SCR_BLT + y0 * STRIDE + W * 8, 4)
        h.hw(0x36, 2 if two else 1)
        h.hw(0x3a, 0x0203)
        h.io[0xa3d] = b | (0x40 if two else 0)
        h.mem.w8(0xff8a3d, b | (0x40 if two else 0))
        for r_, v in ((R.A1, 0xff8a28), (R.A6, 0xff8a2c), (R.A2, 0xff8a3c), (R.A3, 0xff8a34), (R.A5, 0xff8a38),
                      (R.A4, MASKS), (R.D3, 4), (R.D2, 0xC0), (R.D4, 152), (R.D1, 7)):
            cpu.w_reg(r_, v)
        blt = self.measure(lambda: h.call(self.routine("blt_row2" if two else "blt_row1"))) + SETUP_TILE
        ok = self.same(SCR_CPU, SCR_BLT)
        return cpu_cycles, blt, ok

    # ---- runs of cells --------------------------------------------------
    def run_case(self, op, k, y0=8):
        """k whole groups (2k cells) of 8 lines: CPU cell by cell, Blitter in one blit"""
        h = self.h
        cpu = h.cpu
        self.fill_screens()
        g0 = 2
        # CPU
        total = 0
        for c in range(2 * g0, 2 * (g0 + k)):
            a4 = cell_addr(SCR_CPU, c) + y0 * STRIDE
            a5 = cell_addr(FRONT, c) + y0 * STRIDE
            for r_, v in ((R.A4, a4), (R.A5, a5), (R.D1, 0)):
                cpu.w_reg(r_, v)
            total += self.measure(lambda: h.call(self.routine("cpu_clear" if op == "clear" else "cpu_copy")))
        # Blitter
        dst = SCR_BLT + y0 * STRIDE + g0 * 8
        h.hw(0x20, 2); h.hw(0x22, (STRIDE - (8 * k - 2)) & 0xFFFF)
        h.hw(0x28, 0xFFFF); h.hw(0x2a, 0xFFFF); h.hw(0x2c, 0xFFFF)
        h.hw(0x2e, 2); h.hw(0x30, (STRIDE - (8 * k - 2)) & 0xFFFF)
        h.hw(0x24, FRONT + y0 * STRIDE + g0 * 8, 4)
        h.hw(0x32, dst, 4)
        h.hw(0x36, 4 * k); h.hw(0x38, 8)
        h.hw(0x3a, 0x0000 if op == "clear" else 0x0203)
        h.mem.w8(0xff8a3d, 0); h.io[0xa3d] = 0
        cpu.w_reg(R.A2, 0xff8a3c); cpu.w_reg(R.D2, 0xC0)
        blt = self.measure(lambda: h.call(self.routine("blt_run"))) + SETUP_RUN
        if op == "clear":     # the CPU clears in SCR_CPU: compare only the touched region
            pass
        a = bytes(h.mem.r_block(SCR_CPU, STRIDE * 64))
        bb = bytes(h.mem.r_block(SCR_BLT, STRIDE * 64))
        ok = a == bb
        return total, blt, ok


def main():
    bn = Bench()
    print("Tiles, cycles for one 8 x 8 tile (loop + estimated register setup); CPU = draw_tile's own loop:\n")
    print("%-34s %9s %9s %7s  identical" % ("case", "CPU", "Blitter", "ratio"))
    rows = []
    for label, cx0, s, opaque in (("aligned, even cell, transparent", 2, 0, False), ("aligned, odd cell, transparent", 3, 0, False),
                                  ("aligned, opaque (no transparent px)", 2, 0, True),
                                  ("shifted 3, left cell even (1 word)", 2, 3, False), ("shifted 3, left cell odd (2 words)", 3, 3, False),
                                  ("shifted 6, left cell even", 2, 6, False), ("shifted 6, left cell odd", 3, 6, False)):
        c, b, ok = bn.tile_case(cx0, s, opaque)
        rows.append((label, c, b))
        print("%-34s %9d %9d %6.2fx  %s" % (label, c, b, c / b, "yes" if ok else "NO"))
    print("\nRuns of whole groups (2 cells a group, 8 lines), CPU cell by cell against one blit:\n")
    print("%-26s %9s %9s %7s  identical" % ("case", "CPU", "Blitter", "ratio"))
    for op in ("clear", "copy"):
        for k in (1, 2, 4, 8):
            c, b, ok = bn.run_case(op, k)
            print("%-26s %9d %9d %6.2fx  %s" % ("%s %d group(s) = %d cells" % (op, k, 2 * k), c, b, c / b, "yes" if ok else "NO"))


if __name__ == "__main__":
    main()
