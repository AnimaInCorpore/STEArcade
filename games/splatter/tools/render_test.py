"""The STE renderer (src/render.s) against the reference board's picture (engine/namcos1.py render_raw).

    venv/bin/python games/splatter/tools/render_test.py [--frames attract,play,...] [--png] [--quick]

render.s is assembled into a small harness (build/splatter/ren_harness.s: render.s, blit_go of engine/rt/borders.s,
`vio`) and run on Musashi (engine/sim.py, its Blitter model).  The arcade states come from the reference
(tools/machine.py: Splatter.boot + run_frame_port, with the inputs of logic_test.py --seed 5: coin, start, random
play; seed 1: the attract mode alone), recorded once into build/splatter/render_states.pkl.  For each state the
harness gets the vio image (palette RAM with the C116 registers, tile RAM, CUS123 control, sprite RAM), render_frame
draws, render_vbl shows; the picture is read back the way the Shifter shows it (the published buffer address, fine
scroll, 512-byte lines) and every pixel of the 288 x 224 picture must have the STE index that the renderer's own
colour mapping gives the reference's pen (the mapping is evaluated here from the renderer's tables: its k-d tree, the
Oklab and 4-bit tables of assets.py; -1, no layer, is index 0).  Pictures the renderer shows black (a new scene
whose palette still moves) are checked to be black.

Also: sprites at the left and right edge and in every one of the 16 fine positions (--edges), the side bands (no
sprite pixel beyond the clip boundaries), a 64 KB crossing of the sprite lines, the colour error (Oklab, mean over the
picture's pixels, against the arcade's RGB), and the cycles of each picture (Musashi's CPU cycles + the Blitter's bus
cycles).  --png writes STE | reference pictures into build/splatter/render_*.png.
"""
import argparse
import pickle
import random
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[2] / "engine")]
from paths import ROOT, VASM, VLINK, RT_INCLUDE, build_dir, src_dir
from machine68k import Register as R
from sim import Sim, TRAP1
import assets

BUILD = build_dir("splatter")
STATES = BUILD / "render_states.pkl"
VIO_SIZE = 0x28000

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
	ifd	TILE_FLAG
tile_written:	ds.b	1
tile_written_fix:	ds.b	1
	even
	endc
