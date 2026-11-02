"""Sprites at the picture's edges, over the backgrounds and the text: render.s's render_frame (run/mpatrol_sim on Musashi
with its Blitter) against the reference renderer (machine.Video.render_raw), in the shown colours, over pictures made up
for it.

    python games/mpatrol/tools/sprite_test.py [--quick]

The Z80 block gets the text RAM (rows 7-31: a few cells of one colour, the rest blank; the ground's rows at random
codes), the sprite RAM and the six video registers; render_frame draws them into a buffer, the test plays the VBL (the
three buffers in turn, as on the STE) and compares the playfield (picture lines 50-251, x 0-239) and the side bands of
the buffer (screen x 0-31 and 272-319 of the shown lines: slot 0, the edges lie on 16-pixel groups and clip exactly):
  * sprites across the left and right edges at every x (all 16 shifts, inside, clipped, culled), flips, codes with
    transparent holes (rows with inner transparent pixels), sprites overlapping (the arcade's order);
  * sprites into the guard lines above and below the playfield (picture lines 35-49 and 237-251 + 16);
  * sprites on the lines of each buffer that cross a 64 KB boundary;
  * consecutive pictures: moving sprites and scrolling backgrounds and ground (the buffers' damage restored: a line is
    drawn again only where it changed), the hills and the city, the backgrounds off.
The colours stay within 16 on the playfield (two sprite colours a picture, one text colour), so every picture must be
exact.
"""
from pathlib import Path
import argparse
import random
import sys
import numpy as np
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
from machine68k import Register as R
from sim import Sim, TRAP1
from machine import Video, VISIBLE
from paths import ROOT, build_dir
from render_test import image, palette, BUF_LINES, PF_TOP, X0
import assets

BUILD = build_dir("mpatrol")


