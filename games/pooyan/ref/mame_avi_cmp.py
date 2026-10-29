"""Pooyan: the reference board (tools/machine.py, MAME's schedule) against a WolfMAME 0.162 recording, frame by frame.

    python games/pooyan/ref/mame_avi_cmp.py [--seconds S] [--keep DIR] [--every N]

This Windows machine has no MAME with the Lua API of engine/mame_cmp.py (0.289); F030Arcade's wolfmame-0162 knows
the set, and its -aviwrite writes uncompressed RGB24 at the native size (porting-guide.md, "Frames from an old MAME").
MAME runs from a fresh directory with no input (the attract mode); the reference runs from power-on and renders its
memory at each VBLANK; the AVI's frame k is matched to the reference frame k + offset (the offset found on the first
frames that differ from their neighbours).  Every frame is compared: 0 differing pixels expected; the first few
mismatching frames are saved as reference | MAME | differences.
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools"), str(Path(__file__).resolve().parents[3] / "engine")]
import mamewin                       # (MAME runs minimized)
from machine import Pooyan
from paths import ROMS

MAME = Path(r"C:/Arbeit/F030Arcade/third_party/wolfmame-0162/mame.exe")
W, H = 224, 256


def record(out, seconds):
    out.mkdir(parents=True, exist_ok=True)
    avi = out / "snap" / "p.avi"
    if not avi.exists():
        with (out / "mame.log").open("w") as log:
            mamewin.run([str(MAME), "pooyan", "-rompath", str(ROMS), "-aviwrite", "p.avi", "-sound", "none",
                            "-nothrottle", "-frameskip", "0", "-seconds_to_run", str(seconds), "-window",
                            "-skip_gameinfo"], cwd=out, stdout=log, stderr=log, check=True, timeout=900)
    return avi


def frames(avi):
    p = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-i", str(avi), "-an", "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-fps_mode", "passthrough", "-"], stdout=subprocess.PIPE)
    n = W * H * 3
    while True:
        b = p.stdout.read(n)
        if len(b) < n:
            break
        yield np.frombuffer(b, np.uint8).reshape(H, W, 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=45)
    ap.add_argument("--keep", default=None)
    ap.add_argument("--every", type=int, default=1)
    a = ap.parse_args()
    out = Path(a.keep) if a.keep else Path(tempfile.mkdtemp(prefix="mame_pooyan_"))
    avi = record(out, a.seconds)
    shots = list(frames(avi))
    print("%d MAME frames in %s" % (len(shots), avi))
    g = Pooyan()
    ref = []
    for _ in range(len(shots) + 8):
        g.run_frame()
        ref.append(g.render_rgb())
    # the offset: the one that makes the most of the first 600 frames equal
    best = max(range(-4, 5), key=lambda o: sum(
        np.array_equal(ref[k + o], shots[k]) for k in range(max(0, -o), min(600, len(shots)))))
    print("offset: AVI frame k = reference frame k %+d" % best)
    bad, worst, saved = 0, 0, 0
    from PIL import Image
    for k in range(max(0, -best), len(shots), a.every):
        r, s = ref[k + best], shots[k]
        d = np.any(r != s, axis=2)
        n = int(d.sum())
        if n:
            bad += 1
            worst = max(worst, n)
            if saved < 5:
                diff = np.where(d[:, :, None], np.uint8([255, 0, 255]), np.uint8(0))
                Image.fromarray(np.concatenate([r, s, diff], 1)).save(out / ("cmp%d.png" % k))
                print("frame %d: %d pixels differ" % (k, n))
                saved += 1
    print("%d of %d frames differ (worst %d pixels); pictures in %s" % (
        bad, len(range(max(0, -best), len(shots), a.every)), worst, out))
    return int(bad != 0)


if __name__ == "__main__":
    sys.exit(main())
