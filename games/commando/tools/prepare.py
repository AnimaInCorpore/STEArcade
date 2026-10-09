"""Verify the Commando archive and prepare the unmodified MAME ROM regions."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from paths import EXTRACTED, ROMS, build_dir

REGION_SIZES = {'maincpu': 49152, 'audiocpu': 65536, 'chars': 16384, 'tiles': 98304, 'sprites': 98304, 'irqprom': 256, 'proms': 1280}


def prepare():
    manifest = json.loads((Path(__file__).resolve().parents[1] / "docs" / "rom_manifest.json").read_text())
    files = {}
    with zipfile.ZipFile(ROMS / "commando.zip") as archive:
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
    extracted = EXTRACTED / "commando"
    extracted.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (extracted / name).write_bytes(data)
    output = build_dir("commando")
    for name, data in regions.items():
        (output / (name + ".rom")).write_bytes(data)
    # Opcode fetches are decrypted; operand/data reads retain the original ROM.
    opcodes = bytearray(regions["maincpu"])
    for address in range(1, len(opcodes)):
        src = opcodes[address]
        opcodes[address] = (src & 0x11) | ((src & 0xe0) >> 4) | ((src & 0x0e) << 4)
    (output / "opcodes.rom").write_bytes(opcodes)
    print(f"Verified {len(files)} ROMs; extracted to {extracted}")
    print(f"Prepared {len(regions)} regions in {output}")


if __name__ == "__main__":
    prepare()
