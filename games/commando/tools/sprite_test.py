"""Sprites at the window's left and right edges: all 16 shifts, transparent holes, a 64 KB crossing.

draw_sprites (get_object_bake, the generated routines, generic_part, sprite_edge / clip_part) runs on Musashi (the sim
build, after its boot).  A sprite across an edge draws only its inner word; it must equal the same columns of that
sprite drawn whole in the middle of the window, and leave the side bands (and everything else) as they were.  Its
damage (restored from the twin lines next time) is the inner chunk only.  Sprites at the top and bottom stay whole
(render_test.py 4 edges).

    python sprite_test.py
"""
import sys
from pathlib import Path
import numpy as np
sys.path[:0] = [str(Path(__file__).resolve().parents[3] / 'engine'), str(Path(__file__).resolve().parents[1] / 'ref')]
from sim import Sim, TRAP1
from machine68k import Register as R
from machine import BUILD
from paths import ROOT

BG = b'\xff\xff\x00\x00\xff\xff\x00\x00'        # (a chunk of colour 5)
LINES = 24
Y = 4                                            # (the sprite's lines 4 .. 19 of the 24)


def main():
    run = ROOT / 'run' / 'commando_sim'
    s = Sim(str(run / 'COMMANDO.PRG'), ram_kib=16384, run_dir=run)
    sym = {k: v + s.base for k, v in s.symbols(BUILD / 'commando_sim.map').items()}
    cpu, mem = s.cpu, s.mem
    bad = sym['z80_badpc']
    word = mem.r16(sym['render_frame']); mem.w16(sym['render_frame'], 0x4E75)
    n = 0
    while cpu.r_pc() != sym['sim_wait']:            # (the boot: caches, pools, Blitter set-up)
        cpu.execute(2000); n += 1
        pc = cpu.r_pc()
        if pc in (bad, bad + 4) or s.terminated: raise RuntimeError(f'CPU stopped at {pc - s.base:06x}')
        if pc == TRAP1: s.gemdos()
        assert n < 100000, 'boot timeout'
    mem.w16(sym['render_frame'], word)
    ret, dmg = 0xEF0000, 0xEF0100
    mem.w16(ret, 0x4E71)
    buf = sym['sprite_buffer']

    def draw(ring, code, x, ring_addr=0x400000):
        mem.w32(sym['ring_addr'], ring_addr)            # (the buffer's line 0: the twin boundary is RING_H lines below)
        mem.w32(sym['draw_base'], ring)
        mem.w16(sym['cur_top'], 0)
        mem.w32(sym['dmg_ptr'], dmg)
        mem.w_block(ring, BG * 32 * LINES)
        mem.w_block(buf, bytes(0x180))             # (x + 16 = 0: hidden)
        raw_y = 240 - Y
        mem.w_block(buf, bytes([code & 255, (code >> 8) << 6, x + 16, raw_y]))
        cpu.w_reg(R.A7, 0xEEFF00); mem.w32(0xEEFF00, ret)
        cpu.w_sr(0x2700); cpu.w_pc(sym['draw_sprites'])
        k = 0
        while cpu.r_pc() != ret:
            cpu.execute(1)
            k += 1
            assert k < 200000, 'sprite stopped'
        raw = np.frombuffer(bytes(mem.r_block(ring, 256 * LINES)), np.uint8).reshape(LINES, 32, 4, 2)
        words = (raw[..., 0].astype(np.uint16) << 8) | raw[..., 1]
        bits = (words[..., None] >> np.arange(15, -1, -1)) & 1
        pic = (bits * (1 << np.arange(4))[None, None, :, None]).sum(2).reshape(LINES, 512)   # x 48 = window x 0
        rects = []
        p = dmg
        while p < mem.r32(sym['dmg_ptr']):
            rects.append((mem.r32(p) - ring, mem.r16(p + 8), mem.r16(p + 10), mem.r32(p + 4) - mem.r32(p)))
            p += 12                                 # (offset, words, lines, source - destination)
        return pic, rects

    codes = []
    for code in range(1, 768):                      # (sprites with transparent holes and opaque pixels)
        p, _ = draw(0x600000, code, 96)
        o = (p[Y:Y + 16, 144:160] != 5).sum()
        if 32 < o < 200:
            codes.append(code)
        if len(codes) == 4:
            break
    cases = clipped = 0
    for ring in (0x600000, 0x6F0000 - 10 * 256):   # (the second: lines 10 on lie above a 64 KB boundary)
        for code in codes:
            for sh in range(16):
                whole, _ = draw(ring, code, 96 + sh)
                whole = whole[:, 144 + sh:160 + sh]
                assert (whole != 5).any()
                for x in (sh - 16, 208 + sh):
                    if x == -16:
                        continue                   # (x + 16 = 0: hidden)
                    got, rects = draw(ring, code, x)
                    want = np.full_like(got, 5)
                    for i in range(16):
                        if 0 <= x + i < 224:
                            want[:, 48 + x + i] = whole[:, i]
                    assert np.array_equal(got, want), (hex(ring), code, sh, x, int((got != want).sum()))
                    for off, words, lines, _ in rects:  # (the damage: inside the window's chunks only)
                        c0 = (off & 255) - 24
                        assert 0 <= c0 and c0 + 2 * words <= 112, (hex(ring), code, sh, x, rects)
                    cases += 1
                    clipped += x < 0 or x > 208
    # The damage across the twin boundary (buffer line RING_H = ring_addr + RING_H lines): split there, each piece's
    # source its twin (RING_H lines below the boundary's upper side, above on its lower side); the same rows as drawn
    # away from it.
    ring_h, splits = 320, 0
    for code in codes:
        for sh in (0, 5):
            _, plain = draw(0x600000, code, 96 + sh, ring_addr=0x600000 - 100 * 256)
            want = {(o & 255, (o >> 8) + i) for o, w, n, _ in plain for i in range(n)}
            for k in range(-2, 24):                 # (the window's line 0 at buffer line RING_H - k)
                base = 0x700000
                got, rects = draw(base, code, 96 + sh, ring_addr=base - (ring_h - k) * 256)
                rows = set()
                for o, w, n, d in rects:
                    first = (o >> 8) + ring_h - k       # (buffer lines)
                    assert first + n <= ring_h or first >= ring_h, (code, sh, k, rects)
                    assert d == (ring_h * 256 if first < ring_h else -ring_h * 256), (code, sh, k, rects)
                    rows |= {(o & 255, (o >> 8) + i) for i in range(n)}
                assert rows == want, (code, sh, k, rects, plain)
                splits += len(rects) > (1 if sh == 0 else 1)
                cases += 1
    print(f'PASS: {cases} cases ({clipped} clipped across an edge, {splits} damaged across the twin boundary; {len(codes)} '
          f'sprites with holes, 16 shifts, a 64 KB crossing): exact, side bands untouched, damage inside the window and '
          f'split at the twin boundary')


if __name__ == '__main__':
    main()
