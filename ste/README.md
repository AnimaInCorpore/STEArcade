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

Static translation, one 68000 snippet per Z80 instruction, labelled `Z<pc>`.  A
`z80x.Config` describes the program (several per machine: Galaga has two): label prefix,
dispatch table and token symbols, the memory model (see below), the two RAM words for IY
and F', write hooks (`ld (nn),a` to an I/O address calls a runtime routine), whether
`rst $28` is followed by a jump table.  `gen.generate_program()` does one program:
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

## Sprites (`rt/sprites.s`)

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

## Checking a reference against MAME (applies to every port)

"The port equals the reference renderer" only means something if the reference equals the arcade.
Compare the reference with MAME's own screenshot, pixel by pixel, before trusting it.  Donkey Kong's
reference had two errors that this found on 2026-10-08, neither visible in a Hatari-vs-reference test:

* **Sprites were one raw row off**: `top = 246 - y`, MAME's `draw_sprites` gives `247 - y` (its
  line buffer fetches the sprite one scanline ahead, hence the `+ 1` in `y + add_y + 1 + scanline`).
  Fixed in `tools/dkong.py` and `rt/sprites.s` (`u0 = y - 23`).  Every sprite was one pixel shifted
  along the arcade's raw Y axis.  Positions derived from the MAME source need a snapshot to confirm
  them (here the derivation and the snapshot agree: 0 pixels differ with 247, about 900 with 246).
* **The palette was wrong** (up to 75 levels per channel, e.g. skin 255,184,85 vs 245,188,160, blue
  0,0,170 vs 4,2,220): the Galaxian style weights 0x21/0x47/0x97 and 0x55/0xAA are not what current
  MAME computes.  Its colours come from resistor network models (`compute_res_net`: darlington stages,
  tri-state black) and are not a per channel sum of weighted PROM bits, so take the numbers from MAME
  itself: `tools/dkong_pens.py` is a dump of `pen_color()` for the 256 pens.  Do the same for any
  game whose reference computes colours from PROM weights; Galaga and Bubble Bobble should be checked.

How (`ref/mame_dump.lua`, `ref/mame_cmp_dkong.py`; MAME is `/opt/homebrew/bin/mame`, 0.289, the ROM zips
are in `assets/roms`): start MAME with **`-window`** (with `-video none` there is no snapshot), run a Lua
script at frame N that writes the pens (`palette:pen_color(i)`), a memory range and `video:snapshot()`, render
the same memory with the reference and count differing pixels.  `venv/bin/python ref/mame_cmp_dkong.py 700 1500 2500 4000`
prints 0 differing pixels for all four frames now.  Notes:

* Take several frames: the memory is read after the frame was drawn, so a fast sprite can be one step ahead.
* Write taps on the I/O latches (`install_write_tap`) did not report the palette bank reliably (it read 0 where the
  screen was bank 2), so the compare tool tries all palette/sprite banks and reports the best.  A bank mismatch
  shows as whole tile colour sets wrong, a position mismatch as a one pixel outline around every sprite.
* Checked and fine for Donkey Kong: tile colour codes, video RAM layout, sprite x (`x + $F8`), flip x/y, the
  8257 sprite DMA (the game programs `$6900` -> `$7000`, `$180` bytes, exactly what `z80_dma` copies).
* **No key press**: MAME shows its startup screens (game info, "ROMs not correct" warning) and waits for a key
  unless `-seconds_to_run` is below 300 (`ui.cpp`: the startup screens are off for `-str` < 300).  The scripts use
  `-seconds_to_run 250` (about 15000 frames with `-nothrottle`, enough for every check here).  The warning itself
  stays in the log; Galaga's comes from the blank MCU ROMs below, Bubble Bobble's from the PAL dumps nobody has.
* **The MAME source in `F030Arcade/third_party/mame` is older than the binary** (Galaga's blue channel differs:
  the source says 0x47/0x97, MAME 0.289 produces 0x51/0xAE).  The installed `mame` is the truth.

Results, 2026-10-08 (all with 0 differing pixels now, `ref/mame_cmp_dkong.py`, `ref/mame_cmp_galaga.py`,
`ref/mame_cmp_bublbobl.py`):

