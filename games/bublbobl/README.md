# Bubble Bobble, Atari STE

![Bubble Bobble on the STE (Hatari)](docs/screenshot.png)

Third port; paths in this file are relative to `games/bublbobl/` (`src/` runtime and renderer, `tools/` reference machine,
translation, build and tests, `ref/` analysis scripts (one-off probes in `ref/probes/`); generated files in `build/bublbobl/`).  Shared pieces:
`docs/architecture.md`; method: `docs/porting-guide.md`.

Started 2026-10-08.  The `bublbobl` set (Taito 1986, with the protection MCU): three Z80s (main, sub, sound) and
an MC6801 whose own firmware (`a78-01.17`) is in the set.  Built the way the Galaga port is: a reference machine,
a static translation of the programs, and a runtime around them.

Controls: **5/6** coins, **1/2** start, **left/right** move, **Space/Ctrl** jump, **Alt** bubble, **Esc** quits.  Joystick
port 1 plays player 1, port 0 player 2 (fire jumps, up blows a bubble).
Jaguar pad / PowerPad (STE enhanced ports, `docs/architecture.md` "Input"): pad A player 1, pad B player 2, the D-pad moves, **A** jump, **B** (or up) bubble, **Option** coin, **Pause** start, keypad **1/2** start, **5/6** coin, **\*** + **#** quit.

## What runs

* **Main CPU** (6 MHz, 11.5k translated instructions, `tools/gen.py`): the 32 KB fixed ROM plus a window
  ($8000-$BFFF) onto four 16 KB banks.  Window code is translated per bank (virtual pc `$10000 + $4000 * bank +
  offset`), a jump from fixed code into the window goes through a stub that picks the bank's label, `ret` and
  `jp (hl)` through the dispatch table of the current bank (`a4` follows the bank register `$FB40`).  Reads of the
  window as data use `g_winbase` (through a0, `Emitter.window_wrap`: with `z80x.FAST` a0 is free, no save); the sites
  are those the coverage runs and `tools/window_audit.py` found.
* **Sub CPU** (1.4k instructions): the same shared RAM (`g_ram`), "long" memory model.
* **MCU** (`engine/m6801x.py`, 940 instructions): the firmware translated 6801 -> 68000, the self-test that
  can never pass on the board skipped (reset = `$F003`), the two bus routines (`$F1BF` read, `$F1DB` write)
  native in the runtime.  It reads the inputs and DIP switches, moves bytes to and from `$FC00-$FFFF` and
  raises the main CPU's interrupt (IM 2, the vector byte is in `$FC00`, the page in the I register).
* **Sound CPU**: not translated; its driver's output is recorded per command and played on the YM2149 (see
  "Sound"); the main CPU's writes of the latch (`$FA00`) reach the player through a write hook.
* **Boot self-tests** are patched out of the ROMs (`machine.skip_tests`, also in the reference): the RAM
  tests, the delay loop, the sub CPU's ROM checksum.  The game checksums `$0001-$0EDC` of its ROM while it runs
  (one byte per frame, `$484B`); a dead byte of the old RAM test (`$C5`) makes the sum the original's.  A second
  check (`$0AE3`, every 4th byte of `$0004-$0C04`) crashes on a mismatch; none of the bytes it reads is patched.
  `tools/build.py` embeds the patched ROMs in the program.

Schedule (`src/bublbobl.s`): at every VBL the MCU's IRQ1 handler, then the main CPU's interrupt handler and the sub
CPU's, each to completion, then the frame is drawn behind them (the VBL nests into the renderer: the game
keeps its pace, the display drops frames).  Three screens (2026-10-10): the one shown, a complete one waiting for the
next VBL (`ready_screen`), the one being drawn; when a picture is done and the game ran meanwhile, the next one starts at
once (`logic_rounds` against `render_from`) instead of waiting for the VBL.  Each renderer keeps per screen what it lacks
(`old_stale`, `sr_stale`) and copies it from the screen drawn last (`last_screen_address`).  The CPUs' foreground threads only boot to their idle loops (the
boot waits for the MCU's handshake at `$0158`: a hook gives the MCU and the sub CPU a turn).

