"""Gauntlet: the reference renderer (tools/video.py) and the reference board (tools/machine.py) against MAME 0.289
(`gauntlet`, rev 14).

    python games/gauntlet/ref/mame_cmp_gauntlet.py [frame ...] [--keep DIR] [--reuse DIR] [--render-only]

One MAME run (engine/mame_frames.lua, PENS_EVERY) dumps at the frames the video RAM $900000-$905FFF and the palette
$910000-$9107FF and taps the write-only x scroll $930000 and the y scroll / tile bank word $905F6E (RAM, tapped for
the beam lines of its writes).  The renderer draws MAME's memory with the scroll values of the frame: 0 differing
pixels against MAME's snapshot (336 x 240) and 0 differing pens.  A scroll write on a visible line v makes MAME draw
lines <= v with the old value (update_partial(vpos)): such frames are drawn in those line ranges and reported.
MAME runs up to 400 s here (the attract mode is longer than mame_cmp.run_mame's 250 s).
(2) logic: the board runs from power-on to the same frames: the work RAM $800000-$801FFF, the video RAM, the palette
and the sound CPU's RAM byte for byte, the x scroll and the frame's sound commands ($803171 writes), and its own
picture (drawn with its partial updates) against MAME's snapshot.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "tools"), str(Path(__file__).resolve().parents[3] / "engine")]
from video import Video, H
from machine import Gauntlet
from mame_roms import rompath
import mame_cmp as C

DEFAULT = [2, 60, 300, 600, 900, 1200, 1500, 1800, 2100, 2400, 2700, 3000, 3001, 3002, 3600, 4200, 4800, 5400,
           6000, 6600, 7200, 7800, 8400, 9000, 9600, 10200, 10800, 11400, 12000, 12600, 13200, 13800, 14400, 15000,
           15600, 16200, 16800, 17400, 18000, 18600, 19200, 19800, 19801]
SECONDS = 400
TAPS = ["maincpu:0x930000:0x930001", "maincpu:0x905f6e:0x905f6f", "maincpu:0x803170:0x803171"]
DUMPS = ["maincpu:0x900000:0x905fff", "maincpu:0x910000:0x9107ff", "maincpu:0x800000:0x801fff", "audiocpu:0x0000:0x0fff"]


def run_mame(frames, keep):
    """mame_cmp.run_mame with a longer -seconds_to_run."""
    exe = os.environ.get("MAME") or shutil.which("mame")
    out = Path(keep) if keep else Path(tempfile.mkdtemp(prefix="mame_gauntlet_"))
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, OUT=str(out), FRAMES=" ".join(map(str, frames)),
               DUMPS=" ".join(DUMPS), TAPS=" ".join(TAPS), SNAPS="",
               PENS_EVERY="1")
    with (out / "mame.log").open("w") as log:
        r = subprocess.run([exe, "gauntlet", "-rompath", str(rompath()), "-window", "-sound", "none", "-nothrottle",
                            "-frameskip", "0", "-seconds_to_run", str(SECONDS), "-skip_gameinfo", "-autoboot_script",
                            str(C.LUA), "-snapshot_directory", str(out)], cwd=out, env=env, stdout=log, stderr=log,
                           timeout=1800)
    if not (out / ("f%d.png" % max(frames))).exists():
        raise RuntimeError("MAME capture failed (exit %d); see %s" % (r.returncode, out / "mame.log"))
    return out


def main():
    reuse = None
    if "--reuse" in sys.argv:                         # compare an earlier --keep run again, without MAME
        i = sys.argv.index("--reuse")
        reuse = sys.argv[i + 1]
        del sys.argv[i:i + 2]
    render_only = "--render-only" in sys.argv
    if render_only:
        sys.argv.remove("--render-only")
    frames, keep = C.parse_args(DEFAULT)
    d = Path(reuse) if reuse else run_mame(frames, keep)
    v = Video()
    worst = 0
    times = []
    m = None if render_only else Gauntlet()
    first_bad = None
    for f in frames:
        vram = C.load_dump(d, f, "maincpu", 0x900000)[0x900000:0x906000]
        pal = C.load_dump(d, f, "maincpu", 0x910000)[0x910000:0x910800]
        segs, mid = segments(d, f)
        ys_ram = (vram[0x5F6E] << 8) | vram[0x5F6F]
        tapped = segs[-1][2]
        segs[-1] = segs[-1][:2] + (ys_ram,)          # (the RAM word at the frame's end is what MAME drew with last)
        pens = C.load_pens(d, f)
        pd = int(np.any(v.pens(pal) != pens, axis=1).sum())
        shot = C.load_shot(d, f)
        t = time.perf_counter()
        rgb = v.render_rgb(vram, pal, segs[-1][1], segs[-1][2], segments=segs if len(segs) > 1 else None)
        times.append(time.perf_counter() - t)
        n = C.diff_pixels(rgb, shot)
        worst = max(worst, n, pd)
        C.save_compare(d / ("cmp%d.png" % f), rgb, shot)
        note = ""
        if mid:
            note = " | mid-frame: " + ", ".join("%s=%04X at line %.2f" % (r, x, l) for l, r, x in mid)
        if ys_ram != tapped:
            note += " | $905F6E %04X, tapped %04X" % (ys_ram, tapped)
        print("frame %5d: %5d px differ, %d pens (x %04X, y %04X, %d objects)%s" % (
            f, n, pd, segs[-1][1], segs[-1][2], objects(vram), note))
        if m is not None:
            ok, text = logic(m, d, f, vram, pal, segs[-1][1], shot)
            print("            logic: " + text)
            if not ok and first_bad is None:
                first_bad = f
    print("snapshot %dx%d; %.1f ms a picture (mean of %d, numpy)" % (
        shot.shape[1], shot.shape[0], 1000 * sum(times) / len(times), len(times)))
    print("compare pictures (reference | MAME | differences) in", d)
    if first_bad is not None:
        print("logic: first differing frame checked", first_bad)
    return int(worst != 0 or first_bad is not None)


def logic(m, d, f, vram, pal, xs, shot):
    """the board run to frame f against MAME's dumps: (all equal, the report)"""
    while m.frame < f:
        m.run_frame()
    ram = C.load_dump(d, f, "maincpu", 0x800000)[0x800000:0x802000]
    snd = C.load_dump(d, f, "audiocpu", 0x0000)[0:0x1000]
    parts = []
    ok = True
    for name, mine, theirs in (("RAM", m.ram(), ram), ("VRAM", m.vram(), vram), ("palette", m.palette(), pal),
                               ("sound RAM", bytes(m.snd_devices.ram), snd)):
        diff = [i for i in range(len(theirs)) if mine[i] != theirs[i]]
        if diff:
            ok = False
            parts.append("%s %d differ (first %04X: %02X vs %02X)" % (name, len(diff), diff[0], mine[diff[0]],
                                                                         theirs[diff[0]]))
        else:
            parts.append("%s ok" % name)
    sound = [x for tag, line, o, x in C.load_taps(d, f) if o == 0x803171]
    mine = [x for fr, x in m.sound_log if fr == f - 1]
    if mine != sound:
        ok = False
        parts.append("sound %s vs %s" % (mine, sound))
    if m.xscroll != xs:
        ok = False
        parts.append("x scroll %04X vs %04X" % (m.xscroll, xs))
    parts.append("own picture %d px" % C.diff_pixels(m.render_rgb(), shot))
    return ok, ", ".join(parts)


