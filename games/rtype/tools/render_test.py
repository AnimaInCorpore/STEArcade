"""The STE renderer of the Irem M72 games (engine/rt/m72render.s, included by games/<game>/src/render.s) against the
reference picture (engine/m72.py, equal to MAME).

    venv/bin/python games/rtype/tools/render_test.py [--game rtype|mrheli] [--set attract|play] [--frames A-B]
                    [--every N] [--png F,F,..] [--alldirty] [--quiet] [--stop N] [-D NAME=V]

render.s is assembled into a small harness (build/<game>/m72_harness.s) and run on Musashi (engine/sim.py, its Blitter
model).  The arcade states come from the reference board (engine/m72board.py from power-on; `attract`: no input,
`play`: a coin at frame 400, start, random input with the Invulnerability switch, the fire button held so the stages go
by), recorded once into build/<game>/render_states.pkl: per frame the video RAMs, the sprite buffer, the palettes, the
bands of MAME's partial updates (m72board frame_bands: the scroll registers and the display-off bit of each).

For each state the harness gets the video state (`m72v`), m72r_frame draws, m72r_vbl shows; the picture is read back as
the Shifter shows it (the published address, the fine scroll, 512-byte lines, 320 pixels) and compared with the
reference:

  * exact: every pixel's STE index must be the renderer's own mapping of the reference's pen (m72r_pidx; the tile pens
    of the HUD bars' lines through m72r_hidx; the black of a display-off band index 0).  The accepted difference is 0
    pixels.  The mapping itself is checked too: each pen's index is the nearest of the renderer's centres (Oklab L1 of
    the pen's colour at the STE's 4 bits a channel), black is 0.
  * the reference is drawn from the port's input: each band's scroll registers and display bit, the video RAMs and
    the sprite buffer at the frame's end (the STE draws once a picture).  MAME's own bands may also see video RAM
    writes made during the frame (a band drawn before the write): the pixels this changes are counted apart
    ("mid-frame VRAM") and are not a renderer error.
  * the colour error: the Oklab distance of the STE colour shown to the arcade's colour, mean over the window (and over
    the saturated pixels, chroma > 0.08).
  * the cycles of each picture: Musashi's CPU cycles + the Blitter's bus cycles (m72r_frame only: the game logic is
    apart).

--every N: every Nth recorded frame (a picture every N arcade frames: more changes between a buffer's pictures, as when
the STE draws a picture every few frames).  --alldirty: every video RAM row marked changed.  The sprites at the window's
edges, in all shifts, flipped, with holes, in the guard lines, across 64 KB boundaries: tools/sprite_test.py.
"""
import argparse
import pickle
import random
import subprocess
import sys
import zlib
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / "engine")]
from paths import VASM, VLINK, RT_INCLUDE, build_dir, src_dir
from machine68k import Register as R
from sim import Sim, TRAP1
import m72
import m72_assets

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
h_stack:	ds.b	8192
h_stack_top:
"""

G = 16
LB = 512


def harness_tag(defines):
    return "m72_harness" + "".join("_" + d.replace("=", "") for d in sorted(defines))


def build_harness(game, defines=()):
    out = build_dir(game)
    m72_assets.build(game, out)
    if not (out / "m72_pal.bin").exists():
        import m72_palettes
        m72_palettes.build(game, out)
    tag = harness_tag(defines)
    m72_assets.write(out / "m72_harness.s", HARNESS.encode())     # (atomic: parallel test runs build too)
    obj = out / (tag + ".o")
    prg = out / (tag + ".PRG")
    cmd = [VASM, "-Fvobj", "-quiet", "-nowarn=2047", "-I", str(out), "-I", str(RT_INCLUDE), "-I", str(src_dir(game)),
           "-DSIM=1"] + ["-D" + d for d in defines] + ["-o", str(obj), str(out / "m72_harness.s")]
    for step in (cmd, [VLINK, "-b", "ataritos", "-s", "-o", str(prg), "-M" + str(out / (tag + ".map")), str(obj)]):
        r = subprocess.run(step, capture_output=True, text=True)
        if r.returncode:
            sys.exit(r.stdout + r.stderr)
        if "warning" in r.stdout + r.stderr:
            print(r.stdout + r.stderr)
    return prg, out / (tag + ".map")


class Harness:
    def __init__(self, game, defines=()):
        self.game = game
        prg, mapfile = build_harness(game, defines)
        self.s = Sim(str(prg), ram_kib=16384, run_dir=build_dir(game))
        self.sym = {k: v + self.s.base for k, v in self.s.symbols(mapfile).items()}
        self.mem, self.cpu = self.s.mem, self.s.cpu
        self.run_to(self.sym["h_wait"])
        self.call("m72r_init")
        self.prev = None

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
            elif pc == 0x600:
                sp = self.cpu.r_reg(R.A7)
                words = [self.mem.r16(sp + 2 * k) for k in range(8)]
                pc6 = (words[1] << 16) | words[2]
                pc14 = (words[5] << 16) | words[6]
                raise RuntimeError("exception: stack %s; as a 6-byte frame pc %s, as a 14-byte frame (address %08X) "
                                   "pc %s" % (" ".join("%04X" % w for w in words), self.near(pc6),
                                              (words[1] << 16) | words[2], self.near(pc14)))
        raise RuntimeError("timeout at %s" % self.near(self.cpu.r_pc()))

    def near(self, a):
        best = max(((v, k) for k, v in self.sym.items() if v <= a and not k.isupper() and v >= self.s.base),
                   default=(0, "?"))
        return "%s+%X" % (best[1], a - best[0])

    def call(self, name):
        """the routine to its rts: (CPU cycles, Blitter bus cycles)"""
        sp = self.cpu.r_reg(R.A7) - 4
        self.mem.w32(sp, self.sym["h_wait"])
        self.cpu.w_reg(R.A7, sp)
        self.cpu.w_pc(self.sym[name])
        self.s.blitter.cycles = 0
        c = self.run_to(self.sym["h_wait"])
        return c, self.s.blitter.cycles

    def profile(self, name, step=1):
        """the routine run instruction by instruction: cycles by the nearest code label before the pc"""
        import bisect
        labels = sorted((v, k) for k, v in self.sym.items() if not k.startswith(".") and not k.isupper())
        addrs = [v for v, k in labels]
        sp = self.cpu.r_reg(R.A7) - 4
        self.mem.w32(sp, self.sym["h_wait"])
        self.cpu.w_reg(R.A7, sp)
        self.cpu.w_pc(self.sym[name])
        out = {}
        stop = self.sym["h_wait"]
        while True:
            pc = self.cpu.r_pc()
            if pc == stop:
                break
            i = bisect.bisect_right(addrs, pc) - 1
            self.s.blitter.cycles = 0
            c = self.cpu.execute(step).cycles + self.s.blitter.cycles
            k = labels[i][1]
            out[k] = out.get(k, 0) + c
        return out

    def r8(self, name, off=0):
        return self.mem.r8(self.sym[name] + off)

    def r16(self, name, off=0):
        return self.mem.r16(self.sym[name] + off)

    def s16(self, name, off=0):
        v = self.r16(name, off)
        return v - 0x10000 if v & 0x8000 else v

    def r32(self, name, off=0):
        return self.mem.r32(self.sym[name] + off)

    def block(self, addr, n):
        return np.frombuffer(bytes(self.mem.r_block(addr, n)), np.uint8)

    def put_state(self, st, alldirty=False):
        """the video state into m72v; the dirty marks of what changed since the last state"""
        prev = self.prev
        w = self.mem.w_block
        w(self.sym["m72v_fg"], st["fg"])
        w(self.sym["m72v_bg"], st["bg"])
        w(self.sym["m72v_spr"], st["spr"])
        w(self.sym["m72v_pal0"], st["pal0"])
        w(self.sym["m72v_pal1"], st["pal1"])
        bands = st["bands"]
        self.mem.w16(self.sym["m72v_nbands"], len(bands))
        for i, (y0, y1, sx, sy, off) in enumerate(bands):
            for k, v in enumerate((y0, sy[0], sx[0], sy[1], sx[1], 1 if off else 0)):
                self.mem.w16(self.sym["m72v_bands"] + 12 * i + 2 * k, v & 0xFFFF)
        dirty = bytearray(128)
        for n, key in enumerate(("fg", "bg")):
            for r in range(64):
                if alldirty or prev is None or st[key][256 * r:256 * r + 256] != prev[key][256 * r:256 * r + 256]:
                    dirty[64 * n + r] = 0xFF
        w(self.sym["m72v_vdirty"], bytes(dirty))
        if prev is None or st["pal0"] != prev["pal0"] or st["pal1"] != prev["pal1"]:
            self.mem.w8(self.sym["m72v_pdirty"], 0xFF)
            if prev is not None and "m72v_pdblk" in self.sym:    # (the blocks written, as the program marks them)
                for n, key in enumerate(("pal0", "pal1")):
                    for b in range(12):
                        if st[key][256 * b:256 * b + 256] != prev[key][256 * b:256 * b + 256]:
                            self.mem.w8(self.sym["m72v_pdblk"] + 12 * n + b, 0xFF)
        self.prev = st

    def frame(self):
        """m72r_frame (again while it leaves conversions for the next call: a new scene) + m72r_vbl: (CPU cycles,
        Blitter cycles) of all the calls; self.calls, self.callmax: the calls, the longest call (CPU + Blitter); None
        when no buffer was free"""
        before = self.r32("m72r_pictures")
        c = b = 0
        self.calls, self.callmax = 0, 0
        while self.calls < 64:
            late = self.r32("m72r_lates")
            c1, b1 = self.call("m72r_frame")
            c, b = c + c1, b + b1
            self.calls += 1
            self.callmax = max(self.callmax, c1 + b1)
            if self.r32("m72r_lates") == late:
                break
        if self.r32("m72r_pictures") == before:
            return None
        self.call("m72r_vbl")           # (the flip)
        self.call("m72r_vbl")           # (a VBL without one: the buffer shown before is free again)
        return c, b

    # ---- the picture as the Shifter shows it ----
    def shown(self):
        d = self.r16("m72r_shown")
        return self.r32("m72r_disp_addr", 4 * d), self.r8("m72r_disp_fine", d)

    def screen(self, addr=None, fine=None, lines=(0, 256), width=320):
        if addr is None:                # the picture shown: the playfield, the status bar's lines from its own buffer
            addr, fine = self.shown()
            out = self.screen(addr, fine, lines, width)
            if lines == (0, 256):
                d = self.r16("m72r_shown")
                top, bot = self.r16("m72r_disp_hud", 4 * d), self.r16("m72r_disp_hud", 4 * d + 2)
                bar = self.r32("m72r_disp_bar", 4 * d)
                if top > 0:
                    out[:top] = self.screen(bar, 0, (0, top), width)
                elif bot < 256:
                    out[bot:] = self.screen(bar, 0, (0, 256 - bot), width)
            return out
        y0, y1 = lines
        n = y1 - y0
        raw = self.block(addr + y0 * LB, n * LB).reshape(n, LB)[:, :21 * 8].reshape(n, 21, 4, 2)
        words = (raw[..., 0].astype(np.uint16) << 8) | raw[..., 1]
        out = np.zeros((n, 21 * 16), np.uint8)
        for p in range(4):
            for b in range(16):
                out[:, b::16] |= (((words[:, :, p] >> (15 - b)) & 1).astype(np.uint8) << p)
        return out[:, fine:fine + width]

    def buffer(self, b):
        """a whole buffer as indices [288, 1024]"""
        base = self.r32("m72r_buf", 4 * b)
        raw = self.block(base, 288 * LB).reshape(288, 64, 4, 2)
        words = (raw[..., 0].astype(np.uint16) << 8) | raw[..., 1]
        out = np.zeros((288, 1024), np.uint8)
        for p in range(4):
            for bb in range(16):
                out[:, bb::16] |= (((words[:, :, p] >> (15 - bb)) & 1).astype(np.uint8) << p)
        return out

    def palette(self, hud=False):
        d = self.r16("m72r_shown")
        words = [self.r16("m72r_disp_hpal" if hud else "m72r_disp_pal", 32 * d + 2 * i) for i in range(16)]
        lv = lambda n: (((n & 7) << 1) | (n >> 3)) * 17
        return np.array([[lv((w >> 8) & 15), lv((w >> 4) & 15), lv(w & 15)] for w in words], np.uint8)

    def hud_lines(self):
        d = self.r16("m72r_shown")
        top, bot = self.r16("m72r_disp_hud", 4 * d), self.r16("m72r_disp_hud", 4 * d + 2)
        rows = np.zeros(256, bool)
        rows[:top] = True
        rows[bot:] = True
        return rows

    def mapping(self):
        return (self.block(self.sym["m72r_pidx"], 512).astype(np.int32),
                self.block(self.sym["m72r_hidx"], 512).astype(np.int32))


# ---- the arcade states ----
def press(m, f, rng, state):
    """the play inputs (IN0 active low: right 1 left 2 down 4 up 8, button 2 $40, button 1 $80 (fire); IN1: start 1
    bit 0, coin 1 bit 2): a coin at 400, start at 460, random moves and the fire button mostly held"""
    in1 = 0xFFFF
    if 400 <= f < 404:
        in1 &= ~0x04
    if 460 <= f < 466:
        in1 &= ~0x01
    m.in1 = in1
    if f < 520:
        m.in0 = 0xFFFF
        return
    if state["hold"] <= 0:
        bits = rng.choice([0, 1, 2, 4, 8, 5, 9, 6, 10, 0x01, 0x01, 0x40])
        if rng.random() < 0.7:
            bits |= 0x80
        state["bits"] = bits
        state["hold"] = rng.randint(2, 60)
    state["hold"] -= 1
    bits = state["bits"]
    if bits & 0x80 and f % 90 == 0:
        bits &= ~0x80
    m.in0 = 0xFFFF & ~bits


def record(game, kind, frames, every=1, start=0, seed=9):
    """[(frame, zlib(pickle(state)))]: state = fg, bg, spr, pal0, pal1, bands [(y0, y1, (sxF, sxB), (syF, syB), off)],
    mame (MAME's own bands: [(y0, y1, fg, bg)] when the video RAM differs between them)"""
    import m72board
    b = m72board.M72(game)
    if kind == "play":
        b.dsw &= ~0x4000                # (Invulnerability: the stages go by)
    rng = random.Random(seed)
    hold = dict(hold=0, bits=0)
    out = []
    for f in range(frames):
        if kind == "play":
            press(b, f, rng, hold)
        else:
            b.in0, b.in1 = 0xFFFF, 0xFFFF
        b.run_frame()
        if f < start or (f - start) % every:
            continue
        fb = b.frame_bands
        last = fb[-1][2]
        st = dict(fg=bytes(last.fg), bg=bytes(last.bg), spr=bytes(last.sprites), pal0=bytes(b.palette[0]),
                  pal1=bytes(b.palette[1]),
                  bands=[(y0, y1, tuple(s.scrollx), tuple(s.scrolly), bool(s.video_off)) for y0, y1, s in fb])
        if any(s.fg != last.fg or s.bg != last.bg or s.sprites != last.sprites for _, _, s in fb):
            st["mame"] = [(y0, y1, bytes(s.fg), bytes(s.bg), bytes(s.sprites)) for y0, y1, s in fb]
        out.append((b.frame, zlib.compress(pickle.dumps(st), 1)))
    return out


SETS = {"attract": (6000, 1, 0), "play": (7000, 1, 300)}


def load_states(game, which):
    path = build_dir(game) / "render_states.pkl"
    have = pickle.loads(path.read_bytes()) if path.exists() else {}
    if which not in have:
        frames, every, start = SETS[which]
        print("recording the reference board's %s states (%d frames, a few minutes, once) ..." % (which, frames),
              flush=True)
        have[which] = record(game, which, frames, every, start)
        path.write_bytes(pickle.dumps(have))
    return have[which]


_video = {}


def reference(game, st, mame=False):
    """the window's pens [256, 320] (512 = black) as the port draws it: the bands' registers, the frame's end video RAM
    and sprites (mame: MAME's own bands with their video RAM)"""
    if game not in _video:
        _video[game] = m72.Video(game)
    v = _video[game]
    if mame and "mame" in st:
        bands = []
        for (y0, y1, sx, sy, off), (_, _, fg, bg, spr) in zip(st["bands"], st["mame"]):
            bands.append((y0, y1, m72.VideoState(fg, bg, spr, sx, sy, off)))
    else:
        bands = [(y0, y1, m72.VideoState(st["fg"], st["bg"], st["spr"], sx, sy, off))
                 for y0, y1, sx, sy, off in st["bands"]]
    return v.render_raw(bands)[:, 96:416]


GROSS, GROSS_GAP, GROSS_PART, GROSS_REST = 0.2, 0.1, 0.01, 3


def check(h, game, st, name, png=False):
    """(differing pixels, mid-frame VRAM pixels, colour error, saturated error, notes)"""
    pens = reference(game, st)
    got = h.screen()
    pidx, hidx = h.mapping()
    hud = h.hud_lines()
    p = np.clip(pens, 0, 511)
    want = np.where(hud[:, None] & (pens >= 256), hidx[p], pidx[p])
    want = np.where(pens == 512, 0, want)
    diff = got != want
    notes = []
    hs = int(np.count_nonzero(hud[:, None] & (pens < 256)))
    if hs:                              # (sprite pixels map through m72r_pidx: shown with the HUD palette they are wrong)
        notes.append("%d sprite pixels in the HUD bars' lines" % hs)
    # (the mapping itself is not checked: the colours shown are, below)
    # mid-frame VRAM writes: MAME's picture differs from the port's input there
    mid = 0
    if "mame" in st:
        mid = int(np.count_nonzero(reference(game, st, mame=True) != pens))
    # the colour error
    pal = m72.pens(st["pal0"], st["pal1"])
    rgb = pal[np.minimum(pens, 512)].astype(float)
    shown = np.where(hud[:, None, None], h.palette(True)[got], h.palette()[got]).astype(float)
    la, lb = m72_assets.oklab(shown), m72_assets.oklab(rgb)
    e = np.sqrt(((la - lb) ** 2).sum(-1))
    sat = np.hypot(lb[..., 1], lb[..., 2]) > 0.08
    # gross colour errors: a pixel shown GROSS or more (Oklab) from its colour while an index of its palette (the
    # playfield's or the HUD bar's, the colours shown) is GROSS_GAP closer: a representative pen whose colour is not
    # the colour of the pens it stands for (the shown colours, not the mapping, are checked here)
    gross = 0
    for rows, pw in ((~hud, h.palette()), (hud, h.palette(True))):
        if not rows.any():
            continue
        lp = m72_assets.oklab(pw.astype(float))                          # 16 x 3
        best = np.sqrt(((lb[rows][:, :, None, :] - lp[None, None]) ** 2).sum(-1)).min(-1)
        er = e[rows]
        g = (er >= GROSS) & (er - best >= GROSS_GAP) & (pens[rows] < 512)
        gross += int(np.count_nonzero(g))
        if g.any():
            ys, xs = np.nonzero(g)
            yl = np.nonzero(rows)[0][ys]
            bad_pens = sorted(set(int(v) for v in pens[rows][g]))[:8]
            # a failure from GROSS_PART of the region's pixels on (a whole index shown wrong: a HUD label, a sprite's
            # colour); fewer (a colour-cycling pen between remaps) are reported only
            n = int(g.sum())
            notes.append("%s%d pixels in %s shown GROSSLY wrong (lines %d-%d, pens %s)" % (
                "" if n >= GROSS_PART * int(rows.sum()) * pens.shape[1] else "(info) ", n,
                "the HUD bars" if rows is hud else "the playfield", yl.min(), yl.max(), bad_pens))
    if png or diff.any():
        from PIL import Image
        a = shown.astype(np.uint8)
        b = rgb.astype(np.uint8)
        c = np.where(diff[..., None], np.array([255, 0, 255], np.uint8), a)
        img = np.hstack([a, b, c])
        Image.fromarray(img).resize((img.shape[1] * 2, img.shape[0] * 2), Image.NEAREST).save(
            build_dir(game) / ("render_%s.png" % name))
    return int(np.count_nonzero(diff)), mid, float(e.mean()), float(e[sat].mean()) if sat.any() else 0.0, notes


def run_sequence(h, game, states, label, png_at=(), alldirty=False, verbose=True, stop_after=None):
    costs = []
    fails = 0
    rest, prevpal = 0, None
    for f, item in states:
        st = pickle.loads(zlib.decompress(item))
        pal = (bytes(st["pal0"]), bytes(st["pal1"]))
        rest = rest + 1 if pal == prevpal else 0       # (pictures the palette has rested: gross colour errors
        prevpal = pal                                   # while it changes are the choices' lag, reported only)
        h.put_state(st, alldirty)
        r = h.frame()
        if r is None:
            print("%s %d: no buffer free" % (label, f))
            continue
        bad, mid, err, sat, notes = check(h, game, st, "%s_%d" % (label, f), png=f in png_at)
        if rest < GROSS_REST:
            notes = [("(transient) " + n) if "GROSSLY" in n and not n.startswith("(") else n for n in notes]
        costs.append((f, r[0], r[1], h.calls, h.callmax))
        if verbose or bad or notes:
            print("%s %5d: %s, CPU %7d + Blitter %6d cycles%s, colour error %.4f (saturated %.4f)%s%s" % (
                label, f, "exact" if not bad else "%d pixels DIFFER" % bad, r[0], r[1],
                " (%d calls, the longest %d)" % (h.calls, h.callmax) if h.calls > 1 else "", err, sat,
                ", mid-frame VRAM %d px" % mid if mid else "", "; " + "; ".join(notes) if notes else ""), flush=True)
        fails += (bad != 0) + bool([n for n in notes if not n.startswith("(")])
        if stop_after and fails >= stop_after:
            break
    return fails, costs


def summary(label, costs):
    if not costs:
        return
    tot = np.array([c[1] + c[2] for c in costs])
    cpu = np.array([c[1] for c in costs])
    print("%s: the longest call %d cycles; pictures that took more than one call: %d" % (
        label, max(c[4] for c in costs), sum(1 for c in costs if c[3] > 1)))
    print("%s: %d pictures, cycles (CPU + Blitter) median %d (CPU %d), 10%% %d, 90%% %d, max %d (frame %d)" % (
        label, len(tot), np.median(tot), np.median(cpu), np.percentile(tot, 10), np.percentile(tot, 90), tot.max(),
        costs[int(tot.argmax())][0]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", default="rtype", choices=["rtype", "mrheli"])
    ap.add_argument("--set", default="attract", choices=["attract", "play"])
    ap.add_argument("--frames", default="")
    ap.add_argument("--every", type=int, default=1)
    ap.add_argument("--png", default="")
    ap.add_argument("--alldirty", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--stop", type=int, default=0)
    ap.add_argument("-D", dest="defines", action="append", default=[])
    args = ap.parse_args()
    states = load_states(args.game, args.set)
    if args.frames:
        a, b = (int(x) for x in args.frames.split("-"))
        states = [s for s in states if a <= s[0] <= b]
    states = states[::args.every]
    h = Harness(args.game, args.defines)
    fails = 0
    pngs = {int(x) for x in args.png.split(",") if x}
    n, costs = run_sequence(h, args.game, states, args.set, pngs, args.alldirty, not args.quiet, args.stop)
    fails += n
    summary(args.set, costs)
    print("FAIL" if fails else "PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
