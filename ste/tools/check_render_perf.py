"""Exercise assembled renderers directly, without game/VBL scheduling.

Run build.py --sim first, then python check_render_perf.py. The optional
--baseline directory contains DKSIM.PRG and its matching dkong.map.
"""
import argparse
import random
from pathlib import Path

import numpy as np
from machine68k import Register as R
from sim import Sim, RUN, STE
from sprites import Gfx, display_bitmap, runs_of, line_params


class Renderer:
    def __init__(self, prg, mapping, repair_tile_bug=False):
        self.s = Sim(prg)
        self.syms = self.s.symbols(mapping)
        self.repair_tile_bug = repair_tile_bug
        self.bg = 0x400000
        self.screens = (0x410000, 0x420000)
        if repair_tile_bug:
            original = self.s.blitter.run
            def repaired_restore():
                blitter = self.s.blitter
                if blitter.reg16(0xA2E) == 2 and blitter.reg16(0xA22) == 234:
                    # Repair the old bottom-edge address carry as well.
                    screen = self.s.mem.r32(self.s.base + self.syms['draw_screen_address'])
                    for off, address in ((0xA24, self.bg), (0xA32, screen)):
                        self.s.io[off] = address >> 24
                        self.s.io[off + 1] = address >> 16
                original()
            self.s.blitter.run = repaired_restore
        self.s.mem.w16(0x700, 0x60FE)
        self.set32('bg_address', self.bg)
        self.call('init_render')

    def set32(self, name, value):
        self.s.mem.w32(self.s.base + self.syms[name], value)

    def call(self, name):
        s = self.s
        s.cpu.w_sr(0x2700)
        s.cpu.w_reg(R.A7, 0x7FFC)
        s.mem.w32(0x7FFC, 0x700)
        s.cpu.w_reg(R.A6, s.base + self.syms['z80_block'])
        s.cpu.w_pc(s.base + self.syms[name])
        s.blitter.cycles = 0
        cycles = 0
        for _ in range(250000):
            if self.repair_tile_bug and s.cpu.r_pc() == s.base + self.syms['draw_tile']:
                # The old renderer calls mark_tile after loading a0, but
                # mark_tile clobbers a0. Repair that known bug in the oracle
                # only for dirty-screen draws, preserving background draws.
                ret = s.mem.r32(s.cpu.r_reg(R.A7)) - s.base
                if self.syms['draw_dirty_tiles'] <= ret < self.syms['clear_cells']:
                    s.cpu.w_reg(R.A0, s.mem.r32(s.base + self.syms['draw_screen_address']))
            r = s.cpu.execute(1)
            cycles += r.cycles
            pc = s.cpu.r_pc()
            if pc == 0x700:
                return cycles + s.blitter.cycles
            if pc in (0x500, 0x600):
                raise AssertionError('unexpected trap/exception at %x' % pc)
        raise AssertionError('renderer did not return')

    def frame(self, bank, tiles, entries, palette):
        s = self.s
        block = s.base + self.syms['z80_block']
        s.mem.w_block(block + 0x7400, bytes(tiles))
        s.mem.w_block(block + 0x6900, bytes(entries))
        s.mem.w8(block + 0x7D86, palette & 1)
        s.mem.w8(block + 0x7D87, palette >> 1)
        s.mem.w16(s.base + self.syms['draw_index'], bank)
        self.set32('draw_screen_address', self.screens[bank])
        cycles = self.call('render_frame')
        # Compare visible pixels, excluding padding erased by the old renderer.
        screen = np.frombuffer(bytes(s.mem.r_block(self.screens[bank], 65536)),
                               np.uint8).reshape(256, 256)
        return screen[:, 24:136].copy(), cycles

    def fresh_screen(self, bank):
        s = self.s
        descriptors = {k: bytes(s.mem.r_block(s.base + self.syms[k], n))
                       for k, n in [('spr_new_rect', 192), ('spr_new_routine', 384),
                                    ('spr_new_src', 384)]}
        rects = s.base + self.syms['spr_prev_rect'] + bank * 192
        saved = bytes(s.mem.r_block(rects, 192))
        s.mem.w_block(rects, bytes([255]) * 192)
        s.mem.w_block(0x430000, bytes(s.mem.r_block(self.bg, 65536)))
        self.set32('draw_screen_address', 0x430000)
        s.mem.w8(s.base + self.syms['spr_invalid'] + bank, 1)
        s.mem.w16(s.base + self.syms['spr_cache_bank'], 0xFFFF)
        self.call('render_sprites')
        for k, data in descriptors.items():
            assert data == bytes(s.mem.r_block(s.base + self.syms[k], len(data))), k
        screen = np.frombuffer(bytes(s.mem.r_block(0x430000, 65536)),
                               np.uint8).reshape(256, 256)
        s.mem.w_block(rects, saved)
        self.set32('draw_screen_address', self.screens[bank])
        return screen[:, 24:136].copy()