* **Donkey Kong**: sprite position and palette, see above.
* **Galaga** (found by the check): (1) `decode_gfx` made the first plane the *least* significant bit, MAME the
  most significant one: pixel values 1 and 2 of every character and sprite were swapped (the enemies were orange
  instead of teal, the ship blue instead of red, the NAMCO logo white instead of red); text only looked right because
  most character colour tables are symmetric in pens 1 and 2.  (2) Blue was 0x47/0x97 (maximum 222), MAME 0x51/0xAE
  (maximum 255; the star palette's blue likewise 0, 0x51, 0xAE, 0xFF).  Both are in `tools/galaga.py`, so
  `galaga_assets.py` (the STE graphics and palette) picks them up on the next `tools/galaga_build.py`.  The
  starfield is not verified (MAME's starfield was off in the frozen frames).  MAME can not run Galaga from the ROM set:
  the Namco 51xx/54xx MCU ROMs are missing, a blank 1 KB stand-in (`namco51.zip`, `namco54.zip`, wrong checksum,
  MAME warns and runs) ends in the test screen, so `ref/mame_dump.lua` with `INJECT=` writes the reference's RAM
  image into MAME's RAM and freezes it with write taps (MAME's Lua has no CPU halt; `set_input_line` is not exposed),
  and MAME draws it: that tests the renderer, not the game.
* **Bubble Bobble**: nothing to fix.  Palette (RGBx444, `v * 17`), tile decode, object/column layout, flip and the
  background pen 255 match MAME at frames 700, 1500 and 2500 (about 77 objects each).  MAME runs the set itself.

Lesson for new ports: do this check *before* building the port's graphics, and re-check whenever the reference
renderer changes.  A plane order or a colour weight that is wrong in the reference is wrong in the port, and
"port equals reference" tests can not see it.

* Known MAME behaviours the port does not have: the 16 sprites per scanline limit (later sprites of a line vanish)
  and the wrap around of sprites at the arcade's 256 pixel edge (MAME draws them again at x - 256 / y - 256).  Neither
  is visible in normal play.

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

## Galaga (`galaga/`, `tools/galaga*.py`)

The second machine, started 2026-10-08.  State: the attract mode runs at the game's
full speed (frame counter = VBL counter, no skipped interrupts) with everything drawn
(tiles, the formation, explosions, the starfield, the high score table); the display
drops frames: 25-28 fps in the title phases, 8-15 fps with the full formation.  Build
`python tools/galaga_build.py [--debug] [--full-selftest]` -> `run/galaga/GALAGA.PRG` (needs the six ROM
files of the `galaga` set extracted to `assets/roms/extracted/galaga/`).  The main CPU's boot
RAM test (about 600 of the 850 frames to the attract mode) is patched out of the translation
(`galaga.skip_ram_test`, the bank checksum byte compensates; `--full-selftest` keeps it).
`tools/hrun.sh galaga|dkong [seconds...]` runs a port in the F030Arcade Hatari and grabs
screenshots at the given times (`/tmp/hrun`); the display starts at buffer line `CROP_TOP` = 24.

Reference: `tools/galaga.py` models the arcade from MAME's galaga.cpp: three Z80s at
3.072 MHz with the shared map (ROM per CPU at 0-3FFF, switches/latches/06XX at 6800-7100,
RAM 8000-9BFF with the sprite table at the end of each 1 KB, video latch A000), IRQ to
CPU1/CPU2 at the vertical blank when enabled, NMI to CPU3 at lines 64 and 192, the 06XX's
NMI clock to CPU1 during transfers, the 51XX simulated the way old MAME did (coins,
credits, start buttons, joysticks with the fire edge; the MCU ROM is not in the set), the
05XX starfield (LFSR period walked once per frame), the renderer (tiles 36x28 through
tilemap_scan, 64 sprites with the double sizes, stars under them, characters over them,
rotated 90).  It boots to the attract mode in 1500 frames at ~45 frames/s; coin, start and
play work (`ref/galaga1.py`).  Probes: `ref/galaga2.py` (the sound CPU can be stopped
after its boot: screens identical over 2400 frames; it only posts its test result $9101
and clears $9A00-$9AFF), `ref/galaga3.py` (sprites changed per frame mean 4.9, 90% 13,
tiles 1.5; every I/O access is a static address except the NMI handler's `ldi` through
hl' and the video latch through hl), `ref/galaga4.py` (13 colours plus black are drawn,
so the STE palette has two entries for the stars), `ref/galaga5.py` (the port's schedule,
below, against the interleaved reference: same game, stars one scroll step apart),
`ref/galaga_cover.py` (coverage pickles for the translation).

Schedule of the port (`run_frame_port` in galaga.py is the model): the main CPU's program
is the foreground thread (its main loop idles at $038D on a flag the IRQ sets); at each
VBL the main CPU's IRQ handler and then the sub CPU's run to completion (the sub CPU's
main loop only idles once booted, so it needs no thread); the 06XX NMIs run at the control
write as often as the program keeps the clock going (a read puts the chip's byte into
the $7000 cell before the handler's `ldi`, a write takes it out afterwards); the boot
handshake (CPU1 spins on the self-test results at $3589/$359C, CPU2 at $057F/$0596) runs
by yields at those spin loops (`z80_hook`), the sound CPU's part natively.

Memory: one block [sub ROM 32K | shared RAM 32K | main ROM 32K]: the main CPU's code
uses the signed model (a6 = its ROM, the RAM below), the sub CPU's the long model (a6 =
its ROM, the RAM above); the register cells $6800-$7FFF are per CPU.  The dispatch
tables are 2 x 256 KB.

Video: 224 x 288 rotated, the screen buffers hold 384 lines (DISP_TOP = 32 lines of slack
above, the STE shows 277 of the 288 from `CROP_TOP` on - which lines to lose is open).
Characters: 8 x 8 cells per colour quad (18 quads, 72 KB), pen 0 transparent and black
in the background; a cell a sprite was drawn in gets its character back masked
(chars_over).  Sprites: as Donkey Kong's renderer with the 64 entries gathered into 8
bytes and split into up to four 16 x 16 parts (double sizes), 16 colour quads (512 KB),
masks 256 KB.  Stars: single pixels in colours 14/15 plotted where the draw screen is
black after the sprites (nothing of the game is black), the previous frame's cleared
first.  Palette: black, 13 game colours, 2 greys.

Budget (reference statistics): both CPUs idle most of the time (about 2100 translated
instructions of work per frame), 5-13 sprites change per frame, 100 stars a frame.

### Findings (2026-10-08)

- The VBL runs the game's interrupts every frame and then draws with the VBL enabled
  (`vbl_render`, SR $2300): a VBL that interrupts the renderer runs the two IRQ handlers
  (the main CPU's with its registers saved in `main_ctx`) and skips the drawing, so the
  game keeps its pace and the display drops frames.  The first version drew inside the
  VBL with the VBL masked, which halved the game speed as soon as drawing took longer
  than a frame (the VBL counter ran twice as fast as the game's frame counter - the
  counters of the `--debug` build, top left, show it); rendering in the main CPU's idle
  loops instead (hooks at $038D/$0373) stalled, since the main loop does not pass those
  pcs in every phase.
- Translator: the IRQ handler's register state after its run is dropped (it restores
  the Z80 registers itself; an in-flight `ldir` keeps its counter in d5/d7, writing the
  registers back corrupted it).  Hooks push their resume label (`pea`) - vasm makes
  `jmp` pc-relative, so a fixed "+10" resume was wrong.  The 06XX data port is the whole
  $7000-$70FF (the NMI handler's `ldi` pointer walks through it).  `ei`/`di` keep
  `g1_iff`/`g2_iff`: an IRQ is only taken when the program enabled it (the NMI
  disables until its retn).  Discovery: Galaga's jump tables are
  `ld hl,T; rst $08 | $10 | add a,l; ld a|e,(hl); inc hl; ld h|d,(hl); .. jp (hl)` (or
  `call $003B`, a `jp (hl)` trampoline) - `Config(hl_tables=True)` finds them by walking
  back from every `jp (hl)` (`discover.hl_jump_tables`); coverage alone missed $179C and
  the task table at $0096 (both crashed with `z80_badpc`).
- Renderer: the sprite records keep the entry's flags at `S_FLAGS` (reading them from
  offset 4 took `S_RECT`'s $FF bytes: every part looked flipped, double and parked at
  x-high 3 - no sprite ever drew).  The video latch cells hold the byte the program
  wrote, the latch is its bit 0.  Stars are plotted in their own colour (list entries
  offset, bit, colour; the erase compares the pixel's colour), 15 colours.  Per
  mark bit `ga_mark_cell` gives the display cell (chars_over walks set bits only); the
  stars' positions are kept per set, sorted, with the STE colour, so a frame scans the
  two sets that are on (`star_frame`).  Per entry and screen `slot_any` says whether a
  part is on the screen (the part loops are skipped otherwise).
- Profile (`--debug`, VBL 8000-8300, full formation, 160256 cycles per VBL): main CPU
  code 55k cycles per VBL, sub CPU code 45k (its IRQ computes the enemy paths), I/O
  chips 4k, so the renderer gets a third of the CPU; a render of that phase costs about
  200k cycles (draw_part 63k for ~30 sprites, draw_stars + erase_stars 54k for ~113
  stars, draw_sprites 32k, entry_loop 17k, scan_cells 13k, chars_over 11k, star_frame
  11k) - 1 render per 4 VBLs.  The translated code runs at ~9 cycles per 68000
  instruction: the costly idioms are the 8-bit halves of the pointer pairs (`ld d,(hl)`
  = move + lsl.w #8 + andi + or = 48 cycles) and `ld h,n` (andi + ori).  50 fps in the
  heavy phases needs both a cheaper renderer and faster translated code.
- Hatari recipes: the dump addresses are map address + text base ($188e4) - and they
  move with every build; `b ($addr).l ! ($addr).l` watchpoints are slow (minutes);
  Hatari's `profile save` writes the per-address lines to stdout and only the header to
  the file (`profagg.py` wants the stdout copy as `<dir>/hatari.out` and the header as
  `<dir>.prof`); an AVI of a 9000 VBL run takes 5 minutes (PNG), the same run without
  one 70 s.

### Findings (2026-10-08, later)

- Sources: MAME's Galaga video code is in the F030Arcade checkout,
  `F030Arcade/third_party/jsm68kdisassembler/third_party/mame/src/mame/namco/galaga_v.cpp`
  (also `galaga.cpp`, `namco/galaga_a.cpp`; commit 5913928b159).  Sprite flags there: bit 0
  flip x, bit 1 flip y, bit 2 double width, bit 3 double height; x = spriteram_2[offs+1] - 40
  + 0x100 * (spriteram_3[offs+1] & 3), y = 256 - spriteram_2[offs] + 1.  Check against it
  before trusting `tools/galaga.py` or the renderer.
- Hatari: use the F030Arcade build (`tools/hrun.sh galaga|dkong [seconds...]`: runs the port,
  screenshots through `--cmd-fifo` + `hatari-debug screenshot` into `/tmp/hrun`; `PRG=` picks
  another program).  Debugger commands go through the same FIFO (`hatari-debug m $addr 8`
  prints memory to Hatari's stdout) - that is how the `--debug` counters are read:
  `cnt_vbl`, `cnt_skip`, `cnt_render` (words, map address + $188e4).
- Bugs found by looking at the screen: (1) the sprite rectangle's line offset was a word
  shift, lines from 256 on (the ship at the bottom) wrapped to the top; (2) flip x was
  tested as bit 7 of the flags (Donkey Kong's attribute), Galaga's is bit 0: enemies on a
  curve were never mirrored along the screen's vertical axis (flip y is in the data
  variants and worked); (3) the dirty cell lists (2048 cells per draw screen) overflowed into
  `star_count` when the program rewrote the screen for several frames before a screen was
  drawn (bus error in `erase_stars`): a full list now sets `list_full` and the draw screen
  redraws every cell.
- Boot: the main CPU's RAM test is skipped (`--full-selftest` keeps it), the grid screen
  and the handshake wait ($3719 loops, ~200 frames) remain.
- Frame rate (VBLs vs renders from the debug counters, 10 s steps from 20 s, the attract
  mode with its demo play): with the starfield 25 fps in the title phases and 7-14 fps with
  the formation (14.3 average); `-D NOSTARS=1` (no erase_stars/draw_stars): 48-49 fps in the
  title phases, 9-22 with the formation (23.8 average).  So the stars cost half of a light
  frame but the heavy phases are bound by the sprites and the translated code (the game's
  two IRQ handlers take ~63% of every VBL, the renderer gets the rest).
- Render throttle (`galaga_stars.s`, `-D NOTHROTTLE=1` switches it off): every render is
  timed with MFP Timer D (81 us ticks, restarted at each VBL; a frame is 246 ticks, Timer
  C's control bits stay).  A render that took longer than a frame thins the starfield one
  step (every 2nd star, every 4th, none: `star_level`; the filter is the star's period
  index, so a star is always shown or always hidden), 8 renders in a row under half a
  frame bring a step back.  Measured as above: 43 fps in the title phases (25 with all
  stars, 48 without), 9-21 with the formation, 22.3 average (14.3 / 23.8).
  The renderer is already sliced: it runs in the VBL handler with the VBL enabled, the
  next VBL's IRQ handlers preempt it and it resumes, its sprite entries are copied
  (`spr_entries`) when `draw_sprites` starts, the finished screen is flipped at the next
  VBL (`frame_ready`).  A scanline budget in the style of F030Arcade's `ffight` would
  chunk the same work differently, not make it cheaper.
- Zero-fill restore (`-D NOZEROFILL=1` switches it off): `cell_content` is a bitmap in
  `tile_marks`' layout, a bit per background cell whose character has an opaque pixel
  (`scan_cells` keeps it with `ga_char_blank`).  Restoring the background under a changed
  sprite part first tests the part's cells against it; when all are blank the rectangle is
  cleared with HOP 1 / OP 0 (no source read, no source address) instead of copied from the
  background.  Measured as above: 22.6 fps against 22.2 over the demo (15.4 against 13.8 in
  the first formation phase, the others within noise) - about 2% of the render, less than
  the 5-10k cycles a frame estimated.  Planes cannot be skipped in the sprite blit itself:
  it overwrites the destination, and all 16 sprite colour quads use plane 3.