vio:	ds.b	$28000
h_stack:	ds.b	8192
h_stack_top:
"""


def harness_tag(defines):
    return "ren_harness" + "".join("_" + d.replace("=", "") for d in sorted(defines))


def build_harness(defines=()):
    assets.build()
    tag = harness_tag(defines)
    (BUILD / "ren_harness.s").write_text(HARNESS)
    obj = BUILD / (tag + ".o")
    prg = BUILD / (tag + ".PRG")
    cmd = [VASM, "-Fvobj", "-quiet", "-nowarn=2047", "-I", str(BUILD), "-I", str(RT_INCLUDE), "-I", str(src_dir("splatter")),
           "-DSIM=1"] + ["-D" + d for d in defines] + ["-o", str(obj), str(BUILD / "ren_harness.s")]
    for step in (cmd, [VLINK, "-b", "ataritos", "-s", "-o", str(prg), "-M" + str(BUILD / (tag + ".map")), str(obj)]):
        r = subprocess.run(step, capture_output=True, text=True)
        if r.returncode:
            sys.exit(r.stdout + r.stderr)
    return prg


class Harness:
    def __init__(self, defines=()):
        prg = build_harness(defines)
        self.s = Sim(str(prg), ram_kib=16384, run_dir=BUILD)
        self.s.mem.set_trace_mode(True)        # (the trace function is the Blitter and the I/O registers)
        self.sym = {k: v + self.s.base for k, v in self.s.symbols(BUILD / (harness_tag(defines) + ".map")).items()}
        self.mem, self.cpu = self.s.mem, self.s.cpu
        self.run_to(self.sym["h_wait"])
        self.call("render_init")

    def run_to(self, stop, limit=2_000_000_000):
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
                inv = {v: k for k, v in self.sym.items()}
                def near(a):
                    best = max((v for v in self.sym.values() if v <= a), default=0)
                    return "%s+%X" % (inv.get(best, "?"), a - best)
                pc6 = (words[1] << 16) | words[2]
                pc14 = (words[5] << 16) | words[6]
                raise RuntimeError("exception: stack %s; as a 6-byte frame pc %s, as a 14-byte frame (address %08X) pc %s" % (
                    " ".join("%04X" % w for w in words), near(pc6), (words[1] << 16) | words[2], near(pc14)))
        raise RuntimeError("timeout at %06X" % (self.cpu.r_pc() - self.s.base))

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
            c = self.cpu.execute(step).cycles
            k = labels[i][1]
            out[k] = out.get(k, 0) + c
        return out

    def r8(self, name, off=0):
        return self.mem.r8(self.sym[name] + off)

    def r16(self, name, off=0):
        return self.mem.r16(self.sym[name] + off)

    def r32(self, name, off=0):
        return self.mem.r32(self.sym[name] + off)

    def block(self, addr, n):
        return np.frombuffer(bytes(self.mem.r_block(addr, n)), np.uint8)

    def put_state(self, st):
        if "tile_written" in self.sym:
            # (TILE_FLAG: what the translated writers would say; any change of tile RAM sets both flags)
            if st["vram"] != getattr(self, "_vram", None):
                self.mem.w8(self.sym["tile_written"], 0xFF)
                self.mem.w8(self.sym["tile_written_fix"], 0xFF)
            if st.get("fix_written"):
                # (the program's HUD writers run in every frame of play: the flag is set even without a change)
                self.mem.w8(self.sym["tile_written_fix"], 0xFF)
            self._vram = st["vram"]
        v = bytearray(VIO_SIZE)
        v[0:0x8000] = st["pal"]
        v[0x10000:0x18000] = st["vram"]
        v[0x1C800:0x1D000] = st["spr"]
        v[0x1D000:0x1D020] = st["ctrl"]
        self.mem.w_block(self.sym["vio"], bytes(v))

    def frame(self):
        """render_frame + render_vbl: (cycles, blitter cycles); None when no buffer was free"""
        before = self.r32("ren_pictures")
        c, b = self.call("render_frame")
        if self.r32("ren_pictures") == before:
            return None
        self.call("render_vbl")         # (the flip)
        self.call("render_vbl")         # (a VBL without one: the buffer shown before is free again)
        return c, b

    # ---- the picture as the Shifter shows it ----
    def screen(self, lines=(0, 224), width=320):
        d = self.r16("ren_shown")
        addr = self.r32("ren_disp_addr", 4 * d)
        fine = self.r8("ren_disp_fine", d)
        y0, y1 = lines
        n = y1 - y0
        raw = self.block(addr + y0 * 512, n * 512).reshape(n, 512)[:, :21 * 8].reshape(n, 21, 4, 2)
        words = (raw[..., 0].astype(np.uint16) << 8) | raw[..., 1]
        out = np.zeros((n, 21 * 16), np.uint8)
        for p in range(4):
            for b in range(16):
                out[:, b::16] |= (((words[:, :, p] >> (15 - b)) & 1).astype(np.uint8) << p)
        return out[:, fine:fine + width]

    def picture(self):
        return self.screen()[:, 16:304]

    def palette(self, hud=False):
        d = self.r16("ren_shown")
        words = [self.r16("ren_disp_hpal" if hud else "ren_disp_pal", 32 * d + 2 * i) for i in range(16)]
        lv = lambda n: (((n & 7) << 1) | (n >> 3)) * 17
        return np.array([[lv((w >> 8) & 15), lv((w >> 4) & 15), lv(w & 15)] for w in words], np.uint8)

    def hud_lines(self):
        """the picture lines shown with the HUD bars' palette (the published buffer's top and bottom bar lines)"""
        d = self.r16("ren_shown")
        top, bot = self.r16("ren_disp_hud", 4 * d), self.r16("ren_disp_hud", 4 * d + 2)
        rows = np.zeros(224, bool)
        rows[:top] = True
        rows[bot:] = True
        return rows

    # ---- the renderer's colour mapping, evaluated here ----
    def mapping(self, pal_bytes, hud=False):
        """STE index of every pen 0-$17FF (the shadow page left out) in the playfield's or the HUD's palette: black 0,
        else the nearest of the palette's centres (Oklab bytes, L1, the first of equals), of the colour in the palette
        the colours were chosen with (ren_palsnap: a fade changes the STE colours, not the mapping)"""
        n = self.r16("ren_ncent", 2 if hud else 0)
        cent = self.block(self.sym["ren_cent"] + (64 if hud else 0), 64).reshape(16, 4)[1:n + 1, :3].astype(int)
        lab = assets.lab_table()[:, :3].astype(int)
        q4 = assets.q4_table()
        a = np.frombuffer(pal_bytes, np.uint8).reshape(4, 4, 0x800)
        rgb = np.stack([a[:, k, :].reshape(-1) for k in range(3)], 1)[:0x1800]
        q = q4[rgb]
        idx = (q[:, 0].astype(int) << 8) | (q[:, 1].astype(int) << 4) | q[:, 2]
        if n == 0:
            return np.zeros(len(idx), np.int32)
        d = np.abs(lab[idx][:, None, :] - cent[None]).sum(-1)
        out = d.argmin(1) + 1
        out[idx == 0] = 0
        return out.astype(np.int32)


# ---- the arcade states ----
def record(kind, frames, every=1, start=0):
    """kind 'play' (logic_test --seed 5 inputs) or 'attract' (seed 1: no coin): {frame: state}"""
    from machine import Splatter
    m = Splatter()
    m.boot()
    rng = random.Random(5)
    hold = 0
    out = {}
    for f in range(frames):
        if kind == "bench":
            # (splatter.s bench_inputs, by the frame: coin at 60, start at 140, from 400 right, with attack for 4
            # frames of every 40)
            m.coin_in = 0xE8 if 60 <= f < 66 else 0xF8
            c = 0xFF
            if 140 <= f < 146:
                c = 0x7F
            elif f >= 400:
                c = 0xEE if f % 40 < 4 else 0xFE
            m.control_in[0] = c
        if kind == "play":
            if f == 30:
                m.coin_in &= ~0x10
            elif f == 36:
                m.coin_in |= 0x10
            elif f == 130:
                m.control_in[0] &= ~0x80
            elif f == 136:
                m.control_in[0] |= 0x80
            elif f > 180:
                if hold <= 0:
                    bits = rng.choice([0, 1, 2, 4, 8, 0x10, 0x20, 0x11, 0x12, 0x21, 0x22, 0x01, 0x01])
                    m.control_in[0] = (0xFF & ~bits) | 0x80
                    hold = rng.randint(2, 40)
                hold -= 1
        m.run_frame_port()
        if f >= start and (f - start) % every == 0:
            out[f] = dict(pal=bytes(m.c116_rd(o) for o in range(0x8000)), vram=bytes(m.vram), ctrl=bytes(m.control),
                          spr=bytes(m.spriteram), c116=list(m.c116_regs), flip=m.flip)
    return out


def load_states():
    if STATES.exists():
        return pickle.loads(STATES.read_bytes())
    print("recording the reference's states (a few minutes, once) ...", flush=True)
    st = {"play": record("play", 1400, 1, 300), "attract": record("attract", 2200, 4, 300)}
    STATES.write_bytes(pickle.dumps(st))
    return st


BENCH_STATES = BUILD / "render_bench.pkl"


def load_bench():
    """the states of splatter.s' BENCH game (its scripted inputs), frames 500-1100"""
    if BENCH_STATES.exists():
        st = pickle.loads(BENCH_STATES.read_bytes())
        for v in st.values():
            v["fix_written"] = True
        return st
    print("recording the BENCH game's states (a few minutes, once) ...", flush=True)
    st = record("bench", 1101, 1, 500)
    BENCH_STATES.write_bytes(pickle.dumps(st))
    for v in st.values():
        v["fix_written"] = True
    return st


