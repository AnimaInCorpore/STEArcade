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

The program needs about 2.3 MB of RAM (sprite data 0.9 MB, the dispatch table 256 KB).

Tests: `tools/fullrun.py 3000` (whole program, lock-step against the Z80 reference, the
NMI injected at the idle loop head), `tools/nmitrace.py N` (the NMIs from frame N on,
instruction by instruction, names the first diverging instruction).  `tools/bench.py`
stops with `KeyError: 'pe'` on a conditional RET/CALL on the parity flag (not translated).

The game itself is not deterministic across builds: its idle loop counts its spins
(`inc ($6019)`), so the attract sequence and the demo play depend on how much CPU time a
frame leaves.  Frame counts of two builds therefore show different game phases; what
compares exactly is a frozen frame of one build against the reference renderer.

## Translator (`tools/z80x.py`)

Static translation, one 68000 snippet per Z80 instruction, labelled `Z<pc>`.  Registers:
d0 = A, d1 = BC, d2 = DE, d3 = HL, d4 = IX, d6 = flags image, a5 = Z80 SP (a pointer),
a6 = the 32 KB Z80 block, a4 = the dispatch table; d5/d7 scratch.  The things that made
the game logic cheap (it was 19% of a frame, 12% now):

* The Z80 stack is always word aligned (the program sets SP to $6C00 and pushes words),
  so `call`/`ret`/`push`/`pop` are word moves.  A word read from the stack is the byte
  swapped pc, and the dispatch table (`z80_dispatch_sw`, 65536 longs, built at start by
  `z80_init_dispatch` from the compact table) is in that order: `ret` is
  `move.w (a5)+,d7; lsl.l #2,d7; move.l (a4,d7.l),a3; jmp (a3)`, 50 cycles instead of 139
  (a3 is free because the program never uses `ex af,af'`).  The one place where the
  stack is odd in between, `inc sp; inc sp`, is one `addq.l #2` (the NMI pushes a word
  and crashed on the odd pointer).
* BC is kept byte swapped (B in the low byte): B is the register the game works with
  (`djnz` is `subq.b #1,d1; bne`, 14 cycles instead of 44; `ld b,(hl)` one move), the pair
  is rare, and the swapped order is the order of the bytes on the stack and in memory.
* Flags in the condition codes: a flag producing instruction leaves S Z C in the CCR, and a
  conditional jump that directly follows it branches on that instead of `move d6,ccr`
  (12 cycles).  `Emitter.analyze` is a forward must-analysis over the code (nothing known
  at the entries, the return points and the targets of computed jumps); the jumps that
  can read the CCR are no longer uses of d6, so a producer whose flags are only read
  that way stores nothing.  Note that a 68000 `move` or `tst` clears C: only address
  register operations, the bit instructions and branches keep the flags.  620 loads
  became 192, 669 stores 481.

## Sprites (`rt/sprites.s`)

Blitter, like the bob routines of `stefastbobs2/main.s`: one blit per sprite line writes the
four planes of the line (Y count 4, source = destination), and the endmasks are the mask:
END1/END3 hold the outline of the line (holes included) shifted to the two screen words, so
the opaque pixels replace what is below and the rest stays.  No clearing pass, no colour
mixing: the screen equals the reference renderer pixel for pixel (frozen at frames 650, 800,
1000 and 1200: 0 of 57344 pixels differ).  The masks of every (shape, flip y, skew) are
a table (`dk_spr_masks`, 256 KB), the line words come from colour data baked per colour quad
(`dk_spr_data`, 608 KB: 19 distinct mappings of the pen values to the planes) that the
Blitter's source address walks through, `NFSR` lets the second destination word reuse the
one source word of a plane (a sprite of skew 0 is one word wide), flip x draws the lines
upwards.  The blitter registers of the line loop are written through preloaded pointers
(END1, END3, control, Y count, and the low word of the destination address, advanced with
`add d4,(a3)` as in the demo; sprites whose lines cross a 64 KB boundary of the screen use
full address writes).  The empty lines at both ends of a shape are left out
(`dk_spr_span`: a sprite of n lines enters the unrolled sequence 16 - n lines in); the
shapes have no empty lines inside, so that is all the reordering of the demo buys here.
39% of the drawn lines would fit one screen word at their skew (X count 1, a third less
Blitter time), but the order of the lines would then depend on the skew, and the colour
data is shared by all 16 skews.  END2 is unused.  Not implemented: the 16-sprites-per-
scanline limit and the wrap-around of the arcade hardware; sprites are not clipped at the
left/right edge of the game area.

