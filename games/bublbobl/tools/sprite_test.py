"""Reordered sprites: all shifts, transparent holes and all four picture edges.

Execute sr_draw1 against independently decoded ROM tiles, including pixels outside
of the arcade picture: whole into the top and bottom guard rows, clipped at the left
and right picture edges (the side bands stay untouched). Also 64 KB destination crossings.
"""
import sys
from pathlib import Path
import numpy as np
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from sim import Sim
from machine68k import Register as R
from machine import decode_tiles
import logic_test as lt


def main():
    s = Sim(str(lt.RUN / 'BUBBLE.PRG'), run_dir=lt.RUN)
    sym = {k: v + s.base for k, v in s.symbols(lt.MAP).items()}
    cpu, mem = s.cpu, s.mem
    stop = sym['sim_frame_done']
    s.bad = sym['z80_badpc']
    while True:
        assert lt.run_to(s, stop), 'boot stopped'
        sp = cpu.r_reg(R.A7)
        cpu.w_pc(mem.r32(sp)); cpu.w_reg(R.A7, sp + 4)
        if mem.r8(sym['booted1']):
            break
    tiles = decode_tiles()
    codes = [i for i, t in enumerate(tiles) if (t != 15).sum() > 16][:4]
    ttab = bytes((p % 15 + 1) if p % 16 != 15 else 0 for p in range(256))
    mem.w_block(sym['ttab'], ttab)
    spread = lambda c: sum(((c >> p) & 1) << (24 - p * 8) for p in range(4))
    for bank in range(16):
        for pair in range(256):
            hi, lo = pair >> 4, pair & 15
            data = (spread(ttab[bank * 16 + hi]) << 1) | spread(ttab[bank * 16 + lo])
            mem.w32(sym['dtab'] + (bank * 256 + pair) * 4, data)
            mem.w8(sym['mtab'] + bank * 256 + pair, (2 if hi == 15 else 0) | (1 if lo == 15 else 0))
    # Do not reuse boot colours after changing the test colour mapping.
    mem.w_block(sym['tcache'], b'\xff' * (4096 * 72))
    mem.w_block(sym['sr_cache'], b'\xff' * (512 * 212))
    ordinary = [(code, i, i & 1, (i >> 1) & 1) for i, code in enumerate(codes)]
    # Exercise the rare path that copies four colliding 72-byte tile entries.
    buckets = {}
    collisions = None
    for code in range(len(tiles)):
        if (tiles[code] != 15).sum() <= 16:
            continue
        for bank in range(16):
            key = code | (bank << 14)
            slot = (key ^ (key >> 7) ^ (key >> 13)) & 4095
            bucket = buckets.setdefault(slot, [])
            bucket.append((code, bank, 0, 0))
            if len(bucket) == 4:
                collisions = bucket
                break
        if collisions:
            break
    assert collisions, 'no collision fixture'
    cases = 0
    for parts in (ordinary, collisions):
        rec = sym['sr_recs']
        expected = np.zeros((16, 16), np.uint8)
        opaque = np.zeros((16, 16), bool)
        for i, (code, bank, fx, fy) in enumerate(parts):
            key = code | (bank << 14) | (fx << 18) | (fy << 19)
            mem.w32(rec + 36 + 4 * i, key)
            t = tiles[code]
            if fy: t = t[::-1]
            if fx: t = t[:, ::-1]
            yy, xx = (i // 2) * 8, (i % 2) * 8
            expected[yy:yy + 8, xx:xx + 8] = np.array([ttab[bank * 16 + int(p)] for p in t.ravel()], np.uint8).reshape(8, 8)
            opaque[yy:yy + 8, xx:xx + 8] = t != 15
        # An aligned scratch screen at the top of 4 MB, with a row crossing 64 KB.
        screen = 0x3DFF00
        mem.w32(sym['rf_screen'], screen)
        for shift in range(16):
            for x, y in ((shift - 15, 128), (240 + shift, 128), (112 + shift, 0), (112 + shift, 240)):
                # background colour five; all transparent pixels must retain it.
                row = b'\xff\xff\x00\x00\xff\xff\x00\x00' * 32
                mem.w_block(screen, row * 280)
                mem.w16(rec + 16, x & 0xFFFF)
                mem.w16(rec + 18, y)
                mem.w16(rec + 34, x & 15)
                mem.w32(rec + 52, 0)
                cpu.w_reg(R.A2, rec)
                cpu.w_reg(R.A7, 0x3CF000 - 4)
                mem.w32(0x3CF000 - 4, stop)
                cpu.w_sr(0x2700); cpu.w_pc(sym['sr_draw1'])
                assert lt.run_to(s, stop), 'sprite stopped'
                raw = np.frombuffer(bytes(mem.r_block(screen, 256 * 280)), np.uint8).reshape(280, 32, 4, 2)
                words = raw[..., 0].astype(np.uint16) * 256 + raw[..., 1]
                pixels = np.zeros((280, 512), np.uint8)
                for p in range(4):
                    for bit in range(16):
                        pixels[:, bit::16] |= ((words[:, :, p] >> (15 - bit)) & 1).astype(np.uint8) << p
                want = np.full((280, 512), 5, np.uint8)
                want[y + 10:y + 26, x + 128:x + 144] = np.where(opaque, expected, 5)
                # Left and right: clipped at the picture (x 0-255); top and bottom: whole into the guard rows.
                want[:, :128] = 5
                want[:, 384:] = 5
                assert np.array_equal(pixels, want), (x, y, int((pixels != want).sum()))
                cases += 1
    # The general object renderer uses draw_tile when sr_frame cannot handle a
    # layout. Its 8-pixel cells must obey the same picture edges as sr_draw1.
    fallback_cases = 0
    vram = sym['snap_vram']
    screen = 0x3D0100                         # y=239 crosses 64 KB between its rows
    mem.w32(sym['rf_screen'], screen)
    for code, bank, fx, fy in ordinary:
        mem.w8(vram, code & 255)
        mem.w8(vram + 1, ((code >> 8) & 3) | (bank << 2) | (fx << 6) | (fy << 7))
        tile = tiles[code]
        if fy: tile = tile[::-1]
        if fx: tile = tile[:, ::-1]
        mapped = np.array([ttab[bank * 16 + int(p)] for p in tile.ravel()], np.uint8).reshape(8, 8)
        for x in list(range(-16, 16)) + list(range(240, 272)):
            for y in (9, 128, 239):
                mem.w_block(screen, row * 280)
                cpu.w_reg(R.D0, x & 0xffff)
                cpu.w_reg(R.D1, y)
                cpu.w_reg(R.D2, 0)
                cpu.w_reg(R.D3, code & 0x3c00)
                cpu.w_reg(R.A7, 0x3CF000 - 4)
                mem.w32(0x3CF000 - 4, stop)
                cpu.w_sr(0x2700); cpu.w_pc(sym['draw_tile'])
                assert lt.run_to(s, stop), 'fallback tile stopped'
                want = np.full((280, 512), 5, np.uint8)
                lo, hi = max(0, x), min(256, x + 8)
                if lo < hi:
                    want[y + 10:y + 18, lo + 128:hi + 128] = np.where(
                        tile[:, lo - x:hi - x] != 15, mapped[:, lo - x:hi - x], 5)
                # Compare every byte, including the margins and vertical guards.
                planar = np.zeros((280, 32, 4), dtype='>u2')
                for p in range(4):
                    for bit in range(16):
                        planar[:, :, p] |= (((want[:, bit::16] >> p) & 1).astype(np.uint16) << (15 - bit))
                assert bytes(mem.r_block(screen, 256 * 280)) == planar.tobytes(), ('fallback', x, y, code)
                fallback_cases += 1
    print(f'{cases} sprite/shift/edge cases and {fallback_cases} fallback tile cases: exact '
          '(clipped left/right, whole into the top/bottom guards), '
          'transparent holes preserved')


if __name__ == '__main__':
    main()
