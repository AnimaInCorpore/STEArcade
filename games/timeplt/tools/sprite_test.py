"""Sprites at the picture's edges: render.s's render_frame (run/timeplt_sim on Musashi with its Blitter) against the
reference renderer, in the shown colours, over pictures made up for it.

    python sprite_test.py [--quick] [--tag timeplt_sim]

The Z80 block gets a tile map (random codes and colours, front tiles (colour bit 4) among them; some pictures with
opaque score bands: picture lines 0-31 and 248-255 front in every column, as the game's), the sprite RAMs a list (and
cloud_list: reused clouds' old contents), render_frame draws it into a buffer; the test plays the VBL and compares the
224 x 256 picture (machine.Video.render_raw, turned, through the pen map) and the side bands (black: the edges lie on
16-pixel groups, clipping is exact):
  * sprites across the left and right edges at every pixel (every shift, inside and outside), flips, codes with
    transparent rows and holes, sprites overlapping (the entry at $3E on top), over front tiles; codes with generated
    code (tools/assets.py sprite_programs: the coverage's shapes) and codes without (the row path);
  * sprites whose rows cross a 64 KB boundary of a buffer (the row path: the generated code steps the low word);
  * sprites into and inside the score bands (band_restore, hidden ones);
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

BUILD = build_dir('timeplt')
LB, PIC_TOP = 160, 10
SLOTS = list(range(0x10, 0x40, 2))


class Harness:
    def __init__(self, tag):
        run = ROOT / 'run' / tag
        self.s = s = Sim(str(run / 'TIMEPLT.PRG'), run_dir=run, ram_kib=16384)
        self.sym = sym = {k: v + s.base for k, v in s.symbols(BUILD / (tag + '.map')).items()}
        self.mem, self.cpu = s.mem, s.cpu
        self.a6 = sym['g_block'] + 0x8000
        for a, x in ((0x7F00, 0xFF), (0x7F01, 0x4B), (0x7F02, 0xFF), (0x7F03, 0xFF), (0x7F04, 0xFF), (0x7F05, 0xFF)):
            self.mem.w8(self.a6 + a, x)
        self.run_to({sym['sim_wait']})        # (booted: init_render done; the game's own state is overwritten)
        self.v = Video()
        self.pmap = np.frombuffer((BUILD / 'tp_penmap.bin').read_bytes(), np.uint8)
        self.zmem = bytearray(0x10000)
        self.extra = []
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

    def sprites(self, ents, clouds=()):
        """ents: {offset: (x, code, attributes, y)}; clouds: [(offset, x, code, attributes, y)] old contents"""
        for o in SLOTS:
            x, code, attr, y = ents.get(o, (0, 0, 0, 0))
            self.poke(0xB000 + o, bytes((x, code)))
            self.poke(0xB400 + o, bytes((attr, y)))
        clouds = sorted(clouds)
        for i, c in enumerate(clouds):
            self.mem.w16(self.sym['cloud_list'] + 6 * i, c[0])
            self.mem.w_block(self.sym['cloud_list'] + 6 * i + 2, bytes(c[1:]))
        self.mem.w16(self.sym['cloud_n'], len(clouds))
        self.extra = [tuple(c) for c in clouds]

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
        raw = self.v.render_raw(self.zmem, self.extra)[16:240]
        exp = np.ascontiguousarray(np.rot90(self.pmap[raw], -1))
        self.sprite_pixels += int((raw >= 128).sum())
        n = int((got[:, 48:272] != exp).sum())
        nb = int((got[:, :48] != 0).sum() + (got[:, 272:] != 0).sum())
        if n or nb:
            ys, xs = np.nonzero(got[:, 48:272] != exp)
            print('%s: %d pixels differ, %d band pixels, first (y, x) %s' % (label, n, nb,
                                                                          list(zip(ys[:4].tolist(), xs[:4].tolist()))))
            return False
        return True


def entry(code, colour, X, Y, flipx=False, flipy=False):
    """(x, code, attributes, y) of a sprite at picture X (-17..), Y: raw x = Y, y byte = X + 17; MAME's flips"""
    return (Y & 255, code & 255, (0 if flipx else 0x40) | (0x80 if flipy else 0) | colour & 0x3F, (X + 17) & 255)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--tag', default='timeplt_sim')
    args = ap.parse_args()
    h = Harness(args.tag)
    rnd = random.Random(7)
    v = h.v
    prepared = {c for c, fx, fy in assets.coverage_shapes()}

    def holes(c):
        px = np.rot90(v.sprites[c], -1) != 0
        rows = [r for r in range(16) if px[r].any()]
        inner = any((~px[r] & (np.cumsum(px[r]) > 0) & (np.cumsum(px[r][::-1])[::-1] > 0)).any() for r in range(16))
        return 0 < len(rows) < 16 and inner
    codes = [c for c in range(256) if holes(c)]
    gen = [c for c in codes if c in prepared]
    rows = [c for c in codes if c not in prepared]
    print('codes with transparent rows and holes: %d (%d with generated code, %d on the row path)' % (
        len(codes), len(gen), len(rows)))

    def tiles(bands):
        colours = bytearray(rnd.randrange(256) & ~0x10 | (0x10 if rnd.randrange(6) == 0 else 0) for _ in range(0x400))
        if bands:                             # (the score bands: raw columns 0-3 and 31 front everywhere)
            for ty in range(32):
                for tx in (0, 1, 2, 3, 31):
                    colours[ty * 32 + tx] |= 0x10
        h.poke(0xA000, bytes(colours))
        h.poke(0xA400, bytes(rnd.randrange(256) for _ in range(0x400)))
    ok = bad = 0

    def pick():
        return rnd.choice(gen if rnd.randrange(3) else rows)
    tiles(False)
    steps = range(-18, 3) if not args.quick else (-17, -9, -1, 0)
    for edge in ('left', 'right'):
        for dx in steps:
            X = dx if edge == 'left' else 224 - 16 - dx
            ents = {0x3E: entry(pick(), rnd.randrange(64), X, 40 + rnd.randrange(20)),
                    0x3C: entry(pick(), rnd.randrange(64), X, 120, flipx=True),
                    0x3A: entry(pick(), rnd.randrange(64), X + (4 if edge == 'left' else -4), 200, flipy=bool(dx & 1)),
                    0x38: entry(pick(), rnd.randrange(64), 100 + dx, 80, flipx=bool(dx & 2), flipy=True),
                    0x36: entry(pick(), rnd.randrange(64), 103 + dx, 84)}          # (under the one before)
            for k, c in enumerate(gen[:4]):   # (generated shapes at every shift too)
                ents[0x10 + 2 * k] = entry(c, rnd.randrange(64), X + 3 * k, 150 + 20 * k, flipx=bool(k & 1))
            clouds = [(0x12, *entry(pick(), rnd.randrange(64), X + 1, 30))]
            h.sprites(ents, clouds)
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
                ents[0x3E - 2 * i] = entry(pick(), rnd.randrange(64), X + k, max(0, line - k), flipy=bool(i & 1))
            h.sprites(ents)
            for _ in range(3):                    # (each buffer in turn)
                crossings += 1
                if h.check('64 KB crossing, line %d' % (line - k)):
                    ok += 1
                else:
                    bad += 1
    print('64 KB crossings tried: %d pictures (lines %s)' % (crossings, sorted(lines)))
    # the score bands: sprites into them, inside them (hidden), across their edges
    tiles(True)
    for step in range(30 if not args.quick else 6):
        ents = {}
        for i, o in enumerate(SLOTS):
            Y = rnd.choice((rnd.randrange(0, 48), rnd.randrange(232, 256), rnd.randrange(256)))
            ents[o] = entry(pick(), rnd.randrange(64), rnd.randrange(-16, 224), Y, flipx=bool(i & 1))
        h.sprites(ents)
        if h.check('bands, step %d' % step):
            ok += 1
        else:
            bad += 1
    # consecutive pictures: moving sprites and clouds
    tiles(False)
    for step in range(60 if not args.quick else 12):
        ents = {}
        for i, o in enumerate(SLOTS):
            ents[o] = entry(pick(), rnd.randrange(64), -16 + (i * 29 + step * 5) % 240, (i * 37 + step * 7) % 256,
                            flipx=bool(i & 1), flipy=bool(i & 2))
        clouds = [(o, *entry(pick(), rnd.randrange(64), (o * 7 + step * 3) % 224, (o * 11 + step) % 256))
                  for o in (0x10, 0x36, 0x3E) if (step + o) % 3]
        h.sprites(ents, clouds)
        if h.check('sequence step %d' % step):
            ok += 1
        else:
            bad += 1
    print('sprite pixels compared: %d' % h.sprite_pixels)
    print('%s: %d pictures exact, %d differ' % ('PASS' if not bad else 'FAIL', ok, bad))
    return int(bad != 0)


if __name__ == '__main__':
    sys.exit(main())
