"""Sprites at the picture's edges: render.s's render_frame (run/kungfum_sim on Musashi with its Blitter) against the
reference renderer, in the shown colours, over pictures made up for it.

    python sprite_test.py [--quick]

The Z80 block gets a tile map (random codes and colours, front colours 26-31 among them), the play state of floor
1 (scene 0) and a sprite list; render_frame draws it into a ring; the test plays the VBL (the ring is shown) and
compares the 256 x 256 picture (machine.Video.render_raw through the scene's pen map) and the side bands:
  * every window fine offset (Wx 0-15 and some more, the wrap at 512 too);
  * cells across the left and right edges at every pixel (so every shift, inside and outside), 1-, 2- and 4-cell
    sprites, flip x / y, codes with transparent rows and holes, sprites overlapping (the later on top);
  * cells whose rows cross a 64 KB boundary of a ring;
  * consecutive pictures: the sprites move, so the rings' damage is restored (into the bands too) and the window
    moves (the strips), all three rings in turn.
The bands must be black except, where the edge lies inside a word, between the edge and the clip boundary (a sprite
may show there: render.s); with Wx a multiple of 16 the clipping is exact.
"""
from pathlib import Path
import argparse
import pickle
import random
import sys
import numpy as np
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine68k import Register as R
from sim import Sim, TRAP1
from machine import Video
from paths import ROOT, build_dir
from render_test import ste_picture

BUILD = build_dir('kungfum')
LB, ROW_OFF = 424, 16


class Harness:
    def __init__(self):
        run = ROOT / 'run' / 'kungfum_sim'
        self.s = Sim(str(run / 'KUNGFUM.PRG'), run_dir=run, ram_kib=16384)
        s = self.s
        self.sym = {k: v + s.base for k, v in s.symbols(BUILD / 'kungfum_sim.map').items()}
        self.mem, self.cpu = s.mem, s.cpu
        sym = self.sym
        for i in range(3):
            self.mem.w8(sym['io_ports'] + i, 0xFF)
        self.mem.w8(sym['io_ports'] + 3, 0xFF)
        self.mem.w8(sym['io_ports'] + 4, 0xFD)
        self.run_to({sym['sim_wait']})        # (booted: init_render done; the game's own state is overwritten)
        self.a6 = sym['g_block'] + 0x8000
        self.v = Video()
        pal = pickle.loads((BUILD / 'kf_palettes.pkl').read_bytes())
        self.maps, self.pmap = pal['maps'], pal['panel_map']
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

    def render(self):
        """render_frame once (returning to sim_render_ret), then the VBL's part; -> the ring drawn, its Wx"""
        sym, mem, cpu = self.sym, self.mem, self.cpu
        for i in range(32):
            mem.w8(sym['tile_rows'] + i, 0xFF)
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
        ring = ready - 1
        return ring, mem.r16(sym['pub_wx'] + 2 * ring)

    def check(self, label):
        ring, wx = self.render()
        got = ste_picture(self.mem, self.sym, ring, wx)
        z = self.zmem
        scroll = z[0xA000] | z[0xB000] << 8
        raw = self.v.render_raw(z, z[0xC000:0xC100], scroll)[:, 128:384]
        exp = np.zeros((256, 256), np.uint8)
        exp[:48] = self.pmap[raw[:48]]
        exp[48:] = self.maps[0][raw[48:]]
        n = int((got[:, 32:288] != exp).sum())
        self.sprite_pixels += int((raw >= 256).sum())
        cl, cr = (wx + 32) & ~15, (wx + 288 + 15) & ~15
        allow = np.zeros(320, bool)
        allow[max(0, cl - wx):32] = True
        allow[288:min(320, cr - wx)] = True
        band = (got != 0) & ~allow[None, :]
        band[:, 32:288] = False
        band[:48] = got[:48] != 0
        band[:48, 32:288] = False
        nb = int(band.sum())
        if n or nb:
            ys, xs = np.nonzero(got[:, 32:288] != exp)
            print('%s: %d pixels differ, %d band pixels (wx %d) first %s' % (label, n, nb, wx,
                                                                         list(zip(ys[:4].tolist(), xs[:4].tolist()))))
            return False
        return True


