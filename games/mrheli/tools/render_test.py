"""Mr. HELI's renderer test: games/rtype/tools/render_test.py (the shared Irem M72 renderer) with --game mrheli.

    venv/bin/python games/mrheli/tools/render_test.py [the same options]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "rtype" / "tools"))
import render_test

if __name__ == "__main__":
    sys.argv[1:1] = ["--game", "mrheli"]
    sys.exit(render_test.main())
