"""Sprites at the picture's edges: render.s's render_frame (run/pooyan_sim on Musashi with its Blitter) against the
reference renderer, in the shown colours, over pictures made up for it.

    python sprite_test.py [--quick] [--tag pooyan_sim]

The Z80 block gets a tile map (random codes, colours and flips), the sprite RAMs a list, render_frame draws it into a
buffer; the test plays the VBL and compares the 224 x 256 picture (machine.Video.render_raw, turned, through the pen
map) and the side bands (black: the edges lie on 16-pixel groups, clipping is exact):
  * sprites across the left and right edges at every pixel (every shift, inside and outside), flips, the colours whose
    lookup makes holes (transparency classes: tools/assets.py), sprites overlapping (the entry at $3E on top); shapes
    with generated code (the coverage's: code, flips, class) and shapes without (the row path);
  * sprites whose rows cross a 64 KB boundary of a buffer (the row path: the generated code steps the low word);
  * sprites at the picture's top and bottom (whole into the guard lines below);
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
from machine import Video
from paths import ROOT, build_dir
from render_test import ste_picture
import assets

BUILD = build_dir('pooyan')
LB, PIC_TOP = 160, 10
SLOTS = list(range(0x10, 0x40, 2))


class Harness:
    def __init__(self, tag):
        run = ROOT / 'run' / tag
        self.s = s = Sim(str(run / 'POOYAN.PRG'), run_dir=run, ram_kib=16384)
        self.sym = sym = {k: v + s.base for k, v in s.symbols(BUILD / (tag + '.map')).items()}
        self.mem, self.cpu = s.mem, s.cpu
        self.a6 = sym['g_block'] + 0x8000
        for a, x in ((0xB100, 0x7B), (0xB101, 0xFF), (0xB102, 0xFF), (0xB103, 0xFF), (0xB104, 0xFF)):
            self.mem.w8(self.a6 + a - 0x10000, x)
        self.run_to({sym['sim_wait']})        # (booted: init_render done; the game's own state is overwritten)
        self.v = Video()
        self.pmap = np.frombuffer((BUILD / 'py_penmap.bin').read_bytes(), np.uint8)
        self.zmem = bytearray(0x10000)
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
        self.zmem[a:a + len(data)] = data
        self.mem.w_block(self.a6 + a - 0x10000, bytes(data))

    def sprites(self, ents):
        """ents: {offset: (x, code, attributes, y)}"""
        for o in SLOTS:
            x, code, attr, y = ents.get(o, (0, 0, 0, 0))
            self.poke(0x9000 + o, bytes((x, code)))
            self.poke(0x9400 + o, bytes((attr, y)))

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
        raw = self.v.render_raw(self.zmem)[16:240]
        exp = np.ascontiguousarray(np.rot90(self.pmap[raw], -1))
        self.sprite_pixels += int((raw >= 256).sum())
        n = int((got[:, 48:272] != exp).sum())
        nb = int((got[:, :48] != 0).sum() + (got[:, 272:] != 0).sum())
        if n or nb:
            ys, xs = np.nonzero(got[:, 48:272] != exp)
            print('%s: %d pixels differ, %d band pixels, first (y, x) %s' % (label, n, nb,
                                                                          list(zip(ys[:4].tolist(), xs[:4].tolist()))))
            return False
        return True


def entry(spec, X, Y):
    """(x, code, attributes, y) of a sprite spec (code, colour, flip x, flip y) at picture X (-16..), Y: raw x = Y, y
    byte = X + 16; MAME's flips (flip x: attribute bit 6 clear)"""
    code, colour, fx, fy = spec
    return (Y & 255, code & 63, (0 if fx else 0x40) | (0x80 if fy else 0) | colour & 15, (X + 16) & 255)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--tag', default='pooyan_sim')
    args = ap.parse_args()
    h = Harness(args.tag)
    rnd = random.Random(7)
    cls, sets = assets.transparency(h.v)
    prepared = set(assets.coverage_shapes(cls))         # (class, code, flip x, flip y)
    by_class = {k: [c for c in range(16) if cls[c] == k] for k in range(len(sets))}
    gen = [(code, colour, fx, fy) for k, code, fx, fy in sorted(prepared) for colour in by_class[k]]
    rows = [(code, colour, fx, fy) for code in range(64) for colour in range(16) for fx in (0, 1) for fy in (0, 1)
            if (cls[colour], code, bool(fx), bool(fy)) not in prepared]
    holey = [s for s in gen + rows if len(sets[cls[s[1]]]) > 1]
    print('sprite specs: %d with generated code, %d on the row path, %d in colours with holes' % (
        len(gen), len(rows), len(holey)))

    def pick():
        r = rnd.randrange(4)
        return rnd.choice(gen if r < 2 else rows if r == 2 else holey)

    def tiles():
        h.poke(0x8000, bytes(rnd.randrange(256) for _ in range(0x400)))
        h.poke(0x8400, bytes(rnd.randrange(256) for _ in range(0x400)))
    ok = bad = 0
    tiles()
    steps = range(-18, 3) if not args.quick else (-16, -9, -1, 0)
    for edge in ('left', 'right'):
        for dx in steps:
            X = dx if edge == 'left' else 224 - 16 - dx
            ents = {0x10: entry(pick(), X, 40 + rnd.randrange(20)),
                    0x12: entry(pick(), X, 120),
                    0x14: entry(pick(), X + (4 if edge == 'left' else -4), 200),
                    0x16: entry(pick(), 100 + dx, 80),
                    0x18: entry(pick(), 103 + dx, 84)}          # (over the one before)
            for k, s in enumerate(gen[::max(1, len(gen) // 6)][:6]):   # (generated shapes at every shift too)
                ents[0x30 + 2 * k] = entry(s, X + 3 * k, 140 + 18 * k)
            h.sprites(ents)
            if h.check('%s edge, X %d' % (edge, X)):
                ok += 1
            else:
                bad += 1
    # 64 KB crossings: sprites on the lines of a buffer that cross a 64 KB boundary
    lines = set()
    for i in range(3):
        base = h.mem.r32(h.sym['buf_base'] + 4 * i)
        nxt = (base + 0x10000) & ~0xFFFF
        if nxt < base + (PIC_TOP + 256) * LB:
            lines.add(((nxt - base) // LB) - PIC_TOP)
    crossings = 0
    for line in sorted(lines):
        for k in range(0, 16, 3):
            ents = {}
            for i, X in enumerate((-5, 30, 77, 150, 215, 64)):
                ents[0x10 + 2 * i] = entry(pick(), X + k, max(0, line - k))
            h.sprites(ents)
            for _ in range(3):                    # (each buffer in turn)
                crossings += 1
                if h.check('64 KB crossing, line %d' % (line - k)):
                    ok += 1
                else:
                    bad += 1
    print('64 KB crossings tried: %d pictures (lines %s)' % (crossings, sorted(lines)))
    # the top and bottom: whole sprites into the guard lines
    for step in range(20 if not args.quick else 4):
        ents = {}
        for i, o in enumerate(SLOTS):
            Y = rnd.choice((rnd.randrange(0, 16), rnd.randrange(236, 256)))
            ents[o] = entry(pick(), rnd.randrange(-16, 224), Y)
        h.sprites(ents)
        if h.check('top / bottom, step %d' % step):
            ok += 1
        else:
            bad += 1
    # consecutive pictures: moving sprites over a changing tile map
    for step in range(60 if not args.quick else 12):
        if step % 20 == 0:
            tiles()
        ents = {}
        for i, o in enumerate(SLOTS):
            ents[o] = entry(pick(), -16 + (i * 29 + step * 5) % 240, (i * 37 + step * 7) % 256)
        h.sprites(ents)
        if h.check('sequence step %d' % step):
            ok += 1
        else:
            bad += 1
    print('sprite pixels compared: %d' % h.sprite_pixels)
    print('%s: %d pictures exact, %d differ' % ('PASS' if not bad else 'FAIL', ok, bad))
    return int(bad != 0)


if __name__ == '__main__':
    sys.exit(main())
