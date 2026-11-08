"""Verify the Super Xevious archive (docs/rom_manifest.json) and unpack it to assets/roms/extracted/xevious/ (engine/roms.py).

The MAME set is `sxevious` (assets/roms/sxevious.zip, a clone of `xevious`); there is no xevious.zip here, so the port
is Super Xevious (see the README).  The Namco 50XX / 51XX / 54XX programs are read from their own device sets
(namco50.zip, namco51.zip, namco54.zip) by tools/machine.py.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from roms import extract

if __name__ == "__main__":
    extract("xevious", "sxevious.zip")
