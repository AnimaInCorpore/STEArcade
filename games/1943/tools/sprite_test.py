"""Sprites at the window's left and right edges: all 16 shifts, transparent holes, a 64 KB crossing.

draw_sprites (sprite_get, sprite_part) runs on Musashi.  A sprite across an edge draws only its inner word
(clip_part); it must equal the same columns of that sprite drawn whole in the middle of the window by its generated
routine, and leave the side band (and everything else) as it was.  A sprite wholly in the right band draws nothing.
"""
import sys
from pathlib import Path
import numpy as np
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from sim import Sim
from machine68k import Register as R
from paths import ROOT, build_dir

BG = b'\xff\xff\x00\x00\xff\xff\x00\x00'        # (a chunk of colour 5)
LINES = 24


def main():
    run = ROOT / 'run' / '1943_sim'
    s = Sim(str(run / '1943.PRG'), ram_kib=16384, run_dir=run)
    sym = {k: v + s.base for k, v in s.symbols(build_dir('1943') / '1943_sim.map').items()}
    cpu, mem = s.cpu, s.mem
    mem.w32(sym['pool_ptr'], sym['pool'])
    mem.w16(sym['pool_epoch'], 1)
    ret, lst, dmg = 0x2F0000, 0x2F0100, 0x300000
    mem.w16(ret, 0x4E71)

    def draw(ring, code, colour, x):
        mem.w32(sym['ring_addr'], ring)
        mem.w16(sym['cur_top'], 0)
        mem.w32(sym['dmg_ptr'], dmg)
        mem.w_block(ring, BG * 32 * LINES)
        for i, v in enumerate((code, colour, 4, x)):
            mem.w16(lst + 2 * i, v & 0xFFFF)
        cpu.w_reg(R.A0, lst); cpu.w_reg(R.A1, lst + 8)
        cpu.w_reg(R.A7, 0x2EFF00); mem.w32(0x2EFF00, ret)
        cpu.w_sr(0x2700); cpu.w_pc(sym['draw_sprites'])
        n = 0
        while cpu.r_pc() != ret:
            cpu.execute(1)
            n += 1
            assert n < 100000, 'sprite stopped'
        raw = np.frombuffer(bytes(mem.r_block(ring, 256 * LINES)), np.uint8).reshape(LINES, 32, 4, 2)
        words = (raw[..., 0].astype(np.uint16) << 8) | raw[..., 1]
        bits = (words[..., None] >> np.arange(15, -1, -1)) & 1
        return (bits * (1 << np.arange(4))[None, None, :, None]).sum(2).reshape(LINES, 512)   # x 48 = window x 0

    bg = draw(0x380000, 0, 0, 300)                 # (culled: the background alone)
    assert (bg == 5).all()
    # sprite codes with transparent holes and opaque pixels
    codes = []
    for code in range(1, 2048):
        p = draw(0x380000, code, 1, 96)
        o = (p[4:20, 144:160] != 5).sum()
        if 32 < o < 200:
            codes.append(code)
        if len(codes) == 4:
            break
    cases = clipped = 0
    for ring in (0x380000, 0x3F0000 - 10 * 256):          # (the second: lines 6 on lie above a 64 KB boundary)
        for code in codes:
            for sh in range(16):
                whole = draw(ring, code, 1, 96 + sh)[:, 144 + sh:160 + sh]
                assert (whole != 5).any()
                for x in (sh - 16, 208 + sh, 224 + sh):
                    if x == -16:
                        continue                       # (sprite_lists culls it)
                    got = draw(ring, code, 1, x)
                    want = np.full_like(got, 5)
                    for i in range(16):
                        if 0 <= x + i < 224:
                            want[:, 48 + x + i] = whole[:, i]
                    assert np.array_equal(got, want), (ring, code, sh, x, int((got != want).sum()))
                    cases += 1
                    clipped += 0 < x + 15 and x < 0 or 208 < x < 224
    print(f'{cases} edge cases ({clipped} clipped, the others inside or culled; {len(codes)} sprites, 16 shifts, '
          f'a 64 KB crossing): exact, side bands untouched, transparent holes preserved')


if __name__ == '__main__':
    main()
