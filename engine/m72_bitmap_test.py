"""Execute M72's 64-bit tile-contribution rotation on the 68000.

All 512 pixel offsets, random bitmaps, and preserved registers; --source accepts
a saved m72render.s for a CPU-cycle comparison independent of ROMs.
"""
import argparse
from pathlib import Path
import random
import subprocess
import tempfile

from machine68k import Machine, CPUType, Register as R
from paths import VASM, RT_INCLUDE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=RT_INCLUDE / 'm72render.s')
    args = parser.parse_args()
    source = args.source.read_text()
    first = source.index('m72r_rol:')
    last = source.index('\n; =====', first)
    source = '''
        org $1000
        bra.w start
done:   bra.s done
start:  movem.l d6-d7,-(sp)
        bra m72r_rol
''' + source[first:last]
    with tempfile.TemporaryDirectory(prefix='m72-bitmap-') as directory:
        folder = Path(directory)
        (folder / 'test.s').write_text(source)
        subprocess.run([VASM, '-Fbin', '-quiet', '-o', str(folder / 'test.bin'), str(folder / 'test.s')], check=True)
        machine = Machine(CPUType.M68000, 1024)
        cpu, mem = machine.cpu, machine.mem
        mem.w_block(0x1000, (folder / 'test.bin').read_bytes())
        cpu.pulse_reset()
        rng = random.Random(72)
        total = 0
        for offset in range(512):
            for vector in (0, (1 << 64) - 1, rng.getrandbits(64), rng.getrandbits(64)):
                cpu.w_sr(0x2700)
                cpu.w_reg(R.A7, 0x8000)
                mem.w32(0x8000, 0x1004)
                cpu.w_reg(R.D0, vector >> 32)
                cpu.w_reg(R.D1, vector & 0xffffffff)
                cpu.w_reg(R.D4, offset)
                cpu.w_reg(R.D6, 0x12345678)
                cpu.w_reg(R.D7, 0x87654321)
                cpu.w_pc(0x1000)
                for _ in range(100):
                    if cpu.r_pc() == 0x1004:
                        break
                    total += cpu.execute(1).cycles
                else:
                    raise AssertionError('did not return')
                shift = offset >> 3
                expected = ((vector << shift) | (vector >> (64 - shift))) & ((1 << 64) - 1)
                actual = cpu.r_reg(R.D0) << 32 | cpu.r_reg(R.D1)
                assert actual == expected, (offset, hex(vector), hex(actual), hex(expected))
                assert cpu.r_reg(R.D4) == offset
                assert cpu.r_reg(R.D6) == 0x12345678
                assert cpu.r_reg(R.D7) == 0x87654321
                assert cpu.r_reg(R.A7) == 0x8004
        machine.cleanup()
        print(f'2048 tile-bitmap rotations passed; {total} CPU cycles')


if __name__ == '__main__':
    main()
