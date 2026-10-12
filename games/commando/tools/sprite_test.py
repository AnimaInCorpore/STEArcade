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

    def draw(ring, code, x):
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
            rects.append((mem.r32(p) - ring, mem.r16(p + 8), mem.r16(p + 10)))   # (offset, words, lines)
            p += 12
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
                    for off, words, lines in rects:  # (the damage: inside the window's chunks only)
                        c0 = (off & 255) - 24
                        assert 0 <= c0 and c0 + 2 * words <= 112, (hex(ring), code, sh, x, rects)
                    cases += 1
                    clipped += x < 0 or x > 208
    print(f'PASS: {cases} edge cases ({clipped} clipped across an edge; {len(codes)} sprites with holes, 16 shifts, '
          f'a 64 KB crossing): exact, side bands untouched, damage inside the window')


if __name__ == '__main__':
    main()
