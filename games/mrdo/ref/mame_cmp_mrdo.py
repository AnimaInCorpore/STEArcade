"""The reference machine against MAME's own picture, every frame of the attract mode.

    python games/mrdo/ref/mame_cmp_mrdo.py [seconds] [--avi existing.avi]

No MAME 0.289 on the Windows machine: this uses F030Arcade's WolfMAME 0.162 (`-aviwrite`: uncompressed RGB at the
native size, 224 x 288 already rotated; see docs/porting-guide.md, "Frames from an old MAME").  MAME runs from a scratch
folder with build/mrdo/mame_roms (tools/prepare.py) and no input, so both run the same attract mode from power on.
Each MAME frame is looked up among the reference's frames by its exact RGB picture: the colours (MAME's resistor
weights), the tile and sprite decode, the positions (sprites 0-2 one line lower) and the logic's timing all have to
agree for a match.  The AVI is written at 60 fps from a 60.606 Hz board, so WolfMAME drops about one frame in 99 and
the offset between the two grows by one each time; a lookup by picture does not care.

Result (2026-10-29, 45 s): 2638 of 2701 MAME frames equal a reference frame.  62 of the rest are the boot's RAM test
(patterns caught mid-test: Z80 timing), one is an energizer's blink a frame apart (frame 1495, 30 pixels).  The exit
status allows two such frames after the boot.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE.parents[2] / "engine"))
import mamewin                       # (MAME runs minimized)
from machine import MrDo  # noqa: E402
from paths import ROOT  # noqa: E402

MAME = os.environ.get("WOLFMAME") or r"C:\Arbeit\F030Arcade\third_party\wolfmame-0162\mame.exe"
W, H = 192, 240
BOOT_FRAMES = 0


def record(seconds):
    out = Path(tempfile.mkdtemp(prefix="mame_mrdo_"))
    cmd = [MAME, "mrdo", "-rompath", str(ROOT / "build" / "mrdo" / "mame_roms"), "-window", "-sound", "none",
           "-nothrottle", "-frameskip", "0", "-skip_gameinfo", "-seconds_to_run", str(seconds), "-aviwrite", "mrdo.avi"]
    mamewin.run(cmd, cwd=out, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out / "snap" / "mrdo.avi"


def frames(avi):
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(avi), "-an", "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-fps_mode", "passthrough", "-"], stdout=subprocess.PIPE)
    n = W * H * 3
    while True:
        b = p.stdout.read(n)
        if len(b) < n:
            break
        yield np.frombuffer(b, np.uint8).reshape(H, W, 3)
    p.wait()


def main():
    args = sys.argv[1:]
    avi = None
    if "--avi" in args:
        i = args.index("--avi")
        avi = Path(args[i + 1])
        del args[i:i + 2]
    seconds = int(args[0]) if args else 45
    if avi is None:
        avi = record(seconds)
        mame = list(frames(avi))
        shutil.rmtree(avi.parent.parent)      # about 12 MB a second of recording
    else:
        mame = list(frames(avi))
    print("MAME: %d frames from %s" % (len(mame), avi))

    m = MrDo()
    ref = {}                                  # picture hash -> first reference frame showing it
    ref_pics = []
    for f in range(len(mame) + 120):
        m.run_frame()
        pic = np.ascontiguousarray(m.render_rgb())
        ref_pics.append(pic)
        ref.setdefault(hashlib.sha1(pic.tobytes()).digest(), f)

    offsets = {}
    unmatched = []
    for k, pic in enumerate(mame):
        f = ref.get(hashlib.sha1(np.ascontiguousarray(pic).tobytes()).digest())
        if f is None:
            unmatched.append(k)
        else:
            offsets[f - k] = offsets.get(f - k, 0) + 1
    print("matched %d of %d MAME frames; reference frame - MAME frame: %s" %
          (len(mame) - len(unmatched), len(mame), dict(sorted(offsets.items(), key=lambda kv: -kv[1])[:8])))
    boot = [k for k in unmatched if k < BOOT_FRAMES]
    print("unmatched in the boot's RAM / ROM test (MAME frames < %d): %d; after it: %d" %
          (BOOT_FRAMES, len(boot), len(unmatched) - len(boot)))
    if unmatched:
        best = max(offsets, key=offsets.get) if offsets else 0
        print("unmatched MAME frames (first 20):", unmatched[:20])
        for k in unmatched[:8]:
            near = [f for f in range(k + best - 6, k + best + 7) if 0 <= f < len(ref_pics)]
            f = min(near, key=lambda f: np.any(ref_pics[f] != mame[k], axis=2).sum())
            if near:
                d = np.any(ref_pics[f] != mame[k], axis=2)
                ys, xs = np.nonzero(d)
                print("  MAME %d vs reference %d: %d pixels differ, rows %d-%d, columns %d-%d" %
                      (k, f, d.sum(), ys.min(), ys.max(), xs.min(), xs.max()))
    colours = {tuple(c) for pic in mame[::30] for c in pic.reshape(-1, 3)}
    print("MAME colours seen:", sorted(colours))
    return 0 if len(unmatched) - len(boot) <= 2 else 1


if __name__ == "__main__":
    sys.exit(main())
