"""Helpers of the ref/mame_cmp_<game>.py scripts that use engine/mame_frames.lua (several frames in one MAME run).

    d = run_mame("trackfld", [60, 600], dumps=["maincpu:0x1800:0x3fff"], taps=[])
    mem = load_dump(d, 600, "maincpu", 0x1800)      # 64 KB image with the dumped range in place
    shot = load_shot(d, 600); pens = load_pens(d)
    n = diff_pixels(rgb, shot)
MAME runs in a fresh temporary directory (no nvram/ or cfg/ from an earlier run), headless but with -window (the
snapshot needs a video system), -seconds_to_run 250 (no startup screens).
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from paths import ENGINE, ROMS

LUA = ENGINE / "mame_frames.lua"


def run_mame(game, frames, dumps, taps=(), timeout=600, keep=None):
    exe = os.environ.get("MAME") or shutil.which("mame")
    if not exe:
        raise RuntimeError("MAME not found; set MAME")
    out = Path(keep) if keep else Path(tempfile.mkdtemp(prefix="mame_%s_" % game))
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, OUT=str(out), FRAMES=" ".join(map(str, frames)), DUMPS=" ".join(dumps), TAPS=" ".join(taps))
    with (out / "mame.log").open("w") as log:
        r = subprocess.run([exe, game, "-rompath", str(ROMS), "-window", "-sound", "none", "-nothrottle",
                            "-frameskip", "0", "-seconds_to_run", "250", "-skip_gameinfo", "-autoboot_script", str(LUA),
                            "-snapshot_directory", str(out)], cwd=out, env=env, stdout=log, stderr=log, timeout=timeout)
    last = max(frames)
    if not (out / ("f%d.png" % last)).exists():
        raise RuntimeError("MAME capture failed (exit %d); see %s" % (r.returncode, out / "mame.log"))
    return out


def load_dump(d, frame, tag, start, into=None):
    data = (Path(d) / ("f%d_%s.bin" % (frame, tag))).read_bytes()
    mem = into if into is not None else bytearray(0x10000)
    mem[start:start + len(data)] = data
    return mem


def load_shot(d, frame):
    return np.array(Image.open(Path(d) / ("f%d.png" % frame)).convert("RGB"))


def load_pens(d):
    return np.array([[int(l.split()[1][i:i + 2], 16) for i in (0, 2, 4)]
                     for l in (Path(d) / "pens.txt").read_text().splitlines()], np.uint8)


def load_taps(d, frame):
    """[(tag, line, offset, data)] of the writes to the TAPS ranges since the previous frame's end (line: the beam
    position in lines, its integer part MAME's vpos)."""
    out = []
    for l in (Path(d) / ("f%d_taps.txt" % frame)).read_text().splitlines():
        t, v, o, x = l.split()
        out.append((t, float(v), int(o, 16), int(x, 16)))
    return out


def diff_pixels(rgb, shot):
    if rgb.shape != shot.shape:
        raise RuntimeError("shape %s, MAME %s" % (rgb.shape, shot.shape))
    return int(np.any(rgb != shot, axis=2).sum())


def save_compare(path, rgb, shot):
    diff = np.any(rgb != shot, axis=2)
    marked = shot.copy()
    marked[diff] = (255, 0, 255)
    Image.fromarray(np.hstack((rgb, shot, marked))).save(path)


def ram_diff(a, b, ranges):
    """Differing bytes of two 64 KB images over [(start, end)] (end inclusive): (count, total, first addresses)."""
    n = tot = 0
    first = []
    for s, e in ranges:
        x = np.frombuffer(bytes(a[s:e + 1]), np.uint8)
        y = np.frombuffer(bytes(b[s:e + 1]), np.uint8)
        idx = np.nonzero(x != y)[0]
        n += len(idx)
        tot += e + 1 - s
        first += ["%04X" % (s + i) for i in idx[:8]]
    return n, tot, first[:8]


def parse_args(default_frames):
    """[frame ...] [--keep DIR] -> (frames, keep)"""
    import sys
    args = sys.argv[1:]
    keep = None
    if "--keep" in args:
        keep = args[args.index("--keep") + 1]
        args.remove(keep)
        args.remove("--keep")
    return [int(a) for a in args] or default_frames, keep


def single_cpu(game, machine_cls, video, dump, ram, default_frames):
    """mame_cmp for a board whose main CPU alone matters: dump = (start, end) of the main CPU's space to capture,
    ram = the ranges whose bytes the logic comparison counts.  (1) the reference renderer draws MAME's memory;
    (2) the reference machine from power-on: its RAM against MAME's at the same frames."""
    frames, keep = parse_args(default_frames)
    d = run_mame(game, frames, ["maincpu:0x%x:0x%x" % dump], keep=keep)
    pens = load_pens(d)
    pen_diff = int(np.any(video.pens != pens, axis=1).sum())
    print("pens: %d of %d differ" % (pen_diff, len(pens)))
    worst = pen_diff
    m = machine_cls()
    for f in frames:
        mem = load_dump(d, f, "maincpu", dump[0])
        rgb = video.render_rgb(mem)
        shot = load_shot(d, f)
        n = diff_pixels(rgb, shot)
        worst = max(worst, n)
        save_compare(d / ("cmp%d.png" % f), rgb, shot)
        while m.frame < f:
            m.run_frame()
        k, tot, first = ram_diff(m.mem, mem, ram)
        own = diff_pixels(m.render_rgb(), shot)
        print("frame %5d: render %5d pixels differ; logic RAM %4d of %d bytes differ %s; its own picture %d pixels" % (
            f, n, k, tot, " ".join(first), own))
    print("compare pictures (reference | MAME | differences) in", d)
    return int(worst != 0)
