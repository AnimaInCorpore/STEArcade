"""The STE picture (src/render.s in a SIM harness, src/render_test.s, on engine/sim.py: Musashi + the Blitter model)
against the reference picture (tools/video.py) through the fixed palette (tools/assets.py Oracle), pixel for pixel on
the colour indices.

    venv/bin/python games/gauntlet/tools/render_test.py [--seed S] [--level L] [--frames N] [--first F] [--every K]
                                                         [--save DIR] [--profile] [--nobuild]

The reference board (tools/machine.py) runs the scenario (seed 0: the attract mode; 1-9: one player at random,
ref/cover.py's Player; 10-19: two to four players; --level L: the level number poked into the game's RAM ($904004)
until the maze is built, so every level can be reached); from frame F on, every K-th frame its video RAM, palette and
x scroll are copied to the STE addresses (map.i) and render_frame draws a picture, which is compared with the
reference picture: the STE's x 0-223 against the arcade's 8-231 (the maze), 224-319 against 240-335 (the panel).
Consecutive pictures alternate between the two rings (the damage of the picture before last restored).
--save: PNGs of the differing pictures (STE | reference | differences).
"""
from pathlib import Path
import argparse
import random
import subprocess
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[2] / "engine"), str(HERE.parent / "ref")]
from paths import ROOT, build_dir, src_dir, VASM, VLINK, RT_INCLUDE

LEVEL_RAM = 0x904004                 # the level number (word; the panel's "LEVEL n" prints it, $41784)
LEVEL_POKE_UNTIL = 790               # (held until the first player's maze is built)
STRIDE = 448                         # (render.s)


def scenario(seed, level=0, frames=3000, sound=True):
    """the reference board through a scenario: yields (frame, machine) after each frame"""
    from machine import Gauntlet
    from cover import Player, COIN_BITS
    rnd = random.Random(seed)
    m = Gauntlet(sound=sound)
    players = []
    if seed:
        n = 1 if seed < 10 else rnd.randint(2, 4)
        players = [Player(rnd, k, 600 + 50 * k) for k in range(n)]
    for f in range(frames):
        coins = 0xFF
        for p in players:
            if p.coin(f):
                coins &= ~COIN_BITS[p.k]
            m.inputs[p.k] = 0xFFFF & ~p.joy(f)
        m.coins = coins
        if level and f < LEVEL_POKE_UNTIL:
            m.cpu.mem[LEVEL_RAM] = level >> 8
            m.cpu.mem[LEVEL_RAM + 1] = level & 0xFF
        m.run_frame()
        yield f, m


def arc_map():
    """build/gauntlet/map.i (tools/patch.py): NAME -> the STE address"""
    out = {}
    for line in (build_dir("gauntlet") / "map.i").read_text().splitlines():
        if "=" in line and not line.startswith(";"):
            k, v = line.split(";")[0].split("=")
            out[k.strip()] = int(v.strip().lstrip("$"), 16)
    return out


def build_harness(defines=()):
    """build/gauntlet/render_test.prg: src/render_test.s (render.s in a harness) for engine/sim.py"""
    import assets
    from patch import write_map
    build = build_dir("gauntlet")
    write_map(build)
    if not (build / "palette.bin").exists() or not (build / "sprite_code.s").exists():
        assets.build()
    src = src_dir("gauntlet")
    inc = ["-I", str(build), "-I", str(RT_INCLUDE)]
    obj = build / "render_test.o"
    prg = build / "render_test.prg"
    for cmd in ([VASM, "-Fvobj", "-quiet", "-nowarn=2047", "-DSIM=1"] + ["-D" + d for d in defines] + inc +
                ["-o", str(obj), "render_test.s"],
                [VLINK, "-b", "ataritos", "-M" + str(build / "render_test.map"), "-o", str(prg), str(obj)]):
        r = subprocess.run(cmd, cwd=src, capture_output=True, text=True)
        if r.returncode:
            sys.exit(r.stdout + r.stderr)
    return prg


