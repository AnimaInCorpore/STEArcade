"""Sprites at the picture's edges: render.s's render_frame (run/hyperspt_sim on Musashi with its Blitter) against the
reference renderer, in the shown colours, over pictures made up for it.

    python sprite_test.py [--quick] [--tag hyperspt_sim]

The 6809's memory gets a tile map (random codes, colours and flips, every cell listed in cell_list as main_io_w lists
them), random row scrolls ($10C0 + 2 row), and the sprite RAMs a list; render_frame draws it into a buffer; the test plays the VBL and
compares the 256 x 224 picture (machine.Video.render_raw through the pen map) and the side bands (black: the edges lie
on 16-pixel groups, clipping is exact):
  * sprites across the left and right edges at every pixel (every shift, inside and outside), flips, codes and colours
    with transparent rows and holes, sprites overlapping (the first entry on top), MAME's wrap (x - 256);
  * sprites into the guard lines above and below the picture;
  * sprites whose rows cross a 64 KB boundary of a buffer;
  * consecutive pictures: the sprites and the scrolls move and tiles change, so the rows the buffers' last sprites
    covered are drawn again, all three buffers in turn.
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
from render_test import ste_picture, LB, PIC_TOP, LEFT

BUILD = build_dir('hyperspt')
SLOTS = list(range(0, 0xC0, 4))


class Harness:
    def __init__(self, tag):
        run = ROOT / 'run' / tag
        self.s = s = Sim(str(run / 'HYPERSPT.PRG'), run_dir=run, ram_kib=16384)
        self.sym = sym = {k: v + s.base for k, v in s.symbols(BUILD / (tag + '.map')).items()}
        self.mem, self.cpu = s.mem, s.cpu
        self.base = sym['hs_mem']
        for n, x in (('io_sys', 0xFF), ('io_in0', 0xFF), ('io_in1', 0xFF), ('io_dsw1', 0xFF), ('io_dsw2', 0x49)):
            self.mem.w8(sym[n], x)
        self.run_to({sym['sim_wait']})        # (booted: init_render done; the game's own state is overwritten)
        self.v = Video()
        self.pmap = np.frombuffer((BUILD / 'hs_penmap.bin').read_bytes(), np.uint8)
        self.tmem = bytearray(0x10000)
        self.sprite_pixels = 0

    def run_to(self, targets):
        cpu, s = self.cpu, self.s
        total = 0
        while total < 2_000_000_000:
            total += cpu.execute(2000).cycles
            pc = cpu.r_pc()
            if pc in targets:
                return pc
            if pc in (self.sym['main_badpc'], self.sym['main_badpc'] + 4) or s.terminated:
                raise RuntimeError('stopped at %06x' % (pc - s.base))
            if pc == TRAP1:
                s.gemdos()
        raise RuntimeError('timeout at %06x' % (self.cpu.r_pc() - self.s.base))

    def poke(self, a, data):
        self.tmem[a:a + len(data)] = data
        self.mem.w_block(self.base + a, bytes(data))

    def cells(self, which):
        """list the cells (as main_io_w does) for render_tiles"""
        sym, mem = self.sym, self.mem
        ptr = mem.r32(sym['cell_ptr'])
        for c in which:
            if not mem.r8(sym['cell_dirty'] + c):
                mem.w8(sym['cell_dirty'] + c, 0xFF)
                mem.w16(ptr, c)
                ptr += 2
        mem.w32(sym['cell_ptr'], ptr)

    def sprites(self, ents):
        """ents: {offset: (attributes, y, code, x)}"""
        for o in SLOTS:
            self.poke(0x1000 + o, bytes(ents.get(o, (0, 0, 0, 0))))

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
        full = self.v.render_raw(self.tmem)[16:240]
        exp = self.pmap[full]
        self.sprite_pixels += int((full < 256).sum())
        n = int((got[:, LEFT:LEFT + 256] != exp).sum())
        nb = int((got[:, :LEFT] != 0).sum() + (got[:, LEFT + 256:] != 0).sum())
        if n or nb:
            ys, xs = np.nonzero(got[:, LEFT:LEFT + 256] != exp)
            print('%s: %d pixels differ, %d band pixels, first (y, x) %s' % (label, n, nb,
                                                                          list(zip(ys[:4].tolist(), xs[:4].tolist()))))
            return False
        return True


def entry(code, colour, X, Y, flipx=False, flipy=False):
    """(attributes, y, code, x) of a sprite at picture X, Y: x = X, y = 225 - Y; code bit 8 in attributes bit 5;
    MAME's flips"""
    return ((0 if flipx else 0x40) | (0x80 if flipy else 0) | (0x20 if code & 0x100 else 0) | colour & 15,
            (225 - Y) & 255, code & 255, X & 255)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--tag', default='hyperspt_sim')
    args = ap.parse_args()
    h = Harness(args.tag)
    rnd = random.Random(7)
    v = h.v

    def holes(c, colour):
        px = v.lut[colour * 16 + v.sprites[c]] != 0
        rows = [r for r in range(16) if px[r].any()]
        inner = any((~px[r] & (np.cumsum(px[r]) > 0) & (np.cumsum(px[r][::-1])[::-1] > 0)).any() for r in range(16))
        return 0 < len(rows) < 16 and inner
    pairs = [(c, k) for c in range(512) for k in range(16) if holes(c, k)]
    print('(code, colour) pairs with transparent rows and holes: %d' % len(pairs))

    def tiles(n=None):
        cells = range(0x800) if n is None else rnd.sample(range(0x800), n)
        for c in cells:
            h.poke(0x2000 + c, bytes((rnd.randrange(256),)))
            h.poke(0x2800 + c, bytes((rnd.randrange(256),)))
        h.cells(cells)

    def scrolls():
        for r in range(32):
            s = rnd.randrange(512) if rnd.randrange(3) else 0
            h.poke(0x10C0 + 2 * r, bytes((s & 255, s >> 8)))
    ok = bad = 0

    def pick():
        return rnd.choice(pairs)
    tiles()
    scrolls()
    steps = range(-18, 3) if not args.quick else (-17, -9, -1, 0)
    for edge in ('left', 'right'):
        for dx in steps:
            X = dx if edge == 'left' else 256 - 16 - dx
            ents = {}
            for k, (Y, fx, fy) in enumerate(((20, 0, 0), (60, 1, 0), (100, 0, 1), (140, 1, 1))):
                c, col = pick()
                ents[4 * k] = entry(c, col, X, Y, bool(fx), bool(fy))
            c, col = pick()
            ents[0x20] = entry(c, col, X + (4 if edge == 'left' else -4), 180, flipy=bool(dx & 1))
            c, col = pick()
            ents[0x24] = entry(c, col, 100 + dx, 80, flipx=bool(dx & 2))
            c, col = pick()
            ents[0x28] = entry(c, col, 103 + dx, 84)          # (under the one before)
            h.sprites(ents)
            if h.check('%s edge, X %d' % (edge, X)):
                ok += 1
            else:
                bad += 1
    # the guard lines: sprites across the top and bottom edges
    for step in range(16 if not args.quick else 4):
        ents = {}
        for i, o in enumerate(SLOTS):
            c, col = pick()
            Y = rnd.choice((rnd.randrange(-18, 4), rnd.randrange(208, 228), rnd.randrange(-30, 240)))
            ents[o] = entry(c, col, rnd.randrange(-20, 260), Y, flipx=bool(i & 1), flipy=bool(i & 2))
        h.sprites(ents)
        if h.check('guards, step %d' % step):
            ok += 1
        else:
            bad += 1
    # 64 KB crossings: sprites on the lines of a buffer that cross a 64 KB boundary
    lines = set()
    for i in range(3):
        base = h.mem.r32(h.sym['buf_base'] + 4 * i)
        nxt = (base + 0x10000) & ~0xFFFF
        if nxt < base + (PIC_TOP + 224 + 16) * LB:
            lines.add(((nxt - base) // LB) - PIC_TOP)
    crossings = 0
    for line in sorted(lines):
        for k in range(0, 16, 3):
            ents = {}
            for i, X in enumerate((-5, 30, 77, 150, 215, 248)):
                c, col = pick()
                ents[4 * i] = entry(c, col, X + k, line - k, flipy=bool(i & 1))
            h.sprites(ents)
            for _ in range(3):                    # (each buffer in turn)
                crossings += 1
                if h.check('64 KB crossing, line %d' % (line - k)):
                    ok += 1
                else:
                    bad += 1
    print('64 KB crossings tried: %d pictures (lines %s)' % (crossings, sorted(lines)))
    # consecutive pictures: moving sprites, scrolls, some tiles changed
    for step in range(60 if not args.quick else 12):
        ents = {}
        for i, o in enumerate(SLOTS):
            c, col = pick()
            ents[o] = entry(c, col, -16 + (i * 29 + step * 5) % 288, -16 + (i * 37 + step * 7) % 256,
                            flipx=bool(i & 1), flipy=bool(i & 2))
        h.sprites(ents)
        if step % 4 == 0:
            scrolls()
        if step % 3 == 0:
            tiles(40)
        if h.check('sequence step %d' % step):
            ok += 1
        else:
            bad += 1
    print('sprite pixels compared: %d' % h.sprite_pixels)
    print('%s: %d pictures exact, %d differ' % ('PASS' if not bad else 'FAIL', ok, bad))
    return int(bad != 0)


if __name__ == '__main__':
    sys.exit(main())
