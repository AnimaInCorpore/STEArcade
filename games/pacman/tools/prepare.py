"""Verify the Pac-Man (Midway) files in the puckman archive (docs/rom_manifest.json) and unpack them to
assets/roms/extracted/pacman/ (engine/roms.py).

`puckman.zip` is MAME's merged Puck Man set: the parent's files at the top, each clone's own files in a folder of its
name.  The Midway set `pacman` takes its files from three of those folders (`pacman/`, `newpuckx/pacman.6f`,
`hangly/pacman.5e`, `hangly/pacman.5f`) and the parent's PROMs (`pm1-*`, MAME's `82s12x` names); the manifest's
`member` says where each one is.  They are written with MAME's names, so build/pacman/mame_roms/ can serve a MAME run.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from roms import extract, mame_folder

if __name__ == "__main__":
    extract("pacman", "puckman.zip")
    print("MAME rompath:", mame_folder("pacman"))