class Harness:
    """render_test.prg on engine/sim.py: put(machine) copies the arcade's state, draw() runs render_frame"""

    def __init__(self, prg, profile=False):
        from sim import Sim, TRAP1
        import bisect
        self.TRAP1 = TRAP1
        build = build_dir("gauntlet")
        self.sim = Sim(str(prg), ram_kib=16384, run_dir=build)
        self.sym = {k: v + self.sim.base for k, v in self.sim.symbols(build / "render_test.map").items()}
        self.map = arc_map()
        self.stops = {self.sym[n]: n for n in ["sim_wait", "sim_render_ret"]}
        self.profile = profile
        import collections
        self.prof = collections.Counter()
        import re
        code = {m.group(1) for m in re.finditer(r"\s+0x[0-9a-f]+ (\S+?): \S+ reloc", (build / "render_test.map").read_text())}
        self.plabs = sorted((v, k) for k, v in self.sym.items() if k in code and not k.startswith(".") and "$" not in k)
        self.paddr = [a for a, k in self.plabs]
        self.bisect = bisect
        self.run_to_stop()

    def run_to_stop(self):
        sim, cpu = self.sim, self.sim.cpu
        used = 0
        while used < 2_000_000_000:
            if self.profile:
                pc = cpu.r_pc()
                r = cpu.execute(1)
                c = r.cycles + sim.blitter.cycles
                self.prof[self.plabs[self.bisect.bisect_right(self.paddr, pc) - 1][1]] += c
            else:
                r = cpu.execute(4000)
                c = r.cycles + sim.blitter.cycles
            used += c
            sim.blitter.cycles = 0
            pc = cpu.r_pc()
            if pc in self.stops:
                return self.stops[pc], used
            if pc == self.TRAP1:
                sim.gemdos()
            if pc == 0x600:
                raise RuntimeError("exception: %s" % sim.log)
        raise RuntimeError("68000 budget exceeded at %06x" % cpu.r_pc())

    def resume(self):
        from machine68k import Register as R
        cpu, mem = self.sim.cpu, self.sim.mem
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp))
        cpu.w_reg(R.A7, sp + 4)

    def put(self, m):
        self.put_raw(m.vram(), m.palette(), m.xscroll)

    def put_raw(self, vram, palette, xscroll):
        mem = self.sim.mem
        pf = bytes(vram[:0x2000])
        old = getattr(self, "last_pf", None)
        for q in range(256):                                 # (the game's writers mark the quarter columns they
            if old is None or pf[q * 32:q * 32 + 32] != old[q * 32:q * 32 + 32]:   # change: gauntlet.s pf_mark)
                mem.w8(self.sym["pf_dirty"] + q, 0xFF)
        self.last_pf = pf
        al = bytes(vram[0x5000:0x5F00])
        if al != getattr(self, "last_al", None):              # (the alphanumerics' writers: gauntlet.s hooks)
            mem.w8(self.sym["al_dirty"], 0xFF)
        self.last_al = al
        mem.w_block(self.map["ARC_VRAM"], bytes(vram))
        mem.w_block(self.map["ARC_PALETTE"], bytes(palette))
        mem.w16(self.map["ARC_XSCROLL"], xscroll & 0xFFFF)

    def draw(self):
        self.resume()
        stop, used = self.run_to_stop()
        if stop != "sim_render_ret":
            raise RuntimeError("the picture stopped at %s" % stop)
        self.resume()
        stop2, _ = self.run_to_stop()
        assert stop2 == "sim_wait"
        return used

    def picture(self):
        """the displayed 320 x 240 colour indices (flip_addr: the window's first word at the picture's line 0)"""
        mem, sym = self.sim.mem, self.sym
        base = mem.r32(sym["flip_addr"])
        fine = mem.r8(sym["flip_fine"])
        return ring_pixels(bytes(mem.r_block(base, 240 * STRIDE)), 240, 21)[:, fine:fine + 320]


def ring_pixels(data, lines, words):
    """interleaved 4-plane lines (STRIDE bytes) -> [lines, words * 16] colour indices"""
    a = np.frombuffer(data, np.uint8).reshape(lines, STRIDE)[:, :words * 8].reshape(lines, words, 4, 2)
    bits = np.unpackbits(a, axis=3).reshape(lines, words, 4, 16)
    pix = (bits * (1 << np.arange(4))[None, None, :, None]).sum(2)
    return pix.reshape(lines, words * 16).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--level", type=int, default=0)
    ap.add_argument("--frames", type=int, default=2000)
    ap.add_argument("--first", type=int, default=400)
    ap.add_argument("--every", type=int, default=3)
    ap.add_argument("--save", default=None)
    ap.add_argument("--profile", action="store_true", help="68000 + Blitter cycles per routine (the pictures drawn)")
    ap.add_argument("--nobuild", action="store_true")
    ap.add_argument("--nomo", action="store_true", help="the motion objects left out (both pictures)")
    ap.add_argument("-D", dest="defines", action="append", default=[])
    args = ap.parse_args()
    import assets
    prg = build_dir("gauntlet") / "render_test.prg" if args.nobuild else build_harness(args.defines)
    h = Harness(prg, args.profile)
    oracle = assets.Oracle()
    save = Path(args.save) if args.save else None
    if save:
        save.mkdir(parents=True, exist_ok=True)
    bad = checked = 0
    cyc = []
    for f, m in scenario(args.seed, args.level, args.frames):
        if f < args.first or (f - args.first) % args.every:
            continue
        vram = bytearray(m.vram())
        if args.nomo:
            vram[0x2000:0x4000] = bytes(0x2000)            # (every list: object 0, linked to itself, nothing drawn)
        h.put_raw(vram, m.palette(), m.xscroll)
        used = h.draw()
        if checked:
            cyc.append(used)                                # (not the first: init_video, every tile and character)
        got = h.picture()
        want = oracle.picture_raw(vram, m.palette(), m.xscroll)
        checked += 1
        n = int((got != want).sum())
        if n:
            bad += 1
            if bad <= 10:
                ys, xs = np.nonzero(got != want)
                print("frame %d: %d pixels differ (first at x %d y %d: %d / %d)" % (
                    f, n, xs[0], ys[0], got[ys[0], xs[0]], want[ys[0], xs[0]]), flush=True)
            if save:
                from PIL import Image
                rgb = oracle.rgb
                diff = rgb[want].copy()
                diff[got != want] = (255, 0, 255)
                Image.fromarray(np.hstack((rgb[got], rgb[want], diff))).save(save / ("f%05d.png" % f))
    if args.profile and checked:
        tot = sum(h.prof.values())
        for k, c in h.prof.most_common(30):
            print("  %-24s %8.0f a picture %5.1f%%" % (k, c / checked, 100 * c / tot))
    if cyc:
        print("cycles a picture: median %.0f, 90%% %.0f" % (np.median(cyc), np.percentile(cyc, 90)))
    print("seed %d level %d: %d pictures compared, %d differ; 68000 + Blitter cycles a picture (Musashi): mean %.0f, "
          "max %d" % (args.seed, args.level, checked, bad, np.mean(cyc) if cyc else 0, max(cyc) if cyc else 0))
    return int(bad != 0)


if __name__ == "__main__":
    sys.exit(main())
