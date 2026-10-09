"""Differential test of two builds of a port (e.g. before / after a translator change): both --sim builds run on
Musashi with the same schedule, and the arcade's memory must be the same at every game frame (the entry of the
main CPU's interrupt handler, after the same number of game frames in both).

    python engine/xdiff.py galaga <old.PRG> <old.map> [frames]

The new build is the current run/<game>_sim one.  The interrupts are delivered on a clock of translated Z80
instructions (ZCLOCK), so the arcade's state at the k-th game frame does not depend on how fast either build is.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sim import Sim, FRAME_CYCLES, TRAP1
from machine68k import Register as R
from paths import ROOT, build_dir

GAMES = {
    # new build, map, the label of a game frame, regions (symbol, start, end) compared, cells skipped (offsets)
    "galaga": ("run/galaga_sim/GALAGA.PRG", "galaga.map", "Z0038",
               [("g_block", 0x8000, 0x10000), ("g_block", 0x16800, 0x18000)],
               # (the IY / F' words of the old register map; the stacks of the main and the sub CPU: an interrupt's
               # push af saves d6, which need not hold the interrupted code's flags (they may be in the CCR))
               set(range(0x9FF0, 0x9FFC)) | set(range(0x8A00, 0x8B00)) | set(range(0x9000, 0x9100)),
               # the Z80 stack pointers at the stop (below them: what the interrupted code pushed, timing dependent):
               # the main CPU's (a5, a6 = g_block + $10000), the sub CPU's (its saved a5, a6 = g_block)
               lambda r: [(r.s.cpu.r_reg(R.A5) - r.sym["g_block"] - 0x10000) & 0xFFFF,
                          (r.s.mem.r32(r.sym["ctx2"] + 4 * 13) - r.sym["g_block"]) & 0xFFFF]),
}
# The VBL comes every ZCLOCK translated instructions (any CPU), not every 160256 cycles: both builds are then
# interrupted at the same points of the Z80 programs, so foreground work (Galaga's main CPU draws text between its
# interrupts) is as far in both at each game frame.  The renderer runs no Z80 code: it takes no time on this clock.
ZCLOCK = 3000
NSP = {"galaga": 2}             # how many stack pointers the lambda gives
STACK_DEAD = 0x100


class Runner:
    def __init__(self, prg, mapfile, label):
        self.s = Sim(prg, ram_kib=16384, run_dir=os.path.dirname(prg))   # (readable registers: borders.s blit_go)
        self.s.mem.set_trace_mode(True)
        self.sym = {k: v + self.s.base for k, v in self.s.symbols(mapfile).items()}
        self.stop = self.sym[label]
        self.total = 0
        self.next_vbl = FRAME_CYCLES
        self.frames = 0
        z = sorted(v for k, v in self.sym.items() if len(k) == 5 and k[0] in "ZYX" and all(c in "0123456789ABCDEF" for c in k[1:]))
        self.code_lo, self.code_hi = z[0], z[-1] + 64       # the translated code (a stop can only be in there)
        self.heads = set(z)
        self.zcount = 0
        self.quiet = 0
        self.pending = False

    def to_next(self):
        """run to the next game frame (past the current stop)"""
        cpu, s = self.s.cpu, self.s
        first = True
        while True:
            pc = cpu.r_pc()
            if pc == self.stop and not first:
                self.frames += 1
                return True
            first = False
            if pc == TRAP1:
                s.gemdos()
                continue
            if pc == 0x600 or s.terminated:
                return False
            if self.frames == 0 and cpu.r_sr() & 0x0700 == 0x0700 and not self.in_code(pc):
                self.total += cpu.execute(2000).cycles      # (the init with the interrupts off: in chunks)
                continue
            if pc in self.heads:                 # a Z80 instruction starts: the clock of the interrupts
                self.zcount += 1
                self.quiet = 0
                if self.zcount >= ZCLOCK:
                    self.zcount = 0
                    self.pending = True
            elif self.quiet > 2 * FRAME_CYCLES:    # no Z80 code for a while (the runtime waits for a VBL):
                self.quiet = 0                     # the same point of the Z80 programs in both builds
                self.zcount = 0
                self.pending = True
            if self.pending and s.irq(4, 28):
                self.pending = False
                self.next_vbl += FRAME_CYCLES
            c = cpu.execute(1).cycles
            self.total += c
            self.quiet += c

    def in_code(self, pc):
        return self.code_lo <= pc < self.code_hi

    def region(self, sym, lo, hi):
        return bytes(self.s.mem.r_block(self.sym[sym] + lo, hi - lo))


def dump(game, prg, mapfile, frames, out):
    """one build: the compared regions at each game frame into the file out"""
    _, _, label, regions, _, sps = GAMES[game]
    r = Runner(prg, mapfile, label)
    with open(out, "wb") as fh:
        for f in range(frames):
            if not r.to_next():
                print("%s stopped at game frame %d" % (prg, f))
                return 1
            for sp in sps(r):
                fh.write(sp.to_bytes(2, "big"))
            for sym, lo, hi in regions:
                fh.write(r.region(sym, lo, hi))
    return 0


def main():
    if sys.argv[1] == "--dump":
        return dump(sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]), sys.argv[6])
    import subprocess
    import tempfile
    game, old_prg, old_map = sys.argv[1:4]
    frames = int(sys.argv[4]) if len(sys.argv) > 4 else 1000
    prg, mapname, label, regions, skip, sps = GAMES[game]
    nsp = NSP[game]
    tmp = tempfile.mkdtemp(prefix="xdiff_")
    # (two builds cannot share a process: Musashi keeps the CPU in globals)
    jobs = [(old_prg, old_map), (str(ROOT / prg), str(build_dir(game) / mapname))]
    procs = [subprocess.Popen([sys.executable, __file__, "--dump", game, p, m, str(frames), os.path.join(tmp, "%d.bin" % i)])
             for i, (p, m) in enumerate(jobs)]
    if any(p.wait() for p in procs):
        return 1
    size = sum(hi - lo for _, lo, hi in regions) + 2 * nsp
    a, b = (open(os.path.join(tmp, "%d.bin" % i), "rb").read() for i in (0, 1))
    for f in range(frames):
        pos = f * size
        dead = set(skip)
        for i in range(nsp):
            spa = int.from_bytes(a[pos + 2 * i:pos + 2 * i + 2], "big")
            spb = int.from_bytes(b[pos + 2 * i:pos + 2 * i + 2], "big")
            dead |= set(range(min(spa, spb) - STACK_DEAD, max(spa, spb)))
        pos += 2 * nsp
        for sym, lo, hi in regions:
            x, y = a[pos:pos + hi - lo], b[pos:pos + hi - lo]
            pos += hi - lo
            if x != y:
                diff = [lo + i for i in range(len(x)) if x[i] != y[i] and (lo + i) not in dead]
                if diff:
                    print("game frame %d: %d bytes differ in %s, first %s" % (f, len(diff), sym, ", ".join(
                        "%X: %02X/%02X" % (d, x[d - lo], y[d - lo]) for d in diff[:8])))
                    return 1
    print("%s: the same memory at all %d game frames" % (game, frames))
    return 0


if __name__ == "__main__":
    sys.exit(main())
