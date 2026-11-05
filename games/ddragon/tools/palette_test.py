"""Native flat text fills: fine scroll, chunks and 64 KiB crossings."""
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / 'engine')]
from machine68k import Register as R
from sprite_test import Renderer


def main():
    r = Renderer()
    mem, cpu, sym = r.mem, r.cpu, r.sym
    stride, lines = 416, 36
    yy, xx = np.indices((lines, stride * 2))
    mem.w8(sym['char_blank'], 0x81)  # a uniform pen-1 character; the fill's normal metadata
    # render_frame normally sets these shared registers before drawing text.
    r.sim.io[0xA2E:0xA30] = (8).to_bytes(2, 'big')
    r.sim.io[0xA2A:0xA2C] = b'\xff\xff'
    bg = bytes.fromhex('ffff0000ffff0000') * (stride // 8 * lines)
    cases = 0
    for base in (0x600000, 0x6F0000 - 10 * stride):
        for pair in (0x00, 0x55, 0xAA, 0xFF):
            mem.w8(sym['pen_map'] + 1, pair)
            for shift in range(16):
                for chars in (1, 2, 5, 32):
                    for height in (8, 24):
                        x, y = 96 + shift, 4
                        mem.w_block(base, bg)
                        mem.w32(sym['work_base'], base)
                        mem.w16(sym['object_x'], x)
                        mem.w16(sym['object_y'], y)
                        cpu.w_reg(R.D0, 0)
                        cpu.w_reg(R.D1, chars << 8)
                        cpu.w_reg(R.D5, height)
                        r.call('solid_fill')
                        data = np.frombuffer(bytes(mem.r_block(base, len(bg))), '>u2').reshape(lines, stride // 8, 4)
                        bits = (data[..., None] >> np.arange(15, -1, -1)) & 1
                        got = (bits * (1 << np.arange(4))[None, None, :, None]).sum(2).reshape(yy.shape)
                        want = np.full(yy.shape, 5, np.uint8)
                        inside = (xx >= x) & (xx < x + chars * 8) & (yy >= y) & (yy < y + height)
                        color = np.where((xx - x + yy - y) & 1, pair & 15, pair >> 4)
                        want[inside] = color[inside]
                        assert np.array_equal(got, want), (base, pair, shift, chars, height, int((got != want).sum()))
                        cases += 1
    print(f'PASS: {cases} native flat-text fills; 16 shifts, single/multiple words, bounded chunks, 64 KiB crossing')


if __name__ == '__main__':
    main()
