"""Verify the ddragon archive (docs/rom_manifest.json) and unpack it to assets/roms/extracted/ddragon/ (engine/roms.py).

The archive holds MAME's `ddragonj` (Double Dragon, Japan set 1) with MAME's own file names: all 23 files, the main
program 21j-1-5.26 / 21j-3.24 / 21j-4-1.23 of the Japanese set.  MAME runs it as `ddragonj` straight from
assets/roms (a clone's files are looked up in the parent's ddragon.zip too).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from roms import extract

if __name__ == "__main__":
    extract("ddragon", "ddragon.zip")
