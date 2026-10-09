"""Where the cycles of the translated programs go: a port's --sim build on Musashi, every 68000 instruction stepped and
charged to the Z80 (or 6801) instruction it was translated from (the generated code's labels, see z80x.py).

    python engine/xprof.py <game> [--frames N] [--skip N] [--top N] [--csv out.csv] [--pcs]

Prints per game frame (one round of the arcade's interrupts: a faster build does the same work per frame): the
cycles of the translated code, of what it calls (runtime) and the rest, then the cycles by instruction form
(`ld a,(hl)`, `jr nz,e`, ...: the numbers replaced), by 68000 instruction, the executed instruction count and the mean
cycles a Z80 instruction.  Idle loops (IDLE) are counted apart.  The inputs are the scripted ones of the port's tests (attract mode for Donkey Kong and
Galaga).  --pcs: the hottest single instructions.

The builds: python port.py build <game> --sim (Donkey Kong / Galaga: --out run/<game>_sim/<NAME>.PRG).
"""
import argparse
import bisect
import collections
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sim import Sim, FRAME_CYCLES, TRAP1
from paths import ROOT, build_dir
from machine68k import Register as R

# idle loops of the translated programs (waiting for an interrupt): counted as "idle", not as translated code
IDLE = {"bublbobl": {("Z", 0x01ED)}}
GAMES = {
    # prg, map, generated sources, label prefixes of the translated programs
    "dkong": ("run/dkong_sim/DKONG.PRG", "dkong.map", ["dk_code.s"], "Z"),
    "galaga": ("run/galaga_sim/GALAGA.PRG", "galaga.map", ["galaga_code.s"], "ZYX"),
    "bublbobl": ("run/bublbobl_sim/BUBBLE.PRG", "bublbobl_sim.map", ["bb_code.s", "bb_mcu.s"], "ZYM"),
    "1942": ("run/1942_sim/1942.PRG", "1942_sim.map", ["code_1942.s"], "Z"),
    "commando": ("run/commando_sim/COMMANDO.PRG", "commando_sim.map", ["code_commando.s"], "Z"),
    "blktiger": ("run/blktiger_sim/BLKTIGER.PRG", "blktiger_sim.map", ["code_blktiger.s"], "Z"),
}
# the ports whose foreground is the game (a kernel with an idle hook): the harness stops at sim_wait, sets vbl_pending
# (1942: and the inputs) and returns; a game frame is one such round (Commando, Black Tiger: attract mode, no inputs)
KERNEL = {"1942", "commando", "blktiger"}
HEAD = re.compile(r"^([A-Z])([0-9A-F]{4,5}):\s*;\s*(.*)$")       # (5 digits: banked code at virtual pcs)
LABEL = re.compile(r"^([A-Za-z_][\w]*):")


def form(text):
    """the instruction with its numbers generalised: ld a,($8123) -> ld a,(nn)"""
    t = text.strip().lower()
    t = re.sub(r"\(i([xy])[+-]\$?[0-9a-f]+\)", r"(i\1+d)", t)
    t = re.sub(r"\(\$[0-9a-f]{3,4}\)", "(nn)", t)
    t = re.sub(r"#\$?[0-9a-f]+", "#n", t)
    t = re.sub(r"\$[0-9a-f]{3,4}\b", "nn", t)
    t = re.sub(r"\$[0-9a-f]{1,2}\b", "n", t)
    t = re.sub(r"(?<=[ ,])\d+\b", "n", t)
    return t


def owners(game):
    """label -> (program prefix, pc, text) of the instruction whose code it is in"""
    out = {}
    for f in GAMES[game][2]:
        cur = None
        for line in (build_dir(game) / f).read_text().splitlines():
            m = HEAD.match(line)
            if m:
                cur = (m.group(1), int(m.group(2), 16), m.group(3))
                out[m.group(1) + m.group(2)] = cur
                continue
            m = LABEL.match(line)
            if m and cur is not None and m.group(1) not in out:
                out[m.group(1)] = cur
            if line.startswith("; ---") or line.startswith("; ===="):
                cur = None
    return out


