"""Verify the rthunder archive (docs/rom_manifest.json) and unpack it to assets/roms/extracted/rthunder/ (engine/roms.py).

The archive is MAME's `rthunder` (Rolling Thunder, rev 3, Namco System 86) as a merged set: the parent's 28 files are
at the top level, the clones' ROMs in sub folders (not used).  The HD637A01 sub-MCU (`hd637a01x0p.e3`) has no dump.
"""
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from roms import extract, fingerprint
from paths import ROMS, game_dir

if __name__ == "__main__":
    mf = game_dir("rthunder") / "docs" / "rom_manifest.json"
    if not mf.exists():                                   # (once: list the parent's files, the top level of the set)
        import json
        with zipfile.ZipFile(ROMS / "rthunder.zip") as z:
            names = sorted(n for n in z.namelist() if "/" not in n)
            mf.write_text(json.dumps([dict(name=n, **fingerprint(z.read(n))) for n in names], indent=1) + "\n")
    extract("rthunder", "rthunder.zip")
