"""Verify the dkong3 archive (docs/rom_manifest.json, MAME's `dkong3`: the parent files at the top of the merged set) and
unpack it to assets/roms/extracted/dkong3/.

cpu.rom is the main CPU's $0000-$5FFF (dk3c.7b, 7c, 7d); dk3c.7e ($8000-$9FFF) stays a file of its own.  The two sound
CPUs' programs (dk3c.5l, dk3c.6h: N2A03s, $8000-$9FFF of their own spaces) are used by MAME only: the port plays
recordings (docs/porting-guide.md, "Recorded sound for every port").
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from roms import extract

if __name__ == "__main__":
    extract("dkong3", "dkong3.zip", derived={"cpu.rom": ["dk3c.7b", "dk3c.7c", "dk3c.7d"]})
