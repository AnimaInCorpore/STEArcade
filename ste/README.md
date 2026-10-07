# Donkey Kong, Atari STE

The arcade Z80 program is translated to 68000 (`tools/gen.py`, `z80x.py`); `rt/` is the
machine around it (video with the top and bottom border removed, tile and sprite
renderer, IKBD input).  See the commit messages for the translator conventions.

## Build and run (macOS)

    python3 -m venv venv && venv/bin/pip install numpy pillow machine68k
    # coverage the translator seeds its code discovery from (gitignored, ~15 min on 8 cores):
    for s in 11 12 13 14; do venv/bin/python ref/cover1.py $s 60000 & done
    for s in 21 22 23 24; do venv/bin/python ref/cover2.py $s 40000 & done; wait
    for s in 31 32 33; do venv/bin/python ref/colors3.py $s 30000 & done; wait   # palette
    venv/bin/python tools/build.py        # -> run/DKONG.PRG (+ the four CPU ROM files)

Run these from `ste/` (the pickles are written to the current folder).  The coverage and
pens runs reproduce the committed logs exactly (3766/4949 PCs, 155/115/154 pens).
`VASM`/`VLINK` select the toolchain; the default on macOS is `~/Work/f030dsp3d/tools`.

    hatari --machine ste --memsize 4 --tos tos206de.img --fast-boot true --cpu-exact true \
        --compatible true run/DKONG.PRG        # run from the folder holding the ROM files

Tests: `tools/fullrun.py 3000` (whole program, lock-step against the Z80 reference).
`tools/bench.py` stops with `KeyError: 'pe'` on a conditional RET/CALL on the parity flag
(not translated, unrelated to the sprite work).

## Sprites (`rt/sprites.s`)

Blitter, one OR pass per screen plane that has bits set, 16 skew routines with both
endmasks, the skew and the word count as constants (like `stefastbobs2/main.s`).  Every
sprite line is 16 pixels wide, i.e. the first width class of that demo's reordered ball:
one source word per line and plane, no pad; for skew 1-15 the Blitter's NFSR lets the
second destination word reuse it (both endmasks keep what gets shifted in out), skew 0 is a
one word wide blit.  Source streams are 7 pen-value masks per (code, flip y) of 16 words
(`tools/assets.py build_sprites`), flip x is a negative source Y increment.  No pass clears
the sprite's pixels first, so an opaque pixel is ORed into what is below it: where a sprite
overlaps another sprite or a girder the colour index is the OR of both (and black pixels
of a sprite do not hide anything).  In the exact-state comparison that is 120-330
of 57344 pixels (0.2-0.6 %), all at sprite/sprite overlaps.  Not implemented: the
16-sprites-per-scanline limit and the wrap-around of the arcade hardware.  Sprites are
not clipped at the left/right edge of the game area (they spill into the black margin).
Each draw screen remembers per sprite slot what it got there (list entry, colour bank,
rectangle).  A frame restores the background only under sprites that changed or are gone,
and draws a sprite that is unchanged only if its rectangle touches an 8x8 cell that was
redrawn (tile) or restored (the old rectangle of another sprite) in this frame; the cells
carry the frame number in `tile_marks`, so nothing has to be cleared.  Redrawing an
unchanged sprite over its own pixels is harmless because the passes OR.  Checked against the
reference renderer by freezing the game at frames 650 / 800 / 1000 / 1200 / 1380: the
screen the incremental drawing leaves is the one a full redraw gave (110-210 pixels off, the
OR overlaps above).
Measured (debug counters, 1800 VBLs): 1465 full frames without sprite drawing, 1323 with
every sprite restored and drawn every frame, 1448 with unchanged sprites skipped.

`z80_dma` (tools/rtlib.s) is the 8257 sprite DMA, hooked on the `ld ($7D85),a` stores.

## Border removal

Timer A must arrive in the *middle* of scanline 31 (`TA_DATA`), its handler then waits for
the next scanline start.  The VBL handler arms both timers first thing, and the rest of
the frame runs below the VBL level, so a frame that overruns the next VBL is interrupted
by it (`vbl_skip`) and the borders keep being removed.  Blits do not start while Timer A
is pending or Timer B is within 5 lines (`wait_borders`).  A measurement for all of this:
the top row of the game area in a Hatari AVI of 1800 VBLs is 0 for 1788 frames, 58 (border
not removed) for none.

## Debug builds (`tools/build.py`)

* `--debug`: frame, Timer A, Timer B, VBL and skipped-VBL counters as bits in the top-left
  corner (plane 0, lines 0-4; read them back from a Hatari AVI).
* `--dumpat N`: at frame N write Z80 memory `$6000-$7FFF` to `DUMP.BIN` and freeze the game;
  the screen can then be compared with `dkong.py render_raw()` of the same memory.
* `--nosprites`: no sprite drawing (frame-rate comparison).
