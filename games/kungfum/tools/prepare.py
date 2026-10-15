"""Verify the kungfum archive (docs/rom_manifest.json) and unpack it to assets/roms/extracted/kungfum/ (engine/roms.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from roms import extract

if __name__ == "__main__":
    extract("kungfum", "kungfum.zip")
