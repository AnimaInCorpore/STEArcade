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

Blitter, like the bob routines of `stefastbobs2/main.s`: one blit per sprite line writes the
four planes of the line (Y count 4, source = destination), and the endmasks are the mask:
END1/END3 hold the outline of the line (holes included) shifted to the two screen words, so
the opaque pixels replace what is below and the rest stays.  No clearing pass, no colour
mixing: the screen equals the reference renderer pixel for pixel (frozen at frames 650, 800,
1000, 1200 and 1380: 0 of 57344 pixels differ).  The masks of every (shape, flip y, skew) are
a table (`dk_spr_masks`, 256 KB), the line words come from colour data baked per colour quad
(`dk_spr_data`, 608 KB: 19 distinct mappings of the pen values to the planes) that the
Blitter's source address walks through, `NFSR` lets the second destination word reuse the
one source word of a plane (a sprite of skew 0 is one word wide), flip x draws the lines
upwards.  A mask table entry costs the same to write as an immediate in an unrolled routine
would; unrolled code per (shape, flips, skew) would be megabytes.  END2 is unused: lines of up to
32 pixels (three words, 48 mask bits, skew up to 15) would use it.  The program needs about
2 MB of RAM now (the data is 0.9 MB).  Not implemented: the 16-sprites-per-scanline limit and
the wrap-around of the arcade hardware.  Sprites are not clipped at the left/right edge of the
game area (they spill into the black margin).

Each draw screen remembers per sprite slot what it got there (list entry, colour bank,
rectangle).  A frame restores the background only under sprites that changed or are gone,
and draws a sprite that is unchanged only if its rectangle touches an 8x8 cell that was
redrawn (tile), restored (the old rectangle of another sprite) or drawn (a sprite earlier in
the list, since later ones go on top) in this frame; the cells carry the frame number in
`tile_marks`, so nothing has to be cleared.
Measured (debug counters, 1800 VBLs): 1465 full frames without sprite drawing, 1409 with
this renderer (1448 with the earlier OR passes, which were not exact).

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
