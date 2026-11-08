"""Sprites at the picture's edges: render.s's render_frame (run/mario_sim on Musashi with its Blitter) against the
reference renderer, in the shown colours, over pictures made up for it.

    python sprite_test.py [--quick] [--tag mario_sim]

The Z80 block gets a tile map (random codes) and a scroll value, the sprite RAM a list, render_frame draws it into a
buffer; the test plays the VBL and compares the 256 x 224 picture (machine.Mario.render_raw through the pen map) and
the side bands (black: the edges lie on 16-pixel groups, clipping is exact), with the screen flip set and clear:
  * sprites across the left and right edges at every pixel (every shift, inside and outside), flips, colours, sprites
    overlapping (the later entry on top); shapes with generated code (the coverage's) and shapes without (the row path);
  * sprites whose rows cross a 64 KB boundary of a buffer;
  * sprites at the picture's top and bottom (whole into the guard lines);
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
import machine
from paths import ROOT, build_dir
from render_test import ste_picture
import assets

BUILD = build_dir('mario')
LB, PIC_TOP = 160, 20
ENTRIES = 24                                  # sprite RAM entries used (the rest y 0: not drawn)


class Harness:
    def __init__(self, tag):
        run = ROOT / 'run' / tag
        self.s = s = Sim(str(run / 'MARIO.PRG'), run_dir=run, ram_kib=16384)
        self.sym = sym = {k: v + s.base for k, v in s.symbols(BUILD / (tag + '.map')).items()}
        self.mem, self.cpu = s.mem, s.cpu
        self.a6 = sym['g_block'] + 0x8000
        self.run_to({sym['sim_wait']})        # (booted: init_render done; the game's own state is overwritten)
        self.m = machine.Mario()
        self.m.gfx = machine.Gfx()
        self.pmap = np.frombuffer((BUILD / 'tm_penmap.bin').read_bytes(), np.uint8)
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
        data = bytes(data)
        self.m.ram[a - 0x6000:a - 0x6000 + len(data)] = data
        self.mem.w_block(self.a6 + a, data)

    def latch(self, n, v):
        self.m.latch[n] = v
        self.mem.w8(self.a6 + 0x7E80 + n, v)

    def scroll(self, v):
        self.m.scroll = v
        self.mem.w8(self.a6 + 0x7D00, v)

    def set_mode(self, flip, pal, gfx):
        self.latch(0, gfx)
        self.latch(2, flip)
        self.latch(3, pal)
        self.flip = flip

    def sprites(self, ents):
        """ents: {index: (y, attributes, code, x)}"""
        data = bytearray(0x400)
        for i, e in ents.items():
            data[4 * i:4 * i + 4] = bytes(e)
        self.poke(0x7000, data)

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
        got = ste_picture(self.mem, self.render())
        bmp, issp = self.m.render_raw(layers=True)
        exp = self.pmap[bmp[16:240]]
        self.sprite_pixels += int(issp[16:240].sum())
        diff = got[:, 32:288] != exp
        n = int(diff.sum())
        nb = int((got[:, :32] != 0).sum() + (got[:, 288:] != 0).sum())
        if n or nb:
            ys, xs = np.nonzero(diff)
            print('%s: %d pixels differ, %d band pixels, first (y, x) %s' % (label, n, nb,
                                                                          list(zip(ys[:4].tolist(), xs[:4].tolist()))))
            return False
        return True


def entry(h, spec, X, Y):
    """(y, attributes, code, x) of a sprite spec (code, colour, flip x, flip y) at picture X (-16..), Y: the inverse of
    the draw's position (MAME's draw_sprites, both screen orientations); the flips as MAME's (inverted by the screen flip
    in the draw)"""
    code, colour, fx, fy = spec
    if h.flip:
        t = (Y + 30) & 255 ^ 255
        y = (-8 - t) & 255
        x = ((X + 7) & 255) ^ 255
    else:
        y = (-25 - Y) & 255
        x = (X + 8) & 255
    return (y or 1, (0x80 if fx else 0) | (0x40 if fy else 0) | colour & 15, code & 255, x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--tag', default='mario_sim')
    args = ap.parse_args()
    h = Harness(args.tag)
    rnd = random.Random(7)
    tiles, sprites, shapes_seen = assets.coverage()
    prepared, _ = assets.coverage_shapes(shapes_seen)          # (code, flip x, flip y)
    prepared = set(prepared)
    gen = [(code, rnd.randrange(16), fx, fy) for code, fx, fy in sorted(prepared)]
    rows = [(code, rnd.randrange(16), fx, fy) for code in range(256) for fx in (0, 1) for fy in (0, 1)
            if (code, bool(fx), bool(fy)) not in prepared]
    print('sprite specs: %d with generated code, %d on the row path' % (len(gen), len(rows)))

    def pick():
        return rnd.choice(gen if rnd.randrange(3) else rows)

    def tiles_new():
        h.poke(0x7400, bytes(rnd.randrange(256) for _ in range(0x400)))
        h.scroll(rnd.randrange(256))
    ok = bad = 0
    for flip in (0, 1):
        h.set_mode(flip, rnd.randrange(2), rnd.randrange(2))
        tiles_new()
        steps = range(-18, 3) if not args.quick else (-16, -9, -1, 0)
        for edge in ('left', 'right'):
            for dx in steps:
                X = dx if edge == 'left' else 256 - 16 - dx
                ents = {0: entry(h, pick(), X, 40 + rnd.randrange(20)),
                        1: entry(h, pick(), X, 120),
                        2: entry(h, pick(), X + (4 if edge == 'left' else -4), 190),
                        3: entry(h, pick(), 100 + dx, 80),
                        4: entry(h, pick(), 103 + dx, 84)}           # (over the one before)
                for k, s in enumerate(gen[::max(1, len(gen) // 6)][:6]):   # (generated shapes at every shift too)
                    ents[8 + k] = entry(h, s, X + 3 * k, 130 + 11 * k)
                h.sprites(ents)
                if h.check('flip %d, %s edge, X %d' % (flip, edge, X)):
                    ok += 1
                else:
                    bad += 1
        # 64 KB crossings: sprites on the lines of a buffer that cross a 64 KB boundary
        lines = set()
        for i in range(3):
            base = h.mem.r32(h.sym['buf_base'] + 4 * i)
            nxt = (base + 0x10000) & ~0xFFFF
            bl = PIC_TOP + 224 + 16
            if nxt < base + bl * LB:
                lines.add(((nxt - base) // LB) - PIC_TOP)
        crossings = 0
        for line in sorted(lines):
            for k in range(0, 16, 3):
                ents = {}
                for i, X in enumerate((-5, 30, 77, 150, 215, 64)):
                    ents[i] = entry(h, pick(), X + k, max(0, line - k))
                h.sprites(ents)
                for _ in range(3):                    # (each buffer in turn)
                    crossings += 1
                    if h.check('flip %d, 64 KB crossing, line %d' % (flip, line - k)):
                        ok += 1
                    else:
                        bad += 1
        print('flip %d: 64 KB crossings tried: %d pictures (lines %s)' % (flip, crossings, sorted(lines)))
        # the top and bottom: whole sprites into the guard lines
        for step in range(20 if not args.quick else 4):
            ents = {}
            for i in range(ENTRIES):
                Y = rnd.choice((rnd.randrange(-15, 16), rnd.randrange(208, 224)))
                ents[i] = entry(h, pick(), rnd.randrange(-16, 256), Y)
            h.sprites(ents)
            if h.check('flip %d, top / bottom, step %d' % (flip, step)):
                ok += 1
            else:
                bad += 1
        # consecutive pictures: moving sprites over a changing tile map
        for step in range(60 if not args.quick else 12):
            if step % 20 == 0:
                tiles_new()
            ents = {}
            for i in range(ENTRIES):
                ents[i] = entry(h, pick(), -16 + (i * 29 + step * 5) % 272, (i * 37 + step * 7) % 224 - 8)
            h.sprites(ents)
            if h.check('flip %d, sequence step %d' % (flip, step)):
                ok += 1
            else:
                bad += 1
    print('sprite pixels compared: %d' % h.sprite_pixels)
    print('%s: %d pictures exact, %d differ' % ('PASS' if not bad else 'FAIL', ok, bad))
    return int(bad != 0)


if __name__ == '__main__':
    sys.exit(main())
