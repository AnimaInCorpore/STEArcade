"""Sprites at the window's left and right edges: all 16 shifts, transparent holes, a 64 KB crossing, both the shapes
with generated code and those of any_part, the window on a 16-pixel group (D802 0, 16, 32) and at a fine offset.

    python sprite_test.py

draw_sprites (get_object, sprite_part / sprite_edge) runs on Musashi over a buffer of colour 5.  The truth is the same
sprite drawn whole in the middle of the window.  Window on a group: a sprite across an edge draws only its inner word
(sprite_edge), equal to those columns of the whole sprite; everything else, the side bars too, stays as it was; its
damage is that one chunk.  Window at a fine offset (the edges inside a word): drawn whole, the window equal to the
whole sprite's columns, the 16 pixels beside the window black or untouched, nothing else changed.  Every changed byte
lies in a damage rectangle.
"""
import sys
from pathlib import Path
import numpy as np
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from sim import Sim, TRAP1
from machine68k import Register as R
from paths import ROOT, build_dir

BG = b'\xff\xff\x00\x00\xff\xff\x00\x00'        # (a chunk of colour 5)
LINES = 24
TOP = 4                                         # (the sprite's buffer line)


def main():
    run = ROOT / 'run' / 'gunsmoke_sim'
    s = Sim(str(run / 'GUNSMOKE.PRG'), ram_kib=16384, run_dir=run)
    sym = {k: v + s.base for k, v in s.symbols(build_dir('gunsmoke') / 'gunsmoke_sim.map').items()}
    cpu, mem = s.cpu, s.mem
    layers = sym['g_block'] + 0x8000 - 0x27FA
    word = mem.r16(sym['render_frame'])         # (the program's init, then draw_sprites alone)
    mem.w16(sym['render_frame'], 0x4E75)
    for _ in range(200000):
        cpu.execute(2000)
        if cpu.r_pc() == TRAP1:
            s.gemdos()
        if cpu.r_pc() == sym['sim_wait']:
            break
    else:
        raise RuntimeError('no sim_wait')
    mem.w16(sym['render_frame'], word)
    shape_tab = np.frombuffer(bytes(mem.r_block(sym['spr_shape'], 8192)), '>u2')
    ret, dmg = 0xA00000, 0xA10000
    mem.w16(ret, 0x4E71)

    def draw(base, code, x, wx, flip=0):
        mem.w32(sym['draw_base'], base)
        mem.w16(sym['cur_top'], 0)
        mem.w16(sym['cur_wx'], wx)
        mem.w32(sym['dmg_ptr'], dmg)
        mem.w_block(base, BG * 32 * LINES)
        bank = min(code >> 8, 3)
        mem.w8(layers, 32 | (code >> 8) - 3 if bank == 3 else 32)
        entries = bytearray(4 * 128)
        entries[0:4] = bytes([code & 255, bank << 6 | flip << 4 | 1, (x + 16) & 255, 240 - TOP])
        mem.w_block(sym['sprite_buffer'], bytes(entries))
        cpu.w_reg(R.A7, 0x9FFF00)
        mem.w32(0x9FFF00, ret)
        cpu.w_sr(0x2700)
        cpu.w_pc(sym['draw_sprites'])
        n = 0
        while cpu.r_pc() != ret:
            cpu.execute(1)
            n += 1
            assert n < 200000, 'draw_sprites stopped'
        raw = np.frombuffer(bytes(mem.r_block(base, 256 * LINES)), np.uint8).reshape(LINES, 32, 4, 2)
        words = (raw[..., 0].astype(np.uint16) << 8) | raw[..., 1]
        bits = (words[..., None] >> np.arange(15, -1, -1)) & 1
        pic = (bits * (1 << np.arange(4))[None, None, :, None]).sum(2).reshape(LINES, 512)
        # every changed byte inside a damage rectangle (destination, source, words a line, lines)
        changed = np.frombuffer(bytes(mem.r_block(base, 256 * LINES)), np.uint8) != np.frombuffer(BG * 32 * LINES, np.uint8)
        cover = np.zeros_like(changed)
        rects = []
        for p in range(dmg, mem.r32(sym['dmg_ptr']), 12):
            d, words_, lines = mem.r32(p), mem.r16(p + 8), mem.r16(p + 10)
            rects.append((d - base, words_, lines))
            for i in range(lines):
                o = d - base + 256 * i
                if 0 <= o < 256 * LINES:
                    cover[o:o + 2 * words_] = True
        if wx & 15:             # (fine offset: the 16 pixels beside the window go black; in the game they are black)
            side = np.zeros((LINES, 256), bool)
            for a, b in ((wx - 16, wx), (wx + 224, wx + 240)):
                side[:, a // 16 * 8:(b + 15) // 16 * 8] = True
            changed &= ~side.reshape(-1)
        assert not (changed & ~cover).any(), 'a change outside the damage'
        return pic, rects

    pic, _ = draw(0x800000, 0, 230, 48)           # (culled: the background alone)
    assert (pic == 5).all()
    gen, anyp = [], []                              # sprite codes with transparent holes, generated / any_part
    for code in range(2048):
        kind = gen if shape_tab[code * 2] != 0xFFFF else anyp
        if len(kind) >= 4:
            continue
        pic, _ = draw(0x800000, code, 96, 48)
        o = (pic[TOP:TOP + 16, 144:160] != 5).sum()
        if 32 < o < 200:
            kind.append(code)
        if len(gen) >= 4 and len(anyp) >= 2:
            break
    assert len(gen) == 4 and len(anyp) == 2, (gen, anyp)
    cases = clipped = whole_cases = 0
    for base in (0x800000, 0x8F0000 - 10 * 256):    # (the second: lines 10 on lie above a 64 KB boundary)
        for code in gen + anyp:
            for flip in (0, 1):
                if code in anyp and shape_tab[code * 2 + flip] != 0xFFFF:
                    continue
                for wx in (48, 64, 80, 53, 59):
                    for sh in range(16):
                        mid = 96 + ((sh - wx) & 15)         # (the middle at buffer shift sh)
                        pic, _ = draw(base, code, mid, wx, flip)
                        whole = pic[:, wx + mid:wx + mid + 16]
                        assert (whole != 5).any()
                        for x in range(-15, 224):
                            if (wx + x) & 15 != sh or 0 <= x <= 208:
                                continue
                            got, rects = draw(base, code, x, wx, flip)
                            want = np.full_like(got, 5)
                            for i in range(16):
                                if 0 <= x + i < 224:
                                    want[:, wx + x + i] = whole[:, i]
                            if wx & 15:                      # (fine offset: whole, the 16 beside the window black)
                                side = np.zeros(512, bool)
                                side[wx - 16:wx] = side[wx + 224:wx + 240] = True
                                ok = (got == want) | (side[None, :] & ((got == 0) | (got == 5)))
                                assert ok.all(), (base, code, flip, wx, sh, x, int((~ok).sum()))
                                assert np.array_equal(got[:, wx:wx + 224], want[:, wx:wx + 224])
                                whole_cases += 1
                            else:
                                assert np.array_equal(got, want), (base, code, flip, wx, sh, x, int((got != want).sum()))
                                assert all(w == 4 for _, w, _ in rects), rects
                                clipped += 1
                            cases += 1
    print(f'PASS: {cases} edge cases ({clipped} clipped to the inner word with a window on a 16-pixel group, '
          f'{whole_cases} whole with the window at a fine offset; {len(gen)} generated + {len(anyp)} any_part shapes, '
          f'both flips, 16 shifts, a 64 KB crossing): exact, side bars untouched, holes preserved, damage covers')


if __name__ == '__main__':
    main()