_board = None


def reference(st):
    """(player-view pens: 224 x 288, -1 = none; the arcade's RGB palette)"""
    global _board
    from namcos1 import NamcoS1
    if _board is None:
        _board = NamcoS1("splatter", cpus=False)
    m = _board
    a = np.frombuffer(st["pal"], np.uint8).reshape(4, 4, 0x800)
    for k in range(3):
        m.pal[k][:] = a[:, k, :].reshape(-1).tobytes()
    m.c116_regs = list(st["c116"])
    m.vram[:] = st["vram"]
    m.control[:] = st["ctrl"]
    m.spriteram[:] = st["spr"]
    m.flip = st["flip"]
    raw = m.render_raw()[::-1, ::-1]
    return np.ascontiguousarray(raw), np.vstack([m.palette_rgb(), [[0, 0, 0]]])


def check(h, st, name, png=False):
    """compare the shown picture with the reference: (differing pixels, black, Oklab error)"""
    want_pens, rgb = reference(st)
    got = h.picture()
    black = h.r8("ren_black")
    if black:
        bad = int(np.count_nonzero(h.palette())) + int(np.count_nonzero(h.palette(True)))
        return bad, True, 0.0
    snap = bytes(h.block(h.sym["ren_palsnap"], 0x6000)) + bytes(0x2000)
    hud = h.hud_lines()
    # the group's cells keep the bank they were drawn with when only a member's bank changes (render.s: ren_dbank,
    # the colours follow the current bank): the reference with those banks gives the pens the indices are of
    drawn = dict(st)
    ctrl = bytearray(st["ctrl"])
    key = h.block(h.sym["ren_grp_key"], 16)
    for i in range(int(key[0])):
        layer = int(key[1 + 4 * i])
        ctrl[0x18 + layer] = (ctrl[0x18 + layer] & ~7) | h.r8("ren_dbank", layer)
    drawn["ctrl"] = bytes(ctrl)
    drawn_pens = reference(drawn)[0] if bytes(ctrl) != st["ctrl"] else want_pens
    clipped = np.clip(drawn_pens, 0, 0x17FF)
    want = np.where(drawn_pens < 0, 0, np.where(hud[:, None], h.mapping(snap, True)[clipped], h.mapping(snap)[clipped]))
    diff = got != want
    pal_pf, pal_hud = h.palette(), h.palette(True)
    shown = np.where(hud[:, None, None], pal_hud[got], pal_pf[got])
    lab_got = assets.oklab(shown.astype(float))
    lab_want = assets.oklab(rgb[np.where(want_pens < 0, len(rgb) - 1, want_pens)].astype(float))
    e = np.sqrt(((lab_got - lab_want) ** 2).sum(-1))
    err = float(e.mean())
    sat = np.hypot(lab_want[..., 1], lab_want[..., 2]) > 0.08     # (the saturated pixels' error apart)
    check.sat = float(e[sat].mean()) if sat.any() else 0.0
    if 0 < np.count_nonzero(diff) <= 16:
        ys, xs = np.nonzero(diff)
        print("  differing pixels (y, x: got, want, pen):", ", ".join(
            "%d,%d: %d %d $%X" % (y, x, got[y, x], want[y, x], drawn_pens[y, x]) for y, x in zip(ys, xs)))
    if png or diff.any():
        from PIL import Image
        a = shown.astype(np.uint8)
        b = rgb[np.where(want_pens < 0, len(rgb) - 1, want_pens)].astype(np.uint8)
        c = np.where(diff[..., None], np.array([255, 0, 255], np.uint8), a)
        img = np.hstack([a, b, c] if diff.any() else [a, b])
        Image.fromarray(img).resize((img.shape[1] * 2, img.shape[0] * 2), Image.NEAREST).save(BUILD / ("render_%s.png" % name))
    return int(np.count_nonzero(diff)), False, err


