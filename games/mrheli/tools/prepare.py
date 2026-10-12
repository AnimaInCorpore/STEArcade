"""Verify the mrheli archive (docs/rom_manifest.json) and unpack it to assets/roms/extracted/mrheli/ (engine/roms.py).

The archive is an older romset: it lacks the i8751 MCU program mh_c-pr-.ic1 (4 KB, crc32 897dc4ee) that MAME 0.289
needs; the game really runs it (shared-RAM test, protection, samples: with a blank MCU it stops at "RAM NG 7").  Put
the file as assets/roms/mh_c-pr-.ic1 (or a current mrheli.zip).  build/mrheli/mame_roms/ gets MAME's names and
zero-filled stand-ins for the PROMs and PALs the driver loads but never reads (see games/rtype/tools/prepare.py).
"""
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from paths import EXTRACTED, ROMS, ROOT
from roms import extract, fingerprint, mame_folder

MAME_ROMS = ROOT / "build" / "mrheli" / "mame_roms"
MCU = ("mh_c-pr-.ic1", {"size": 4096, "crc32": "897dc4ee", "sha1": "05a24bf76e8fa9ca96ba9376cbf44d299df04138"})
MAME_NAMES = {"b-b0-.rom": "mh_b-b0-.ic26", "b-b1-.rom": "mh_b-b1-.ic27", "b-b2-.rom": "mh_b-b2-.ic25",
              "b-b3-.rom": "mh_b-b3-.ic24", "c-v0-b.rom": "mh_c-v0-b.ic44", "mh-b-a0.bin": "mh_b-a0.ic21",
              "mh-b-a1.bin": "mh_b-a1.ic22", "mh-b-a2.bin": "mh_b-a2.ic20", "mh-b-a3.bin": "mh_b-a3.ic23",
              "mh-c-00.bin": "mh_c-00.ic53", "mh-c-10.bin": "mh_c-10.ic51", "mh-c-20.bin": "mh_c-20.ic49",
              "mh-c-30.bin": "mh_c-30.ic47", "mh-c-h0.bin": "mh_c-h0-.ic40", "mh-c-h1.bin": "mh_c-h1-.ic41",
              "mh-c-h3.bin": "mh_c-h3-.ic43", "mh-c-l0.bin": "mh_c-l0-.ic37", "mh-c-l1.bin": "mh_c-l1-.ic36",
              "mh-c-l3.bin": "mh_c-l3-.ic34"}
STAND_INS = {"m72_a-8l-.ic66": 256, "m72_a-9l-.ic75": 256, "m72_a-3d-.ic11": 279, "m72_a-4d-.ic19": 279,
             "mh-c-3f-.ic13": 279}


def mcu():
    """the MCU program from assets/roms/ or the archive, verified, into extracted/mrheli/ (None: missing)"""
    name, want = MCU
    data = (ROMS / name).read_bytes() if (ROMS / name).exists() else None
    if data is None:
        with zipfile.ZipFile(ROMS / "mrheli.zip") as z:
            data = z.read(name) if name in z.namelist() else None
    if data is None:
        return None
    if fingerprint(data) != want:
        sys.exit("%s does not match (%s, expected %s)" % (name, fingerprint(data), want))
    (EXTRACTED / "mrheli" / name).write_bytes(data)
    return data


if __name__ == "__main__":
    extract("mrheli", "mrheli.zip")
    if mcu() is None:
        print("mrheli: the MCU program %s is missing (see this file's docstring): no MAME runs" % MCU[0])
    else:
        mame_folder("mrheli", MAME_NAMES, STAND_INS)
