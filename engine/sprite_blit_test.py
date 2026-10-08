"""Execute assembled sprite code on Musashi with the STE blitter model.

Builds both implementations in a temporary directory. Exhaustively tests every
shape, skew and line direction against independently masked pixels, then compares
the complete draw_sprites entry points (including restoration and 64 KB crossings).
Reported cycles are CPU cycles plus blitter bus accesses, not measured frame rates.

    venv/bin/python engine/sprite_blit_test.py
"""
import random
import sys
import shutil
import subprocess
import tempfile
from pathlib import Path

from machine68k import Register as R
from sim import Sim

from paths import ROOT, ENGINE, build_dir
HERE = Path(__file__).resolve().parent
STOP = 0x700
SCREEN = 0x300000
SOURCE = 0x320000


class Harness(Sim):
    def __init__(self, prg, mapfile):
        # Map the entire 24-bit bus so CPU read/modify/write operations on the
        # blitter registers see the addresses written back by the hardware.
        super().__init__(prg, ram_kib=16384)
        self.syms = self.symbols(mapfile)
        self.bus_cycles = self.blits = self.words = 0

    def addr(self, symbol):
        return self.base + self.syms[symbol]

    def on_access(self, mode, width, addr, value):
        if mode != 'W' or (addr & 0xffffff) < 0xff8000:
            return
        off = (addr & 0xffffff) - 0xff8000
        n = (1, 2, 4)[width]
        self.io[off:off + n] = value.to_bytes(n, 'big')
        if off <= 0xa3c < off + n and self.io[0xa3c] & 0x80:
            b = self.blitter
            x, y = b.reg16(0xa36), b.reg16(0xa38)
            masks = [b.reg16(0xa28)] if x == 1 else [b.reg16(0xa28), b.reg16(0xa2c)]
            assert x in (1, 2, 4, 8), x
            if x > 2:
                masks[1:1] = [b.reg16(0xa2a)] * (x - 2)
            reads = x - bool(self.io[0xa3d] & 0x40)
            if self.io[0xa3a] < 2:
                reads = 0
            self.bus_cycles += 4 * y * (reads + x + sum(m != 0xffff for m in masks))
            self.blits += 1
            self.words += x * y
            self.mem.set_trace_mode(False)
            try:
                b.run()
                self.mem.w_block(0xff8000, bytes(self.io))
            finally:
                self.mem.set_trace_mode(True)

    def call(self, addr):
        self.cpu.w_sr(0x2700)
        self.cpu.w_reg(R.A7, 0x8000)
        self.mem.w32(0x8000, STOP)
        self.cpu.w_pc(addr)
        cycles = 0
        for _ in range(100000):
            if self.cpu.r_pc() == STOP:
                return cycles
            cycles += self.cpu.execute(1).cycles
        raise AssertionError(f'routine did not return: {self.cpu.r_pc():x}')

    def hw(self, off, value, size=2):
        value &= (1 << (size * 8)) - 1
        self.io[0xa00 + off:0xa00 + off + size] = value.to_bytes(size, 'big')
        getattr(self.mem, f'w{size * 8}')(0xff8a00 + off, value)

    def setup(self):
        for off, value in ((0x20, 2), (0x22, 2), (0x2a, 0xffff), (0x2e, 8), (0x3a, 0x0203)):
            self.hw(off, value)
        for reg, value in ((R.A1, 0xff8a28), (R.A2, 0xff8a3c), (R.A3, 0xff8a34),
                           (R.A5, 0xff8a38), (R.A6, 0xff8a2c), (R.D1, 4), (R.D2, 0xffffffc0)):
            self.cpu.w_reg(reg, value)


