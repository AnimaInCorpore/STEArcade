"""The reference renderer (engine/namcos1.py) against MAME's own picture of dspirit: engine/namcos1_mame.py.

    venv/bin/python games/dspirit/ref/mame_cmp_dspirit.py [frames...]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from namcos1_mame import main

if __name__ == "__main__":
    sys.exit(main("dspirit", sys.argv[1:]))