## Sprite renderer (`src/srender.s`, 2026-10-10)

Most frames (the play, the demo play, the title and instruction screens) have the object list in layers: columns (32
rows of 2 tiles: the level's back), sprites (shapes 0-3: 16 x 16, 2 x 2 tiles), columns again (the walls and platforms,
in front of the sprites), sometimes sprites after those.  `render_frame` gives such frames to `sr_frame`, the others to
the general renderer below (switching draws everything once).  On the 8 x 8 grid the columns make a static picture:

* `sr_img` (both column layers, in the screen's layout), `sr_msk` (the front layer's opacity, a byte per 8 pixels and
  line), `sr_any` (per block: the front layer has an opaque pixel).  Two tiles per cell and layer are allowed (the
  title has 32 columns and no sprites: both sets are behind); a cell is drawn again when one of its tile entries changed
  (`rf_vdiff`'s `tile_dirty` through `sr_vinv`, the cell of every entry) or a pen of its tiles changed slot
  (`pen_chg`, `bb_penmask`: the pens each tile uses).  The maps (`sr_maps`) are built again when a column, its x or
  its layer changed (sprites coming or going between the two sets move the front set to the back).
* The screen is handled in blocks of 16 pixels (one plane word group) x 4 lines.  Per object a record (`sr_recs`, 64
  bytes) of what the last frame drawn here saw; `sr_scan` compares: a sprite whose entry, tile entries (the page flags of
  `rf_vdiff`) or colour generation (`sr_gen`, per bank, new on a mapping change) changed puts its old and new blocks into
  the set; one that only moved keeps its tiles' keys.  The visible sprites are listed (`sr_vlist`).
* Closure: a sprite with a block in the set is drawn whole and its blocks join the set, until nothing changes.  The
  screen to draw gets: the blocks it lacks outside the set copied from the screen drawn last, the set restored from
  `sr_img`, the set's sprites in list order, the front columns again through `sr_msk` where a back sprite was drawn
  (blocks of `sr_s1` and `sr_any`), the sprites after the front columns.
* A sprite is drawn from its baked image (`sr_cache`, 512 entries of 408 bytes, direct mapped, keyed by the four tiles'
  keys with their generations and the shift x & 15): two plane word groups per line, the mask inverted and doubled,
  `and.l` / `or.l` per plane pair, clipped by whole groups (the game area is 16 groups wide) and by lines.  A miss bakes
  it from the tile cache (`tcache`).

Exact: `render_test.py seq 100 1500` (attract, coin, start, two rounds, a level transition) 1500 of 1500 frames,
`render_bench.py` 0 wrong pixels.  `render_bench.py ... --step 2` renders every second frame (the pace of 25 pictures a
second); it leaves the first frame (a full redraw) out of its means and profile and prints how many sprites were drawn
and baked.

## Fixed palette (2026-10-10, `STATICPAL`, the default; `-D DYNPAL=1` the colours chosen per picture as before)

Colour 0 is the background (palette entry 255), colours 1-13 are fixed: fitted to the game's own colours by
`ref/palette_fit.py` (weighted k-means in Oklab over the reference pictures of the logic test's 3000 frames and the 64 MAME
attract frames of `docs/`, each colour snapped to one that occurs; `docs/palette_static.json`), every pen maps to the
nearest of them in Oklab (`stat_near`, 4096 entries, built by `tools/assets.py`).  Colours 14 and 15 are lent to flashing
entries: an entry that changed `VOLMIN` (4) times takes a free one, and from then on its changes only rewrite that STE
colour; it gives it back after `VIDLE` (48) palette changes without one of its own, and a new picture (16 entries or
more at once) takes both back.  A change of slot redraws only the tiles that use that pen.  Colour error against the
arcade (per channel, 0-255): gameplay 1.38 with 94.7% of the pixels exact (`palette_fit.py`'s histogram); in
`render_bench.py`'s windows 0.25-2.4, against 0.08-7.9 for the per-picture choice, whose stable slots drift on the
second round (7.2-7.9 there).  DawnBringer 16 (black for its darkest) would be 17.8 (68% exact); the earlier Oklab default
`docs/palette16.json` 8.0.

## Renderer (`src/render.s`)

The arcade draws a list of objects (strips of 8 x 8 tiles, shape from a PROM, columns chained across objects;
`tools/machine.py render_raw` is the reference, checked against MAME with `ref/mame_cmp_bublbobl.py`: 0 pixels
differ).  The STE port:

* 16 colours: the 15 most used colours of the banks in use + the background; every (bank, pen) maps to its
  slot.  Colours that change (flashing) get a slot of their own, so the mapping survives them; a palette change
  that leaves the mapping alone only rewrites the STE palette.  The colour choice is made again (`rf_palette`)
  when an entry starts to flash, when a colour that does not flash changed together with the tile entries (a new
  picture), or when a bank comes into use; not for the flashing entries' colours alone (every frame of the play):
  their slots just get the new colours.  **Slots are stable**: a colour that was in a slot stays in it, new ones
  take a free slot (`.stabilize`), so a new colour changes the mapping of the pens near it, not of everything
  behind it.  A mapping change redraws only the tiles of the banks whose 15 pens map differently (`bank_chg_b`,
  `rf_mark_banks`) and re-bakes / flushes only those; all 16 banks (the first palette) redraw everything.
* Tiles are baked per (code, bank, flips) into planar rows + inverted mask (`tcache`); an aligned tile is one
  `movep.l` per row, a shifted one is merged into two cells.
* Dirty cells (8 x 8): an object that changed marks the cells of its old and its new tiles, a tile entry that
  changed (diff of the video RAM against a copy) its cells; a shifted tile that touches a dirty cell makes all
  its cells dirty; the dirty cells are cleared and every object's tiles on them are drawn in list order.  Exact:
  the result is the reference's bitmap through the colour table.
* **Layers and composites** (2026-10-09): the objects whose tiles changed within the last 8 renders make the
  *moving range* (the sprites, 16-62 in the play); the objects before it are composited *below* it, those after it
  (the level's 16 background columns, drawn last, in front of the sprites) *above* it, per 8 x 8 cell: `comp_B`
  (below), `comp_S` (below and above: the static picture), `comp_K` (where above is opaque, the four planes).  A dirty
  cell without moving tiles is one copy of `comp_S`; with them: `comp_B`, the moving range's tiles in list order, then
  `comp_S` through `comp_K`.  The composites are built lazily, for the dirty cells that lack them (`comp_bad`): below
  and above drawn on a canvas, the mask by drawing above with each tile's opacity as its pixels (`rf_maskmode`); a
  colour change rebuilds `comp_B` / `comp_S` only, a change of layer only invalidates.  A frame with more than 300
  dirty cells is drawn whole, as before.  The closure of the moving range works on the objects' row x column
  rectangles; the old and new cells of a changed object are marked the same way (supersets: only more cells drawn).
  An object whose shape starts a new column no longer counts as changed when the x entering it changes (the
  background columns were redrawn whenever the last sprite moved).
* **The video RAM diff** compares only the 128-byte pages the translated writers marked (`gen.VRAM_WRITERS`, 104
  instructions from `ref/vsites.py`; `logic_test.py` checks that every difference from the renderer's copy is marked),
  plus one page a frame in turn.
* Double buffer: the screen being drawn also lacks the last frame's changes.  The cells of those that this frame
  does not draw are **copied from the screen shown** (`rf_copy`: one `movep.l` per line, ~500 cycles a cell
  against ~7000 to draw it): that screen holds the last frame complete, and nothing changed in them since.
* Game rows 16-239 at screen pixel 32, borders removed (277 lines, the picture centred).

## Reference captures, palette, ROM manifest

`docs/` (see `docs/README.md`): 64 MAME attract-mode frames with all 68 on-screen colours, the 16-colour Oklab palette
adopted from the JsOklabQuantizer default (`docs/palette16.json`, not yet checked against gameplay frames; it has no
green), the CRC manifest of the `bublbobl` (Japan) and `bublboblr` (US / Romstar) sets, and hardware notes with
evidence grades.  The scripts that produce them are in `ref/`: `mame_attract_collage.py`, `quantize_collage.py`
(+ `oklab_quantize.mjs`), `palette16.py`, `rom_manifest.py`; the fixed palette the port uses: `palette_fit.py`
(`docs/palette_static.json`, see "Fixed palette").  The port itself is built on the `bublbobl` set; the US set
differs only in the two main-CPU ROMs and has not been run through the translator.

## Tests

Paths relative to `games/bublbobl/`; from the repository root `python port.py test bublbobl` runs the sequence below.

    python port.py build bublbobl --sim              # run/bublbobl_sim, with the hooks the tests use
    python port.py build bublbobl                    # run/bublbobl/BUBBLE.PRG (the patched ROMs embedded)
    venv/bin/python tools/mcu_test.py 2600           # translated MCU vs the 6801 reference, every IRQ
    venv/bin/python tools/logic_test.py 700          # whole game (Musashi) vs the reference, RAM every frame
    venv/bin/python tools/render_test.py seq 1500 20 # renderer vs the reference bitmap, consecutive frames
    venv/bin/python tools/align_test.py 900          # odd word accesses (a 68000 faults on them, Musashi does not)
    venv/bin/python tools/render_bench.py 110 60 400 60 620 120   # renderer cost and picture quality, windows of frames
    venv/bin/python tools/profile.py 1200            # where the 68000's cycles go, in the real VBL schedule
    python port.py run bublbobl shot@20              # Hatari (F030Arcade), screenshots
    python port.py run bublbobl key:5@20 key:1@26 shot@60   # ... with keys (5 = coin, 1 = start)
    python port.py run bublbobl dump:0xADDR:0xSIZE@50       # ... and memory dumps (savebin)

Reference: `tools/machine.py` (three Z80s + the 6801 running its ROM, 30 frames/s; `run_frame_port` is the
runtime's schedule, identical RAM).  Coverage for the translator: `ref/cover.py <seed> <frames>` (`port.py cover bublbobl`).

The two measuring tools run the `--sim` build.  `tools/render_bench.py A N [A N ...] [--prof|--detail|--count]` feeds the
renderer consecutive reference frames (as `render_test.py seq` does, including the screen swap of the VBL) and prints, per
window, `render_frame`'s cycles, wrong pixels (must be 0), the picture's colour error against the arcade's RGB, how
often the colour mapping changed and how many cells were drawn; `--prof` shows where the cycles go, `--count` how often
`draw_tile` (aligned / shifted), `tc_bake`, `mark_tile` and `obj_slots` run.  It calls the renderer once per *game* frame,
which the real program never does (it draws a picture every few VBLs and so sees larger changes): use it to compare
two renderers, and `tools/profile.py` for the real thing: the whole program with the 50 Hz VBL, scripted coin / start /
play, the PC sampled every 64 cycles, cycles per VBL by area (renderer / main Z80 / sub Z80 / MCU / runtime), the hottest
routines, **game frames run per VBL** (1.00 = the port's full speed: 50 of the arcade's 59.19 frames a second) and
pictures drawn a second (`--hist` gives a routine's per-VBL distribution).  The `--sim` build counts both
(`sim_game_frames`, `sim_renders`).  `render_test.py` / `render_bench.py` keep their scratch stack and slot buffer at
the top of the 4 MB RAM: they used to write them into the tile ROM data (`$60000`, `$7F000`), where the baked tiles of
a build with another code size were damaged.

## Status (2026-10-08)

Works: boots in the F030Arcade Hatari straight into the attract mode (the boot self-tests are skipped), every
screen of it is drawn correctly (title, the instruction pages, the demo play), the picture is centred with the
borders removed.  Game logic: identical to the reference (RAM compared every frame, 760 frames of boot, attract,
coin, play); renderer: the reference's bitmap through the colour table, pixel for pixel, on consecutive frames.

Slow.  The game's interrupts cost 0.1-1.1 M cycles per VBL (a frame is 0.16 M; the main CPU executes 4-10k
translated instructions per frame, the MCU 40k cycles, the demo play phases are the worst) and drawing a frame
0.16-0.9 M (gameplay ~0.9 M).  So the plain 8 MHz STE neither keeps the arcade's 60 Hz nor updates the picture
more than a few times a second: while a frame is being drawn, every other VBL skips the game's interrupts
(`render_age`), so the game slows down and the display keeps coming.  Not playable at that speed; the port needs
a faster 68000 (the Falcon's 16 MHz 030) or the work below.

Measured 2026-10-08 (`tools/profile.py 1200`, 300 VBL windows, the `--sim` build on Musashi; the CPU is 100% busy, the
renderer takes 63-72% of it, the main Z80 12-25%, the sub Z80 and the MCU a few percent):

| window | game frames per VBL (1.00 = full speed) | pictures a second |
|---|---|---|
| attract, frames 100-400 | 0.76 -> **0.79** | 12.3 -> **13.8** |
| play, 600-900 | 0.55 -> **0.57** | 1.2 -> **1.8** |
| play, 900-1200 | 0.55 -> **0.63** | 1.3 -> **3.3** |

(before -> after the double buffer copy, the stable colour slots, per-bank mapping changes and the recompute rule
above; `render_bench.py` over the same frames: 0 wrong pixels before and after, identical colour error: 0.80, 0.23 and
0.08 of 255.)  What the cycles went to in the play before these changes (`render_bench.py 640 40 --prof --count`): a frame
of ~2.0-2.2 M cycles over ~250 dirty cells (now ~1.8 M over ~205): 572 `draw_tile` calls (**495 aligned, only 77
shifted**) = 37%, `rf_redraw` 17%, `obj_slots` 6%, the palette 11%, `mark_tile` 5%, `tc_bake` + `get_tile` 9% (30 cache
misses a frame), the video RAM diff 4%.  In the attract mode and at every scene change the cost was the **colour mapping
change**: in 60-frame windows of the attract and the coin / start, 62-64% of all `render_frame` cycles were in the frames
that changed it (+22-24% in the frame after), 3-9 M cycles each, and 10-16 of the 16 banks changed.  Stable slots and the
per-bank redraw remove the changes that were only a shifted slot order; when a scene really loads a new palette (13 banks
change colour) the frame still costs ~6.5 M cycles.

**Can it reach 50 fps on a plain STE?  No.**  The game's own work per game frame (translated Z80 + MCU + the runtime glue) is
75k cycles in the attract mode and 89-107k in the play, of the 160k a VBL has: 56-67% before anything is drawn.  A picture
costs ~1.8 M cycles in the play (~0.4 M in the attract mode), so drawing one every VBL would have to fit in 53-71k:
25-35 times less.  Nothing measured comes close: the renderer changes above took ~10%, the Blitter (below) would take
another 7.5% at best, a micro-optimising pass perhaps 20-30%.  Full speed needs a CPU several times faster (the Falcon's
16 MHz 030 with its caches is the obvious candidate: it has no Blitter, which this renderer does not use anyway, but the
STE-specific parts, the border removal and the palette writes, would need checking) or a different division of work.  That is an
estimate from simulator cycles; nothing has run on such a machine, and the STE Blitter would not be there to help.

**Colour cycling deferred** (`-D NOCYCLE=1`, `rf_palette`): a palette change of fewer than 16 entries (the arcade flashes 1-3
entries, 14 at most in the first 1500 frames) is ignored, so the picture keeps the colours it had.  Real schedule,
`tools/profile.py`: attract 0.79 / 13.8 -> **0.86 / 17.8** (game frames per VBL / pictures a second), play 0.57 / 1.8 -> **0.60 / 2.5**
and 0.63 / 3.3 -> **0.65 / 3.7**; the 8 M cycle spikes of the play disappear (max 2.0 M); the colour error against the arcade
rises to ~5 of 255 (7% of the pixels not in their colour), as the flashing is lost.  So the palette work is worth 5-9% of the
speed and 30-40% of the picture rate, and it is the one place where exactness is traded for speed: not on by default.

**Blitter experiment** (`ref/blit_bench.py`, `tools/blit_project.py`; the engine's Blitter model with 4 cycles a bus word, partial
masks read the destination, register set-up estimated; Blitter and CPU results are **pixel-identical** in every case).  One
8 x 8 tile, cycles with set-up (CPU = `draw_tile`'s own loop, Blitter = one blit per row, Y count 4 = the four planes, the
row's opaque pixels as end masks):

| case | CPU | Blitter |
|---|---|---|
| aligned, with transparent pixels | 836-876 | 904 (no gain) |
| aligned, opaque | 516 | 904 (worse) |
| shifted, left cell even (one destination word) | 2494 | 904 (2.8x) |
| shifted, left cell odd (two words, `NFSR`) | 2494 | 1256 (2.0x) |
| clear / copy 1 group (2 cells) / 8 groups (16 cells) | 544 / 4352, 1056 / 8448 | 276 / 1172, 404 / 2196 (2-3.9x) |

Applied to real frames (exact counters of the `--sim` build): in the play a frame has 244 aligned tiles (all with transparent
pixels) and 79 shifted ones (40 even, 40 odd), 198 cells cleared in 51 whole-group runs (+49 lone cells), 39 copied; the
Blitter would save 113k cycles on the shifted tiles (6.3% of a 1.82 M frame), 13.6k on the clears (0.7%) and 8k on the copies
(0.5%): **7.5%**; in the coin / start window 4.8%, in the attract mode 1.7%.  The aligned tiles, the bulk, gain nothing: an 8 x 8
tile is too small to pay the blit set-up.  Caveats: the long run blits (up to 2.2 k cycles) hog the bus and would delay the border
timers (see the Blitter notes in `docs/porting-guide.md`), so they would have to be split, which costs part of the gain; the
numbers are simulated bus cycles, not Hatari frame times.  A Blitter renderer for this game would pay for a background layer
composited by rectangle copies and for sprite-like objects, i.e. a different renderer, not a different inner loop.

**The whole-object rule** (`docs/architecture.md` / `docs/porting-guide.md`, "Whole-object drawing (all ports)": a wider virtual
screen with hidden margins, objects drawn whole, no clipping routines or runtime edge masks): the renderer already draws whole
tiles and has the 16-byte margins left and right and the guard rows above and below (`YPAD`); what it does is cull a tile that is
entirely outside (`draw_tile`, allowed by the rule) and erase the overhang of the partly outside tiles each frame (`rf_cleanup`,
25k cycles = 1.1% of a play frame), because the margins are **visible** black bands of the 320 pixel screen: the 256 pixel
game area leaves 32 pixels each side, so the "hidden" space of the rule does not exist here and a tile spilling over the edge
would show.  Keeping `rf_cleanup` is the exact choice (the arcade clips); dropping it would be the 1942 choice (spill into the
margins, a visible deviation) and would save 1.1%.

Next, in order: the steady cost of the play, i.e. the per-cell work (the aligned tile: ~300 cycles of set-up before
its first row, `get_tile`'s hash, the clearing of a cell an opaque tile overwrites anyway, `rf_redraw`'s object loop),
fewer dirty cells (an object marks all its tiles, old and new), table driven `obj_slots`; the scene change (draw the
tiles of the banks that changed over several frames, or fade through the old colours); the video RAM diff (4%, a write
barrier would remove it; 106 store sites) and the shifted tiles (77 a frame, 2.7k cycles each: **not** the main cost as
the earlier estimate had it, so the Blitter is not the first thing to try); cheaper translated code (the Z80 handler
is 40-70% of the logic, the `ld a,r` / `ex af,af'` / `exx` register shuffles are in the hot paths).
`logic_test.py` passes 6000 frames (2026-10-09).  Its reference keeps S Z C in `push af` / `pop af` (`afmask`, as the
other ports' tests do) and does not compare the bytes of merged `push rr / pop rr'` until something else writes them.
The difference it showed from frame 923 on (`$E0A8`, later `$E0A6`) was a flags byte in a task context: `$1929` does
`push af ... pop bc` with the alternate F (the reference's `$2C`, Y X P/V, the translation's `$00`), `exx` keeps it as
C', the task switch at `$0094` pushes it; no reader (the reference with and without the mask differs in these two
bytes only over 6000 frames).  `$E0DE`/`$E0DF` from frame 1002 were the dead word of the merged `push hl / pop iy` at
`$1479`.  Open: the coverage run of seed 4 stops at frame ~18000 with
`handler of 01ED did not return` in the reference machine (`ref/cover.py 4 20000`), so five seeds were used.
Not done: the 16 sprites per line limit, screen flip (`$FB40` bit 7), test / service modes, per-band palettes (22-26 distinct colours on a screen, the STE shows 16: the 15 most used
per bank weight are kept, the rest map to the nearest).

## Translator speed (2026-10-08)

Main CPU `z80x.FAST` (A' F' and BC' DE' HL' in the upper words of d0 / d6 and d1-d3, IY in a2), sub CPU
`z80x.FAST_LONG`; the window stubs' `move.l ...,a3` no longer clobbers A'.  `gen.py` goes through `translate.compile_code`
(its own copy of the pipeline is gone) and uses the engine's `ldir`; its return points in the window are left out of
the direct returns (`direct_ok`: a stack word cannot tell the bank).  `engine/xprof.py bublbobl` (frames 500-800 of
the logic test's input script, per game frame, the main CPU's idle loop `$01ED` apart): translated code 70.3k -> 54.2k
cycles (1.30x; 2026-10-09, the engine's window wrapper without the a0 save).  What is left: `ret` / `call` (~15%), the 360 byte copy at `$04B6` (odd source, even destination: bytes,
~5k), the MCU (5.3k, `m6801x.py` untouched).  Tests: `logic_test.py 700`, `render_test.py seq 1500 20`, `mcu_test.py`,
`align_test.py` all pass; Hatari runs the attract mode.

`tools/profile.py 1200` after it (2026-10-09, Musashi, the real VBL schedule): game frames per VBL / pictures a second
0.80 / 14.2 (attract, 100-400), 0.58 / 2.2 (play, 600-900), 0.65 / 3.5 (play, 900-1200), against 0.79 / 13.8, 0.57 / 1.8,
0.63 / 3.3 before: the translated code is a fifth of the CPU in the play, the renderer more than two thirds
(~109k cycles a VBL), so the frame rate moved little.

## Edge bands (2026-10-09)

Tiles that hang over the game area are drawn whole into the 16-pixel bands around it (the screen is the plain 320-pixel
one); `draw_tile` notes which band it drew into (`hang_top`, `hang_bottom`, `hang_rows` for the 8-line rows with a tile
at x < 0 or x > 248) and `rf_cleanup` erases only those, in the same frame: 27k -> 1.7k cycles a frame.  What a frame
costs (`tools/render_bench.py 1500 150 --prof`, play, about 870k cycles): the redraw of the dirty cells in list order
(`draw_tile` 224k, `rf_redraw` 210k), the video RAM compare (`rf_vdiff`, 84k), the object bookkeeping (`obj_slots`,
`mark_tile`, `tile_state`, about 150k) and the copy of what the other screen lacks (`rf_copy`, 41k).

## Speed (2026-10-10)

`tools/profile.py 1500` (the real schedule on Musashi; game frames per VBL / pictures a second):

| window | 2026-10-09 | sprite renderer, fixed palette | + three screens |
|---|---|---|---|
| attract, 100-400 | 0.77 / 23.7 | 0.86 / 34.5 | 0.85 / 34.7 |
| start of the game, 600-900 | 0.57 / 1.7 | 0.65 / 3.7 | 0.58 / 3.0 |
| play, 900-1200 | 0.75 / 6.7 | 0.75 / 9.7 | 0.76 / **13.2** |
| play, 1200-1500 | 0.49 / 3.5 | 0.56 / 13.2 | 0.57 / **16.2** |

A picture of the play costs ~180k cycles (`render_bench.py 900 300 1200 300 --step 2`, median; ~620k before).  The
limit is the game itself now: its interrupts cost 95k-146k cycles a game frame in the play (main Z80 70-93k, sub Z80 up
to 21k, the MCU and its bus routines ~30k) of the 160k a VBL has, so 25 pictures a second and the full speed cannot both
be had in busy scenes on an 8 MHz STE; the game's speed comes first (the user's choice, 2026-10-10).  Also changed:
the MCU's bus routines (`mcu_bus_read` / `mcu_bus_write`, ~80 calls a game frame) address its memory through a6.

`logic_test.py` had been failing since the pads came (2026-10-10, release 0.1): the VBL composed the inputs and
overwrote the ones the test sets; the `--sim` build leaves them to the test now.

## Speed (2026-10-09)

`tools/profile.py 1200` (the real schedule on Musashi; game frames per VBL, pictures a second):

| window | 2026-10-08 | video RAM marks | + layers |
|---|---|---|---|
| attract, 100-400 | 0.79 / 13.8 | 0.78 / 26.3 | 0.77 / 23.7 |
| play, 600-900 | 0.57 / 1.8 | 0.57 / 1.8 | 0.57 / 1.7 |
| play, 900-1200 | 0.63 / 3.3 | | **0.75 / 6.7** |

Consecutive frames (`render_test.py seq 1600 100`, every frame drawn): median 920k -> 640k cycles.  The start of a
level (600-900) builds the composites of nearly every cell; `NEED_MAX` 96-160 (draw such frames whole and leave
the composites) gives 0.58 / 2.0 there and 0.68-0.69 / 4.5-5.0 later, so it is off.  All 1200 frames of
`render_test.py seq` over attract and play are exact; `--layers` prints the moving range and the cell counts.

## Sound (2026-10-11)

The sound board (MAME `taito/bublbobl.cpp`): a Z80 at 3 MHz, a YM2203 (its timers interrupt the CPU) and a YM3526
(OPL), both at 3 MHz; the main CPU's latch raises the NMI.  The driver (`tools/sound.py`, which models the board:
the timers, the OPL's timer the boot waits for, the SSG registers read back) queues commands (NMI, 0066) and starts
their items, one a track: 26 tracks, two for each of the 9 OPL channels, the 3 FM channels and the SSG (sets A and B);
a track takes a new item unless it plays one with a lower priority number (0357), and a channel plays its A track
while that plays, else its B track (0535).  The stage tunes are OPL set B, the jingles OPL set A, the effects FM (and
three on the SSG).  The game sends $EF first (the sound on), then the sound commands $00-$34.

The tempo is the YM2203's timer A, which a tune may change (`8FA3`): so the recording is in real time, a value a
50 Hz VBL.  Each command is recorded alone: per track a YM2149 period and volume (an OPL channel through
`engine/opl.py`, new: the YM3526's envelopes after ymfm; an FM channel through `engine/opn.py`) or the SSG's
registers, until the track ends, or with its loop: the chip writes of the driver's timer ticks repeat with a period
(the tracks' blocks hold a counter that never repeats), the loop rounded to whole VBLs.  `build/bublbobl/bb_sound.s`:
270 KB (53 commands; the program leaves 167 KB from the desktop).

`src/sound.s` runs in the VBL (`bb_snd_vbl`, every VBL, also those that only arm the border timers): the queued
commands start their items, every track steps a VBL, each channel takes its A track's value or its B track's, and the
mixer of `engine/rt/capsnd_core.s` (now for up to 12 music channels, `CS_MCH`, with a per-channel boost: the FM
effects before the OPL music) puts the loudest on the YM channels the SSG leaves.  12,500-14,000 cycles a VBL (Musashi:
the game's commands / random ones), 8-9% of the CPU: the game runs that much slower than without the sound
(`-D NOSOUND=1` builds without it).

Checks: `sound.py check` runs the real driver beside the model, a VBL at a time.  With the game's commands
(`logic_test.py`'s inputs, 2,400 frames): the SSG 0 VBLs differ audibly; of 14,688 sounding OPL / FM channel-VBLs
2,972 differ by a VBL (the driver's ~60 Hz ticks fall elsewhere in the VBL than in the recording) or a volume step,
1,719 more, mostly the vibrato's phase (a few cents) and a note starting a VBL later.  With random commands far more
differ: commands that change another's tracks (effect $1A changes a parameter of two OPL channels' B tracks, which
lasts) are not modelled.  `sound_test.py` (in `port.py test`): the 68000 player against the model, 0 of 6,000 VBLs
differ.  Hatari: music and effects in the attract mode and play.  `build.py --sound` records again (~10 min).