def exhaustive(h, prefix):
    rng = random.Random(80)
    masks_base = h.addr(prefix + '_spr_masks')
    span_base = h.addr(prefix + '_spr_span')
    table = h.addr(prefix + '_spr_code')
    tested = narrow = empty = 0
    cpu_cycles = old_cpu = old_bus = 0
    background = rng.randbytes(16 * 256)
    for variant in range(256):
        first = h.mem.r8(span_base + variant * 2)
        count = h.mem.r8(span_base + variant * 2 + 1)
        for skew in range(16):
            masks = [(h.mem.r16(masks_base + (variant * 16 + skew) * 64 + row * 4),
                      h.mem.r16(masks_base + (variant * 16 + skew) * 64 + row * 4 + 2))
                     for row in range(16)]
            words = [rng.getrandbits(16) for _ in range(64)]
            h.mem.w_block(SOURCE, b''.join(w.to_bytes(2, 'big') for w in words))
            for reverse in (False, True):
                expected = bytearray(background)
                for row in range(first, first + count):
                    dest_row = 15 - row if reverse else row
                    for plane in range(4):
                        shifted = words[row * 4 + plane] << (16 - skew)
                        for chunk, mask in enumerate(masks[row]):
                            off = dest_row * 256 + chunk * 8 + plane * 2
                            previous = int.from_bytes(expected[off:off + 2], 'big')
                            source = (shifted >> (16 if chunk == 0 else 0)) & 0xffff
                            result = (previous & ~mask) | (source & mask)
                            expected[off:off + 2] = result.to_bytes(2, 'big')
                    narrow += bool(masks[row][0] and not masks[row][1] and skew)
                    empty += not any(masks[row])
                    x = 2 if skew else 1
                    old_bus += 4 * 4 * (1 + x + sum(m != 0xffff for m in masks[row][:x]))
                h.mem.w_block(SCREEN, background)
                h.setup()
                h.hw(0x24, SOURCE + first * 8, 4)
                start_row = 15 - first if reverse else first
                h.hw(0x32, SCREEN + start_row * 256, 4)
                h.cpu.w_reg(R.D4, (-264 if reverse else 248) & 0xffffffff)
                entry = table + (variant * 16 + skew) * 8
                h.cpu.w_reg(R.A0, h.mem.r32(entry + 4))
                cpu_cycles += h.call(h.mem.r32(entry))
                actual = h.mem.r_block(SCREEN, len(expected))
                assert actual == bytes(expected), (prefix, variant, skew, reverse, first, count, [(i, a, e) for i, (a, e) in enumerate(zip(actual, expected)) if a != e][:12], h.io[0xa20:0xa40].hex())
                assert h.blitter.reg32(0xa24) == SOURCE + (first + count) * 8, (variant, skew)
                # Original first line: 4 register moves; subsequent lines add
                # a memory RMW. Include RTS for a like-for-like line-body comparison.
                old_cpu += (40 + (count - 1) * 52 if count else 0) + 16
                tested += 1
    total = cpu_cycles + h.bus_cycles
    baseline = old_cpu + old_bus
    print(f'{prefix}: {tested} shape/skew/direction checks; {narrow} narrow and {empty} empty lines; '
          f'line-body CPU+bus cycles {baseline} -> {total} ({100 * (1-total/baseline):.1f}% less)')


def integrated(h, prefix, expected=None):
    rng = random.Random(68000)
    total = 0
    results = []
    h.mem.w32(h.addr('bg_address'), SOURCE)
    # Cross the 64 KB boundary in both directions; change/remove entries to
    # exercise restoration and overlapping sprites on successive draws.
    for boundary in (False, True):
        screen = SCREEN + (0xf000 if boundary else 0)
        background = rng.randbytes(384 * 256)
        h.mem.w32(h.addr('draw_screen_address'), screen)
        h.mem.w_block(screen, background)
        h.mem.w_block(SOURCE, background)
        h.call(h.addr('init_sprites'))
        for frame in range(24):
            if prefix == 'dk':
                entries = bytearray(512)
                for slot in range(16):
                    entries[slot*4:slot*4+4] = bytes((24 + slot,
                        rng.randrange(256), rng.randrange(256), 8 + rng.randrange(32)))
                if frame % 4 == 0:
                    entries[:8] = b'\0' * 8
                h.cpu.w_reg(R.A6, 0x350000)
                h.mem.w_block(0x357000, bytes(entries))
                h.mem.w16(h.addr('bank16'), (frame % 4) * 16)
            else:
                entries = [bytearray(128) for _ in range(3)]
                for slot in range(64):
                    entries[0][slot*2:slot*2+2] = bytes((rng.randrange(128), rng.randrange(64)))
                    entries[1][slot*2:slot*2+2] = bytes((rng.randrange(256), 40 + rng.randrange(216)))
                    entries[2][slot*2:slot*2+2] = bytes((rng.randrange(16), 0))
                for off, data in zip((0xb80, 0x1380, 0x1b80), entries):
                    h.mem.w_block(h.addr('g_ram') + off, bytes(data))
            h.mem.w_block(h.addr('tile_marks'), bytes(416 if prefix == 'ga' else 288))
            before = h.bus_cycles
            total += h.call(h.addr('draw_sprites')) + h.bus_cycles - before
            image = h.mem.r_block(screen, len(background))
            if expected is not None:
                assert expected[len(results)] == image, (prefix, boundary, frame)
            results.append(image)
    return results, total


def main():
    with tempfile.TemporaryDirectory(prefix='sprite-blit-') as directory:
        root = Path(directory)
        for prefix, game, prg, mapname in (
                ('dk', 'dkong', 'DKONG.PRG', 'dkong.map'),
                ('ga', 'galaga', 'GALAGA.PRG', 'galaga.map')):
            builds = []
            for kind in ('old', 'new'):
                target = root / prefix / kind
                target.mkdir(parents=True)
                cmd = [sys.executable, str(ROOT / 'games' / game / 'tools' / 'build.py'), '--out', str(target / prg)]
                if kind == 'old':
                    cmd += ['-D', 'NOSPRITECODE=1']
                subprocess.run(cmd, check=True)
                shutil.copy(build_dir(game) / mapname, target / mapname)
                builds.append((target / prg, target / mapname))
            # Musashi's memory mapping is global: run one machine at a time.
            old = Harness(*builds[0])
            expected, before = integrated(old, prefix)
            old.m.cleanup()
            new = Harness(*builds[1])
            exhaustive(new, prefix)
            _, after = integrated(new, prefix, expected)
            new.m.cleanup()
            print(f'{prefix}: {len(expected)} complete renderer comparisons including '
                  f'64 KB crossings/restoration; CPU+bus cycles {before} -> {after} '
                  f'({100*(1-after/before):.1f}% less)')


if __name__ == '__main__':
    main()
