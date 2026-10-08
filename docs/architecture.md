# Architecture

The project ports Z80 arcade games to the Atari STE (8 MHz 68000, 4 MB, 16 colours, Blitter).  Every port has three
parts, and the first two are checked against each other with a lock-step test:

1. **A reference machine** (`games/<game>/tools/machine.py`, on `engine/z80.py` and, for Bubble Bobble's protection MCU,
   `engine/m6801.py`): a Python model of the arcade board from the MAME driver.  It is the ground truth for the logic
   (RAM compared every frame) and for the picture (`render_raw`, itself compared with MAME's own screenshot, see
   `docs/porting-guide.md`).
2. **A static translation** of the Z80 (and 6801) programs to 68000 code (`engine/z80x.py`, `engine/translate.py`,
   `engine/m6801x.py`; the game specific part in `games/<game>/tools/gen.py`).  No interpreter runs: the arcade program
   is 68000 code, with the hardware accesses calling runtime routines.
3. **The STE runtime and renderer** (`games/<game>/src/*.s`, shared `engine/rt/rtlib.s`): video with the borders removed,
   the arcade's interrupts at the vertical blank, input, and a renderer that draws the arcade's tile map and sprite
   list.  Sprites are drawn with the **Blitter** (one blit per sprite line, masks as end masks, no clearing pass);
   tiles with the CPU.

Layout: `engine/` (shared), `games/<game>/{src,tools,ref}` (plus `docs/` where a game keeps notes and reference captures),
`build/<game>/` and `run/<game>/` (generated, not in git), `assets/roms/` (archives; `extracted/<game>/` the unpacked files),
`tools/hatari.sh` (Hatari driver) and `tools/windows/`, `port.py` (build/test/run front end), `legacy/` (superseded, not
built).  `engine/paths.py` knows where things are; `engine/toolchain.py` assembles and links (VASM/VLINK environment
variables select the tools).

## Renderers of the ports

| game | tiles | sprites | what is exact |
|---|---|---|---|
| Donkey Kong | CPU, shadow diff of the tile map, dirty queue per draw screen | Blitter, generated per shape/skew code | pixel for pixel against the reference and MAME |
| Galaga | CPU, 8 x 8 cells per colour quad, `chars_over` on top of sprites | Blitter, double sizes split into 16 x 16 parts, stars plotted after | renderer against MAME (RAM injected), reference identical |
| Bubble Bobble | CPU, `movep.l` per planar row, tile bake cache, dirty 8 x 8 cells | none: objects are strips of 8 x 8 tiles, shifted tiles merged into two cells by the CPU | pixel for pixel against the reference |
| 1942 | hardware scroll of a 768 line ring (two draw rings + clean), tiles baked per palette bank, characters redrawn when the window moves | Blitter, one blit per line, masks as end masks, rectangles put back from the clean ring | pixel for pixel against the reference (which equals MAME) |

Bubble Bobble's cost is in the shifted tiles (about 2.7k cycles each) and the per-frame video RAM diff (83k cycles);
the Blitter (halftone/endmask merge of a baked tile into the screen) is the next step for it, as in the other two ports.

## Translator (`engine/z80x.py`)

Static translation, one 68000 snippet per Z80 instruction, labelled `Z<pc>`.  A
`z80x.Config` describes the program (several per machine: Galaga has two): label prefix,
dispatch table and token symbols, the memory model (see below), the two RAM words for IY
and F', write hooks (`ld (nn),a` to an I/O address calls a runtime routine), whether
`rst $28` is followed by a jump table.  `translate.generate_program()` (`engine/translate.py`) does one program:
discovery seeded by the coverage pickles, flag liveness, the CCR analysis, emission,
dispatch table.  Memory models: "signed" (a6 = Z80 address 0, signed word index, a 64 KB
block puts $8000-$FFFF below a6) and "long" (long index with the upper words of the
registers kept 0, static accesses to $8000 and up through an absolute symbol).
Instructions added for Galaga: `ldi`/`ldd`/`lddr`/`cpi`, `jp pe/po` right after them
(P/V = BC != 0, the only parity use), `rld`, `ex (sp),hl`, `halt` (runtime `z80_halt`:
wait for the next interrupt), `ld a,r` (runtime `z80_rnd`, a shift register the reference
reproduces), the IX/IY halves.  Registers:
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

