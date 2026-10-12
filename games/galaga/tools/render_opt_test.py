"""Compare renderer builds, including cached repaints and star ownership: the game area's bytes (every line, bytes
24-135; sprites clip at its left and right edges since 2026-10-12), and AFTER's side bands must stay clean.
Usage: python games/galaga/tools/render_opt_test.py BEFORE_DIR AFTER_DIR
Each directory contains GALAGA.PRG and galaga.map.
"""
import random
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from sprite_blit_test import Harness, integrated, SCREEN, SOURCE, STOP, R

class TestHarness(Harness):
    def call(self, addr):
        self.cpu.w_sr(0x2700)
        self.cpu.w_reg(R.A7, 0x8000)
        self.mem.w32(0x8000, STOP)
        self.cpu.w_pc(addr)
        cycles = 0
        for _ in range(4000000):
            if self.cpu.r_pc() == STOP:
                return cycles
            cycles += self.cpu.execute(1).cycles
        raise AssertionError(f"routine did not return: {self.cpu.r_pc():x}")

def written(h):
    """the video RAM was written: as a translated writer would, mark it (vblock_all, builds that have it)"""
    try:
        h.mem.w8(h.addr("vblock_all"), 0xFF)
    except KeyError:
        pass


def sequence(h, repaint=False):
    rng = random.Random(1942)
    h.mem.w32(h.addr("bg_address"), SOURCE)
    h.call(h.addr("init_render"))
    screens = (SCREEN, SCREEN + 0x18000)
    for address in (*screens, SOURCE):
        h.mem.w_block(address, bytes(384 * 256))
    ram = h.addr("g_ram")
    # Sparse characters, all sprite flips/sizes/colours, stars and two buffers.
    h.mem.w_block(ram, bytes(rng.randrange(128) if i % 31 == 0 else 0 for i in range(1024)))
    h.mem.w_block(ram + 0x400, bytes(rng.randrange(64) for _ in range(1024)))
    h.mem.w8(ram + 0x2005, 1)
    written(h)
    entries = [bytearray(128) for _ in range(3)]
    for slot in range(48):
        entries[0][slot*2:slot*2+2] = bytes((rng.randrange(128), rng.randrange(64)))
        entries[1][slot*2:slot*2+2] = bytes((rng.randrange(256), 40 + rng.randrange(216)))
        entries[2][slot*2:slot*2+2] = bytes((rng.randrange(16), 0))
    images, cycles = [], 0
    for frame in range(48):
        index = frame % 2
        h.mem.w16(h.addr("draw_index"), index)
        h.mem.w32(h.addr("draw_screen_address"), screens[index])
        # Keep most slots unchanged, move overlapping parts, and remove sprites.
        for slot in range(frame % 7, 48, 13):
            entries[1][slot*2+1] = (entries[1][slot*2+1] + 3) % 256
        if frame % 8 == 0:
            entries[0][2] = rng.randrange(128)
            h.mem.w8(ram + frame, rng.randrange(128))
            written(h)
        for off, data in zip((0xb80, 0x1380, 0x1b80), entries):
            h.mem.w_block(ram + off, bytes(data))
        b = h.bus_cycles
        if repaint:
            h.mem.w_block(h.addr("tile_marks"), bytes([255]) * 416)
        cycles += h.call(h.addr("draw_sprites" if repaint else "render_frame")) + h.bus_cycles - b
        images.append(bytes(h.mem.r_block(screens[index], 384 * 256)))
    return images, cycles

def main():
    assert len(sys.argv) == 3, __doc__
    for repaint in (False, True):
        expected = None
        for directory in map(Path, sys.argv[1:]):
            h = TestHarness(directory / "GALAGA.PRG", directory / "galaga.map")
            images, cycles = sequence(h, repaint)
            h.m.cleanup()
            area = [b"".join(img[line * 256 + 24:line * 256 + 136] for line in range(384)) for img in images]
            band = sum(any(img[line * 256 + x] for line in range(384) for x in (*range(24), *range(136, 256)))
                       for img in images)
            if expected is not None:
                for frame, (a, b) in enumerate(zip(expected, area)):
                    assert a == b, ("frame", frame, "different bytes", sum(x != y for x, y in zip(a, b)))
            expected = area
            print(directory.name, "repaint" if repaint else "full frame", len(images), "frames", cycles, "CPU+bus cycles;",
                  band, "frames with bytes in the side bands", flush=True)
        assert not band, "AFTER drew into the side bands"
    print("PASS: identical bytes in the game area (all lines), AFTER's side bands clean")

if __name__ == "__main__":
    main()