def entries_for(items):
    # y=0 is hidden; x on screen = y-23, screen row = raw x-8.
    entries = bytearray(384)
    for slot, (x, y, code, colour, fx, fy) in enumerate(items):
        entries[slot*4:slot*4+4] = bytes(((x + 23) & 255,
            code | (fy << 7), colour | (fx << 7), (y + 8) & 255))
    return entries


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--baseline', type=Path)
    args = ap.parse_args()
    gfx = Gfx()
    shapes = 0
    for code in range(128):
        for fx in range(2):
            for fy in range(2):
                lines = runs_of(display_bitmap(gfx, code, fx, fy))
                if not lines:
                    continue
                shapes += 1
                for shift in range(16):
                    for line in lines:
                        p = line_params(line, shift)
                        assert (p['off'] % 256) // 8 + p['n'] <= 2
    print('two-chunk bounds:', shapes, 'shapes, all 16 shifts', flush=True)
    rng = random.Random(17)
    tiles = bytearray([0x10] * 1024)
    scenes = []
    # Every shift, overlaps, clipped left/right edges and first/last rows.
    for shift in range(16):
        scenes.append((entries_for([(32+shift, 32, 0, 1, 0, 0),
            (40+shift, 40, 1, 2, 1, 0), (-15+shift, 0, 2, 3, 0, 1),
            (208+shift, 240, 3, 4, 1, 1)]), 0))
    for i in range(48):
        items = [(rng.randrange(-15, 224), rng.randrange(241),
                  rng.randrange(128), rng.randrange(16),
                  rng.randrange(2), rng.randrange(2)) for _ in range(24)]
        scenes.append((entries_for(items), (i // 12) % 4))
    scenes += [(entries_for([]), 0)] * 3
    inputs = []
    for scene, (entries, palette) in enumerate(scenes):
        # Render the scene twice into each buffer: covers descriptor reuse,
        # per-buffer history and the completely unchanged fast path.
        for repeat in range(4):
            if repeat == 2 and scene % 5 == 0:
                tiles[rng.randrange(1024)] = rng.randrange(256)
            bank = repeat & 1
            inputs.append((bank, bytes(tiles), bytes(entries), palette))
    # Musashi uses global CPU state: run each machine separately.
    total = [0, 0]
    expected_frames = []
    if args.baseline:
        old = Renderer(args.baseline / 'DKSIM.PRG', args.baseline / 'dkong.map',
                       repair_tile_bug=True)
        for values in inputs:
            expected, cost = old.frame(*values)
            expected_frames.append(expected)
            total[0] += cost
        del old
        print('baseline frames:', len(expected_frames), flush=True)
    current = Renderer(RUN / 'DKSIM.PRG', STE / 'build' / 'dkong.map')
    for frame, values in enumerate(inputs):
        got, cycles = current.frame(*values)
        total[1] += cycles
        if frame >= len(inputs) - 2:
            assert current.s.mem.r8(current.s.base + current.syms['cells_ready']) == 0
        fresh = current.fresh_screen(values[0])
        if not np.array_equal(got, fresh):
            np.savez(STE / 'build' / 'render_failure.npz', got=got, fresh=fresh,
                     entries=np.frombuffer(values[2], np.uint8), frame=frame)
        assert np.array_equal(got, fresh), ('fresh redraw', frame,
            int(np.count_nonzero(got != fresh)))
        if expected_frames:
            expected = expected_frames[frame]
            assert np.array_equal(got, expected), (frame,
                int(np.count_nonzero(got != expected)))
        if frame % 64 == 0:
            print('frames checked:', frame + 1, flush=True)
    print('frames checked:', len(inputs),
          'exact match to fresh redraw and repaired baseline' if expected_frames
          else 'exact match to fresh redraw')
    if expected_frames:
        print('simulated cycles, baseline/current:', *total,
              '(includes return-loop sampling; excludes arbitration)')


if __name__ == '__main__':
    main()
