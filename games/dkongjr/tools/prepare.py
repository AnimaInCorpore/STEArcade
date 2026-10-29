"""Verify the dkongjr archive (docs/rom_manifest.json, MAME's US set F-2) and unpack it to assets/roms/extracted/dkongjr/.

cpu.rom is the main CPU's $0000-$5FFF.  The three 8 KB ROMs are not in address order: each holds 4 KB or 2 KB pieces
of several address ranges (MAME's ROM_LOAD / ROM_CONTINUE for dkongjr), put back here.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from paths import EXTRACTED
from roms import extract

# (file, [(address, length), ...]) in file order
LAYOUT = [("djr1-c_5b_f-2.5b", [(0x0000, 0x1000), (0x3000, 0x1000)]),
          ("djr1-c_5c_f-2.5c", [(0x2000, 0x0800), (0x4800, 0x0800), (0x1000, 0x0800), (0x5800, 0x0800)]),
          ("djr1-c_5e_f-2.5e", [(0x4000, 0x0800), (0x2800, 0x0800), (0x5000, 0x0800), (0x1800, 0x0800)])]


def cpu_rom(folder):
    rom = bytearray(0x6000)
    filled = 0
    for name, pieces in LAYOUT:
        data = (folder / name).read_bytes()
        pos = 0
        for addr, n in pieces:
            rom[addr:addr + n] = data[pos:pos + n]
            pos += n
            filled += n
        assert pos == len(data), name
    assert filled == len(rom)
    return bytes(rom)


if __name__ == "__main__":
    extract("dkongjr", "dkongjr.zip")
    out = EXTRACTED / "dkongjr"
    (out / "cpu.rom").write_bytes(cpu_rom(out))
    print("cpu.rom: $0000-$5FFF in address order")