def segments(d, f):
    """[(first line, xscroll, yscroll)] of the frame's picture (the first at line 0) and the visible-line changes
    [(line, register, value)].  The tap log runs from the previous frame's end (line 240, in the vertical blank) to
    this frame's: writes before the beam wraps to line 0 hold for the whole picture; a change on visible line v
    holds from line v + 1 (MAME's update_partial(vpos) first draws lines <= v with the old value)."""
    st = {o: x for (tag, o), x in C.load_tap_state(d, f).items()}

    def reg():
        return ((st.get(0x930000, 0) << 8) | st.get(0x930001, 0), (st.get(0x905F6E, 0) << 8) | st.get(0x905F6F, 0))
    segs = None
    mid = []
    prev = None
    wrapped = False
    for tag, line, o, x in C.load_taps(d, f):
        if prev is not None and line < prev:
            wrapped = True
        if not wrapped and line < H:                  # (the log started inside the picture: no vertical blank part)
            wrapped = True
        prev = line
        if wrapped and segs is None:
            segs = [(0,) + reg()]
        old = reg()
        st[o] = x
        if segs is not None and reg() != old:
            v = int(line)
            change = (line, "%06X" % (o & ~1), reg()[0] if o >= 0x930000 else reg()[1])
            if mid and mid[-1][:2] == change[:2]:
                mid[-1] = change                      # (one word write, logged byte by byte)
            else:
                mid.append(change)
            if v < H - 1:
                if segs[-1][0] == v + 1:
                    segs[-1] = (v + 1,) + reg()
                else:
                    segs.append((v + 1,) + reg())
    if segs is None:
        segs = [(0,) + reg()]
    return segs, [m for m in mid if int(m[0]) < H - 1]


def objects(vram):
    """The motion objects reachable from the SLIP table (a measure of the scene)."""
    w = np.frombuffer(bytes(vram[0x2000:0x4000]), ">u2").reshape(4, 1024)
    slip = np.frombuffer(bytes(vram[0x5F80:0x6000]), ">u2")
    seen = set()
    for s in slip:
        link = int(s) & 0x3FF
        while link not in seen:
            seen.add(link)
            link = int(w[3, link]) & 0x3FF
    return len(seen)


if __name__ == "__main__":
    sys.exit(main())
