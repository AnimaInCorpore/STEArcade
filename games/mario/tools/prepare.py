"""Verify the mario archive (docs/rom_manifest.json, MAME's US revision E, `mario`) and unpack it to
assets/roms/extracted/mario/.

The archive is an older merged set: revision E's files lie partly at the top (shared with revision G) and partly in
`marioe/` (the manifest's `member`).  cpu.rom is the main CPU's $0000-$5FFF in address order; the fourth ROM
(tma1-c-7c_e-3.7c) stays a file of its own ($F000-$FFFF).  The sound MCU's internal ROM (M58715) has no dump: MAME
bootstraps it, the port plays recordings (docs/porting-guide.md, "Recorded sound for every port").
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from roms import extract

if __name__ == "__main__":
    extract("mario", "mario.zip", derived={"cpu.rom": ["tma1-c-7f_e-1.7f", "tma1-c-7e_e-3.7e", "tma1-c-7d_e-1.7d"]})
