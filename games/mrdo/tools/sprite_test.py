"""Sprites at the picture's edges and the scrolled background: render.s's render_frame (run/mrdo_sim on Musashi with its
Blitter) against the reference renderer, in the shown colours, over pictures made up for it.

    python sprite_test.py [--quick] [--tag mrdo_sim]

The Z80 block gets two random tile maps (codes, colours, opaque cells, empty cells) and a scroll value, the sprite RAM a
list; render_frame draws it into a buffer; the test plays the VBL and compares the 192 x 240 picture
(machine.MrDo.render_raw, turned, through the pen map) and the side bands (black: the edges lie on 16-pixel groups,
clipping is exact):
  * sprites across the left and right edges at every pixel (every shift, inside and outside), flips, codes with
    transparent rows and holes, sprites overlapping (entry 0 on top); codes with generated code (tools/assets.py
    sprite_programs: the coverage's shapes) and codes without (the row path);
  * sprites above and below the picture (the guard lines: raw x 0-7 and 233-255);
  * sprites whose rows cross a 64 KB boundary of a buffer (the row path: the generated code steps the low word);
  * every scroll value 0-255 over random maps (the background's shifted chunks), and scroll changes from picture to
    picture (only the rows with background content composited again);
  * consecutive pictures: the sprites move, so the buffers' damage is restored, all three buffers in turn.
"""
from pathlib import Path
import argparse
import random
import sys
import numpy as np
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine68k import Register as R
from sim import Sim, TRAP1
from machine import MrDo, Gfx, VIS_X0, VIS_X1, VIS_Y0, VIS_Y1
from paths import ROOT, build_dir
from render_test import ste_picture, LEFT, W, GUARD, LB
import assets

BUILD = build_dir('mrdo')
BLANK = 41                  # (a character with no pixel in both sets)


class Harness:
    def __init__(self, tag):
        run = ROOT / 'run' / tag
        self.s = s = Sim(str(run / 'MRDO.PRG'), run_dir=run, ram_kib=16384)
        self.sym = sym = {k: v + s.base for k, v in s.symbols(BUILD / (tag + '.map')).items()}
        self.mem, self.cpu = s.mem, s.cpu
        self.a6 = sym['g_block'] + 0x8000
        for a, x in ((0xA000, 0xFF), (0xA001, 0xFF), (0xA002, 0xDF), (0xA003, 0xFF)):
            self.mem.w8(self.a6 + a - 0x10000, x)
        self.run_to({sym['sim_wait']})        # (booted: init_render done; the game's own state is overwritten)
        self.ref = MrDo()
        self.ref.gfx = Gfx()
        self.pmap = np.frombuffer((BUILD / 'md_penmap.bin').read_bytes(), np.uint8)
        self.sprite_pixels = 0

    def run_to(self, targets):
        cpu, s = self.cpu, self.s
        total = 0
        while total < 2_000_000_000:
            total += cpu.execute(2000).cycles
            pc = cpu.r_pc()
            if pc in targets:
                return pc
            if pc in (self.sym['z80_badpc'], self.sym['z80_badpc'] + 4) or s.terminated:
                raise RuntimeError('stopped at %06x' % (pc - s.base))
            if pc == TRAP1:
                s.gemdos()
        raise RuntimeError('timeout at %06x' % (self.cpu.r_pc() - self.s.base))

    def poke(self, a, data):
        self.mem.w_block(self.a6 + a - 0x10000, bytes(data))

    def tiles(self, vram, scroll, full=True):
        self.ref.vram[:] = vram
        self.ref.scrolly = scroll
        self.poke(0x8000, vram)
        self.poke(0xF800, bytes((scroll,)))
        if full:
            self.mem.w8(self.sym['tiles_all'], 0xFF)

    def scroll(self, scroll):
        self.ref.scrolly = scroll
        self.poke(0xF800, bytes((scroll,)))

    def sprites(self, ents):
        """ents: {entry: (code, byte 1, attributes, x)}"""
        sr = bytearray(256)
        for n, e in ents.items():
            sr[4 * n:4 * n + 4] = bytes(e)
        self.ref.spriteram[:] = sr
        self.poke(0x9000, sr)

    def render(self):
        """render_frame once (returning to sim_render_ret), then the VBL's part; -> the buffer drawn"""
        sym, mem, cpu = self.sym, self.mem, self.cpu
        a7 = cpu.r_reg(R.A7)
        sp = a7 - 64
        mem.w32(sp, sym['sim_render_ret'])
        cpu.w_reg(R.A7, sp)
        cpu.w_pc(sym['render_frame'])
        self.run_to({sym['sim_render_ret']})
        cpu.w_reg(R.A7, a7)
        ready = mem.r8(sym['frame_ready'])
        mem.w16(sym['prev_idx'], mem.r16(sym['shown_idx']))
        mem.w8(sym['frame_ready'], 0)
        mem.w16(sym['shown_idx'], ready - 1)
        return mem.r32(sym['buf_base'] + 4 * (ready - 1))

    def check(self, label):
        base = self.render()
        got = ste_picture(self.mem, base)
        raw = self.ref.render_raw()[VIS_Y0:VIS_Y1, VIS_X0:VIS_X1]
        exp = np.ascontiguousarray(self.pmap[raw].T[::-1])
        self.sprite_pixels += int((raw >= 256).sum())
        n = int((got[:, LEFT:LEFT + W] != exp).sum())
        nb = int((got[:, :LEFT] != 0).sum() + (got[:, LEFT + W:] != 0).sum())
        if n or nb:
            ys, xs = np.nonzero(got[:, LEFT:LEFT + W] != exp)
            print('%s: %d pixels differ, %d band pixels, first (y, x) %s' % (label, n, nb,
                                                                          list(zip(ys[:4].tolist(), xs[:4].tolist()))))
            return False
        return True


