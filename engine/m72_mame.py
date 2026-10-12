"""The M72 reference renderer (engine/m72.py) against MAME 0.289: ref/mame_cmp_<game>.py of the M72 games.

One MAME run (engine/mame_frames.lua) dumps the video RAMs at each frame and the one before it, the palettes and
MAME's pens at the frame, logs the writes to the video RAMs and to the video ports ($02-$07, $80-$87, the V30's I/O
space) with their beam lines, and copies the sprite RAM at each sprite DMA (port $04: MAME's buffered sprite RAM is
not in an address space).  The renderer draws each frame per band of MAME's partial updates (m72.bands: the previous
frame's state plus the logged writes, cut at the raster interrupt's line); the goal is 0 differing pixels and pens.
"""
import numpy as np

import mame_cmp as C
import m72

DUMPS = ["maincpu:0xc8000:0xc8bff", "maincpu:0xcc000:0xccbff", "maincpu:0xd0000:0xd3fff", "maincpu:0xd8000:0xdbfff"]
TAPS = ["maincpu:io:0x02:0x07", "maincpu:io:0x80:0x87", "maincpu:0xd0000:0xd3fff", "maincpu:0xd8000:0xdbfff"]
SNAPS = ["maincpu:io:0x04=maincpu:0xc0000:0xc03ff"]


def frame_bands(d, f):
    """(bands, palette pens, consistency) of frame f from a capture: consistency = the video RAM bytes in which the
    previous frame's dump plus the logged writes differ from this frame's dump (0 when nothing was missed)."""
    vram = lambda fr: (bytes(C.load_dump(d, fr, "maincpu", m72.FG_RAM)[m72.FG_RAM:m72.FG_RAM + 0x4000]),
                       bytes(C.load_dump(d, fr, "maincpu", m72.BG_RAM)[m72.BG_RAM:m72.BG_RAM + 0x4000]))
    fg0, bg0 = vram(f - 1)
    fg1, bg1 = vram(f)
    start = dict(fg=fg0, bg=bg0, sprites=C.load_snap(d, f, prev=True))
    end = dict(fg=fg1, bg=bg1, sprites=C.load_snap(d, f))
    writes = []
    for tag, line, off, x in C.load_taps(d, f):
        writes.append((line, "io" if tag.endswith(":io") else "program", off, x))
    ports0 = {o: v for (t, o), v in C.load_tap_state(d, f).items() if t.endswith(":io")}
    bands, (fg, bg) = m72.bands(start, end, writes, ports0)
    miss = sum(a != b for a, b in zip(fg, fg1)) + sum(a != b for a, b in zip(bg, bg1))
    pal = [C.load_dump(d, f, "maincpu", a)[a:a + 0xC00] for a in (m72.PAL0, m72.PAL1)]
    pens = m72.pens(*pal)
    return bands, pens, miss


def compare(game, video, frames, rompath, keep=None):
    allf = sorted(set(frames) | {f - 1 for f in frames})
    d = C.run_mame(game, allf, DUMPS, TAPS, keep=keep, rompath=rompath, snaps=SNAPS, pens_every=True)
    worst = 0
    for f in frames:
        bands, pens, miss = frame_bands(d, f)
        mame_pens = C.load_pens(d, f)
        pen_diff = int(np.any(pens[:len(mame_pens)] != mame_pens, axis=1).sum())
        rgb = video.render_rgb(bands, pens)
        shot = C.load_shot(d, f)
        n = C.diff_pixels(rgb, shot)
        worst = max(worst, n, pen_diff, miss)
        C.save_compare(d / ("cmp%d.png" % f), rgb, shot)
        cuts = " ".join("%d-%d" % (b[0], b[1]) for b in bands)
        print("frame %5d: %5d pixels differ, %3d of %d pens; bands %s; scroll FG %s BG %s%s" % (
            f, n, pen_diff, len(mame_pens), cuts, "/".join("%d,%d" % (b[2].scrollx[0], b[2].scrolly[0]) for b in bands),
            "/".join("%d,%d" % (b[2].scrollx[1], b[2].scrolly[1]) for b in bands),
            "; %d video RAM bytes not explained by the log" % miss if miss else ""))
    print("compare pictures (reference | MAME | differences) in", d)
    return int(worst != 0)
