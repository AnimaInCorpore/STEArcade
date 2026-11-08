"""Sprites at the picture's edges: render.s's render_frame (run/sbasketb_sim on Musashi with its Blitter) against the
reference renderer, in the shown colours, over pictures made up for it.

    python sprite_test.py [--quick] [--tag sbasketb_sim]

The 6809's memory gets a tile map (random codes, colours and flips, every cell listed in cell_list as main_io_w lists
them), random scrolls and palette banks, and the sprite RAM a list (both banks: latch Q5); render_frame draws it into a
buffer; the test plays the VBL and compares the 224 x 256 picture (machine.Video.render_raw, turned, through the pen
map) and the side bands (black: the edges lie on 16-pixel groups, clipping is exact):
  * sprites across the left and right edges at every pixel (every shift, inside and outside), flips, codes and colours
    with transparent rows and holes, sprites overlapping (the last entry under the first);
  * sprites into the guard lines below the picture;
  * sprites whose rows cross a 64 KB boundary of a buffer;
  * consecutive pictures: the sprites and the scrolls move and tiles change, all three buffers in turn.
"""
from pathlib import Path
import os
import argparse
import random
import sys
import numpy as np
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine68k import Register as R
from sim import Sim, TRAP1
from machine import Video
from paths import ROOT, build_dir
from render_test import ste_picture, band_bad, LB, PIC_TOP, LEFT, PICW

BUILD = build_dir('sbasketb')
SLOTS = list(range(0, 0x100, 4))


class Harness:
    def __init__(self, tag):
        run = ROOT / 'run' / tag
        self.s = s = Sim(str(run / 'SBASKETB.PRG'), run_dir=run, ram_kib=16384)
        self.sym = sym = {k: v + s.base for k, v in s.symbols(BUILD / (tag + '.map')).items()}
        self.mem, self.cpu = s.mem, s.cpu
        self.base = sym['sb_mem']
        for n, x in (('io_sys', 0xFF), ('io_p1', 0xFF), ('io_p2', 0xFF), ('io_dsw1', 0xFF), ('io_dsw2', 0x60)):
            self.mem.w8(sym[n], x)
        self.run_to({sym['sim_wait']})        # (booted: init_render done; the game's own state is overwritten)
        self.v = Video()
        self.pmap = np.frombuffer((BUILD / 'sb_penmap.bin').read_bytes(), np.uint8)
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

    def sprites(self, ents, bank=0):
        """ents: {offset: (code, attributes, x, y)}: the sprite RAM's bank (latch Q5) $3800 + 256 bank"""
        self.mem.w8(self.sym['sb_latch'] + 5, bank)
        for o in SLOTS:
            self.poke(0x3800 + 0x100 * bank + o, bytes(ents.get(o, (0, 0, 0, 0))))
        self.poke(0x3800 + 0x100 * (1 - bank), bytes(range(256)))       # (the other bank holds noise: not drawn)

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
        self.r = mem.r16(sym['pub_r'] + 2 * (ready - 1))
        return mem.r32(sym['buf_base'] + 4 * (ready - 1))

    def check(self, label):
        base = self.render()
        got = ste_picture(self.mem, base, self.r)
        full = self.v.render_raw(self.tmem, select=self.mem.r8(self.sym['sb_latch'] + 5))[16:240]
        exp = self.pmap[np.ascontiguousarray(np.rot90(full, -1))]
        self.sprite_pixels += int((full >= 256).sum())
        n = int((got[:, LEFT:LEFT + PICW] != exp).sum())
        nb = band_bad(got, self.r)
        if n or nb:
            ys, xs = np.nonzero(got[:, LEFT:LEFT + PICW] != exp)
            print('%s: %d pixels differ, %d band pixels, first (y, x) %s' % (label, n, nb,
                                                                          list(zip(ys[:4].tolist(), xs[:4].tolist()))))
            if os.environ.get('DBG'):
                print('   rows', sorted(set(ys.tolist())), 'x', sorted(set(xs.tolist()))[:12], 'R', self.r, 'sc', self.tmem[0x3F80], 'bank', self.mem.r8(self.sym['sb_latch'] + 5))
            return False
        return True