def entry(code, colour, X, Y, flipx=False, flipy=False):
    """(code, byte 1, attributes, x) of a sprite at picture X (-31 .. 223), Y (-23 .. 232)"""
    assert -31 <= X <= 223 and -23 <= Y <= 232
    return (code & 0x7F, 224 - X, (colour & 15) | (0x10 if flipx else 0) | (0x20 if flipy else 0), 232 - Y)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--tag', default='mrdo_sim')
    args = ap.parse_args()
    h = Harness(args.tag)
    rnd = random.Random(7)
    g = h.ref.gfx
    prepared = {c for c, fx, fy in assets.coverage_shapes()}

    def holes(c):
        px = assets.turned(g.sprites[c]) != 0
        rows = [r for r in range(16) if px[r].any()]
        inner = any((~px[r] & (np.cumsum(px[r]) > 0) & (np.cumsum(px[r][::-1])[::-1] > 0)).any() for r in range(16))
        return 0 < len(rows) < 16 and inner
    codes = [c for c in range(128) if holes(c)]
    gen = [c for c in codes if c in prepared]
    rows = [c for c in codes if c not in prepared] or [c for c in range(128) if c not in prepared]
    print('codes with transparent rows and holes: %d (%d with generated code); row path codes: %d' % (
        len(codes), len(gen), len(rows)))

    def vram():
        """both layers: random codes and colours, opaque cells (bit 6) now and then, empty cells (code 41 is blank in
        both character sets) often, so the background shows through the foreground"""
        v = bytearray(0x1000)
        for layer in (0, 0x800):
            for i in range(0x400):
                empty = rnd.randrange(3 if layer else 5) == 0
                v[layer + i] = rnd.randrange(256) & ~0x40 | (0x40 if rnd.randrange(8) == 0 else 0)
                v[layer + 0x400 + i] = BLANK if empty else rnd.randrange(256)
                if empty:
                    v[layer + i] &= 0x3F
        return v
    assert not g.fg_chars[BLANK].any() and not g.bg_chars[BLANK].any()
    ok = bad = 0

    def pick():
        return rnd.choice(gen if rnd.randrange(3) else rows)

    def count(res):
        nonlocal ok, bad
        if res:
            ok += 1
        else:
            bad += 1
    h.tiles(vram(), 0)
    steps = range(-18, 3) if not args.quick else (-17, -9, -1, 0)
    for edge in ('left', 'right'):
        for dx in steps:
            X = dx if edge == 'left' else W - 16 - dx
            ents = {0: entry(pick(), rnd.randrange(16), X, 20 + rnd.randrange(20)),
                    1: entry(pick(), rnd.randrange(16), X, 110, flipx=True),
                    2: entry(pick(), rnd.randrange(16), X + (4 if edge == 'left' else -4), 200, flipy=bool(dx & 1)),
                    3: entry(pick(), rnd.randrange(16), 100 + dx, 80, flipx=bool(dx & 2), flipy=True),
                    4: entry(pick(), rnd.randrange(16), 103 + dx, 84)}          # (under the one before)
            for k, c in enumerate(gen[:6]):   # (generated shapes at every shift too)
                ents[10 + k] = entry(c, rnd.randrange(16), X + 3 * k, 130 + 15 * k, flipx=bool(k & 1))
            ents[30] = entry(pick(), rnd.randrange(16), X + 1, -20 + (dx & 7))         # (into the guard lines)
            ents[31] = entry(pick(), rnd.randrange(16), X + 2, 230 - (dx & 3))
            h.sprites(ents)
            count(h.check('%s edge, X %d' % (edge, X)))
    # 64 KB crossings: sprites on the lines of a buffer that cross a 64 KB boundary
    lines = set()
    for i in range(3):
        base = h.mem.r32(h.sym['buf_base'] + 4 * i)
        nxt = (base + 0x10000) & ~0xFFFF
        if nxt < base + (GUARD + 240) * LB:
            lines.add(((nxt - base) // LB) - GUARD)
    crossings = 0
    for line in sorted(lines):
        for k in range(0, 16, 3):
            ents = {}
            for i, X in enumerate((-5, 30, 77, 150, 185, 64)):
                ents[i] = entry(pick(), rnd.randrange(16), X + k, min(232, max(-23, line - k)), flipy=bool(i & 1))
            h.sprites(ents)
            for _ in range(3):                    # (each buffer in turn)
                crossings += 1
                count(h.check('64 KB crossing, line %d' % (line - k)))
    print('64 KB crossings tried: %d pictures (lines %s)' % (crossings, sorted(lines)))
    # the scroll: every value over a fresh map, then changes from picture to picture over one map
    h.sprites({})
    for s in (range(256) if not args.quick else range(0, 256, 9)):
        h.tiles(vram(), s)
        count(h.check('scroll %d (full)' % s))
    h.tiles(vram(), 3)
    h.check('scroll base')
    for step in range(64 if not args.quick else 12):
        h.scroll(rnd.randrange(256) if step % 4 == 0 else (h.ref.scrolly + rnd.choice((1, 1, 2, 7, 8, 255))) & 255)
        count(h.check('scroll change to %d' % h.ref.scrolly))
    # consecutive pictures: moving sprites over a scrolling map
    for step in range(60 if not args.quick else 12):
        h.scroll((step * 3) & 255)
        ents = {}
        for n in range(64):
            if (n + step) % 3 == 0:
                continue
            ents[n] = entry(pick(), rnd.randrange(16), -31 + (n * 29 + step * 5) % 255, -23 + (n * 37 + step * 7) % 256,
                            flipx=bool(n & 1), flipy=bool(n & 2))
        h.sprites(ents)
        count(h.check('sequence step %d' % step))
    print('sprite pixels compared: %d' % h.sprite_pixels)
    print('%s: %d pictures exact, %d differ' % ('PASS' if not bad else 'FAIL', ok, bad))
    return int(bad != 0)


if __name__ == '__main__':
    sys.exit(main())
