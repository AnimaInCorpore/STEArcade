"""The STE renderer (src/render.s) against the reference picture, pixel by pixel.

    venv/bin/python games/galaga88/tools/render_test.py [--play A-B] [--attract A-B] [--every N] [--png N,..] [-D NAME=V]

render.s is assembled into a small harness (render.s, borders.s' blit_go, vio, the tile flags) and run on Musashi with
the simulator's Blitter.  The states come from the reference (tools/states.py: build/galaga88/render_states.pkl): per
state the harness gets vio (the C116 image, tile RAM, sprite RAM, CUS123 control; tile_written / tile_written_fix
when that part of tile RAM changed since the state before, as the translated writers would say), render_frame
draws, render_vbl shows; the shown buffer is read back and every pixel of the 288 x 224 picture must have the STE
index the renderer's mapping gives the reference's pen (tools/stemodel.py, checked against MAME's picture): black
is 0, any other colour (the palette when the colours were chosen, ren_palsnap, 4 bits a channel) the nearest of the
renderer's centres (ren_cent, Oklab bytes of assets.py ren_lab, L1, the first of equals); no pen: 0.  A picture
shown black (its palette all 0: a new scene waiting) is only counted.  The colour error: the Oklab distance of the
STE colour shown to the arcade's, the mean over the pictures' pixels.
The side bands (x < 48, x >= 272) must stay 0 in every line of the picture.  Cycles: Musashi's CPU cycles + the
Blitter's bus cycles, per picture.  --png: STE | reference into build/galaga88/render_N.png.
"""
import argparse
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

BUILD = build_dir("galaga88")
STATES = BUILD / "render_states.pkl"
VIO_SIZE = 0x28000
STRIDE, GUARD, PIC_H, PIC_W = 160, 32, 288, 224

HARNESS = r"""
; render.s alone, for tools/render_test.py
	section text,code
start:	clr.l	-(sp)
	move	#$20,-(sp)
	trap	#1
	addq	#6,sp
	lea	h_stack_top,sp
h_wait:	bra.s	h_wait
	include	"borders.s"
	borders_blit_go
	include	"render.s"
	section	bss,bss
	borders_vars
	even
tile_written:	ds.b	1
tile_written_fix:	ds.b	1
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
    tag = "ren_harness" + "".join("_" + d.replace("=", "") for d in sorted(defines))
    (BUILD / "ren_harness.s").write_text(HARNESS)
    obj, prg = BUILD / (tag + ".o"), BUILD / (tag + ".PRG")
    cmd = [VASM, "-Fvobj", "-quiet", "-nowarn=2047", "-I", str(BUILD), "-I", str(RT_INCLUDE), "-I",
           str(src_dir("galaga88")), "-DSIM=1", "-DTILE_FLAG=1"] + ["-D" + d for d in defines] + [
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
        old = self._vram
        v = st["vram"]
        if old is not None:
            if v[:0x7000] != old[:0x7000]:
                self.mem.w8(self.sym["tile_written"], 0xFF)
            if v[0x7000:] != old[0x7000:]:
                self.mem.w8(self.sym["tile_written_fix"], 0xFF)
        self._vram = v
        vio = self.sym["vio"]
        self.mem.w_block(vio, c116_image(st))
        self.mem.w_block(vio + 0x10000, v)
        self.mem.w_block(vio + 0x1C800, st["spriteram"])
        self.mem.w_block(vio + 0x1D000, st["control"])

    def shown(self):
        """(288 x 320 indices of the shown picture's lines, the buffer's base)"""
        base = self.r32("ren_vbase") - (GUARD + self.cropped()) * STRIDE
        raw = np.frombuffer(bytes(self.mem.r_block(base + GUARD * STRIDE, PIC_H * STRIDE)), ">u2").reshape(PIC_H, 20, 4)
        bits = np.unpackbits(raw.view(np.uint8).reshape(PIC_H, 20, 4, 2), axis=3).reshape(PIC_H, 20, 4, 16)
        idx = (bits * (1 << np.arange(4))[None, None, :, None]).sum(2)     # plane p = bit p
        return idx.reshape(PIC_H, 320)

    def cropped(self):
        return self.sym.get("CROP_TOP_VALUE", 0)


LAB = None


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
    args = ap.parse_args()
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
        return 0
    states = pickle.load(open(STATES, "rb"))
    pngs = {int(x) for x in args.png.split(",") if x}
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
        errs = []
        bad = black = 0
        for n, k in enumerate(idxs):
            st = states[name][k]
            h.put_state(st)
            c, b = h.call("render_frame")
            h.call("render_vbl")
            cyc.append(c + b)
            pic = h.shown()
            band = np.concatenate([pic[:, :48], pic[:, 272:]], 1)
            if band.any():
                bad += 1
                ys, xs = np.nonzero(band)
                print("%s %d: the side bands are not clean (row %d)" % (name, k, ys[0]))
                continue
            stepal = [h.mem.r16(h.sym["ren_vbl_pal"] + 2 * i) for i in range(16)]
            if not any(stepal):
                black += 1
                continue
            got = pic[:, 48:272]
            pens, src = stemodel.ste_pens(st)
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
                    s = src[ys[0], xs[0]]
                    print("%s %d: %d pixels differ, first r %d c %d got %d want %d (pen %d, %s)" % (
                        name, k, int(d.sum()), ys[0], xs[0], got[ys[0], xs[0]], want[ys[0], xs[0]], pens[ys[0], xs[0]],
                        "sprite %d" % (s - 100) if s >= 100 else "layer %d" % s))
            if k in pngs:
                from PIL import Image
                ref = stemodel.reference(st)
                pal = np.vstack([np.stack([np.frombuffer(p, np.uint8) for p in st["pal"]], 1), np.zeros((1, 3), np.uint8)])
                im = np.zeros((PIC_H, 2 * PIC_W + 8, 3), np.uint8)
                im[:, :PIC_W] = rgb[got]
                im[:, PIC_W + 8:] = pal[np.where(ref < 0, len(pal) - 1, ref)]
                Image.fromarray(im).resize((im.shape[1] * 2, PIC_H * 2), Image.NEAREST).save(BUILD / ("render_%s_%d.png" % (name, k)))
        cyc = sorted(cyc)
        print("%s: %d pictures, %d differ, %d black, %d colour choices; colour error %.4f; cycles a picture: median %dk, "
              "90%% %dk, max %dk (least %dk)" % (
                  name, len(idxs), bad, black, h.r32("ren_choices"), float(np.mean(errs)) if errs else 0,
                  cyc[len(cyc) // 2] // 1000, cyc[int(len(cyc) * 0.9)] // 1000, cyc[-1] // 1000, cyc[0] // 1000))
        total_bad += bad
    return 1 if total_bad else 0


if __name__ == "__main__":
    sys.exit(main())