## Runtime schedule (all ports)

The arcade's CPUs are not run as threads.  At every vertical blank the runtime delivers the arcade's interrupts in a
fixed order and runs each handler to completion (Galaga: main CPU IRQ, sub CPU IRQ; Bubble Bobble: MCU IRQ1, main
CPU IM 2 interrupt, sub CPU IRQ).  What the arcade's main loop does between interrupts is only the boot and
idle loops, so the foreground "thread" is the boot until the idle loop and the renderer afterwards.  The handler's
return address is a token pc (the dispatch table maps it to the runtime's return label), which also lets code that
inspects the interrupted pc run (Bubble Bobble requires its high byte < $C0).  `run_frame_port` in each machine.py is
the same schedule in Python: the lock-step tests compare against it, not against the interleaved reference.

Rules learned the hard way (details in `docs/porting-guide.md`):

* The VBL handler arms the border timers first, then runs the game's interrupts at IPL 3 (`move #$2300,sr`), then draws.
  A VBL arriving during the drawing runs the handlers again and skips the drawing: the game keeps its pace and the
  display drops frames.
* Timer A lowering the IPL can let a pending VBL nest 28 deep: guard with an `in_logic` flag.
* When the game logic alone takes longer than a frame the renderer starves: throttle (`render_age`, Galaga's star
  levels) - skip the logic every other VBL while drawing.
* Boot self-tests (RAM, ROM, checksums) are patched out in the reference and the translation; the code that
  checksums ROM while running is compensated by a dead byte.  Never use frames of a self-test as a performance
  reference: they fill video RAM and load the renderer unrealistically.

## Blitter sprite renderer (`games/dkong/src/sprites.s`, `engine/sprite_codegen.py`)

Blitter, like the bob routines of `stefastbobs2/main.s`: one blit per sprite line writes the
four planes of the line (Y count 4, source = destination), and the endmasks are the mask:
END1/END3 hold the outline of the line (holes included) shifted to the two screen words, so
the opaque pixels replace what is below and the rest stays.  No clearing pass, no colour
mixing: the screen equals the reference renderer pixel for pixel (frozen at frames 650, 800,
1000 and 1200: 0 of 57344 pixels differ; frame 800 re-checked after the MAME fixes below), and
the reference equals MAME's screenshot (see "Checking a reference against MAME").  A sprite's
left display column is u0 = y - 23 (it was y - 22 until 2026-10-08, see below).  The masks of every (shape, flip y, skew) are
a table (`dk_spr_masks`, 256 KB), the line words come from colour data baked per colour quad
(`dk_spr_data`, 608 KB: 19 distinct mappings of the pen values to the planes) that the
Blitter's source address walks through, `NFSR` lets the second destination word reuse the
one source word of a plane (a sprite of skew 0 is one word wide), flip x draws the lines
upwards.  The blitter registers of the line loop are written through preloaded pointers
(END1, END3, control, Y count, and the low word of the destination address, advanced with
`add d4,(a3)` as in the demo; sprites whose lines cross a 64 KB boundary of the screen use
full address writes).  The empty lines at both ends of a shape are left out (`dk_spr_span`). The fast
path now selects generated code for the shape/skew (`engine/sprite_codegen.py`): masks
that stay the same are not written again, empty interior lines are skipped, and a
line whose END3 is zero uses X count 1 even at a nonzero skew. Such a line clears
NFSR and sets destination Y increment to 2; a two-word line sets NFSR and Y increment
-6. Both finish eight bytes past their starting destination and consume eight source
bytes. Lines whose END1 alone is zero still use two words: their source would need a
different shift/pipeline arrangement. Colour data remains shared by every skew.
The generated instruction sequences and compressed mask streams are deduplicated
separately. Sprites near a 64 KB boundary retain the original unrolled full-address
path. `-D NOSPRITECODE=1` selects the generic renderer for comparison. END2 is unused.  Not implemented: the 16-sprites-per-
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

`z80_dma` (`engine/rt/rtlib.s`) is the 8257 sprite DMA, hooked on the `ld ($7D85),a` stores.

### Sprite blitter revision (2026-10-08)

`venv/bin/python engine/sprite_blit_test.py` builds both paths and executes the
assembled 68000 code on Musashi with a blitter model. For each port it verifies all
8192 shape/skew/line-direction combinations against independent masked pixels,
then compares 48 successive complete sprite renders against the generic path,
including overlap, background restoration, colour changes and 64 KB crossings.
The workload gives 3.2% less CPU plus blitter bus work for Donkey Kong and 4.3% for
Galaga; isolated line bodies save 9.0% and 9.9%. These are simulated cycle counts,
not Hatari frame-rate measurements. Executables grow by about 407 KB and 558 KB;
both ports still fit the configured 4 MB STE. Both rebuilt binaries also completed
5000 VBLs in the pinned Hatari with no crash file; screenshots confirmed the games
running (including Galaga's sprites).  Bubble Bobble's renderer (`games/bublbobl/src/bb_render.s`) is
a complete tile renderer but does not use the Blitter yet; it has no sprite blitter to optimize, it is
the candidate for one (see "Renderers of the ports" below).

The reference's arbitrary row reordering relies on matching reordered source data.
Copying that order directly into these ports would break their sequential source
walk. This revision retains the source layout and uses the reference's register
reuse and variable-width blits where they can be applied without new colour copies.

## Tiles (`games/dkong/src/render.s`)

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

## Measuring (`games/dkong/tools/build.py` options, `games/dkong/tools/frametimes.py`)

* `--debug`: frame, Timer A, Timer B, VBL and skipped-VBL counters as bits in the top-left
  corner (plane 0, lines 0-4; read them back from a Hatari AVI).  An AVI starts at power
  on; the program starts about 300 VBLs later.
* `--dumpat N`: at frame N write Z80 memory `$6000-$7FFF` to `DUMP.BIN` and freeze the game;
  the screen can then be compared with `games/dkong/tools/machine.py render_raw()` of the same memory.
* `-D TIMES=1 --debug --frames N`: MFP Timer D (81 us ticks) is started at every VBL and
  its count recorded when the NMI and when the drawing end, with the skipped-VBL count
  and the palette bank; `TIMES.BIN` is written when the program quits after N frames
  (`python games/dkong/tools/frametimes.py TIMES.BIN` prints the histogram).  Run with
  `--run-vbls` of about N*5/4+600.
* `--nosprites`: no sprite drawing (frame-rate comparison).  `-D NAME=VALUE`: any define.
* Profile: in the Hatari debugger `profile on` at one VBL breakpoint and `profile save` at
  a later one; Hatari 2.6 prints the per-address lines to its stdout.

Measured on 2026-10-07 (2400 frames of attract mode and demo play, 50 Hz frame =
160256 cycles): the average frame takes 44% of a frame (Z80 NMI 14%, drawing 30%),
play frames 50-80%, the busiest play frames 96-119% (6 of 2400), 0.5% of the frames run
into the next VBL; before this round the average was 75% and 9% of the VBLs were skipped.
Level starts and the title wipe redraw every tile and take about ten frames each.


## Whole-object drawing (all ports)

Use a wider virtual screen with enough hidden space on both sides for a whole
object, including the extra destination word of a shifted sprite. Objects crossing
an edge are drawn whole and disappear behind the visible display window. Do not
implement sprite clipping routines or calculate edge masks at runtime. Reserve
vertical guard rows too when whole objects can cross the top or bottom.

Sprite drawing follows `C:/Arbeit/stefastbobs2/main.s`: reorder source rows to group
equal opaque masks, bake the end masks for all 16 horizontal shifts, and reuse
Blitter state and its automatically advancing source address. Use short HOG blits
with the border timer guard. This is the required approach for every port; older
renderers must be migrated when their sprite drawing is changed.
