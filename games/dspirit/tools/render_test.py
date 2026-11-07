"""The STE renderer (src/render.s) against the reference picture, pixel by pixel.

    venv/bin/python games/dspirit/tools/render_test.py [--play A-B] [--attract A-B] [--every N] [--png N,..] [-D NAME=V]

render.s is assembled into a small harness (render.s, vio) and run on Musashi with the simulator's Blitter.  The
states come from the reference (tools/states.py: build/dspirit/render_states.pkl): per state the harness gets vio
(the C116 image, tile RAM, sprite RAM, CUS123 control), render_frame draws, render_vbl shows; the shown buffer is
read back and every pixel of the 288 x 224 picture must have the STE index the renderer's mapping gives the
model's pen (tools/stemodel.py picture: exact against the reference's picture on the play states): black
is 0, any other colour (the palette when the colours were chosen, ren_palsnap, 4 bits a channel) the nearest of the
renderer's centres (ren_cent, Oklab bytes of assets.py ren_lab, L1, the first of equals); no pen: 0.  A picture
shown black (its palette all 0: a new scene waiting) is only counted.  The colour error: the Oklab distance of the
STE colour shown to the arcade's, the mean over the pictures' pixels.
The widened picture (stemodel.picture_wide: the whole 320 pixels, the rows shown, the water locked at the renderer's
offsets, layer 0 in the bank the renderer holds: Harness.held) is compared.  Cycles: Musashi's CPU cycles + the
Blitter's bus cycles, per picture.  --png: STE | model into build/dspirit/render_<kind>_N.png.
"""
import argparse
import os
import pickle
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[2] / "engine")]
from paths import VASM, VLINK, RT_INCLUDE, build_dir, src_dir
from machine68k import Register as R
from sim import Sim, TRAP1
import assets
import stemodel

BUILD = build_dir("dspirit")
STATES = BUILD / "render_states.pkl"
FLAGS_ALL = bool(os.environ.get("FLAGS_ALL"))  # (every writer flag set for every state)
VIO_SIZE = 0x28000
LINEB, PIC_H, PIC_W = 424, 288, 224

HARNESS = r"""
; render.s alone, for tools/render_test.py
	section text,code
start:	clr.l	-(sp)
	move	#$20,-(sp)
	trap	#1
	addq	#6,sp
	lea	h_stack_top,sp
h_wait:	bra.s	h_wait
	include	"render.s"
	section	bss,bss
	even
tile_written:	ds.b	5
	even
vio:	ds.b	$28000
h_stack:	ds.b	8192
h_stack_top:
"""


def c116_image(st):
    """the C116's 32 KB as the CPUs see them: the three colour planes and the registers (plane 3, mirrored)"""
    o = np.arange(0x8000)
    plane = (o >> 11) & 3
    idx = ((o & 0x6000) >> 2) | (o & 0x7FF)
    pal = np.stack([np.frombuffer(p, np.uint8) for p in st["pal"]] + [np.zeros(0x2000, np.uint8)])
    img = pal[plane, idx].astype(np.uint8)
    regs = st["regs"]
    for k in range(0x8000):
        if (k >> 11) & 3 == 3:
            r = regs[(k & 0xF) >> 1]
            img[k] = r & 0xFF if k & 1 else r >> 8
    return img.tobytes()


def build_harness(defines=()):
    assets.build()
    import make_render          # (src/render.s)
    tag = "ren_harness" + "".join("_" + d.replace("=", "") for d in sorted(defines))
    (BUILD / "ren_harness.s").write_text(HARNESS)
    obj, prg = BUILD / (tag + ".o"), BUILD / (tag + ".PRG")
    cmd = [VASM, "-Fvobj", "-quiet", "-nowarn=2047", "-I", str(BUILD), "-I", str(RT_INCLUDE), "-I",
           str(src_dir("dspirit")), "-DSIM=1"] + ["-D" + d for d in defines] + [
           "-o", str(obj), str(BUILD / "ren_harness.s")]
    for step in (cmd, [VLINK, "-b", "ataritos", "-s", "-o", str(prg), "-M" + str(BUILD / (tag + ".map")), str(obj)]):
        r = subprocess.run(step, capture_output=True, text=True)
        if r.returncode:
            sys.exit(r.stdout + r.stderr)
    return prg, BUILD / (tag + ".map")


