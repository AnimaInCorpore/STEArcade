"""Front tiles at the window's left and right edges: all 16 shifts, transparent holes, a 64 KB crossing.

front_tile runs on Musashi.  A tile across an edge draws only its words inside the window (unshifted: one word,
shifted: the band words' end masks 0); it must equal the same columns of that tile drawn whole in the middle of the
window, leave the side bands (and everything else) as they were, and list damage only inside the window.  A tile
wholly in a band draws nothing.
"""
import sys
from pathlib import Path
import numpy as np
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from sim import Sim
from machine68k import Register as R
from paths import ROOT, build_dir

BG = b'\xff\xff\x00\x00\xff\xff\x00\x00'        # (a chunk of colour 5)
LINES = 40
STUB = 0x2F0000
STRIDE, GAME_X = 256, 24


def main():
    run = ROOT / 'run' / '1943_sim'
    s = Sim(str(run / '1943.PRG'), ram_kib=16384, run_dir=run)
    sym = {k: v + s.base for k, v in s.symbols(build_dir('1943') / '1943_sim.map').items()}
    cpu, mem = s.cpu, s.mem
    dmg = 0x700000                       # (the damage list and the rings above the program: ram_kib 16384)
    assert s.base + (ROOT / 'run' / '1943_sim' / '1943.PRG').stat().st_size < dmg
    fmap = np.frombuffer((build_dir('1943') / 'front_map.bin').read_bytes(), '>u4')
    entries = []
    for e in fmap:
        e = int(e)
        if e and not e & (1 << 31) and e not in entries:
            entries.append(e)
    entries = entries[::max(1, len(entries) // 4)][:4]

    def draw(ring, entry, x):
        mem.w32(sym['ring_addr'], ring)
        mem.w16(sym['cur_top'], 0)
        mem.w32(sym['dmg_ptr'], dmg)
        mem.w8(sym['front_full'], 0)
        mem.w8(sym['front_nodmg'], 0)
        mem.w16(sym['front_x'], x & 0xFFFF)
        mem.w16(sym['front_y'], 4)
        mem.w_block(ring, BG * 32 * LINES)
        # (the Blitter's constants of the front tiles, set by the CPU as draw_front does, then jsr front_tile)
        stub = b''.join(bytes.fromhex('31fc') + v.to_bytes(2, 'big') + reg.to_bytes(2, 'big')
                        for reg, v in ((0x8a20, 2), (0x8a2e, 8), (0x8a3a, 0x0203), (0x8a2a, 0xffff)))
        stub += bytes.fromhex('4eb9') + sym['front_tile'].to_bytes(4, 'big')
        mem.w_block(STUB, stub)
        mem.w16(STUB + len(stub), 0x4E71)
        for r, v in ((R.A3, 0xff8a24), (R.A4, 0xff8a32), (R.A5, 0xff8a38), (R.A6, 0xff8a3c),
                     (R.A0, sym['front_tiles'] - 1 + entry)):
            cpu.w_reg(r, v)
        cpu.w_reg(R.A7, 0x2EFF00)
        cpu.w_sr(0x2700); cpu.w_pc(STUB)
        n = 0
        while cpu.r_pc() != STUB + len(stub):
            cpu.execute(1)
            n += 1
            assert n < 200000, 'front tile stopped'
        raw = np.frombuffer(bytes(mem.r_block(ring, STRIDE * LINES)), np.uint8).reshape(LINES, 32, 4, 2)
        words = (raw[..., 0].astype(np.uint16) << 8) | raw[..., 1]
        bits = (words[..., None] >> np.arange(15, -1, -1)) & 1
        pix = (bits * (1 << np.arange(4))[None, None, :, None]).sum(2).reshape(LINES, 512)   # x 48 = window x 0
        rects = []
        for a in range(dmg, mem.r32(sym['dmg_ptr']), 12):
            off = mem.r32(a) - ring
            rects.append(((off % STRIDE - GAME_X) // 8, mem.r16(a + 8) & 0x7fff, off // STRIDE, mem.r16(a + 10)))
        return pix, rects

    cases = clipped = 0
    for ring in (0x780000, 0x7F0000 - 20 * STRIDE):           # (the second: lines 20 on lie above a 64 KB boundary)
        for entry in entries:
            for sh in range(16):
                whole, _ = draw(ring, entry, 96 + sh)
                whole = whole[:, 144 + sh:176 + sh]
                assert (whole != 5).any() and (whole == 5).any(), 'want holes and opaque pixels'
                for x in [sh - 48, sh - 32, sh - 16, 192 + sh, 208 + sh, 224 + sh]:
                    got, rects = draw(ring, entry, x)
                    want = np.full_like(got, 5)
                    for i in range(32):
                        if 0 <= x + i < 224:
                            want[:, 48 + x + i] = whole[:, i]
                    assert np.array_equal(got, want), (hex(ring), entry, sh, x, int((got != want).sum()))
                    for c0, words, line, lines in rects:
                        assert 0 <= c0 and c0 + words // 4 <= 14, ('damage outside the window', x, rects)
                    changed = np.nonzero((got != 5).any(0))[0]
                    for col in changed:
                        assert any(c0 * 16 <= col - 48 < (c0 + words // 4) * 16 for c0, words, _, _ in rects), \
                            ('a change outside the damage', x, col)
                    cases += 1
                    clipped += (x < 0 < x + 32) or (x < 224 < x + 32)
    print(f'{cases} front tile edge cases ({clipped} across an edge; {len(entries)} tiles with holes, 16 shifts, '
          f'a 64 KB crossing): exact, side bands untouched, damage inside the window')


if __name__ == '__main__':
    main()
