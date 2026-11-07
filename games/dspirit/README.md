# Dragon Spirit

Atari STE port (4 MB) of the MAME set `dspirit` (Namco System 1, ROT90): the main and sub MC6809E programs translated
to 68000 code (`engine/m6809x.py`, `tools/gen.py`, `src/core.s`) on the reference board `engine/namcos1.py`, as
Galaga '88 (`games/galaga88`) and Splatterhouse (`games/splatter`).  Work in progress: the translated logic runs in
lock-step with the reference (SIM build only); the STE program, the MCU, the renderer and sound are not written yet.
This port uses its standalone scripts and is not registered in `port.py` or included in releases.

## Logic

* **Coverage** (`ref/cover.py SEED FRAMES [--port]` -> `build/dspirit/cover_[port_]SEED.pkl`): seeds 1-3 the attract
  mode, seeds 4+ coin, start and random play (the 8-way stick, air shot 60%, bomb 15% of the holds: `random_bits`).
  `--port` runs the port's schedule (`tools/machine.py run_frame_port`) with the inputs of `tools/logic_test.py`: the
  port runs ahead of MAME's schedule (no frames the game overran), so MAME-schedule coverage misses scenes the port
  reaches (the attract mode's later scenes, page $371).  `tools/gen.py` reads both kinds.
* **Schedule** (`tools/machine.py`): as Galaga '88's (the vertical blank, the MCU and the sound CPU on the board's
  scheduler, then the main CPU's IRQ and frame, then the sub CPU's).  The port starts at frame 300.
  * Main (DP $40: slot 2, the work RAM): `8048: JSR $8770` (the random numbers: an LFSR step of `<$D3/$D4`),
    `804B: STA $F200; LDA <$FF; BNE 8048`, then `INC <$FF; JSR $8140` (the frame).  The IRQ handler ($81B4) clears
    `<$FF`.  The arcade steps the LFSR on every pass (~3600 a frame); the port once a frame: idle at $804B while `<$FF`
    is set (core.s `main_idle`).
  * Sub (DP $20: slot 1, the scratch RAM; its stack in slot 2): it never waits.  The IRQ handler ($D6CD) clears byte 9
    of every sprite entry; the foreground loop `D6C5: STA $F200; JSR $D8B0; BRA D6C5` builds the sprite list from the
    objects in the work RAM ($41A0 + $28 n) on every pass, from scratch (~12 passes a frame in the arcade).  The port
    runs one pass a frame: back from the IRQ at $D6C5 the pass starts, at its end the sub is idle (`sub_pass`, core.s
    `sub_idle`).
  * The port's game runs ahead of the arcade's (frame 600 of the intro: the dragon already formed, MAME still in the
    flash): the arcade's main CPU overruns some frames; the port's schedule has no such frames.
* **Direct page**: per CPU (`Program(dp=, a3_slot=)`; core.s `DPS` / `DPR` in the context).  The main CPU's bank
  routines in page $334 ($A215, $A22A) use DP as a scratch register (`TFR B,DP`: DP = slot * $20 + $10) and map slot 6
  to the C116 registers (page $173) or TRIRAM (page $17F); the code after them reaches those through `<$xx` with DP
  $C0 / $D0 (a constant per site, `dp_sites`).  The routines' shared instructions run with several DPs: allowed where
  the instruction neither addresses the direct page nor reads DP (`gen.py dp_free`).
* **Page $334 in two slots**: the main CPU runs that page's position-independent code from slots 5 and 6.  The
  translation keeps one slot per page: slot 6's copy is page $30C (a mirror of the same ROM bytes; `PAGE_ALIAS` in
  ref/cover.py and tools/gen.py, `Program.page_alias` for the translation's inline bank writes, core.s `bank_set` and
  `alias_page`, its own 8 KB copy so the translation's page checks by address tell the two apart).
* **Jump tables** (`gen.py table_targets`): random play does not reach every entry of the state machines' tables
  (`JMP [A,U]`, `JMP $2000,U` after `LDU A,U`, `JMP D,X`).  Per computed jump the coverage saw: the table's base from
  an immediate load on an executed path just before it, then its entries while they stay in the slot of the seen
  targets, outside the table and the executed instructions, and decode as legal code; they become roots (30 tables,
  ~250 entries).  Entries into a slot whose page is set just before the jump (main $B80B: slot 3 = page $371) are not
  found that way: coverage only.
* **The protection check** (main $B65C-$B672): slot 0 gets page $173 (the C116's registers), the program patches the
  byte at $0004 from $0001 / $0003 and calls `JSR $0002`: `PSHU` with no registers, then `RTS` ($39) when the check
  passes.  The port does not run code from RAM: core.s `main_prot` checks the three bytes and goes on after the JSR
  (else badpc $0002).
* **Stores into ROM**: main $AC00-$AC1A (`STA $6000` / `$6200` / `$6400` / `$6600`) write into slot 3's ROM page; the
  arcade ignores them.  Such sites (`gen.py rom_writes`) go through core.s `io_w`, which drops stores into ROM pages.
* **Key custom**: CUS136 (type 1): registers 0-2 read the remainder and the quotient of regs 1-2 (16 bits) by reg 0
  (8 bits), register 3 the id $36 (core.s `key_divide`: one `divu`).

Translator fix found here (engine/m6809x.py, all 6809 ports): a post-increment operand whose slot is computed at run
time (`LDD ,Y++`) took the slot of the incremented register when the 16-bit access emitted the operand twice (Y = $7FFE
read $8000's slot).  Galaga '88 and Splatterhouse: 600 frames still identical.

Test: `tools/build.py --sim`, then `tools/logic_test.py FRAMES --seed N` (frame by frame against the reference: work
RAM, TRIRAM, the CUS30 RAM, tile RAM, palette, scratch and sprite RAM, CUS123 control, the key custom, `sub_pass`,
both CPUs' registers and pages; `--steplock F` instruction by instruction, with the slot pages, the cached registers and
the ROM image's changed bytes at a difference; `--trace F` the last translated labels).

Results (2026-11-07): main 13579, sub 2657 instructions translated, none unsupported (coverage: MAME schedule seeds 1,
4-8, 4000-6000 frames; port schedule seeds 1, 5, 6, 12-15, 8000 frames).  `logic_test.py 7700` identical for the
attract mode (seed 1), the covered play seeds 5 and 6 and the uncovered seeds 9, 10 and 11; 96k-114k 68000 cycles a
frame for the two CPUs (Musashi), the attract mode ~63k.  Random play reaches only the first stage or two: later
stages' code is translated where static flow and the jump tables reach it (`badpc` / CRASH.TXT where not); coverage
of later stages (snapshots, a scripted or Go-Explore player, `docs/go-explore.md`) is open.

Natives (src/natives.s, tools/gen.py NATIVES; NO_NATIVES=1 builds without, 2026-11-07, R-Type's "exact natives"):
the object-slot loop $C37F (empty slots skipped), the tile-column fill $7A54 and the 4 x 4 tile block $C0DB (the
stage's tile streaming).  `logic_test.py 3000` identical on seeds 5 and 22 (after `build.py --sim`: logic_test runs
the built program); 106.8k -> 89.3k (seed 5) and 143.1k -> 117.5k (seed 22) cycles a frame.  `tools/profile.py`
(from Splatterhouse's): gameplay ~140k a frame before - the translation's own costs (LDD/STD indexed ~80 cycles,
dynamic slots, D built from A and B) are most of what is left: at 60 frames a second the logic alone needs more
than the STE's 160k cycles a VBL.

Next: the STE program (snapshot at frame 300, the MCU - Splatterhouse's native model of the CUS64 program, to be
checked for Dragon Spirit -, the display, a renderer from Galaga '88's), then sound.

## The STE program (src/dspirit.s, from Galaga '88's)

`tools/build.py` (and `--sim` for the logic tests): the translated CPUs, the snapshot at frame 300
(`tools/snapshot.py`: snapshot_vio.bin is vio's starting content - core.s -, snapshot_ctx.bin the CPUs', the key
custom's and the MCU's), the MCU (Splatterhouse's native CUS64 model, the same ROM in all four Namco System 1 sets;
`tools/mcu_test.py` 1500 frames: TRIRAM and the MCU's RAM equal, 12 frames with 98 / 100 instead of 99 voice DAC
writes around a sample's start - the voice, not the game), a picture every PIC_EVERY (2) arcade frames.  Keys: arrows,
space / Z air shot, X / Alternate bomb, 1 start, 5 / 6 coin, Esc quits (COUNTERS.BIN); joystick 1, its button both
air shot and bomb.  Uncovered code: CRASH.TXT.  The dispatcher's page tables are two-level (a directory of 32 blocks
of 256 labels a page: tools/gen.py dispatch_tables; 556 -> 267 KB).  Size 3.79 MB (text + data + bss): it loads on a
4 MB STE; for development Hatari may run it with 14 MB (as R-Type; the user, 2026-11-07).

## Renderer (src/render.s)

`tools/make_render.py` writes src/render.s from src/render_new.s (Dragon Spirit's parts), the colour, bank-map and
sprite-cache routines of Galaga '88's renderer (copied by label) and src/render_data.s.  Galaga '88's picture (ROT270
with its screen flip) has Dragon Spirit's geometry (ROT90, no flip): its turned characters and sprites and its
ren_convert are right as they are; the sprite positions are Dragon Spirit's.  `tools/stemodel.py picture_wide` is the
picture in Python; its arcade part is exact against the reference (`stemodel.py 2000`: 200 play pictures).

The user's decisions (2026-11-07): the scrolling layers and the sprites over the STE's whole 320 pixels (the terrain
maps hold valid tiles beyond the arcade's 224: checked in areas 1-4), the text layers at their old place (x 48-271;
their rows 0-15 shown 5 lines lower, 264-287 6 higher, so all of them fit the 277 lines: picture rows 5-281 shown),
stage 1's water layer (2, under the terrain) locked to the terrain (its offsets taken when the lock begins).

* Layers in play: 0 the terrain (all areas; stage 1: holes over layer 2, the water), 1 / 3 clouds, 4 / 5 the text.
* The buffers: two, each 2 x 288 lines (twins: any 277 in one block) of 424 bytes (the terrain's 512 columns and its
  first 336 again: any 320 + the fine scroll's 16 in one line).  The window: its first line follows layer 0's
  scroll (`ren_view`), screen x 0 is layer 0's image column K (`ren_xo`): the VBL sets the base, $ffff8265 (the
  fine scroll) and $ffff820f (the line's rest).  Vertical and horizontal scrolling are free.
* The terrain mode (`ren_mode`: layer 0 on and the first layer drawn, the C116 window whole, no sprite below
  layer 0): layer 0's image (all 64 tile columns of the 288 rows, the locked layers in its holes, its holes black)
  is the buffer's terrain: drawn whole only for a new tag (colours, bank, lock) or a scroll of a window or more;
  else last picture's damage is restored from the twin lines, and the rows that scrolled in or whose image rows
  changed (ren_tdirty) are drawn (both twins, both column copies).  Clouds, text and sprites go on top into the
  window; their rows' group spans are the damage (ren_dspan).  The text layers' passes are recorded per fine shift
  (ren_pbufs) and streamed while the text is unchanged.
* Otherwise (the title, the intro, the iris windows) every layer is drawn into the window (black first): the buffer's
  terrain is lost (drawn whole next time).
* Shared: a layer's turned image (512 x 512, mask, per row run lists rebuilt only when a tile changed its bytes),
  tiles drawn where their slot's stamp differs (refresh skipped when no writer flag - the translated stores into
  tile RAM, per layer: gen.py tile_marks - and the same window and tag), per row the opaque runs as HOG passes
  (HOP 2 / OP 3, end masks), consecutive full rows as plane passes, rows a later layer covers skipped.
* `tools/render_test.py` (the window as the STE shows it: base, fine scroll, line width): `--every 3` play 500 / 500,
  attract 167 / 167 exact, `--edges` 252 / 252.  Musashi: play median 1.3M cycles a picture (the simple renderer:
  4.1M), attract 3.4M.  Hatari (14 MB, coin, start, intro, stage 1, 210 s): 5.2 arcade frames/s, 1.25 pictures/s.
* Speed-ups (2026-11-07, R-Type's lessons): the locked water filled per character row (not per pixel: a layer-0
  redraw 50M -> 23M cycles); a tile shadow per layer (its tile words as last drawn, compared word by word: the
  per-slot stamps' scan 425k -> 160k a picture); a row's damage gathered over its passes (one ren_dmg a row); a
  locked layer flagged as written (the translated writers flag a layer on any store) compared with its copy
  (ren_lkshd) before layer 0 is drawn again - in Hatari this was nearly all of the render time.  render_test
  FLAGS_ALL=1 sets every writer flag every picture (exact too).  `tools/bench.sh` (BENCH game, frames 600-1600:
  the intro, then stage 1; PHASES=1 per phase of render_frame): 0.55 -> 7.97 arcade frames/s, 0.24 -> 3.02
  pictures/s, render 14 VBLs a picture; with R-Type's schedule (-D PIC_EVERY=8 -D MAX_BEHIND=12) 11.2 frames/s,
  1.40 pictures/s.
* The intro's lightning as a palette flash (the user, 2026-11-07): layer 0's bank flips 0 <-> 3 every ~35 frames;
  layer 0 stays drawn with the bank it had when the colours were chosen (ren_l0bank), and while the game shows
  another the representative pens of the held bank show their colours in the bank shown (ren_flash_pen; the
  quality check looks pens up in the held bank, ren_unflash_pen, and does not choose again during a flash).
  Sprites sharing those indices flash too (the hero's blue goes grey in the bright flash).  The copied Galaga '88
  routines are patched in tools/make_render.py PATCHES.  render_test's model draws layer 0 in the held bank
  (Harness.held): exact; play 230-560: colour choices 14 -> 6, 1036M -> 711M cycles; colour error over the play
  states 0.032 -> 0.053.
* Open (in order): the logic (~0.86 VBL an arcade frame in Hatari); the colour choices (~40-60M); the text layers' passes (~300 a picture: recordings per fine shift
  rarely reused, the window pans every frame); tile conversion of new terrain rows.

## Display (decided with the user, 2026-11-07)

Upright (the arcade picture 288 x 224 turned, as MAME shows it), widened to the STE's 320 pixels (see the renderer);
the open borders give 277 lines (engine/rt/borders.s, as Galaga '88).  For development Hatari runs it with 14 MB
(3.8 MB + the buffers: the 4 MB release is open).

## Full-game verification status

Automated players such as Dreamer can attempt a full playthrough once this port's
adapter and native Hatari replay transport are verified. An attempt or assisted
stage visit does not establish completion; a successful natural Hatari playthrough
and graphics, sound and control checks are required for green **Complete** status.
See the shared [status and verification policy](../../docs/port-status.md) and
[current port status](../../README.md). Existing test results above retain their
stated scope; this note does not claim a new successful run or Dreamer integration.
