"""Sprites at the picture's edges: render.s's render_frame (run/gyruss_sim on Musashi with its Blitter) against the
reference renderer, in the shown colours, over pictures made up for it.

    python sprite_test.py [--quick] [--tag gyruss_sim]

The Z80 block gets a tile map (random codes and colours, front tiles (colour bit 4) among them), the sub CPU's sprite RAM
a sprite list (and the bands' log: entries given to other objects at a line, sub.s), render_frame draws it into a
buffer; the test plays the VBL and compares the 224 x 256 picture (machine.Video.render_raw per band, turned, through
the pen map) and the side bands (black: the edges lie on 16-pixel groups, clipping is exact):
  * sprites across the left and right edges at every pixel (every shift, inside and outside), flips, codes with
    transparent rows and holes, sprites overlapping (the first entry on top), over front tiles;
  * sprites whose rows cross a 64 KB boundary of a buffer;
  * entries given to another object at a line (the old content above it, the new below: clip_slot);
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
from machine import Video, sprite_bands
from paths import ROOT, build_dir
from render_test import ste_picture

BUILD = build_dir('gyruss')
LB, PIC_TOP = 160, 10


class Harness:
    def __init__(self, tag):
        run = ROOT / 'run' / tag
        self.s = s = Sim(str(run / 'GYRUSS.PRG'), run_dir=run, ram_kib=16384)
        self.sym = sym = {k: v + s.base for k, v in s.symbols(BUILD / (tag + '.map')).items()}
        self.mem, self.cpu = s.mem, s.cpu
        for off, x in ((0, 0x3B), (4, 0xFF), (5, 0xFF), (6, 0xFF), (7, 0xFF), (8, 0xFE)):
            self.mem.w8(sym['io_in'] + off, x)
        self.run_to({sym['sim_wait']})        # (booted: init_render done; the game's own state is overwritten)
        self.a6 = sym['g_block'] + 0x8000
        self.v = Video()
        self.pmap = np.frombuffer((BUILD / 'gy_penmap.bin').read_bytes(), np.uint8)
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

    def sprites(self, ram, segs=()):
        """the sprite RAM (192 bytes: the final contents) and the bands' log [(entry, old 4 bytes, line)] in order"""
        sym, mem = self.sym, self.mem
        mem.w_block(sym['sub_ram'] + 0x40, bytes(ram))
        mem.w_block(sym['seg_head'], bytes(4 * 48))
        mem.w16(sym['seg_n'], len(segs))
        tail = {}
        for i, (e, old, line) in enumerate(segs):
            mem.w_block(sym['seg_list'] + 8 * i, bytes(old) + bytes([line >> 8, line & 255, 0, 0]))
            if e in tail:
                mem.w16(sym['seg_list'] + 8 * (tail[e] - 1) + 6, i + 1)
            else:
                mem.w16(sym['seg_head'] + 2 * e, i + 1)
            tail[e] = i + 1
            mem.w16(sym['seg_tail'] + 2 * e, i + 1)
        # the reference: the old contents at the start, the writes of the final ones at their lines
        s0 = bytearray(ram)
        writes = []
        first = {}
        for e, old, line in segs:
            if e not in first:
                first[e] = old
                s0[4 * e:4 * e + 4] = old
        last = {}
        for e, old, line in segs:
            if e in last:
                for k in range(4):
                    writes.append((last[e][1], 4 * e + k, old[k]))
            last[e] = (old, line)
        for e, (old, line) in last.items():
            for k in range(4):
                writes.append((line, 4 * e + k, ram[4 * e + k]))
        writes.sort(key=lambda w: w[0])
        self.bands = sprite_bands(bytes(s0), writes)

    def render(self):
        """render_frame once (returning to sim_render_ret), then the VBL's part; -> the buffer drawn"""
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
        return mem.r32(sym['buf_base'] + 4 * (ready - 1))

    def check(self, label):
        got = ste_picture(self.mem, self.render())
        raw = self.v.render_raw(self.zmem, self.bands)[16:240]
        exp = np.ascontiguousarray(np.rot90(self.pmap[raw], -1))
        self.sprite_pixels += int((raw < 256).sum())
        n = int((got[:, 48:272] != exp).sum())
        nb = int((got[:, :48] != 0).sum() + (got[:, 272:] != 0).sum())
        if n or nb:
            ys, xs = np.nonzero(got[:, 48:272] != exp)
            print('%s: %d pixels differ, %d band pixels, first (y, x) %s' % (label, n, nb,
                                                                          list(zip(ys[:4].tolist(), xs[:4].tolist()))))
            return False
        return True


