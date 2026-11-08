"""SCREEN.BIN (src/ste.s dbg_counters: the shown buffer's 224 picture lines of 544 bytes) as a PNG.

    python games/rthunder/tools/screen.py run/<tag>/SCREEN.BIN out.png [fine]
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[3] / "engine")]
from paths import build_dir
from render_test import planar_to_index


def main():
    data = Path(sys.argv[1]).read_bytes()
    cnt = Path(sys.argv[1]).with_name("COUNTERS.BIN")
    fine = int(sys.argv[3]) if len(sys.argv) > 3 else (int.from_bytes(cnt.read_bytes()[22:24], "big") if cnt.exists() else 0)
    lines = np.frombuffer(data, np.uint8).reshape(224, 544)[:, :168]
    idx = planar_to_index(bytes(lines.tobytes()), 224, 21)[:, fine:fine + 320]
    pal = np.load(build_dir("rthunder") / "palfit.npz")["palette"].astype(np.uint8)
    Image.fromarray(pal[idx]).resize((960, 672), Image.NEAREST).save(sys.argv[2])


if __name__ == "__main__":
    main()
