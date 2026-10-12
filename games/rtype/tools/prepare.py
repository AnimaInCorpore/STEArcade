"""Verify the rtype archive (docs/rom_manifest.json) and unpack it to assets/roms/extracted/rtype/ (engine/roms.py).

It also fills build/rtype/mame_roms/ for the MAME comparisons (mame_cmp.run_mame(..., rompath=MAME_ROMS)): MAME 0.289
wants five files the archive does not have, two TBP24S10 PROMs and three PALs of the M72 boards.  The driver loads but
never reads them, so zero-filled stand-ins let it run (with a checksum warning).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from paths import ROOT
from roms import extract, mame_folder

MAME_ROMS = ROOT / "build" / "rtype" / "mame_roms"
MAME_NAMES = {"rt_b-a0.3c": "rt_b-a0.ic20", "rt_b-a1.3d": "rt_b-a1.ic22", "rt_b-a2.3a": "rt_b-a2.ic20",
              "rt_b-a3.3e": "rt_b-a3.ic23", "rt_b-b0.3j": "rt_b-b0.ic26", "rt_b-b1.3k": "rt_b-b1.ic27",
              "rt_b-b2.3h": "rt_b-b2.ic25", "rt_b-b3.3f": "rt_b-b3.ic24"}
STAND_INS = {"m72_a-8l-.ic66": 256, "m72_a-9l-.ic75": 256, "m72_a-3d-.ic11": 279, "m72_a-4d-.ic19": 279,
             "m72_r-3a-.3a": 279}

if __name__ == "__main__":
    extract("rtype", "rtype.zip")
    mame_folder("rtype", MAME_NAMES, STAND_INS)
