"""Verify the dkong archive (docs/rom_manifest.json) and unpack it to assets/roms/extracted/dkong/;
cpu.rom is the four CPU ROMs in address order (engine/roms.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from roms import extract

if __name__ == "__main__":
    extract("dkong", "dkong.zip", derived={"cpu.rom": ["c_5et_g.bin", "c_5ct_g.bin", "c_5bt_g.bin", "c_5at_g.bin"]})