def run_sequence(h, states, frames, label, png_at=(), verbose=True):
    costs = []
    fails = 0
    for f in frames:
        h.put_state(states[f])
        r = h.frame()
        if r is None:
            print("%s %d: no buffer free" % (label, f))
            continue
        bad, black, err = check(h, states[f], "%s_%d" % (label, f), png=f in png_at)
        costs.append(r[0] + r[1])
        if verbose:
            print("%s %5d: %s, CPU %7d + Blitter %6d cycles, colour error %.4f (saturated %.4f)" % (
                label, f, ("black (new scene)" if black else "exact") if not bad else "%d pixels DIFFER" % bad,
                r[0], r[1], err, 0.0 if black else check.sat), flush=True)
        fails += bad != 0
    return fails, costs


# ---- sprites at the edges, in every fine position, across 64 KB boundaries ----
SIZES = {16: 0, 8: 1, 32: 2, 4: 3}


def sprite_entry(x, y, code, colour, w=32, h=32, flipx=False, flipy=False, pri=7, xoffs=0, yoffs=0):
    """the six attribute bytes (sprite RAM +10..+15) that put a sprite's player-view top left at (x, y)"""
    raw_x = 361 - x - w
    sx = (-raw_x - w) & 0x1FF
    v = (sx - xoffs) & 0x1FF
    a15 = (256 - y - h - yoffs - 17) & 0xFF
    attr1 = (SIZES[w] << 6) | (0x20 if flipx else 0) | ((code >> 8) & 7)
    attr2 = (pri << 5) | (SIZES[h] << 1) | (1 if flipy else 0)
    return bytes([attr1, code & 0xFF, (colour << 1) | (v >> 8), v & 0xFF, attr2, a15])


