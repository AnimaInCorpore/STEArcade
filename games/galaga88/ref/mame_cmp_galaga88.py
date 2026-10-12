"""The reference renderer (engine/namcos1.py) against MAME's own picture of galaga88: engine/namcos1_mame.py.

    venv/bin/python games/galaga88/ref/mame_cmp_galaga88.py [frames...]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from namcos1_mame import main

if __name__ == "__main__":
    sys.exit(main("galaga88", sys.argv[1:]))
