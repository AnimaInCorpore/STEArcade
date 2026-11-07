"""Verify the Dig Dug archive (docs/rom_manifest.json) and unpack it to assets/roms/extracted/digdug/ (engine/roms.py).

MAME set `digdug` (Dig Dug rev 2): the 19 files of digdug.zip plus the Namco 51XX and 53XX MCU programs from
namco51.zip / namco53.zip (the manifest's `archive` field)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from roms import extract

if __name__ == "__main__":
    extract("digdug", "digdug.zip")
