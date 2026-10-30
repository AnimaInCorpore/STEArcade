"""R-Type's stage renderer (src/stage.s) against tools/stage_model.py, on Musashi (engine/sim.py, its Blitter model).

    venv/bin/python games/rtype/tools/stage_test.py STATES.pkl [--frames A-B] [--every N] [--png F,..]
                    [--quiet] [--stop N] [-D NAME=V]

STATES.pkl: tools/logic_test.py --record (the video state and the object records the program hands the renderer, every
arcade frame).  stage.s is assembled alone into a harness with the program's variables (the V30 image's video part,
v30_vmarks, m72_objs, the scroll registers, the raster line, port $02).  Per state (every Nth: a picture every N arcade
frames) the harness gets the state - the blocks that changed since the last one marked, as the translated stores mark
them -, m72r_frame draws, m72r_vbl shows; the picture is read back as the Shifter shows it (the published address,
the fine scroll, 512-byte lines; the status bar's lines from its image) and compared index for index with the model's
picture through the colour tables of the scene the renderer picks (tools/stage_assets.py scenes).  Cycles: m72r_frame's CPU + Blitter bus cycles.
"""
import argparse
import pickle
import subprocess
import sys
import zlib
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / "engine")]
from paths import VASM, VLINK, RT_INCLUDE, build_dir, src_dir
from machine68k import Register as R
from sim import Sim, TRAP1
import m72
import stage_model as SM

HARNESS = r"""
; src/stage.s alone, for tools/stage_test.py
	section text,code
start:	clr.l	-(sp)
	move	#$20,-(sp)
	trap	#1
	addq	#6,sp
	lea	h_stack_top,sp
h_wait:	bra.s	h_wait
	include	"stage.s"
	section	bss,bss
	even
v30_image:	ds.b	$E0000
v30_vmarks:	ds.b	$180
m72_objs:	ds.b	$400
m72_objs_end:	ds.w	1
m72_scroll:	ds.w	4
m72_scroll_vbl:	ds.w	4
m72_raster:	ds.w	1
m72_port02:	ds.w	1
h_stack:	ds.b	8192
h_stack_top:
"""
LB = 512
G = 64


def swap(b):
    a = bytearray(b)
    a[0::2], a[1::2] = b[1::2], b[0::2]
    return bytes(a)


def build(defines):
    out = build_dir("rtype")
    tag = "stage_harness" + "".join("_" + d.replace("=", "") for d in sorted(defines))
    (out / (tag + ".s")).write_text(HARNESS)
    obj, prg, mp = out / (tag + ".o"), out / (tag + ".PRG"), out / (tag + ".map")
    cmd = [VASM, "-Fvobj", "-quiet", "-nowarn=2047", "-I", str(out), "-I", str(RT_INCLUDE), "-I", str(src_dir("rtype")),
           "-DSIM=1"] + ["-D" + d for d in defines] + ["-o", str(obj), str(out / (tag + ".s"))]
    for step in (cmd, [VLINK, "-b", "ataritos", "-s", "-o", str(prg), "-M" + str(mp), str(obj)]):
        r = subprocess.run(step, capture_output=True, text=True)
        if r.returncode:
            sys.exit(r.stdout + r.stderr)
    return prg, mp