class Harness:
    def __init__(self):
        run = ROOT / "run" / "mpatrol_sim"
        self.s = s = Sim(str(run / "MPATROL.PRG"), run_dir=run, ram_kib=16384)
        self.sym = sym = {k: v + s.base for k, v in s.symbols(BUILD / "mpatrol_sim.map").items()}
        self.mem, self.cpu = s.mem, s.cpu
        for i, val in enumerate((0xFF, 0xFF, 0xFF, 0xFF, 0xFD)):
            self.mem.w8(sym["io_in"] + i, val)
        self.run_to({sym["sim_wait"]})       # (booted: init_render done; the game's own state is overwritten)
        self.v = Video()
        self.pens = np.array([assets.ste_rgb(assets.ste(c)) for c in self.v.pens], np.uint8)
        self.vram = bytearray(0x400)
        self.cram = bytearray(0x400)
        self.sr = bytearray(0x100)
        self.regs = [0, 0, 0, 0, 0, 0xFF]
        self.sprite_pixels = 0

    def run_to(self, targets):
        cpu, s = self.cpu, self.s
        total = 0
        while total < 2_000_000_000:
            total += cpu.execute(2000).cycles
            pc = cpu.r_pc()
            if pc in targets:
                return pc
            if pc in (self.sym["z80_badpc"], self.sym["z80_badpc"] + 4) or s.terminated:
                raise RuntimeError("stopped at %06x" % (pc - s.base))
            if pc == TRAP1:
                s.gemdos()
        raise RuntimeError("timeout at %06x" % (cpu.r_pc() - s.base))

    def zpoke(self, a, data):
        self.mem.w_block(self.sym["g_block"] - 0x8000 + a, bytes(data))

    def render(self):
        """render_frame once (returning to sim_render_ret), then the VBL's part; -> the buffer drawn"""
        sym, mem, cpu = self.sym, self.mem, self.cpu
        self.zpoke(0x8000, self.vram)
        self.zpoke(0x8400, self.cram)
        self.zpoke(0xC800, self.sr)
        scroll, x1, y1, x2, y2, ctl = self.regs
        for i, val in ((0, scroll), (2, x1), (3, y1), (4, x2), (5, y2), (6, ctl)):
            mem.w8(sym["io_regs"] + i, val)
        a7 = cpu.r_reg(R.A7)
        sp = a7 - 64
        mem.w32(sp, sym["sim_render_ret"])
        cpu.w_reg(R.A7, sp)
        cpu.w_pc(sym["render_frame"])
        self.run_to({sym["sim_render_ret"]})
        cpu.w_reg(R.A7, a7)
        ready = mem.r8(sym["frame_ready"])
        mem.w16(sym["prev_idx"], mem.r16(sym["shown_idx"]))
        mem.w8(sym["frame_ready"], 0)
        mem.w16(sym["shown_idx"], ready - 1)
        return ready - 1

    def check(self, label):
        buf = self.render()
        mem, sym = self.mem, self.sym
        idx = image(mem, sym["pf_bufs"] + buf * BUF_LINES * 160 + PF_TOP * 160, 252 - PF_TOP)
        got = palette(mem, sym["pf_pal"] + 32 * buf)[idx[:, X0:X0 + 240]]
        x0, x1, y0, y1 = VISIBLE
        raw = self.v.render_raw(self.vram, self.cram, self.sr, self.regs)[y0:y1 + 1, x0:x1 + 1][PF_TOP:]
        want = self.pens[raw]
        self.sprite_pixels += int(((raw > 512) & (raw < 768)).sum())
        n = int(np.any(got != want, axis=2).sum())
        nb = int((idx[:, :X0] != 0).sum() + (idx[:, X0 + 240:] != 0).sum())
        if n or nb:
            ys, xs = np.nonzero(np.any(got != want, axis=2))
            print("%s: %d pixels differ, %d band pixels, first (line, x) %s" % (
                label, n, nb, list(zip((ys[:4] + PF_TOP).tolist(), xs[:4].tolist()))))
            return False
        return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    h = Harness()
    rnd = random.Random(11)
    v = h.v
    lut = v.sp_lookup
    blank = next(c for c in range(512) if not v.tiles[c].any())

    def holes(c):
        px = v.sprites[c] != 0
        return any((~px[r] & (np.cumsum(px[r]) > 0) & (np.cumsum(px[r][::-1])[::-1] > 0)).any() for r in range(16))
    visible = [c for c in range(1, 128) if v.sprites[c].any()]
    hcodes = [c for c in visible if holes(c)]
    # sprite colours that show values 1-3 (the lookup's colour 0 is transparent)
    colours = [c for c in range(16) if all(lut[c * 8 + k] != 0 for k in (1, 2, 3))] or \
              [c for c in range(16) if any(lut[c * 8 + k] != 0 for k in (1, 2, 3))]
    print("codes %d visible, %d with transparent holes; sprite colours used %s" % (len(visible), len(hcodes), colours))

    def text(colour=None):
        """rows 0-6 blank (the panel is not compared), a few cells of one colour on rows 7-23, the ground's rows 24-31
        random codes of that colour"""
        col = rnd.randrange(128) if colour is None else colour
        for i in range(0x400):
            h.vram[i], h.cram[i] = blank & 0xFF, (blank >> 8) << 7
        for _ in range(12):
            i = rnd.randrange(7 * 32, 24 * 32)
            c = rnd.randrange(512)
            h.vram[i], h.cram[i] = c & 0xFF, (c >> 8) << 7 | col
        for i in range(24 * 32, 32 * 32):
            c = rnd.randrange(512) if rnd.randrange(3) else blank
            h.vram[i], h.cram[i] = c & 0xFF, (c >> 8) << 7 | col

    def sprite(n, code, colour, x, y, fx=False, fy=False):
        h.sr[4 * n:4 * n + 4] = bytes((y & 255, colour | (0x40 if fx else 0) | (0x80 if fy else 0), code, x & 255))

    def line_y(line):                        # (a sprite's picture line is 235 - y)
        return 235 - line
    ok = bad = 0

    def count(res):
        nonlocal ok, bad
        ok, bad = ok + bool(res), bad + (not res)

    text(colour=5)
    h.regs = [10, 40, 148, 90, 114, 0x04]    # the hills over the mountains, the ground
    # both side edges at every x: screen x = x + 25 (25-31: across the left edge; 257-271: the right; 272 on: culled)
    xs = range(256) if not args.quick else list(range(0, 24)) + list(range(224, 256))
    for x in xs:
        h.sr[:] = bytes(256)
        c0, c1 = rnd.sample(colours, 2)
        sprite(0, rnd.choice(hcodes), c0, x, line_y(60 + (x & 7)))
        sprite(1, rnd.choice(hcodes), c1, x, line_y(110), fx=True)
        sprite(2, rnd.choice(hcodes), c0, x, line_y(150), fy=True)
        sprite(3, rnd.choice(hcodes), c1, x, line_y(200 + (x & 3)), fx=True, fy=True)
        sprite(4, rnd.choice(visible), c0, (x + 5) & 255, line_y(205))        # (under 3: the order)
        sprite(16, rnd.choice(visible), c1, (x + 9) & 255, line_y(210))       # (another group: over both)
        sprite(5, rnd.choice(visible), c0, x, line_y(36 + (x % 14)))          # (into the guard lines above)
        sprite(6, rnd.choice(visible), c1, x, line_y(240 + (x % 12)))         # (and below)
        count(h.check("x %d (screen %d)" % (x, x + 25)))
    # 64 KB crossings: sprites on the playfield lines of each buffer that cross a 64 KB boundary
    lines = set()
    for i in range(3):
        base = h.sym["pf_bufs"] + i * BUF_LINES * 160
        nxt = (base + 0x10000) & ~0xFFFF
        for b in range(nxt, base + BUF_LINES * 160, 0x10000):
            line = (b - base) // 160
            if PF_TOP - 15 <= line < 252:
                lines.add(line)
    crossings = 0
    for line in sorted(lines):
        for k in range(0, 16, 5):
            h.sr[:] = bytes(256)
            for n, x in enumerate((3, 40, 101, 160, 231, 70)):
                sprite(n, rnd.choice(hcodes), colours[n & 1], x + k, line_y(min(251, line - k)), fy=bool(n & 1))
            for _ in range(3):
                crossings += 1
                count(h.check("64 KB crossing, line %d" % (line - k)))
    print("64 KB crossings tried: %d pictures (lines %s)" % (crossings, sorted(lines)))
    # consecutive pictures: moving sprites over scrolling backgrounds and ground; scenes
    scenes = [(0x04, 148, 114), (0x03, 148, 114), (0x14, 140, 100), (0x24, 148, 114), (0x04, 120, 90), (0x06, 148, 114)]
    steps = 240 if not args.quick else 48
    for step in range(steps):
        ctl, y1, y2 = scenes[(step // 40) % len(scenes)]
        if step % 40 == 0:
            text(colour=rnd.choice((5, 9, 17)))
        elif step % 7 == 0:                  # (a few text cells change: the sky's shots, the ground's new column)
            for _ in range(3):
                i = rnd.randrange(7 * 32, 32 * 32)
                c = rnd.choice((blank, rnd.randrange(512)))
                h.vram[i] = c & 0xFF
                h.cram[i] = (c >> 8) << 7 | (h.cram[i] & 0x7F)
        scroll, x1, _, x2, _, _ = h.regs
        if step % 5 != 4:                    # (some pictures with nothing scrolled)
            scroll, x1, x2 = (scroll - 2) & 255, (x1 - (step & 1)) & 255, (x2 - (step % 4 == 0)) & 255
        h.regs = [scroll, x1, y1, x2, y2, ctl]
        h.sr[:] = bytes(256)
        c0, c1 = rnd.sample(colours, 2)
        for n in range(64):
            if (n + step) % 3:
                continue
            sprite(n, rnd.choice(visible), (c0, c1)[n & 1], (n * 29 + step * 5) % 256,
                   line_y(36 + (n * 37 + step * 7) % 230), fx=bool(n & 4), fy=bool(n & 8))
        count(h.check("sequence step %d (control %02X)" % (step, ctl)))
    print("sprite pixels compared: %d" % h.sprite_pixels)
    print("%s: %d pictures exact, %d differ" % ("PASS" if not bad else "FAIL", ok, bad))
    return int(bad != 0)


if __name__ == "__main__":
    sys.exit(main())
