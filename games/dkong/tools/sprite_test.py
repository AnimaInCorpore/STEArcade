"""Sprites at the game area's left and right edges: all 16 shifts, both flips, transparent holes, a 64 KB crossing.

draw_sprites runs on Musashi (engine/sprite_blit_test.py's harness: the STE Blitter model).  A sprite across an edge
(display column u0 -15 .. -1 or 209 .. 223) draws only its inner word (sprite_edge); it must equal the same columns of
that sprite drawn whole in the middle of the game area by the common path, and leave the side bands (and everything
else) as they were.  A sprite wholly outside draws nothing.  The next frame takes the sprite away: the restored
rectangle must leave the screen as the background was.

    python sprite_test.py [--prg run/dkong/DKONG.PRG --map build/dkong/dkong.map]
"""
import argparse, sys
from pathlib import Path
import numpy as np
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine68k import Register as R
from sprite_blit_test import Harness
from paths import ROOT, build_dir

BLOCK = 0x350000                     # the Z80 block (a6): the sprite list at $7000, bank $7D83 = 0
SCREEN = 0x400000                    # the draw screen (64 KB aligned like the program's)
BG_SCREEN = 0x420000                 # the background screen (restores)
LINES = 272                          # (16 lines past the 64 KB boundary)
GAME_X = 48                          # pixels


def chunks(colour):
    return b''.join((0xffff if colour >> p & 1 else 0).to_bytes(2, 'big') for p in range(4))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--prg', default=str(ROOT / 'run' / 'dkong' / 'DKONG.PRG'))
    ap.add_argument('--map', default=str(build_dir('dkong') / 'dkong.map'))
    a = ap.parse_args()
    h = Harness(a.prg, a.map)
    mem = h.mem
    marks = h.addr('tile_marks')

    def screen(base):
        raw = np.frombuffer(bytes(mem.r_block(base, 256 * LINES)), np.uint8).reshape(LINES, 32, 4, 2)
        words = (raw[..., 0].astype(np.uint16) << 8) | raw[..., 1]
        bits = (words[..., None] >> np.arange(15, -1, -1)) & 1
        return (bits * (1 << np.arange(4))[None, None, :, None]).sum(2).reshape(LINES, 512)

    def frame(entry):
        mem.w_block(BLOCK + 0x7000, bytes(entry) + bytes(512 - len(entry)))
        mem.w_block(marks, bytes(288))
        h.cpu.w_reg(R.A6, BLOCK)
        h.call(h.addr('draw_sprites'))
        return screen(SCREEN)

    def draw(code, flips, colour, u0, v0, bg=5, away=None):
        """the sprite at display column u0, line v0 on a screen of colour bg; away: the next frame without it"""
        mem.w_block(SCREEN, chunks(bg) * (32 * LINES))
        mem.w_block(BG_SCREEN, chunks(bg) * (32 * LINES))
        mem.w32(h.addr('draw_screen_address'), SCREEN)
        mem.w32(h.addr('bg_address'), BG_SCREEN)
        mem.w16(h.addr('draw_index'), 0)
        mem.w16(h.addr('bank16'), 0)
        mem.w8(BLOCK + 0x7d83, 0)
        h.call(h.addr('init_sprites'))
        got = frame((u0 + 23, code | (flips & 1) << 7, colour | (flips & 2) << 6, (v0 + 8) & 0xff))
        if away is not None:
            away.append(frame(()))
        return got

    # sprite shapes with transparent holes: opaque where the shape looks the same on two backgrounds
    shapes = []
    for code in range(1, 128):
        p5 = draw(code, 0, 1, 96, 100)[100:116, GAME_X + 96:GAME_X + 112]
        p10 = draw(code, 0, 1, 96, 100, bg=10)[100:116, GAME_X + 96:GAME_X + 112]
        opaque = (p5 == p10) & (p5 != 5)
        rows = [r for r in range(16) if opaque[r].any()]
        holes = sum(1 for r in rows for c in range(16)
                    if not opaque[r, c] and opaque[r, :c].any() and opaque[r, c + 1:].any())
        if 32 < opaque.sum() < 200 and holes:
            shapes.append(code)
        if len(shapes) == 4:
            break
    assert len(shapes) == 4, shapes
    blank = np.full((LINES, 512), 5)
    cases = clipped = culled = 0
    for v0 in (100, 248):                              # (248: lines 256 on lie past the 64 KB boundary)
        for code in shapes:
            for flips in range(4):
                colour = (code * 5 + flips) & 15
                for sh in range(16):
                    whole = draw(code, flips, colour, 96 + sh, v0)[:, GAME_X + 96 + sh:GAME_X + 112 + sh]
                    assert (whole != 5).any()
                    for u0 in (sh - 16, -16 - sh % 7, 208 + sh, min(224 + sh, 232)):
                        away = []
                        got = draw(code, flips, colour, u0, v0, away=away)
                        want = blank.copy()
                        for i in range(16):
                            if 0 <= u0 + i < 224:
                                want[:, GAME_X + u0 + i] = whole[:, i]
                        bad = got != want
                        assert not bad.any(), (v0, code, flips, sh, u0, int(bad.sum()),
                                               sorted(set(np.nonzero(bad)[1].tolist()))[:8])
                        assert np.array_equal(away[0], blank), (v0, code, flips, sh, u0, 'restore')
                        cases += 1
                        clipped += -16 < u0 < 0 or 208 < u0 < 224
                        culled += u0 <= -16 or u0 >= 224
    print(f'{cases} edge cases ({clipped} clipped, {culled} culled, the others whole; {len(shapes)} shapes with holes '
          f'{shapes}, both flips, 16 shifts, plain and across 64 KB, and the restore a frame later): exact, side bands '
          f'untouched')


if __name__ == '__main__':
    main()
