"""Sprites at the picture's edges: render.s's render_frame (run/pacman_sim on Musashi with its Blitter) against the
reference renderer over pictures made up for it.

    python sprite_test.py [--quick] [--tag pacman_sim]

The Z80 block gets a tile map (random codes and colours), the sprite RAMs a list; render_frame draws it into a buffer;
the test plays the VBL and compares the 224 x 274 picture (machine.Pacman.render_raw, turned, the shown lines:
render_test.SHOWN) and the side bands (black: the edges lie on 16-pixel groups, clipping is exact):
  * sprites across the left and right edges at every pixel (every shift, inside and outside), flips, codes with
    transparent rows and holes (and colours whose pen 2 or 3 is black), sprites overlapping (entry 0 on top);
    shapes with generated code (tools/assets.py: the coverage's) and without (the row path);
  * sprites whose rows cross a 64 KB boundary of a buffer (the row path: the generated code steps the low word);
  * sprites into the bands (lines 17-23 and 264-287: band_restore) and MAME's wrapped copy (lines 265-272: the copy
    256 lines up reaches the maze);
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
from machine import Pacman, Gfx
from paths import ROOT, build_dir
from render_test import ste_picture, expected, LB, GT
import assets

BUILD = build_dir('pacman')


class Harness:
    def __init__(self, tag):
        run = ROOT / 'run' / tag
        self.s = s = Sim(str(run / 'PACMAN.PRG'), run_dir=run, ram_kib=16384)
        self.sym = sym = {k: v + s.base for k, v in s.symbols(BUILD / (tag + '.map')).items()}
        self.mem, self.cpu = s.mem, s.cpu
        self.a6 = sym['g_block'] + 0x8000
        for a, x in ((0x5100, 0xFF), (0x5101, 0xFF), (0x5102, 0xC9), (0x5103, 0)):
            self.mem.w8(self.a6 + a, x)
        self.run_to({sym['sim_wait']})        # (booted: init_render done; the game's own state is overwritten)
        self.ref = Pacman()
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

    def tiles(self, rnd):
        codes = bytes(rnd.randrange(256) for _ in range(0x400))
        colours = bytes(rnd.randrange(32) for _ in range(0x400))
        self.ref.ram[0:0x400] = codes
        self.ref.ram[0x400:0x800] = colours
        self.mem.w_block(self.a6 + 0x4000, codes + colours)

    def sprites(self, ents):
        """ents: {entry 0-7: (code, colour, X, line, flip x, flip y)} (X: the picture column, line: the buffer line)"""
        r = self.ref
        for o in range(8):
            code, colour, X, line, fx, fy = ents.get(o, (0, 0, 100, 272, 0, 0))
            y = ((238 if o <= 2 else 239) - X) & 255
            x = (272 - line) & 255
            r.ram[0xFF0 + 2 * o] = (code << 2 | fy << 1 | fx) & 255
            r.ram[0xFF1 + 2 * o] = colour
            r.sprite2[2 * o], r.sprite2[2 * o + 1] = y, x
        self.mem.w_block(self.a6 + 0x4FF0, bytes(r.ram[0xFF0:0x1000]))
        self.mem.w_block(self.a6 + 0x5060, bytes(r.sprite2))

    def render(self):
        """render_frame once (returning to sim_render_ret), then the VBL's part; -> the buffer drawn"""
        sym, mem, cpu = self.sym, self.mem, self.cpu
        mem.w8(sym['tiles_all'], 0xFF)        # (the tile map as poked: every cell)
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
        got = ste_picture(self.mem, self.render())
        exp = expected(self.ref)
        r = self.ref
        n = int((got[:, 48:272] != exp).sum())
        nb = int((got[:, :48] != 0).sum() + (got[:, 272:] != 0).sum())
        self.sprite_pixels += sum(1 for o in range(8) if r.ram[0xFF1 + 2 * o] & 31)
        if n or nb:
            ys, xs = np.nonzero(got[:, 48:272] != exp)
            print('%s: %d pixels differ, %d band pixels, first (display line, X) %s' % (
                label, n, nb, list(zip(ys[:4].tolist(), xs[:4].tolist()))))
            return False
        return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--tag', default='pacman_sim')
    args = ap.parse_args()
    h = Harness(args.tag)
    rnd = random.Random(7)
    g = Gfx()
    drawable = [c for c in range(32) if assets.colour_pattern(g, c) >= 0]
    by_pattern = {p: [c for c in drawable if assets.colour_pattern(g, c) == p] for p in range(3)}
    prepared = assets.coverage_shapes(g)       # (pattern << 8 | code << 2 | flip x << 1 | flip y)
    gen = sorted(prepared)

    def holes(code):
        px = np.rot90(g.sprites[code], -1) != 0
        rows = [r for r in range(16) if px[r].any()]
        inner = any((~px[r] & (np.cumsum(px[r]) > 0) & (np.cumsum(px[r][::-1])[::-1] > 0)).any() for r in range(16))
        return 0 < len(rows) < 16 and inner
    hole_codes = [c for c in range(64) if holes(c)]
    print('codes with transparent rows and holes: %d; shapes with generated code: %d' % (len(hole_codes), len(gen)))

    def pick(gen_first=True):
        """-> (code, colour, flip x, flip y): a shape with generated code, or any (mostly the row path)"""
        if gen_first and rnd.randrange(3):
            sid = rnd.choice(gen)
            return sid >> 2 & 63, rnd.choice(by_pattern[sid >> 8]), sid >> 1 & 1, sid & 1
        p = rnd.randrange(3)
        return rnd.choice(hole_codes + list(range(64))), rnd.choice(by_pattern[p]), rnd.randrange(2), rnd.randrange(2)

    def ent(X, line, shape=None):
        code, colour, fx, fy = shape or pick()
        return code, colour, X, line, fx, fy
    ok = bad = 0

    def result(passed):
        nonlocal ok, bad
        if passed:
            ok += 1
        else:
            bad += 1
    h.tiles(rnd)
    steps = range(-18, 3) if not args.quick else (-17, -9, -1, 0)
    for edge in ('left', 'right'):
        for dx in steps:
            X = dx if edge == 'left' else 224 - 16 - dx
            ents = {7: ent(X, 40 + rnd.randrange(20)), 6: ent(X, 120), 5: ent(X + (4 if edge == 'left' else -4), 200),
                    4: ent(100 + dx, 80), 3: ent(103 + dx, 84)}                  # (4 under 3)
            for k in range(3):                # (generated shapes at every shift too; entries 0-2: X one less)
                sid = gen[(k * 7 + dx) % len(gen)]
                ents[k] = ent(X + 3 * k, 150 + 20 * k, (sid >> 2 & 63, by_pattern[sid >> 8][0], sid >> 1 & 1, sid & 1))
            h.sprites(ents)
            result(h.check('%s edge, X %d' % (edge, X)))
    # 64 KB crossings: sprites on the lines of a buffer that cross a 64 KB boundary
    lines = set()
    for i in range(3):
        base = h.mem.r32(h.sym['buf_base'] + 4 * i)
        nxt = (base + 0x10000) & ~0xFFFF
        if nxt < base + 288 * LB:
            lines.add((nxt - base) // LB)
    crossings = 0
    for line in sorted(lines):
        for k in range(0, 16, 3):
            L = min(max(line - k, 24), 255)
            ents = {o: ent(X + k, L) for o, X in enumerate((-5, 30, 77, 150, 215, 64))}
            h.sprites(ents)
            for _ in range(3):                    # (each buffer in turn)
                crossings += 1
                result(h.check('64 KB crossing, line %d' % L))
    print('64 KB crossings tried: %d pictures (lines %s)' % (crossings, sorted(lines)))
    # the bands and the wrap: sprites from line 17 into the top band, from 257 into the bottom band and beyond 264 (the
    # wrapped copy reaches the maze from 265 on)
    for step in range(30 if not args.quick else 6):
        ents = {o: ent(rnd.randrange(-16, 224), rnd.choice((rnd.randrange(17, 30), rnd.randrange(257, 273),
                                                              rnd.randrange(17, 273)))) for o in range(8)}
        h.sprites(ents)
        result(h.check('bands, step %d' % step))
    # consecutive pictures: moving sprites
    for step in range(60 if not args.quick else 12):
        ents = {o: ent(-16 + (o * 29 + step * 5) % 240, 17 + (o * 37 + step * 7) % 256) for o in range(8)}
        h.sprites(ents)
        result(h.check('sequence step %d' % step))
    print('sprites drawn: %d' % h.sprite_pixels)
    print('%s: %d pictures exact, %d differ' % ('PASS' if not bad else 'FAIL', ok, bad))
    return int(bad != 0)


if __name__ == '__main__':
    sys.exit(main())
