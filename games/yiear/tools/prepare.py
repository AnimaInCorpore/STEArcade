"""Verify the yiear archive (docs/rom_manifest.json) and unpack it to assets/roms/extracted/yiear/ (engine/roms.py).

The set is MAME's `yiear` (version I); the archive also holds the clone `yiear2` and the bootleg `yieartf`, which the
port does not use.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from roms import extract

if __name__ == "__main__":
    extract("yiear", "yiear.zip")
