"""The Namco System 1 reference renderer (engine/namcos1.py) against MAME's own picture.

    capture(game, frames) -> {frame: folder}     MAME runs the set, engine/namcos1_dump.lua writes the video state
    compare(game, frames)                        renders each captured state with the reference, counts the pixels
                                                 that differ from MAME's snapshot (compare.png: reference | MAME)

The games' ref/mame_cmp_<game>.py call this; `port.py mame <game>` runs them.  MAME is `mame` on the PATH or $MAME.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mamewin                       # (MAME runs minimized)
from namcos1 import NamcoS1
from paths import ROMS

LUA = Path(__file__).with_name("namcos1_dump.lua")
RANGES = [(0x2E0000, 0x8000), (0x2F0000, 0x8000), (0x2FC000, 0x1000), (0x2FD000, 0x20), (0x2FF000, 0x800),
          (0x300000, 0x8000)]


def capture(game, frames, extra=()):
    exe = os.environ.get("MAME") or shutil.which("mame")
    if not exe:
        raise RuntimeError("MAME not found; set MAME")
    out = Path(tempfile.mkdtemp(prefix="mame_%s_" % game))
    with (out / "mame.log").open("w") as log:
        mamewin.run([exe, game, "-rompath", str(ROMS), "-window", "-sound", "none", "-nothrottle",
                        "-frameskip", "0", "-seconds_to_run", "250", "-skip_gameinfo", *extra,
                        "-autoboot_script", str(LUA), "-snapshot_directory", str(out), "-snapname", "shot"],
                       cwd=out, env=dict(os.environ, OUT=str(out), FRAMES=" ".join(map(str, frames))),
                       stdout=log, stderr=log, check=True, timeout=600)
    return {f: out / str(f) for f in frames}


def load_state(m, folder):
    """the captured video state into a NamcoS1 (cpus=False is enough)"""
    data = (Path(folder) / "video.bin").read_bytes()
    pos = 0
    for start, n in RANGES:
        chunk = data[pos:pos + n]
        pos += n
        if start == 0x2E0000:
            for o in range(n):
                m.c116_wr(o, chunk[o])
        elif start == 0x2F0000:
            m.vram[:] = chunk
        elif start == 0x2FC000:
            m.scratch[:] = chunk[:0x800]
            m.spriteram[:] = chunk[0x800:]
            m.flip = bool(m.spriteram[0x7F6] & 1)
        elif start == 0x2FD000:
            m.control[:] = chunk
        elif start == 0x2FF000:
            m.triram[:] = chunk
        else:
            m.ram[:] = chunk


def mame_pens(folder):
    lines = (Path(folder) / "pens.txt").read_text().splitlines()
    return np.array([[int(l.split()[1][i:i + 2], 16) for i in (0, 2, 4)] for l in lines], np.uint8)


def compare(game, frames, verbose=True):
    from PIL import Image
    m = NamcoS1(game, cpus=False)
    worst = 0
    for f, folder in capture(game, frames).items():
        load_state(m, folder)
        pens = mame_pens(folder)
        mine = m.palette_rgb()
        bad_pens = int(np.any(pens[:0x2000] != mine, axis=1).sum())
        rgb = m.render_rgb()
        shot = np.array(Image.open(folder / "shot.png").convert("RGB"))
        if rgb.shape != shot.shape:
            raise RuntimeError("shape %s, MAME %s" % (rgb.shape, shot.shape))
        diff = int(np.any(rgb != shot, axis=2).sum())
        worst = max(worst, diff)
        Image.fromarray(np.hstack((rgb, shot))).save(folder / "compare.png")
        if verbose:
            print("%s frame %d: %d pixels differ, %d pens differ; %s" % (game, f, diff, bad_pens,
                                                                       folder / "compare.png"), flush=True)
    return worst


def main(game, argv):
    frames = [int(a) for a in argv] or [300, 700, 1200, 2000, 3000]
    return int(compare(game, frames) != 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2:]))