class Driver:
    """runs the build VBL by VBL with the port's inputs; step() executes one 68000 instruction"""

    def __init__(self, game, s, sym):
        self.game, self.s, self.sym = game, s, sym
        self.cpu, self.mem = s.cpu, s.mem
        self.total = 0
        self.next_vbl = FRAME_CYCLES
        self.f = 0
        self.gframes = 0
        self.rnd = random.Random(1)
        self.stops = {sym[k] for k in ("sim_frame_done", "sim_wait") if k in sym}
        self.bad = sym.get("z80_badpc")
        if game in KERNEL:
            self.block = sym["g_block"]

    def inputs(self):
        f, mem, sym = self.f, self.mem, self.sym
        if self.game == "bublbobl":
            in0 = 0x03 | (0x04 if 400 <= f < 406 else 0)
            in1 = 0xFF
            if 440 <= f < 446:
                in1 &= ~0x40
            if f > 560:
                in1 &= ~(0x02 if (f // 50) % 2 else 0x01)
                if f % 30 < 3:
                    in1 &= ~0x20
                if f % 90 < 3:
                    in1 &= ~0x10
            mem.w8(sym["in0_val"], in0); mem.w8(sym["in1_val"], in1); mem.w8(sym["in2_val"], 0xFF)

    def resume(self):
        sp = self.cpu.r_reg(R.A7)
        self.cpu.w_pc(self.mem.r32(sp))
        self.cpu.w_reg(R.A7, sp + 4)

    def vbl(self):
        """a new VBL: True when one was delivered"""
        if self.game in KERNEL:
            return False                      # (the VBL of these builds is the harness setting vbl_pending at sim_wait)
        if self.s.irq(4, 28):
            self.next_vbl += FRAME_CYCLES
            self.f += 1
            self.s.frames = self.f
            self.inputs()
            return True
        return False

    def on_stop(self, pc):
        """at a harness stop: True when a VBL starts"""
        if self.game in KERNEL and pc == self.sym["sim_wait"] and self.game != "1942":
            self.mem.w8(self.sym["vbl_pending"], 1)
            self.resume()
            self.f += 1
            return True
        if self.game == "1942" and pc == self.sym["sim_wait"]:
            z = lambda a: self.block + a - 0x8000
            sys_in, p1 = 0xFF, 0xFF
            f = self.f
            if 900 <= f < 905:
                sys_in &= 0x7F
            if 940 <= f < 945:
                sys_in &= 0xFE
            if f >= 1000:
                p1 = (0xFF, 0xFF, 0xFE, 0xFD, 0xFB, 0xF7, 0xFA, 0xF6)[(f // 20 + self.rnd.randrange(2)) % 8]
                if self.rnd.random() < 0.3:
                    p1 &= ~0x10
                if f % 400 < 3:
                    p1 &= ~0x20
            self.mem.w8(z(0xC000), sys_in); self.mem.w8(z(0xC001), p1); self.mem.w8(z(0xC002), 0xFF)
            self.mem.w8(self.sym["vbl_pending"], 1)
            self.resume()
            self.f += 1
            return True
        self.resume()
        return False


class Prof:
    """charges executed 68000 instructions to the translated instruction they belong to"""

    def __init__(self, game, sym, cpu, own=None):
        self.cpu = cpu
        self.own = own if own is not None else owners(game)
        self.addrs = sorted((v, k) for k, v in sym.items())
        self.keys = [v for v, _ in self.addrs]
        self.heads = {v for k, v in sym.items() if k in self.own and k == "%s%04X" % self.own[k][:2]}
        self.by_form, self.n_form = collections.Counter(), collections.Counter()
        self.by_pc, self.n_pc = collections.Counter(), collections.Counter()
        self.by_area, self.by_rt, self.by_68k = collections.Counter(), collections.Counter(), collections.Counter()
        self.cache, self.dis = {}, {}
        self.idle = IDLE.get(game, set())

    def kind(self, pc):
        k = self.dis.get(pc)
        if k is None:
            k = self.cpu.disassemble(pc)[1].lower()
            k = re.sub(r"\$[0-9a-f]+", "n", k)
            k = re.sub(r"\b\d+\b", "n", k)
            self.dis[pc] = k
        return k

    def owner(self, pc):
        o = self.cache.get(pc)
        if o is None:
            i = bisect.bisect_right(self.keys, pc) - 1
            name = self.addrs[i][1] if i >= 0 else "?"
            o = self.own.get(name) or name
            self.cache[pc] = o
        return o

    def charge(self, pc, c):
        o = self.owner(pc)
        if isinstance(o, tuple) and o[:2] in self.idle:
            self.by_area["idle (translated wait loop)"] += c
            return
        if isinstance(o, tuple):
            f = (o[0], form(o[2]))
            self.by_area["translated " + o[0]] += c
            self.by_form[f] += c
            self.by_pc[o] += c
            self.by_68k[self.kind(pc)] += c
            if pc in self.heads:
                self.n_form[f] += 1
                self.n_pc[o] += 1
        else:
            self.by_area["other"] += c
            self.by_rt[o] += c

    def report(self, title, n, top, pcs=False, csv=""):
        n = max(n, 1)
        tr = sum(v for k, v in self.by_area.items() if k.startswith("translated"))
        ins = sum(self.n_form.values())
        print(title)
        for k, v in sorted(self.by_area.items()):
            print("  %-14s %8d cycles/frame" % (k, v // n))
        print("  translated code: %d cycles/frame, %d Z80 instructions/frame, %.1f cycles each" % (tr // n, ins // n, tr / max(ins, 1)))
        print("\n  by instruction form (cycles/frame, %, count/frame, cycles each):")
        for (p, f), v in self.by_form.most_common(top):
            k = self.n_form[(p, f)]
            print("   %s %-22s %8d %5.1f%% %7d %6.1f" % (p, f, v // n, 100.0 * v / tr, k // n, v / max(k, 1)))
        print("\n  by 68000 instruction in the translated code (cycles/frame, %):")
        for k, v in self.by_68k.most_common(top):
            print("   %-34s %8d %5.1f%%" % (k, v // n, 100.0 * v / tr))
        print("\n  runtime / other routines called (cycles/frame):")
        for k, v in self.by_rt.most_common(15):
            print("   %-28s %8d" % (k, v // n))
        if pcs:
            print("\n  hottest instructions:")
            for o, v in self.by_pc.most_common(top):
                print("   %s%04X %-22s %8d %7d" % (o[0], o[1], o[2], v // n, self.n_pc[o] // n))
        if csv:
            with open(csv, "w") as fh:
                fh.write("prog,form,cycles,count\n")
                for (p, f), v in self.by_form.most_common():
                    fh.write('%s,"%s",%d,%d\n' % (p, f, v, self.n_form[(p, f)]))
        return tr / n


def dkong(a):
    """Donkey Kong: the lock-step test (games/dkong/tools/fullrun.py) with its run loop stepped: the translated code
    alone (NMI injected at the idle loop), compared with the reference every frame"""
    sys.path.insert(0, str(ROOT / "games" / "dkong" / "tools"))
    import fullrun
    frames = a.frames or 1500
    L = fullrun.Lock()
    prof = Prof("dkong", L.sym, L.cpu)
    cpu = L.cpu

    def run68(budget=50_000_000):
        used = 0
        while used < budget:
            pc = cpu.r_pc()
            if pc in L.stops:
                return L.stops[pc]
            c = cpu.execute(1).cycles
            used += c
            prof.charge(pc, c)
        return "budget"
    fullrun.Lock = lambda *x, **k: L
    L.run68 = run68
    sys.argv = ["fullrun.py", str(frames)]
    rc = fullrun.main()
    prof.report("dkong: %d NMI frames of fullrun.py (lock-step%s); figures per frame" % (frames, " FAILED" if rc else " ok"),
                frames, a.top, a.pcs, a.csv)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("game", choices=sorted(GAMES))
    ap.add_argument("--frames", type=int, default=0, help="game frames counted (default per game)")
    ap.add_argument("--skip", type=int, default=-1, help="game frames run first, not counted (default per game)")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--pcs", action="store_true")
    ap.add_argument("--csv", default="")
    ap.add_argument("--prg", default="")
    a = ap.parse_args()
    if a.game == "dkong":
        return dkong(a)
    # defaults: past the boot, into the attract demo / the play of the tests' input scripts
    skip, frames = {"galaga": (800, 400), "bublbobl": (500, 300), "1942": (1100, 400), "commando": (600, 400),
                    "blktiger": (600, 400)}[a.game]
    if a.skip >= 0:
        skip = a.skip
    if a.frames:
        frames = a.frames
    prg, mapname, _, prefixes = GAMES[a.game]
    prg = a.prg or str(ROOT / prg)
    s = Sim(prg, ram_kib=16384 if a.game in KERNEL else 4096, run_dir=os.path.dirname(prg))
    s.mem.set_trace_mode(a.game != "bublbobl")      # (the Blitter model starts on a traced write)
    sym = {k: v + s.base for k, v in s.symbols(build_dir(a.game) / mapname).items()}
    d = Driver(a.game, s, sym)
    cpu = s.cpu
    prof = Prof(a.game, sym, cpu)
    d.inputs()
    # a game frame: one round of the arcade's interrupts (the work of a frame is the same in every build)
    tick_pc = {"galaga": sym.get("Z0038")}.get(a.game)
    gf = lambda: (d.gframes if a.game == "galaga" else d.f if a.game in KERNEL else s.mem.r32(sym["sim_game_frames"]))
    vbls = 0
    step = cpu.execute
    g0 = None
    while True:
        g = gf()
        if g0 is None and g >= skip:
            g0 = g
        if g0 is not None and g - g0 >= frames:
            break
        counting = g0 is not None
        pc = cpu.r_pc()
        if pc == tick_pc:
            d.gframes += 1
        if pc in d.stops:
            if d.on_stop(pc) and d.f % 100 == 0:
                print("frame", d.f, gf(), file=sys.stderr, flush=True)
            continue
        if pc == TRAP1:
            s.gemdos()
            continue
        if pc == 0x600 or pc == d.bad or s.terminated:
            print("stopped at %06X" % pc)
            break
        c = step(1).cycles
        d.total += c
        if counting:
            prof.charge(pc, c)
        if d.game not in KERNEL and d.total >= d.next_vbl:
            if d.vbl():
                vbls += counting
                if d.f % 100 == 0:
                    print("frame", d.f, gf(), file=sys.stderr, flush=True)
    prof.report("%s: %d game frames from %d (%d VBLs; a VBL is %d cycles); figures per game frame" % (a.game, frames, skip, vbls, FRAME_CYCLES),
                frames, a.top, a.pcs, a.csv)


if __name__ == "__main__":
    main()
