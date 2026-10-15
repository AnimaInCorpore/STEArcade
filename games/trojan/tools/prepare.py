"""Verify the trojanr archive (docs/rom_manifest.json) and unpack it to assets/roms/extracted/trojan/ (engine/roms.py).

The archive is MAME's `trojanr` (Trojan, Romstar, set 1) with the old file names: tb01.bin-tb25.bin, mb7114e.1e,
tbp24s10.7j.  The files keep those names in extracted/trojan/; build/trojan/mame_roms/trojan/ gets MAME 0.289's names
(matched by CRC: tb04/05/06 are the Romstar program ROMs tbu_04/05/06, the rest tb_NN.<position>) for the MAME runs
(mame_cmp.run_mame("trojanr", ..., rompath=MAME_ROMS); MAME looks for the clone's files in the parent's folder too).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from paths import ROOT
from roms import extract, mame_folder

MAME_ROMS = ROOT / "build" / "trojan" / "mame_roms"
MAME_NAMES = {"tb01.bin": "tb_01.6d", "tb02.bin": "tb_02.15h", "tb03.bin": "tb_03.8k", "tb04.bin": "tbu_04.10n",
              "tb05.bin": "tbu_05.12n", "tb06.bin": "tbu_06.13n", "tb07.bin": "tb_07.3a", "tb08.bin": "tb_08.4a",
              "tb09.bin": "tb_09.6a", "tb10.bin": "tb_10.8a", "tb11.bin": "tb_11.3b", "tb12.bin": "tb_12.4b",
              "tb13.bin": "tb_13.6b", "tb14.bin": "tb_14.8b", "tb15.bin": "tb_15.2l", "tb16.bin": "tb_16.3l",
              "tb17.bin": "tb_17.5l", "tb18.bin": "tb_18.7l", "tb19.bin": "tb_19.2n", "tb20.bin": "tb_20.3n",
              "tb21.bin": "tb_21.5n", "tb22.bin": "tb_22.7n", "tb23.bin": "tb_23.9n", "tb24.bin": "tb_24.13n",
              "tb25.bin": "tb_25.15n", "mb7114e.1e": "tbb-1.1e", "tbp24s10.7j": "tbb-2.7j"}

if __name__ == "__main__":
    extract("trojan", "trojanr.zip")
    mame_folder("trojan", MAME_NAMES)