def entry(bank, code, colour, X, Y, flipx=False, flipy=False):
    """the 4 bytes of a sprite at picture X (-17..), Y: raw x = Y, y byte = X + 17; flip x / y the raw ones"""
    return bytes((Y & 255, ((code & 0x7F) << 1) | bank,
                  (0x20 if code & 0x80 else 0) | (0 if flipx else 0x40) | (0x80 if flipy else 0) | colour & 15,
                  (X + 17) & 255))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--tag', default='gyruss_sim')
    args = ap.parse_args()
    h = Harness(args.tag)
    rnd = random.Random(7)
    v = h.v

    def holes(bank, c):
        px = np.rot90(v.sprites[bank][c], -1) != 0
        rows = [r for r in range(8) if px[r].any()]
        inner = any((~px[r] & (np.cumsum(px[r]) > 0) & (np.cumsum(px[r][::-1])[::-1] > 0)).any() for r in range(8))
        return 0 < len(rows) < 8 and inner
    codes = [(b, c) for b in (0, 1) for c in range(256) if holes(b, c)]
    print('codes with transparent rows and holes: %d' % len(codes))
    colours = bytes(rnd.randrange(256) & ~0x20 | (0x20 if rnd.randrange(2) else 0) for _ in range(0x400))
    h.poke(0x8000, colours)
    h.poke(0x8400, bytes(rnd.randrange(256) for _ in range(0x400)))
    print('front cells: %d' % sum(1 for c in colours if c & 0x10))
    ok = bad = 0

    def pick():
        return rnd.choice(codes)
    steps = range(-18, 3) if not args.quick else (-17, -9, -1, 0)
    for edge in ('left', 'right'):
        for dx in steps:
            X = dx if edge == 'left' else 224 - 16 - dx
            ram = bytearray(192)
            ents = [entry(*pick(), rnd.randrange(16), X, 40 + rnd.randrange(20)),
                    entry(*pick(), rnd.randrange(16), X, 120, flipx=True),
                    entry(*pick(), rnd.randrange(16), X + (4 if edge == 'left' else -4), 200, flipy=bool(dx & 1)),
                    entry(*pick(), rnd.randrange(16), 100 + dx, 80, flipx=bool(dx & 2), flipy=True),
                    entry(*pick(), rnd.randrange(16), 103 + dx, 84)]           # (under the one before: entry 4)
            for i, e in enumerate(ents):
                ram[4 * i:4 * i + 4] = e
            h.sprites(ram)
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
        for k in range(0, 8, 2):
            ram = bytearray(192)
            for i, X in enumerate((-5, 30, 77, 150, 215)):
                ram[4 * i:4 * i + 4] = entry(*pick(), rnd.randrange(16), X + k, max(0, line - k))
            h.sprites(ram)
            for _ in range(3):                    # (each buffer in turn)
                crossings += 1
                if h.check('64 KB crossing, line %d' % (line - k)):
                    ok += 1
                else:
                    bad += 1
    print('64 KB crossings tried: %d pictures (lines %s)' % (crossings, sorted(lines)))
    # entries given to other objects at a line (the bands)
    for step in range(30 if not args.quick else 6):
        ram = bytearray(192)
        for i in range(12):
            ram[4 * i:4 * i + 4] = entry(*pick(), rnd.randrange(16), rnd.randrange(-16, 224), rnd.randrange(250))
        segs = []
        for _ in range(rnd.randrange(1, 8)):
            e = rnd.randrange(12)
            segs.append((e, entry(*pick(), rnd.randrange(16), rnd.randrange(-16, 224), rnd.randrange(250)),
                         rnd.randrange(16, 240)))
        segs.sort(key=lambda s: s[2])
        h.sprites(ram, segs)
        if h.check('bands, step %d' % step):
            ok += 1
        else:
            bad += 1
    # consecutive pictures: moving sprites
    for step in range(60 if not args.quick else 12):
        ram = bytearray(192)
        for i in range(48):
            ram[4 * i:4 * i + 4] = entry(*pick(), rnd.randrange(16), -16 + (i * 29 + step * 5) % 256,
                                         (i * 37 + step * 7) % 250, flipx=bool(i & 1))
        h.sprites(ram)
        if h.check('sequence step %d' % step):
            ok += 1
        else:
            bad += 1
    print('sprite pixels compared: %d' % h.sprite_pixels)
    print('%s: %d pictures exact, %d differ' % ('PASS' if not bad else 'FAIL', ok, bad))
    return int(bad != 0)


if __name__ == '__main__':
    sys.exit(main())
