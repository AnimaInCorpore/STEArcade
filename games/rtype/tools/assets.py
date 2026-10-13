"""The STE renderer's data for R-Type (engine/rt/m72render.s through src/render.s): the shared Irem M72 converter
(engine/m72_assets.py: the tiles' and sprites' pen bit planes, the pens they use, the Oklab and 5-bit -> STE level
tables) into build/rtype/m72_*.bin.  Nothing here is in STE colours: the renderer maps the pens at run time.

    venv/bin/python games/rtype/tools/assets.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "engine"))
import m72_assets


def build(out=None):
    out = m72_assets.build("rtype", out)
    import m72_palettes                  # (the colours of the scenes: from the recorded states, render_test.py)
    m72_palettes.build("rtype", out)
    return out


if __name__ == "__main__":
    print("assets in", build(), "(tiles FG %d, BG %d, sprites %d)" % m72_assets.counts("rtype"))
