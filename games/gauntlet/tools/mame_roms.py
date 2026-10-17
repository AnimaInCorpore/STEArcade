"""build/gauntlet/mame_roms/: the set as MAME 0.289 wants it (-rompath for engine/mame_cmp.run_mame).

The archive's 136037-104.6p (alphanumerics) is the 8 KB dump of the 27128; MAME's gauntlet lists the whole 16 KB chip,
whose second half is 0x00 (crc32 6c276a1d): the stand-in is the 8 KB file followed by 8 KB of zeros."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from paths import EXTRACTED
from roms import mame_folder


def rompath():
    out = mame_folder("gauntlet")
    chars = (EXTRACTED / "gauntlet" / "136037-104.6p").read_bytes()
    (out / "gauntlet" / "136037-104.6p").write_bytes(chars + bytes(0x4000 - len(chars)))
    return out


if __name__ == "__main__":
    print(rompath())