class Harness:
    def __init__(self, defines=()):
        prg, mp = build_harness(defines)
        self.s = Sim(str(prg), ram_kib=16384, run_dir=BUILD)
        self.s.mem.set_trace_mode(True)
        self.sym = {k: v + self.s.base for k, v in self.s.symbols(mp).items()}
        self.mem, self.cpu = self.s.mem, self.s.cpu
        self.run_to(self.sym["h_wait"])
        self._c116 = None
        self._vram = None

    def run_to(self, stop, limit=4_000_000_000):
        total = 0
        while total < limit:
            r = self.cpu.execute(5000)
            total += r.cycles
            pc = self.cpu.r_pc()
            if pc == stop:
                return total
            if pc == TRAP1:
                self.s.gemdos()
            elif pc < 0x1000:
                sp = self.cpu.r_reg(R.A7)
                words = [self.mem.r16(sp + 2 * k) for k in range(8)]
                inv = {v: k for k, v in self.sym.items()}

                def near(a):
                    best = max((v for v in self.sym.values() if v <= a), default=0)
                    return "%s+%X" % (inv.get(best, "?"), a - best)
                raise RuntimeError("exception at vector %X: stack %s; pc %s / %s" % (
                    pc, " ".join("%04X" % w for w in words), near((words[1] << 16) | words[2]),
                    near((words[5] << 16) | words[6])))
        raise RuntimeError("timeout at %06X" % (self.cpu.r_pc() - self.s.base))

    def call(self, name):
        sp = self.cpu.r_reg(R.A7) - 4
        self.mem.w32(sp, self.sym["h_wait"])
        self.cpu.w_reg(R.A7, sp)
        self.cpu.w_pc(self.sym[name])
        self.s.blitter.cycles = 0
        c = self.run_to(self.sym["h_wait"])
        return c, self.s.blitter.cycles

    def profile(self, name):
        """the routine run instruction by instruction: cycles by the nearest code label before the pc"""
        import bisect
        labels = sorted((v, k) for k, v in self.sym.items() if k.startswith("ren_") or k == "blit_go")
        addrs = [v for v, k in labels]
        sp = self.cpu.r_reg(R.A7) - 4
        self.mem.w32(sp, self.sym["h_wait"])
        self.cpu.w_reg(R.A7, sp)
        self.cpu.w_pc(self.sym[name])
        out = {}
        stop = self.sym["h_wait"]
        while self.cpu.r_pc() != stop:
            i = bisect.bisect_right(addrs, self.cpu.r_pc()) - 1
            c = self.cpu.execute(1).cycles
            k = labels[i][1] if i >= 0 else "?"
            out[k] = out.get(k, 0) + c
        return out

    def r8(self, name, off=0):
        return self.mem.r8(self.sym[name] + off)

    def r32(self, name, off=0):
        return self.mem.r32(self.sym[name] + off)

    def put_state(self, st):
        v = st["vram"]
        if self._vram is None:
            self._vram = bytes(len(v))
        for k, (x, y) in enumerate(((0, 0x2000), (0x2000, 0x4000), (0x4000, 0x6000), (0x6000, 0x7000), (0x7000, 0x8000))):
            if v[x:y] != self._vram[x:y] or FLAGS_ALL:   # (the translated writers' flags: a layer's tile RAM
                                                              # written; FLAGS_ALL: every picture, as stores of the
                                                              # same words set them)
                self.mem.w8(self.sym["tile_written"] + k, 0xFF)
        self._vram = v
        vio = self.sym["vio"]
        self.mem.w_block(vio, c116_image(st))
        self.mem.w_block(vio + 0x10000, v)
        self.mem.w_block(vio + 0x1C800, st["spriteram"])
        self.mem.w_block(vio + 0x1D000, st["control"])

    def held(self, st):
        """the state as the renderer draws it: layer 0 with the bank held since the colours were chosen (ren_l0bank;
        the lightning as a palette flash, render.s ren_flash_pen)"""
        b = self.mem.r16(self.sym["ren_l0bank"])
        if b >= 0x8000 or (st["control"][0x18] & 7) == b:
            return st
        c = bytearray(st["control"])
        c[0x18] = (c[0x18] & ~7) | b
        return dict(st, control=bytes(c))

    def lock(self):
        """the renderer's locked layers: {layer: (row offset, column offset)}"""
        n = self.mem.r16(self.sym["ren_nlock"])
        r16 = lambda nm, i: self.mem.r16(self.sym[nm] + 2 * i)
        return {r16("ren_lockl", i): (r16("ren_lockdr", i), r16("ren_lockdc", i)) for i in range(n)}

    def shown(self):
        """the SHOWN lines x 320 indices the STE shows: from the published base (ren_vbase), a line every LINEB bytes,
        21 groups read, the fine scroll's pixels skipped"""
        base = self.r32("ren_vbase")
        fine = self.r8("ren_vfine")
        n = stemodel.SHOWN
        rows = []
        for i in range(n):
            rows.append(bytes(self.mem.r_block(base + i * LINEB, 21 * 8)))
        raw = np.frombuffer(b"".join(rows), ">u2").reshape(n, 21, 4)
        bits = np.unpackbits(raw.view(np.uint8).reshape(n, 21, 4, 2), axis=3).reshape(n, 21, 4, 16)
        idx = (bits * (1 << np.arange(4))[None, None, :, None]).sum(2).reshape(n, 336)
        return idx[:, fine:fine + 320]