def with_sprites(st, sprites):
    """the state with only these sprites (list of entry bytes), the others below the picture"""
    spr = bytearray(st["spr"])
    xoffs = spr[0x7F5] + ((spr[0x7F4] & 1) << 8)
    yoffs = spr[0x7F7]
    for k in range(127):
        e = sprites[k] if k < len(sprites) else sprite_entry(0, 240, 0, 0, xoffs=xoffs, yoffs=yoffs)
        spr[16 * k + 10:16 * k + 16] = e
    out = dict(st)
    out["spr"] = bytes(spr)
    return out


def edge_tests(h, states, verbose=False):
    """a 32 x 32 sprite (and a 16 x 16 one) along the left and right edges, at all 16 fine positions in the middle,
    flipped, and with lines across a 64 KB boundary of a buffer: exact, and nothing outside the clip groups in the
    side bands (the bands compared with the same picture without the sprite)"""
    from namcos1 import NamcoS1
    base = states["play"][max(f for f in states["play"] if f <= 900)]
    spr = np.asarray(NamcoS1("splatter", cpus=False).gfx()[2])
    code = max(range(2048), key=lambda c: np.count_nonzero(spr[c] != 15) - 4 * np.count_nonzero(spr[c][:, :8] == 15))
    sr = base["spr"]
    xoffs, yoffs = sr[0x7F5] + ((sr[0x7F4] & 1) << 8), sr[0x7F7]
    colour = sr[12] >> 1 if sr[12] >> 1 != 0x7F else 1
    empty = with_sprites(base, [])
    cases = []
    for x in list(range(-31, 9)) + list(range(256, 288)):
        cases.append(dict(x=x, y=100))
    for x in range(100, 116):
        for fx, fy in ((False, False), (True, False), (False, True), (True, True)):
            cases.append(dict(x=x, y=60, flipx=fx, flipy=fy))
    for x in (-9, 3, 140, 277):
        cases.append(dict(x=x, y=120, w=16, h=16))
    for y in (-31, -5, 200, 223):
        cases.append(dict(x=50, y=y))
    # a 64 KB boundary inside each buffer's picture lines: a sprite across it
    nbuf = 2 if h.r32("ren_buf", 8) == h.r32("ren_buf", 4) else 3
    for b in range(nbuf):
        buf = h.r32("ren_buf", 4 * b)
        for line in range(32, 256):
            a0, a1 = buf + line * 512, buf + (line + 1) * 512
            if a0 >> 16 != a1 >> 16 or (a0 & 0xFFFF) > 0x10000 - 512:
                cases.append(dict(x=130 + 8 * b, y=line - 32 - 16, buffer=b))
                break
    # the same at other window positions (group-aligned and not): a few cases each
    def at_w(st, wv):
        ctrl = bytearray(st["ctrl"])
        ex = (wv + 16) & 511
        for layer, adj in ((0, 4), (1, 2), (2, 1)):
            sx = (-(ex + 332) - adj) & 0xFFFF
            ctrl[4 * layer], ctrl[4 * layer + 1] = sx >> 8, sx & 0xFF
        out = dict(st)
        out["ctrl"] = bytes(ctrl)
        return out
    for wv in (0, 16, 21, 300, 496, 511):
        for x in (-31, -17, -16, -9, 0, 7, 256, 264, 271, 272, 280, 287):
            cases.append(dict(x=x, y=90, wv=wv))
    fails = 0
    bands_ref = {}
    for i, c in enumerate(cases):
        if "wv" in c and c["wv"] != getattr(edge_tests, "_wv", None):
            base, empty = at_w(base, c["wv"]), at_w(empty, c["wv"])
            edge_tests._wv = c["wv"]
        w, hh = c.get("w", 32), c.get("h", 32)
        e = sprite_entry(c["x"], c["y"], code, colour, w, hh, c.get("flipx", False), c.get("flipy", False),
                         xoffs=xoffs, yoffs=yoffs)
        st = with_sprites(base, [e])
        # (the buffer the case needs: the empty picture until it comes round; the first ones: a new scene)
        for _ in range(8 if i == 0 else 3):
            h.put_state(empty)
            h.frame()
            nxt = min(set(range(nbuf)) - {h.r16("ren_shown"), h.r16("ren_prev")})
            if i > 0 and ("buffer" not in c or nxt == c["buffer"]):
                break
        if "buffer" in c and nxt != c["buffer"]:
            continue                    # (a buffer the steady rotation does not use: one picture a VBL or less)
        bands_ref[nxt] = None
        h.put_state(empty)
        # (the reference bands: the empty picture in the same buffer, drawn just before in it? no: the background is
        # the same in all three buffers; the last empty picture's screen)
        ref_screen = h.screen()
        h.put_state(st)
        if h.frame() is None:
            continue
        if "buffer" in c:
            assert h.r16("ren_shown") == c["buffer"]
        bands_ref[h.r16("ren_shown")] = ref_screen
        bad, black, err = check(h, st, "edge_%d" % i)
        scr = h.screen()
        wv = h.r16("ren_w")
        cl = ((wv + 16) & ~15) - wv
        cr = ((wv + 304 + 15) & ~15) - wv
        ref = bands_ref.get(h.r16("ren_shown"))
        outside = np.ones(320, bool)
        outside[cl:cr] = False
        band_bad = int(np.count_nonzero((scr != ref)[:, outside])) if ref is not None else 0
        if bad or band_bad or black:
            fails += 1
            print("edge case %s: %d pixels differ, %d band pixels drawn (W %d), black %s" % (c, bad, band_bad, wv, black))
        elif verbose:
            print("edge case %s: exact" % c)
    print("edges: %d cases, %d failed (sprite code %d, colour %d)" % (len(cases), fails, code, colour))
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--play", default="300-1699")
    ap.add_argument("--attract", default="300-2200")
    ap.add_argument("--edges", action="store_true")
    ap.add_argument("--bench", default="", help="frames A-B of splatter.s' BENCH game (500-1100), e.g. 500-1100")
    ap.add_argument("--png", default="")
    ap.add_argument("-D", dest="defines", action="append", default=[])
    ap.add_argument("--every", type=int, default=1, help="a picture every N recorded frames (the program: PIC_EVERY)")
    ap.add_argument("--phase", type=int, default=0, help="with --every: the frames whose number %% N is this")
    args = ap.parse_args()
    states = load_states()
    h = Harness(args.defines)
    fails = 0
    pngs = {int(x) for x in args.png.split(",") if x}
    if args.edges:
        fails += edge_tests(h, states)
        h = Harness(args.defines)
    if args.bench:
        states = dict(states, bench=load_bench())
    for kind in ("bench", "play", "attract"):
        spec = getattr(args, kind)
        if not spec:
            continue
        a, b = (int(x) for x in spec.split("-"))
        fr = [f for f in sorted(states[kind]) if a <= f <= b]
        if kind in ("play", "bench") and args.every > 1:       # (attract states are recorded every 4th frame already)
            fr = [f for f in fr if f % args.every == args.phase]
        n, costs = run_sequence(h, states[kind], fr, kind, pngs)
        fails += n
        if costs:
            print("%s: %d pictures, median %d, 10%% %d, 90%% %d, max %d cycles" % (
                kind, len(costs), np.median(costs), np.percentile(costs, 10), np.percentile(costs, 90), max(costs)))
    print("FAIL" if fails else "PASS")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
