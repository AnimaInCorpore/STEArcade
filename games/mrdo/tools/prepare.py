"""Verify the Mr. Do! (Universal) files in assets/roms/mrdo.zip (docs/rom_manifest.json) and unpack them to
assets/roms/extracted/mrdo/ (engine/roms.py), with MAME's names: build/mrdo/mame_roms/ can serve a MAME run."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from roms import extract, mame_folder

if __name__ == "__main__":
    extract("mrdo", "mrdo.zip")
    print("MAME rompath:", mame_folder("mrdo"))
