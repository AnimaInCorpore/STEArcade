"""ROM sets: a game's archive verified against its manifest and unpacked to assets/roms/extracted/<game>/.

    extract(game, "dkong.zip", derived={"cpu.rom": ["c_5et_g.bin", ...]})

The manifest (games/<game>/docs/rom_manifest.json) lists the files the port uses: name, size, crc32, sha1.  Every one
is checked before anything is written; `derived` files are the concatenation of manifest files (Donkey Kong's
cpu.rom).  The extracted folders are not in git: port.py runs the game's tools/prepare.py when one is missing.
"""
import hashlib
import json
import sys
import zipfile
import zlib

from paths import EXTRACTED, ROMS, game_dir


def fingerprint(data):
    return {"size": len(data), "crc32": "%08x" % zlib.crc32(data), "sha1": hashlib.sha1(data).hexdigest()}


def extract(game, archive, derived=None):
    manifest = json.loads((game_dir(game) / "docs" / "rom_manifest.json").read_text())
    files = {}
    with zipfile.ZipFile(ROMS / archive) as z:
        for entry in manifest:
            data = z.read(entry["name"])
            got = fingerprint(data)
            if any(got[k] != entry[k] for k in ("size", "crc32", "sha1")):
                sys.exit("%s: %s does not match the manifest (%s, expected %s)" % (archive, entry["name"], got, entry))
            files[entry["name"]] = data
    for name, parts in (derived or {}).items():
        files[name] = b"".join(files[p] for p in parts)
    out = EXTRACTED / game
    out.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (out / name).write_bytes(data)
    print("%s: %d ROMs verified, %d files in %s" % (archive, len(manifest), len(files), out))


def write_manifest(game, names):
    """(once, when a set is added) the manifest of already verified files in extracted/<game>/"""
    entries = [dict(name=n, **fingerprint((EXTRACTED / game / n).read_bytes())) for n in names]
    (game_dir(game) / "docs" / "rom_manifest.json").write_text(json.dumps(entries, indent=1) + "\n")