LAB = None
GFX = None


def gfx():
    global GFX
    if GFX is None:
        sys.path.insert(0, str(HERE.parents[2] / "engine"))
        from namcos1 import NamcoS1
        GFX = NamcoS1("dspirit", cpus=False).gfx()
    return GFX


def mapped_index(h, pens):
    """the renderer's index of each pen (its snapshot, centres)"""
    global LAB
    if LAB is None:
        LAB = np.frombuffer((BUILD / "ren_lab.bin").read_bytes(), np.uint8).reshape(4096, 4)[:, :3].astype(int)
    snap = np.frombuffer(bytes(h.mem.r_block(h.sym["ren_palsnap"], 0x4000)), np.uint8)
    n = h.mem.r16(h.sym["ren_ncent"])
    cent = np.frombuffer(bytes(h.mem.r_block(h.sym["ren_cent"], 64)), np.uint8).reshape(16, 4)[1:n + 1, :3].astype(int)
    p = np.where(pens < 0, 0, pens)
    off = ((p & 0x1800) << 2) | (p & 0x7FF)
    q = np.round(np.arange(256) / 17).astype(int)
    key = (q[snap[off]] << 8) | (q[snap[off + 0x800]] << 4) | q[snap[off + 0x1000]]
    d = np.abs(LAB[key][..., None, :] - cent[None, None]).sum(-1)       # (H, W, n)
    idx = np.argmin(d, -1) + 1
    return np.where((pens < 0) | (key == 0), 0, idx)


SIZE_CODE = {16: 0, 8: 1, 32: 2, 4: 3}


def place(sr, e, r0, c0, sizex, sizey, code, colour, flipx, flipy, pri=6):
    """sprite RAM entry e at picture row r0, column c0 (stemodel's geometry inverted: x = r0 + 73,
    y = 240 - sizey - c0, b15 = (1 - sizey - yoffs - y) & $FF; y must lie in -16 .. 239)"""
    xoffs = sr[0x7F5] + ((sr[0x7F4] & 1) << 8)
    yoffs = sr[0x7F7]
    v = (r0 + 73 - xoffs) & 0x1FF
    y = 240 - sizey - c0
    off = e * 16
    sr[off + 10] = (SIZE_CODE[sizex] << 6) | (0x20 if flipx else 0) | ((code >> 8) & 7)
    sr[off + 11] = code & 0xFF
    sr[off + 12] = (colour << 1) | (v >> 8)
    sr[off + 13] = v & 0xFF
    sr[off + 14] = (pri << 5) | (SIZE_CODE[sizey] << 1) | (1 if flipy else 0)
    sr[off + 15] = (1 - sizey - yoffs - y) & 0xFF


