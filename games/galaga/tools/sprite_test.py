"""Sprites at the game picture's left and right edges: all 16 shifts, 16- and 32-wide (double) sprites, flip x (lines
drawn upwards), transparent holes, plain and across a 64 KB boundary, and the restore after a move.

draw_sprites runs on Musashi with one sprite entry.  A part across an edge draws only its inner destination word
(sprites.s edge_blits); the picture must equal the same columns of that sprite drawn whole in the middle of the
picture (the generated / generic routines), and the side bands (left and right of the 224 pixels, every line) keep
their bytes.  A sprite wholly in a band draws nothing.  Then the edge sprite moves to the middle: its restore (the
record's inner chunk only) must leave the bands as they were.

    python sprite_test.py [DIR]          (DIR: GALAGA.PRG and galaga.map; default run/galaga_sim and its map)
"""
import os
import sys
from pathlib import Path

sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "engine")]
import numpy as np
from machine68k import Register as R
from sim import Sim
from paths import ROOT, build_dir

STOP = 0x700
DISP_TOP, GAME_X, STRIDE = 32, 24, 256
LINE = 100                       # display line of the sprite's top
SPAN = range(DISP_TOP + LINE - 8, DISP_TOP + LINE + 40)     # buffer lines looked at
BG = b"\xff\xff\x00\x00\xff\xff\x00\x00"                     # a chunk of colour 5
BAND = b"\x00\x00\xff\xff\xff\xff\x00\x00"                   # colour 6: the background's side bands (restores)


def main():
    if len(sys.argv) > 1:
        d = Path(sys.argv[1])
        prg, mapfile = d / "GALAGA.PRG", d / "galaga.map"
    else:
        d = ROOT / "run" / "galaga_sim"
        prg, mapfile = d / "GALAGA.PRG", build_dir("galaga") / "galaga.map"
    s = Sim(str(prg), ram_kib=16384, run_dir=d)
    s.mem.set_trace_mode(True)
    syms = s.symbols(mapfile)
    sym = lambda k: s.base + syms[k]
    cpu, mem = s.cpu, s.mem
    ram = sym("g_ram")
    source = 0x200000
    src = bytearray(BG * 32 * 384)
    for line in range(384):
        for x in list(range(0, GAME_X, 8)) + list(range(GAME_X + 112, STRIDE, 8)):
            src[line * STRIDE + x:line * STRIDE + x + 8] = BAND
    mem.w_block(source, bytes(src))
    mem.w32(sym("bg_address"), source)

    def call(addr):
        cpu.w_sr(0x2700)
        cpu.w_reg(R.A7, 0x8000)
        mem.w32(0x8000, STOP)
        cpu.w_pc(addr)
        for _ in range(200000):
            if cpu.r_pc() == STOP:
                return
            cpu.execute(1)
        raise AssertionError("draw_sprites did not return")

    def entry(code, colour, flags, left):
        """one sprite with its leftmost display column at `left` (y = left - 239: see draw_part's u0)"""
        for off, data in ((0xB80, (code, colour)), (0x1380, ((left - 239) & 255, 40 + LINE)), (0x1B80, (flags, 0))):
            mem.w_block(ram + off, bytes(data) + bytes(126))

    def draw(screen, keep=False):
        if not keep:
            mem.w_block(screen, BG * 32 * 384)
            call(sym("init_sprites"))
            mem.w_block(sym("cell_content"), b"\xff" * 416)        # (restores copy the background)
        mem.w_block(sym("tile_marks"), bytes(416))
        mem.w_block(sym("spr_marks"), bytes(416))
        mem.w16(sym("draw_index"), 0)
        mem.w32(sym("draw_screen_address"), screen)
        call(sym("draw_sprites"))
        raw = np.frombuffer(bytes(mem.r_block(screen + SPAN[0] * STRIDE, len(SPAN) * STRIDE)), np.uint8)
        raw = raw.reshape(len(SPAN), 32, 4, 2)
        words = (raw[..., 0].astype(np.uint16) << 8) | raw[..., 1]
        bits = (words[..., None] >> np.arange(15, -1, -1)) & 1
        return (bits * (1 << np.arange(4))[None, None, :, None]).sum(2).reshape(len(SPAN), 512)   # x 48 = column 0

    plain = 0x300000
    crossing = 0x3F0000 - (DISP_TOP + LINE + 4) * STRIDE          # (the sprite's lines 4 on lie above 64 KB)
    entry(0, 0, 0, 230)
    assert (draw(plain) == 5).all()
    codes = []
    for code in range(128):
        entry(code, 1, 0, 96)
        p = draw(plain)
        o = (p[:, 48 + 96:48 + 112] != 5).sum()
        if 40 < o < 180 and len(np.unique(p)) > 2:
            codes.append(code)
        if len(codes) == 4:
            break
    cases = clipped = culled = 0
    for screen in (plain, crossing):
        for code in codes:
            for flags in (0, 1, 2, 8, 9, 12):               # flip x, flip y, 32 wide, 32 wide flipped, double both
                width = 32 if flags & 8 else 16
                for sh in range(16):
                    entry(code, 1, flags, 96 + sh)
                    whole = draw(screen)[:, 48 + 96 + sh:48 + 96 + sh + width]
                    assert (whole != 5).any() and (whole == 5).any()          # opaque pixels and holes
                    lo, hi = (-15, 240) if width == 16 else (-31, 224)       # (what the arcade's y byte can say)
                    for left in sorted({sh - width, sh - 16, 224 - width + sh, 208 + sh, 224 + sh}):
                        if not lo <= left <= hi:
                            continue
                        entry(code, 1, flags, left)
                        got = draw(screen)
                        want = np.full_like(got, 5)
                        for i in range(width):
                            if 0 <= left + i < 224:
                                want[:, 48 + left + i] = whole[:, i]
                        assert np.array_equal(got, want), (hex(screen), code, flags, sh, left, int((got != want).sum()))
                        across = left < 0 < left + width or left < 224 < left + width
                        clipped += across
                        culled += left >= 224 or left + width <= 0
                        cases += 1
                        if across:
                            # moved to the middle: the restore of the edge part leaves the bands alone
                            entry(code, 1, flags, 96 + sh)
                            moved = draw(screen, keep=True)
                            assert (moved[:, :48] == 5).all() and (moved[:, 48 + 224:] == 5).all(), (
                                "restore touched a band", hex(screen), code, flags, sh, left)
                            assert np.array_equal(moved[:, 48 + 96 + sh:48 + 96 + sh + width], whole)
    print("%d edge cases (%d across an edge, %d culled; %d sprites, flips and double sizes, 16 shifts, a 64 KB "
          "crossing): exact, side bands untouched by draws and restores, transparent holes preserved" % (
              cases, clipped, culled, len(codes)))
    s.m.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
