"""Verify 1943 Euro or US Rev C ROMs and construct the unmodified MAME regions.

Accept a complete archive, or missing shared ROMs alongside it in assets/roms.
Resolve mislabeled archive entries by size/CRC32/SHA1, never by filename alone.
"""
import hashlib
import json
from pathlib import Path
import sys
import zipfile
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'engine'))
from paths import EXTRACTED, ROMS, build_dir

REGION_SIZES = {'maincpu': 0x30000, 'audiocpu': 0x10000, 'mcu': 0x1000,
                'gfx1': 0x8000, 'gfx2': 0x40000, 'gfx3': 0x10000,
                'gfx4': 0x40000, 'tilerom': 0x10000, 'proms': 0xc00}
MANIFEST = Path(__file__).resolve().parents[1] / 'docs' / 'rom_manifest.json'


def fingerprint(data):
    return len(data), f'{zlib.crc32(data):08x}', hashlib.sha1(data).hexdigest()


def verify(set_name=None):
    if set_name is None:
        set_name = "1943u" if (ROMS / "1943u.zip").exists() else "1943"
    if set_name not in ("1943", "1943u"):
        raise ValueError("Unknown 1943 ROM set: " + set_name)
    manifest = MANIFEST if set_name == "1943u" else MANIFEST.with_name("rom_manifest_euro.json")
    entries = json.loads(manifest.read_text())
    candidates = {}
    archives = [ROMS / '1943u.zip', ROMS / '1943.zip']
    for path in archives:
        if not path.exists():
            continue
        with zipfile.ZipFile(path) as archive:
            for item in archive.infolist():
                if not item.is_dir():
                    data = archive.read(item)
                    source = item.filename if path.name == '1943u.zip' else path.name + '/' + item.filename
                    candidates.setdefault(fingerprint(data), (source, data))
    files, sources, missing = {}, {}, []
    for entry in entries:
        loose = ROMS / entry['name']
        if loose.is_file():
            data = loose.read_bytes()
            candidates.setdefault(fingerprint(data), (str(loose), data))
        match = candidates.get((entry['size'], entry['crc32'], entry['sha1']))
        if match is None:
            missing.append(entry)
        else:
            sources[entry['name']], files[entry['name']] = match
    return entries, files, sources, missing


def prepare(set_name=None):
    set_name = set_name or ("1943u" if (ROMS / "1943u.zip").exists() else "1943")
    entries, files, sources, missing = verify(set_name)
    print("ROM set:", set_name)
    for name, source in sources.items():
        if Path(source).name != name:
            print(f'{name}: verified content from {source}')
    if missing:
        for entry in missing:
            print(f"Missing verified ROM: {entry['name']} ({entry['size']} bytes, "
                  f"CRC32 {entry['crc32']}, SHA1 {entry['sha1']})", file=sys.stderr)
        print('Add the missing ROMs to assets/roms or provide a complete archive. '
              'No regions were written.', file=sys.stderr)
        return 2
    regions = {name: bytearray(size) for name, size in REGION_SIZES.items()}
    for entry in entries:
        offset, size = entry['offset'], entry['size']
        assert 0 <= offset <= len(regions[entry['region']]) - size
        regions[entry['region']][offset:offset+size] = files[entry['name']]
    extracted = EXTRACTED / '1943'
    extracted.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (extracted / name).write_bytes(data)
    output = build_dir('1943')
    for name, data in regions.items():
        (output / (name + '.rom')).write_bytes(data)
    (output / 'set.txt').write_text(set_name + '\n')
    print(f'Verified {len(files)} ROMs; prepared {len(regions)} regions in {output}')
    return 0


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", choices=["1943", "1943u"], default=None)
    args = parser.parse_args()
    sys.exit(prepare(args.set))