def edge_states(base, bufs, seed=1):
    """pictures of test sprites: across the left and right edges and inside, all 16 fine positions, the four flips,
    the sizes, the top and bottom guards, and across the 64 KB boundaries of each shown buffer (bufs: their
    addresses; a picture is drawn into each in turn); the other entries parked off the picture"""
    import random
    rng = random.Random(seed)
    out = []
    shapes = [(32, 32, 300), (16, 16, 300), (8, 8, 300), (32, 16, 300), (16, 32, 300), (4, 4, 300)]
    for n in range(240):
        st = dict(base)
        sr = bytearray(base["spriteram"])
        for e in range(127):
            place(sr, e, 400, 100, 16, 16, 0, 0, 0, 0)        # (parked below the picture)
        buf = bufs[n % len(bufs)]
        for e in range(12):
            sx, sy, code = shapes[rng.randrange(len(shapes))]
            kind = rng.randrange(6)
            if kind == 0:
                c0 = -sy + 1 + rng.randrange(sy + 15)            # across the left edge
            elif kind == 1:
                c0 = 224 - sy + rng.randrange(sy + 15) - 14      # across the right edge
            else:
                c0 = rng.randrange(-sy + 1, 224)
            c0 = (c0 & ~15) | (n % 16) if kind == 2 else c0      # (every fine position in turn)
            c0 = max(c0, -sy + 1 if sy > 16 else -15)            # (y within the hardware's range)
            if kind == 3:
                r0 = -sx + 1 + rng.randrange(sx)                 # into the top guard
            elif kind == 4:
                r0 = 288 - rng.randrange(1, sx)                  # into the bottom guard
            elif kind == 5:
                # across a 64 KB boundary of this picture's buffer: the row whose line crosses it
                line0 = buf + 32 * 160
                k = (line0 + 0xFFFF) // 0x10000 * 0x10000
                rc = (k - line0) // 160
                r0 = max(-sx + 1, min(287, rc - rng.randrange(sx)))
            else:
                r0 = rng.randrange(-sx + 1, 288)
            place(sr, e, r0, c0, sx, sy, code + rng.randrange(4), rng.randrange(1, 100), rng.randrange(2), rng.randrange(2))
        st["spriteram"] = bytes(sr)
        out.append(st)
    return out


