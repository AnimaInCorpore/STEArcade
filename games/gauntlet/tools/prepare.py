"""Verify the gauntlet archive (docs/rom_manifest.json) and unpack it to assets/roms/extracted/gauntlet/ (engine/roms.py).

The archive holds MAME's `gauntlet` (Gauntlet, rev 14, Atari Games 1985) with MAME's own file names: all 20 files, the
main program 136037-1307.9a / -1308.9b / -1409.7a / -1410.7b and the slapstic-protected 136037-205.10a / -206.10b.
MAME runs it as `gauntlet` straight from assets/roms.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from roms import extract

if __name__ == "__main__":
    extract("gauntlet", "gauntlet.zip")
