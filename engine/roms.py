"""ROM sets: a game's archive verified against its manifest and unpacked to assets/roms/extracted/<game>/.

    extract(game, "dkong.zip", derived={"cpu.rom": ["c_5et_g.bin", ...]})

The manifest (games/<game>/docs/rom_manifest.json) lists the files the port uses: name, size, crc32, sha1 (and
`member`, the file's path in the archive when that differs from its name: a clone's files in a merged set).  Every one
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
            data = z.read(entry.get("member", entry["name"]))     # member: its path in a merged archive (Pac-Man)
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


def mame_folder(game, names=None, stand_ins=None, extra=()):
    """build/<game>/mame_roms/<game>/ for a MAME 0.289 run (-rompath build/<game>/mame_roms) when the archive is from an
    older romset: a ROM folder is matched by name, not CRC, so the files get MAME's names (names: ours -> MAME's);
    stand_ins: {name: size} zero-filled files MAME requires but the driver never reads (PROMs, PALs; a checksum warning
    only); extra: files outside the archive (assets/roms/<name>) copied as they are.  Returns the -rompath."""
    out = ROMS.parent.parent / "build" / game / "mame_roms"
    (out / game).mkdir(parents=True, exist_ok=True)
    for f in (EXTRACTED / game).iterdir():
        (out / game / (names or {}).get(f.name, f.name)).write_bytes(f.read_bytes())
    for name, size in (stand_ins or {}).items():
        (out / game / name).write_bytes(bytes(size))
    for name in extra:
        (out / game / name).write_bytes((ROMS / name).read_bytes())
    return out