def sprite_entry(code, colour, x, y, flipx=False, flipy=False):
    """the 8 bytes for a sprite whose top-left cell is at MAME's (x, y) (x in the 384 wide bitmap)"""
    y9 = (256 + 128 - 15 - y) & 0x1FF
    return bytes((colour & 0x1F, 0, y9 & 0xFF, y9 >> 8, code & 0xFF, (code >> 8) & 7 | (0x40 if flipx else 0) |
                  (0x80 if flipy else 0), x & 0xFF, (x >> 8) & 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true')
    args = ap.parse_args()
    h = Harness()
    rnd = random.Random(5)
    v = h.v
    height = bytes(v.height)
    # codes: single cells with holes (a transparent pixel between opaque ones in a row) and transparent rows,
    # and the first codes of 2- and 4-cell sprites
    def holes(c):
        px = v.sprites[c]
        rows = [r for r in range(16) if px[r].any()]
        inner = any(((px[r] == 0) & (np.cumsum(px[r] != 0) > 0) & (np.cumsum((px[r] != 0)[::-1])[::-1] > 0)).any()
                    for r in range(16))
        return len(rows) < 16 and inner
    singles = [c for c in range(1024) if height[c >> 5] == 0 and holes(c)]
    doubles = [c for c in range(0, 1024, 2) if height[c >> 5] == 1 and holes(c)]
    quads = [c for c in range(0, 1024, 4) if height[c >> 5] == 2 and holes(c)]
    print('codes with holes: %d single, %d double, %d quad' % (len(singles), len(doubles), len(quads)))
    h.poke(0xE000, bytes([4]))                   # play, floor 1: scene 0
    h.poke(0xE080, bytes([0]))
    codes = bytes(rnd.randrange(256) for _ in range(0x800))
    attrs = bytes(rnd.randrange(256) for _ in range(0x800))
    h.poke(0xD000, codes)
    h.poke(0xD800, attrs)
    ok = bad = 0
    wxs = list(range(16)) + [16, 31, 200, 470, 480, 495, 496, 511] if not args.quick else [0, 5, 16, 495]
    for wx in wxs:
        scroll = (wx - 96) & 0xFFFF
        h.poke(0xA000, bytes([scroll & 0xFF]))
        h.poke(0xB000, bytes([(scroll >> 8) & 0xFF]))
        steps = range(-18, 3) if not args.quick else (-16, -9, -1, 0)
        for edge, base in (('left', 128), ('right', 384 - 16)):
            for dx in steps:
                x = base + dx if edge == 'left' else base - dx
                spr = bytearray(256)
                ents = [
                    sprite_entry(rnd.choice(singles), rnd.randrange(32), x, 100 + rnd.randrange(20)),
                    sprite_entry(rnd.choice(doubles), rnd.randrange(32), x, 160, flipx=True),
                    sprite_entry(rnd.choice(quads), rnd.randrange(32), x + (8 if edge == 'left' else -8), 200,
                                 flipy=bool(dx & 1)),
                    sprite_entry(rnd.choice(singles), rnd.randrange(32), 200 + dx, 120, flipx=bool(dx & 2),
                                 flipy=True),
                    sprite_entry(rnd.choice(singles), rnd.randrange(32), 204 + dx, 126),   # (over the one before)
                ]
                for i, e in enumerate(ents):
                    spr[8 * (4 + i):8 * (5 + i)] = e
                h.poke(0xC000, spr)
                if h.check('%s edge, wx %d, x %d' % (edge, wx, x)):
                    ok += 1
                else:
                    bad += 1
    # 64 KB crossings: a sprite at every 4th line through a ring's 64 KB boundary
    rb = [h.mem.r32(h.sym['ring_base'] + 4 * i) for i in range(3)]
    crossings = 0
    h.poke(0xA000, bytes([0x30]))
    h.poke(0xB000, bytes([0]))
    lines = []
    for ring_base in rb:
        nxt = (ring_base + 0x10000) & ~0xFFFF
        while nxt < ring_base + 304 * LB:
            line = (nxt - ring_base) // LB
            if 48 + ROW_OFF + 16 <= line < 256 + ROW_OFF:
                lines.append(line)
            nxt += 0x10000
    for line in lines:
        for k in range(0, 16, 3):
            spr = bytearray(256)
            for i, x in enumerate((140, 180, 230, 300, 370)):
                spr[8 * (4 + i):8 * (5 + i)] = sprite_entry(rnd.choice(singles + doubles), rnd.randrange(32), x + k,
                                                            line - ROW_OFF - k)
            h.poke(0xC000, spr)
            for _ in range(3):                    # (each ring in turn)
                crossings += 1
                if h.check('64 KB crossing, line %d' % (line - k)):
                    ok += 1
                else:
                    bad += 1
    print('64 KB crossings tried: %d pictures' % crossings)
    # consecutive pictures: moving sprites and a moving window
    for step in range(60 if not args.quick else 12):
        wx = (300 + step * 3 - (step // 20) * 70) & 511
        scroll = (wx - 96) & 0xFFFF
        h.poke(0xA000, bytes([scroll & 0xFF]))
        h.poke(0xB000, bytes([scroll >> 8]))
        spr = bytearray(256)
        for i in range(10):
            spr[8 * (4 + i):8 * (5 + i)] = sprite_entry(rnd.choice(singles + doubles + quads), rnd.randrange(32),
                                                        110 + (i * 29 + step * 5) % 290, 60 + (i * 37 + step * 7) % 190,
                                                        flipx=bool(i & 1))
        h.poke(0xC000, spr)
        if h.check('sequence step %d' % step):
            ok += 1
        else:
            bad += 1
    print('sprite pixels compared: %d' % h.sprite_pixels)
    print('%s: %d pictures exact, %d differ' % ('PASS' if not bad else 'FAIL', ok, bad))
    return int(bad != 0)


if __name__ == '__main__':
    sys.exit(main())
