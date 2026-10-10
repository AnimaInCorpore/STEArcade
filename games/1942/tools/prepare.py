"""Verify the 1942 archive (docs/rom_manifest.json) and unpack it to assets/roms/extracted/1942/ (engine/roms.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from roms import extract

if __name__ == "__main__":
    extract("1942", "1942.zip")
