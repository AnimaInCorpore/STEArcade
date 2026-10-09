"""Verify the Black Tiger archive and prepare the unmodified MAME ROM regions."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from paths import EXTRACTED, ROMS, build_dir

REGION_SIZES = {"maincpu": 0x50000, "audiocpu": 0x10000, "mcu": 0x1000,
                "chars": 0x8000, "tiles": 0x40000, "sprites": 0x40000, "proms": 0x400}


def prepare():
    manifest = json.loads((Path(__file__).resolve().parents[1] / "docs" / "rom_manifest.json").read_text())
    files = {}
    with zipfile.ZipFile(ROMS / "blktiger.zip") as archive:
        for entry in manifest:
            data = archive.read(entry["name"])
            if (len(data) != entry["size"] or
                    f"{zlib.crc32(data):08x}" != entry["crc32"] or
                    hashlib.sha1(data).hexdigest() != entry["sha1"]):
                raise ValueError(f"ROM verification failed: {entry['name']}")
            files[entry["name"]] = data
    # Validate the entire set before writing any output. Region gaps follow MAME's zero fill.
    regions = {name: bytearray(size) for name, size in REGION_SIZES.items()}
    for entry in manifest:
        offset = entry["offset"]
        regions[entry["region"]][offset:offset + entry["size"]] = files[entry["name"]]
    extracted = EXTRACTED / "blktiger"
    extracted.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (extracted / name).write_bytes(data)
    output = build_dir("blktiger")
    for name, data in regions.items():
        (output / (name + ".rom")).write_bytes(data)
    print(f"Verified {len(files)} ROMs; extracted to {extracted}")
    print(f"Prepared {len(regions)} regions in {output}")


if __name__ == "__main__":
    prepare()