def parse_range(s, n):
    if not s:
        return []
    a, b = (s.split("-") + [None])[:2]
    a = int(a)
    b = int(b) if b else a + 1
    return list(range(a, min(b, n)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--play", default="0-1500")
    ap.add_argument("--attract", default="0-500")
    ap.add_argument("--every", type=int, default=1)
    ap.add_argument("--png", default="")
    ap.add_argument("-D", dest="defines", action="append", default=[])
    ap.add_argument("--profile", type=int, default=-1, help="a state (play): render_frame's cycles by routine")
    ap.add_argument("--edges", action="store_true", help="test sprites at the edges, all fine positions, flips, sizes, "
                    "the guards and 64 KB crossings (on play state 400's background)")
    ap.add_argument("--bench", action="store_true", help="the BENCH game's states (tools/states.py --bench) as 'play'")
    ap.add_argument("--profile-range", default="", help="A-B: every --every-th play state from A to B, the cycles by "
                    "routine summed")
    args = ap.parse_args()
    if args.profile_range:
        states = pickle.load(open(STATES if not args.bench else BUILD / "render_bench.pkl", "rb"))
        if args.bench:
            states = {"play": states["bench"]}
        a, b = map(int, args.profile_range.split("-"))
        h = Harness(args.defines)
        w = max(0, a - 30 * args.every)          # (30 pictures before, not counted: the colours chosen, the caches warm)
        h.put_state(states["play"][w])
        h.call("render_init")
        for k in range(w, a, args.every):
            h.put_state(states["play"][k])
            h.call("render_frame")
            h.call("render_vbl")
            h.call("render_vbl")          # (a second VBL: the buffer shown before is free again, REN_NBUF 2)
        tot = {}
        n = 0
        for k in range(a, b, args.every):
            h.put_state(states["play"][k])
            for name, c in h.profile("render_frame").items():
                tot[name] = tot.get(name, 0) + c
            h.call("render_vbl")
            h.call("render_vbl")          # (a second VBL: the buffer shown before is free again, REN_NBUF 2)
            n += 1
        allc = sum(tot.values())
        print("%d pictures, %dk cycles a picture" % (n, allc // n // 1000))
        for name, c in sorted(tot.items(), key=lambda x: -x[1])[:25]:
            print("%-24s %8dk a picture  %4.1f%%" % (name, c // n // 1000, 100 * c / allc))
        return 0
    if args.profile >= 0:
        states = pickle.load(open(STATES, "rb"))
        h = Harness(args.defines)
        h.put_state(states["play"][0])
        h.call("render_init")
        for k in range(args.profile + 1):
            h.put_state(states["play"][k])
            if k == args.profile:
                prof = h.profile("render_frame")
                for name, c in sorted(prof.items(), key=lambda x: -x[1])[:25]:
                    print("%-24s %9d" % (name, c))
                print("total", sum(prof.values()))
            else:
                h.call("render_frame")
            h.call("render_vbl")
            h.call("render_vbl")          # (a second VBL: the buffer shown before is free again, REN_NBUF 2)
        return 0
    states = pickle.load(open(STATES, "rb"))
    if args.bench:
        states = {"play": pickle.load(open(BUILD / "render_bench.pkl", "rb"))["bench"], "attract": []}
    if args.edges:
        h0 = Harness(args.defines)
        bufs = [h0.sym["ren_bufs"] + i * (288 + 64) * 160 for i in range(2)]
        base = states["play"][400]
        seq = [base] * 12 + edge_states(base, bufs)               # (12 pictures: the colours chosen first)
        states = {"play": seq, "attract": []}
        args.play, args.attract = "0-%d" % len(seq), ""
    pngs = {int(x) for x in args.png.split(",") if x}
    gfx()
    total_bad = 0
    for name in ("attract", "play"):
        idxs = parse_range(getattr(args, name), len(states[name]))[::args.every]
        if not idxs:
            continue
        h = Harness(args.defines)
        st0 = states[name][idxs[0]]
        h.put_state(st0)
        h.call("render_init")
        cyc = []
        classes = {}
        errs = []
        bad = black = 0
        for n, k in enumerate(idxs):
            st = states[name][k]
            h.put_state(st)
            ch0 = h.r32("ren_choices")
            c, b = h.call("render_frame")
            h.call("render_vbl")
            h.call("render_vbl")          # (a second VBL: the buffer shown before is free again, REN_NBUF 2)
            cyc.append(c + b)
            kind = "choice" if h.r32("ren_choices") != ch0 else "big" if c + b > 1500000 else "normal"
            classes.setdefault(kind, []).append(c + b)
            pic = h.shown()
            stepal = [h.mem.r16(h.sym["ren_vbl_pal"] + 2 * i) for i in range(16)]
            if not any(stepal):
                black += 1
                continue
            got = pic
            pens = stemodel.picture_wide(GFX, h.held(st), h.lock())[stemodel.CROP_TOP:stemodel.CROP_TOP + stemodel.SHOWN]
            want = mapped_index(h, pens)
            lv = lambda w, sh: (((w >> sh) & 7) << 1 | ((w >> (sh + 3)) & 1)) * 17
            rgb = np.array([[lv(w, 8), lv(w, 4), lv(w, 0)] for w in stepal], np.uint8)
            arc = np.stack([np.frombuffer(p, np.uint8) for p in st["pal"]], 1)
            want_rgb = np.where((pens < 0)[..., None], 0, arc[np.where(pens < 0, 0, pens)])
            from m72_assets import oklab
            errs.append(float(np.abs(oklab(rgb[got].astype(float)) - oklab(want_rgb.astype(float))).sum(-1).mean()))
            d = got != want
            if d.any():
                bad += 1
                if bad <= 8:
                    ys, xs = np.nonzero(d)
                    print("%s %d: %d pixels differ, first r %d c %d got %d want %d (pen %X)" % (
                        name, k, int(d.sum()), ys[0], xs[0], got[ys[0], xs[0]], want[ys[0], xs[0]], pens[ys[0], xs[0]]))
            if k in pngs:
                from PIL import Image
                ref = pens
                pal = np.vstack([np.stack([np.frombuffer(p, np.uint8) for p in st["pal"]], 1), np.zeros((1, 3), np.uint8)])
                W = stemodel.SCR_W
                im = np.zeros((got.shape[0], 2 * W + 8, 3), np.uint8)
                im[:, :W] = rgb[got]
                im[:, W + 8:] = pal[np.where(ref < 0, len(pal) - 1, ref)]
                Image.fromarray(im).resize((im.shape[1] * 2, im.shape[0] * 2), Image.NEAREST).save(BUILD / ("render_%s_%d.png" % (name, k)))
        cyc = sorted(cyc)
        print("   choices: new scenes %d, rested %d" % (h.r32("ren_ch_scene"), h.r32("ren_ch_rest")))
        print("%s: %d pictures, %d differ, %d black, %d colour choices; colour error %.4f; cycles a picture: median %dk, "
              "90%% %dk, max %dk (least %dk)" % (
                  name, len(idxs), bad, black, h.r32("ren_choices"), float(np.mean(errs)) if errs else 0,
                  cyc[len(cyc) // 2] // 1000, cyc[int(len(cyc) * 0.9)] // 1000, cyc[-1] // 1000, cyc[0] // 1000))
        tot = sum(cyc)
        print("   total %dM cycles: %s" % (tot // 1000000, ", ".join("%s %d pictures %dM (%d%%)" % (
            k, len(v), sum(v) // 1000000, 100 * sum(v) // max(tot, 1)) for k, v in sorted(classes.items()))))
        total_bad += bad
    return 1 if total_bad else 0


if __name__ == "__main__":
    sys.exit(main())