class Harness:
    def __init__(self, defines=()):
        prg, mp = build(defines)
        self.s = Sim(str(prg), ram_kib=16384, run_dir=build_dir("rtype"))
        self.sym = {k: v + self.s.base for k, v in self.s.symbols(mp).items()}
        self.mem, self.cpu = self.s.mem, self.s.cpu
        self.run_to(self.sym["h_wait"])
        self.prev = None
        self.put_state_init = True

    def run_to(self, stop, limit=4_000_000_000):
        total = 0
        while total < limit:
            total += self.cpu.execute(5000).cycles
            pc = self.cpu.r_pc()
            if pc == stop:
                return total
            if pc == TRAP1:
                self.s.gemdos()
            elif pc == 0x600:
                raise RuntimeError("exception at %s" % self.near(self.mem.r32(self.cpu.r_reg(R.A7) + 2)))
        raise RuntimeError("timeout at %s" % self.near(self.cpu.r_pc()))

    def near(self, a):
        best = max(((v, k) for k, v in self.sym.items() if v <= a and v >= self.s.base), default=(0, "?"))
        return "%s+%X" % (best[1], a - best[0])

    def call(self, name):
        sp = self.cpu.r_reg(R.A7) - 4
        self.mem.w32(sp, self.sym["h_wait"])
        self.cpu.w_reg(R.A7, sp)
        self.cpu.w_pc(self.sym[name])
        self.s.blitter.cycles = 0
        c = self.run_to(self.sym["h_wait"])
        return c, self.s.blitter.cycles

    def r16(self, name, off=0):
        return self.mem.r16(self.sym[name] + off)

    def r32(self, name, off=0):
        return self.mem.r32(self.sym[name] + off)

    def put_state(self, st):
        img = self.sym["v30_image"]
        marks = bytearray(0x180)
        for base, key in ((0xC8000, "pal0"), (0xCC000, "pal1"), (0xD0000, "fg"), (0xD8000, "bg")):
            data = st[key]
            old = self.prev[key] if self.prev else None
            for b in range(len(data) // 256):
                if old is None or data[256 * b:256 * b + 256] != old[256 * b:256 * b + 256]:
                    marks[((base - 0xC8000) >> 8) + b] = 0xFF
            self.mem.w_block(img + base, swap(data))
        m = bytes(self.mem.r_block(self.sym["v30_vmarks"], 0x180))
        self.mem.w_block(self.sym["v30_vmarks"], bytes(a | b for a, b in zip(m, marks)))
        self.mem.w_block(self.sym["m72_objs"], st["objs"])
        self.mem.w16(self.sym["m72_objs_end"], st["objs_end"])
        bands = st["bands"]
        y0, y1, sx, sy, off = bands[0]
        for k, v in enumerate((sy[0], sx[0], sy[1], sx[1])):
            self.mem.w16(self.sym["m72_scroll_vbl"] + 2 * k, v & 0xFFFF)
            self.mem.w16(self.sym["m72_scroll"] + 2 * k, v & 0xFFFF)
        if len(bands) > 1:
            y0, y1, sx, sy, off = bands[1]
            for k, v in enumerate((sy[0], sx[0], sy[1], sx[1])):
                self.mem.w16(self.sym["m72_scroll"] + 2 * k, v & 0xFFFF)
            self.mem.w16(self.sym["m72_raster"], (y0 - 1 + 128) & 0xFFFF)
        else:
            self.mem.w16(self.sym["m72_raster"], 0)
        self.mem.w16(self.sym["m72_port02"], 8 if off else 0)
        self.prev = st

    def frame(self):
        before = self.r32("m72r_pictures")
        c, b = self.call("m72r_frame")
        if self.r32("m72r_pictures") == before:
            return None
        self.call("m72r_vbl")
        self.call("m72r_vbl")
        return c, b

    def planar(self, addr, lines, lb, words):
        raw = np.frombuffer(bytes(self.mem.r_block(addr, lines * lb)), np.uint8).reshape(lines, lb)[:, :words * 8]
        raw = raw.reshape(lines, words, 4, 2)
        w = (raw[..., 0].astype(np.uint16) << 8) | raw[..., 1]
        out = np.zeros((lines, words * 16), np.uint8)
        for p in range(4):
            for b in range(16):
                out[:, b::16] |= (((w[:, :, p] >> (15 - b)) & 1).astype(np.uint8) << p)
        return out

    def screen(self):
        d = self.r16("m72r_shown")
        addr = self.r32("m72r_disp_addr", 4 * d)
        fine = self.mem.r8(self.sym["m72r_disp_fine"] + d)
        out = self.planar(addr, 256, LB, 21)[:, fine:fine + 320]
        bot = self.r16("m72r_disp_hud", 4 * d + 2)
        if bot < 256:
            bar = self.r32("m72r_disp_bar", 4 * d)
            out[bot:] = self.planar(bar, 256 - bot, 160, 20)
        return out, bot


class Expected:
    """the model's picture in STE indices: the scene the renderer picks (tools/stage_assets.py choose_scene, when a
    tile pen's colour changed), its colour tables at the pens' current colours, its reserved pens"""
    def __init__(self):
        import stage_assets as SA
        self.SA = SA
        self.scenes = SA.load_scenes()
        self.model, self.lock = SM.Model(), SM.Lock()
        self.cur, self.tiles = None, None

    def __call__(self, st):
        col = self.SA.pen_colours(st)
        if self.tiles is None or (col[256:] != self.tiles).any():
            self.cur = self.SA.choose_scene(col[256:], [sc[0] for sc in self.scenes], self.cur)
            self.tiles = col[256:].copy()
        ref, pal, hpal, ctab, htab, res, flags = self.scenes[self.cur]
        pens = self.model.picture(st, self.lock, squeeze=bool(flags & 1), tile_dx=flags >> 8)
        pidx = ctab[col].copy()
        for j, rp in enumerate(res):
            pidx[rp] = 16 - len(res) + j
        hidx = htab[col]
        bar = any(b[0] == SM.HUD_Y for b in st["bands"])
        pp = np.minimum(pens, 511)
        want = pidx[pp]
        if bar:
            want[SM.HUD_Y:] = hidx[pp[SM.HUD_Y:]]
        want[pens == 512] = 0
        return want


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("states")
    ap.add_argument("--frames", default="")
    ap.add_argument("--every", type=int, default=2)
    ap.add_argument("--png", default="")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--stop", type=int, default=3)
    ap.add_argument("-D", dest="defines", action="append", default=[])
    args = ap.parse_args()
    states = [(i, it) for i, (_, it) in enumerate(pickle.load(open(args.states, "rb")))]
    if args.frames:
        a, b = (int(x) for x in args.frames.split("-"))
        states = [s for s in states if a <= s[0] <= b]
    states = states[::args.every]
    h = Harness(args.defines)
    c0 = h.call("m72r_init")
    print("init: %d cycles" % sum(c0))
    expected = Expected()
    pngs = {int(x) for x in args.png.split(",") if x}
    costs, fails = [], 0
    for f, item in states:
        st = pickle.loads(zlib.decompress(item))
        h.put_state(st)
        r = h.frame()
        want = expected(st)
        if r is None:
            print("%d: no buffer free" % f)
            continue
        got, bot = h.screen()
        diff = got != want
        bad = int(diff.sum())
        costs.append((f, r[0], r[1]))
        unk = h.r32("st_unknown")
        if bad or not args.quiet or f in pngs:
            print("%5d: %s, CPU %7d + Blitter %6d%s" % (f, "exact" if not bad else "%d pixels DIFFER (lines %d-%d)" % (
                bad, np.nonzero(diff.any(1))[0].min(), np.nonzero(diff.any(1))[0].max()), r[0], r[1],
                ", unknown definitions so far %d" % unk if unk else ""), flush=True)
        if bad or f in pngs:
            from PIL import Image
            lut = np.array([[i * 16] * 3 for i in range(16)], np.uint8)
            img = np.hstack([lut[got], lut[want], np.where(diff[..., None], np.array([255, 0, 255], np.uint8),
                                                             lut[got])])
            o = build_dir("rtype") / ("stage_test_%d.png" % f)
            Image.fromarray(img).resize((img.shape[1] * 2, img.shape[0] * 2), Image.NEAREST).save(o)
            print("   ", o)
        fails += bad != 0
        if args.stop and fails >= args.stop:
            break
    if costs:
        tot = np.array([c[1] + c[2] for c in costs])
        print("%d pictures: cycles (CPU + Blitter) median %d, 10%% %d, 90%% %d, max %d (frame %d)" % (
            len(tot), np.median(tot), np.percentile(tot, 10), np.percentile(tot, 90), tot.max(),
            costs[int(tot.argmax())][0]))
    print("FAIL" if fails else "PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
