"""Reference renderer against MAME's own picture (the old wolfmame-0162 of F030Arcade: it has no Lua snapshot, so the
frames come from its AVI recording, see docs/porting-guide.md).

    python mame_cmp_1942.py [frame ...]        (default 50 100 300 700 1000 1500 1600 1800 2000 2400)

Runs MAME for the attract mode with mame_dump_1942.lua (video RAM, sprite RAM and the game's shadows of the scroll
and palette bank at E0D2 / E0D5 at those frames, plus the AVI), loads every dump into the reference machine, renders it and
counts the pixels that differ from the AVI frame (searching the lag of a few frames).  MAME= selects the executable
(default F030Arcade's wolfmame-0162), needs ffmpeg.  Result 2026-10-08: 0 differing pixels in all of the default frames
(palette banks 0 and 2, scrolling, sprites, characters).

The same dumps also gave a game logic check (done by hand, not in this tool): the reference's sprite RAM and background RAM equal MAME's
at frame n + 122 from frame 700 on (character RAM: one byte differs), the rest of E000-EFFF only in stack and task data.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "tools")]
import numpy as np
from machine import Machine1942, ROMDIR

MAME = os.environ.get("MAME", r"C:\Arbeit\F030Arcade\third_party\wolfmame-0162\mame.exe")
ROMS = str(Path(ROMDIR).parent.parent)          # assets/roms
W, H = 224, 256
FB = W * H * 3
LAG0 = 119                                       # AVI index = hook count + 119 (+/- 1)


def record(frames, work):
    env = dict(os.environ, FRAMES=" ".join(map(str, frames)), LAST=str(max(frames) + 130))
    subprocess.run([MAME, "1942", "-rompath", ROMS, "-window", "-sound", "none", "-nothrottle", "-frameskip", "0",
                    "-skip_gameinfo", "-seconds_to_run", "100", "-aviwrite", "m1942.avi",
                    "-autoboot_script", str(HERE / "mame_dump_1942.lua")], cwd=work, env=env,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)


def avi_frames(avi, need):
    out = {}
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(avi), "-an", "-fps_mode", "passthrough", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, bufsize=FB * 4)
    i = 0
    while i <= max(need):
        b = p.stdout.read(FB)
        if len(b) < FB:
            break
        if i in need:
            out[i] = np.frombuffer(b, np.uint8).reshape(H, W, 3).copy()
        i += 1
    p.kill()
    return out


def main():
    frames = [int(a) for a in sys.argv[1:]] or [50, 100, 300, 700, 1000, 1500, 1600, 1800, 2000, 2400]
    work = tempfile.mkdtemp(prefix="mame1942_")
    record(frames, work)
    need = {k + LAG0 + d for k in frames for d in (-2, -1, 0, 1, 2)}
    pics = avi_frames(Path(work) / "snap" / "m1942.avi", need)
    m = Machine1942()
    worst = 0
    for k in frames:
        d = open(os.path.join(work, "dump_%d.bin" % k), "rb").read()
        m.sprram[:] = d[0xC00:0xC80]
        m.fg[:] = d[0x1000:0x1800]
        m.bg[:] = d[0x1800:0x1C00]
        ram = d[0x2000:0x3000]
        m.scroll = [ram[0xD2], ram[0xD3]]
        m.palette_bank = ram[0xD5] & 3
        mine = m.render_rgb()
        diff, lag = min((int((mine != pics[k + LAG0 + dl]).any(axis=2).sum()), dl) for dl in (-2, -1, 0, 1, 2))
        worst = max(worst, diff)
        print("frame %5d: %d of %d pixels differ (lag %+d), palette bank %d, scroll %d" % (k, diff, W * H, lag, m.palette_bank, m.scrollx))
    print("worst:", worst)
    return 1 if worst else 0


if __name__ == "__main__":
    sys.exit(main())