Most of the 128 list entries are empty, and visiting them all twice a frame cost 24K
cycles: a frame first lists the entries that are not empty (`tst.l` over the list), and
each draw screen keeps the list it was last drawn with.  Each draw screen remembers per
slot what it got there (list entry, colour bank, rectangle, cells).  A frame restores the
background under the sprites of the screen's old list that changed or are gone, then
draws the active list: a sprite that is unchanged is drawn only if its rectangle touches
an 8x8 cell that was redrawn (tile), restored or drawn (a sprite earlier in the list) in
this frame.  The cells are a bitmap (`tile_marks`, 8 bytes per display row, cleared each
frame); a sprite's cells are a window of four bits in up to three rows, kept in its slot
record, so a test is three `and.l` and a mark three `or.l`.

`z80_dma` (tools/rtlib.s) is the 8257 sprite DMA, hooked on the `ld ($7D85),a` stores.

## Tiles (`rt/render.s`)

The 1 KB tile map is compared with a shadow every frame (the 224 visible longs, eight
per turn); changed tiles go into the background screen at once and into a queue for each
draw screen.  A palette bank change redraws everything (three times 1024 tiles, about ten
frames); the arcade does that at level starts and in the title screen's colour wipe, where
the game shows a still picture anyway.

## Border removal

Timer A must arrive in the *middle* of scanline 31 (`TA_DATA`), its handler then waits for
the next scanline start.  The VBL handler arms both timers first thing, and the rest of
the frame runs below the VBL level, so a frame that overruns the next VBL is interrupted
by it (`vbl_skip`) and the borders keep being removed.  Blits do not start while Timer A
is pending or Timer B is within 5 lines (`wait_borders`).  A measurement for all of this:
the top row of the game area in a Hatari AVI of 1800 VBLs is 0 for 1788 frames, 58 (border
not removed) for none.

## Measuring (`tools/build.py` options, `tools/frametimes.py`)

* `--debug`: frame, Timer A, Timer B, VBL and skipped-VBL counters as bits in the top-left
  corner (plane 0, lines 0-4; read them back from a Hatari AVI).  An AVI starts at power
  on; the program starts about 300 VBLs later.
* `--dumpat N`: at frame N write Z80 memory `$6000-$7FFF` to `DUMP.BIN` and freeze the game;
  the screen can then be compared with `dkong.py render_raw()` of the same memory.
* `-D TIMES=1 --debug --frames N`: MFP Timer D (81 us ticks) is started at every VBL and
  its count recorded when the NMI and when the drawing end, with the skipped-VBL count
  and the palette bank; `TIMES.BIN` is written when the program quits after N frames
  (`python tools/frametimes.py TIMES.BIN` prints the histogram).  Run with
  `--run-vbls` of about N*5/4+600.
* `--nosprites`: no sprite drawing (frame-rate comparison).  `-D NAME=VALUE`: any define.
* Profile: in the Hatari debugger `profile on` at one VBL breakpoint and `profile save` at
  a later one; Hatari 2.6 prints the per-address lines to its stdout.

Measured on 2026-10-07 (2400 frames of attract mode and demo play, 50 Hz frame =
160256 cycles): the average frame takes 44% of a frame (Z80 NMI 14%, drawing 30%),
play frames 50-80%, the busiest play frames 96-119% (6 of 2400), 0.5% of the frames run
into the next VBL; before this round the average was 75% and 9% of the VBLs were skipped.
Level starts and the title wipe redraw every tile and take about ten frames each.
