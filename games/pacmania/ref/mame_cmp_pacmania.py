"""The reference renderer (engine/namcos1.py) against MAME's own picture of pacmania: engine/namcos1_mame.py.

    venv/bin/python games/pacmania/ref/mame_cmp_pacmania.py [frames...]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
from namcos1_mame import main

if __name__ == "__main__":
    sys.exit(main("pacmania", sys.argv[1:]))
