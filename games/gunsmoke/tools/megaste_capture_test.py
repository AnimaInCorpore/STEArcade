#!/usr/bin/env python3
"""Check native test 3 capture/BMP conversion against a synthetic planar picture."""
import argparse
import json
from pathlib import Path
import struct
import sys
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(Path(__file__).resolve().parent), str(ROOT / 'engine')]
from machine68k import Register as R
from sim import Sim
from megaste_capture import decode, SLOT


def test(out):
    s = Sim(out/'GUNSMOKE.TOS')
    sym = {k: v+s.base for k, v in s.symbols(out/'GUNSMOKE.MAP').items()}
    s.mem.set_trace_mode(False)
    image = (out/'GUNSMOKE.TOS').read_bytes()
    end = s.base + sum(struct.unpack('>3L', image[2:14]))
    source = 0x39ff00  # row 1 crosses a 64 KB boundary
    assert end <= source, hex(end)
    y, x = np.indices((256, 512))
    want = ((x//5 + y//3 + (x >> 4)*7) & 15).astype(np.uint8)
    words = np.zeros((256, 32, 4), dtype='>u2')
    for plane in range(4):
        for bit in range(16):
            words[:, :, plane] |= ((want[:, bit::16] >> plane) & 1).astype(np.uint16) << (15-bit)
    s.mem.w_block(source, words.tobytes())
    s.mem.w_block(sym['shown_pal'], (ROOT/'build/gunsmoke/palette.bin').read_bytes())
    s.mem.w32(sym['draw_base'], source)
    s.mem.w16(sym['isr_count'], 1000)
    work = out/'VERIFY-capture'
    work.mkdir(exist_ok=True)
    path = work/'CAPTURE.BIN'

    def call(name, regs):
        s.mem.w32(0x8000, 0x600)
        s.cpu.w_reg(R.A7, 0x8000)
        s.cpu.w_sr(0x2700)
        for reg, val in regs.items():
            s.cpu.w_reg(reg, val)
        s.cpu.w_pc(sym[name])
        for _ in range(100):
            s.cpu.execute(1_000_000)
            if s.cpu.r_pc() == 0x600:
                return
        raise RuntimeError(('native capture timeout', name, hex(s.cpu.r_pc())))

    saved = {reg: 0x120000 + i*0x123 for i, reg in enumerate(
        [R.D0, R.D1, R.D2, R.D3, R.D4, R.D5, R.D6, R.D7,
         R.A0, R.A1, R.A2, R.A3, R.A4, R.A5, R.A6])}
    for fine in range(16):
        s.mem.w16(sym['mc_n'], 0)
        s.mem.w8(sym['mc_pending'], 0xff)
        s.mem.w8(sym['flip_fine'], fine)
        offset = fine + (16 if fine & 1 else 0)
        s.mem.w16(sym['cur_hw'], offset)
        call('mc_capture_frame', saved)
        assert all(s.cpu.r_reg(r) == v for r, v in saved.items())
        assert s.mem.r16(sym['mc_n']) == 1
        path.write_bytes(bytes(s.mem.r_block(sym['mc_slots'], SLOT)))
        _, got, rgb = decode(path)
        assert np.array_equal(got, want[:, offset:offset+320]), fine
        call('mc_bmp', {R.A3: sym['mc_slots']})
        path.with_suffix('.BMP').write_bytes(bytes(s.mem.r_block(sym['mc_bitmap'], 41078)))
        bmp = np.array(Image.open(path.with_suffix('.BMP')).convert('RGB'))
        assert np.array_equal(bmp, rgb[got]), ('native BMP fine scroll', fine)
    before = bytes(s.mem.r_block(sym['mc_slots'], 3*SLOT))
    for full in [3, 0xffff]:
        s.mem.w16(sym['mc_n'], full)
        call('mc_capture_frame', saved)
        assert s.mem.r16(sym['mc_n']) == full
        assert bytes(s.mem.r_block(sym['mc_slots'], 3*SLOT)) == before
    result = dict(horizontal_shifts=16, pixels_per_shift=320*256,
                  native_capture_and_bmp_exact=True, capture_registers_preserved=True,
                  source_crosses_64k=True, capture_capacity_checked=True,
                  program_memory_bytes=end-s.base+256)
    assert result['program_memory_bytes'] < 3_700_000
    (work/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(result)
    return result


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('out', type=Path)
    test(ap.parse_args().out.resolve())
