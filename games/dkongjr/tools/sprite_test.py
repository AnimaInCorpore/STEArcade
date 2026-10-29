"""Sprites at the game area's edges: games/dkong/tools/sprite_test.py on Junior's program (src/sprites.s is Donkey
Kong's).  The program and its map must be one build (tools/build.py without --out writes both).

    python sprite_test.py
"""
import runpy, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.argv = [sys.argv[0], "--prg", str(ROOT / "run" / "dkongjr" / "DKONGJR.PRG"),
            "--map", str(ROOT / "build" / "dkongjr" / "dkongjr.map")]
runpy.run_path(str(ROOT / "games" / "dkong" / "tools" / "sprite_test.py"), run_name="__main__")