def entry(code, colour, X, Y, flipx=False, flipy=False):
    """(code, attributes, x, y) of a sprite at picture X, Y: x = Y, y = 224 - X; raw flips (x: the turned rows, y: the
    columns); the code's bit 8 is attribute bit 5"""
    return (code & 255, (0x40 if flipx else 0) | (0x80 if flipy else 0) | colour & 15 | (0x20 if code & 256 else 0),
            Y & 255, (224 - X) & 255)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--tag', default='sbasketb_sim')
    args = ap.parse_args()
    h = Harness(args.tag)
    rnd = random.Random(7)
    v = h.v

    def holes(c):
        px = v.sprites[c] != 0
        rows = [r for r in range(16) if px[r].any()]
        inner = any((~px[r] & (np.cumsum(px[r]) > 0) & (np.cumsum(px[r][::-1])[::-1] > 0)).any() for r in range(16))
        return 0 < len(rows) < 16 and inner
    good = [c for c in range(384) if holes(c)]
    pairs = [(c, k) for c in good for k in range(16)]
    print('codes with transparent rows and holes: %d of 384' % len(good))

    def tiles(n=None):
        cells = range(0x800) if n is None else rnd.sample(range(0x800), n)
        for c in cells:
            h.poke(0x3000 + c, bytes((rnd.randrange(256),)))
        h.cells(cells)

    def scrolls():
        h.poke(0x3F80, bytes((rnd.randrange(256) if rnd.randrange(3) else 0,)))
        h.poke(0x3C20, bytes((rnd.choice((0, 0, 0, 1, 5, 15, 16, 255)),)))     # (the sprite palette bank: any byte)
    ok = bad = 0

    def pick():
        return rnd.choice(pairs)
    tiles()
    scrolls()
    steps = range(-18, 3) if not args.quick else (-17, -9, -1, 0)
    # the window's edges anywhere in a word: every position of R & 15 (the scroll P0 = (16 - scroll) & 255, R = P0 or P0 + 256)
    for scr in ((0, 3, 8, 13, 16, 29, 200, 233) if not args.quick else (0, 7, 200)):
        h.poke(0x3F80, bytes((scr,)))
        for edge in ('left', 'right'):
            for dx in steps:
                X = dx if edge == 'left' else PICW - 16 - dx
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
                h.sprites(ents, bank=dx & 1)
                if h.check('%s edge, X %d, scroll %d' % (edge, X, scr)):
                    ok += 1
                else:
                    bad += 1
    # the guard lines: sprites across the bottom edge (none reaches above line 0)
    for step in range(16 if not args.quick else 4):
        ents = {}
        for i, o in enumerate(SLOTS):
            c, col = pick()
            Y = rnd.choice((rnd.randrange(238, 256), rnd.randrange(230, 256), rnd.randrange(0, 256)))
            ents[o] = entry(c, col, rnd.randrange(-20, 236), Y, flipx=bool(i & 1), flipy=bool(i & 2))
        h.sprites(ents, bank=1)
        if h.check('guards, step %d' % step):
            ok += 1
        else:
            bad += 1
    # 64 KB crossings: sprites on the lines of a buffer that cross a 64 KB boundary
    lines = set()
    for i in range(3):
        base = h.mem.r32(h.sym['buf_base'] + 4 * i)
        nxt = (base + 0x10000) & ~0xFFFF
        if nxt < base + (PIC_TOP + 256 + 16) * LB:
            lines.add(((nxt - base) // LB) - PIC_TOP)
    crossings = 0
    for line in sorted(lines):
        for k in range(0, 16, 3):
            ents = {}
            for i, X in enumerate((-5, 30, 77, 120, 180, 215)):
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
            ents[o] = entry(c, col, -16 + (i * 29 + step * 5) % 256, (i * 37 + step * 7) % 256,
                            flipx=bool(i & 1), flipy=bool(i & 2))
        h.sprites(ents, bank=step & 1)
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
