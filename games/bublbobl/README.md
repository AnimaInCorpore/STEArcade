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
  are those the coverage runs and `tools/window_audit.py` found, kept in `docs/window-sites.json` (`W_GUARD_ALL=1`
  guards every indirect access: the main CPU's translated code 67.7k instead of 62.4k cycles a frame, `engine/xprof.py`;
  the audit of seed 7, 3000 frames: no site missed).
* **Sub CPU** (1.4k instructions): the same shared RAM (`g_ram`), "long" memory model.
* **MCU**: its VBL interrupt is native 68000 code (`src/mcu_native.s`, since 2026-10-12, see "Native routines"); the
  firmware translated 6801 -> 68000 (`engine/m6801x.py`, 940 instructions) runs the boot and stands in when the
  ports are not as the init leaves them (`-D MCU_XLATE`: always), the self-test that can never pass on the board
  skipped (reset = `$F003`), the two bus routines (`$F1BF` read, `$F1DB` write) native in the runtime.  It reads
  the inputs and DIP switches, moves bytes to and from `$FC00-$FFFF` and raises the main CPU's interrupt (IM 2, the
  vector byte is in `$FC00`, the page in the I register).
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
  (`pen_chg`, `bb_penmask`: the pens each tile uses; only the cells whose banks, as last composed, include a changed
  one are looked at: `sr_cbm`, a bank mask per cell).  A cell's four tile keys look up the **composite cache**
  (`sr_ccache`, 1024 entries of 64 bytes: the keys, a palette stamp, the cell's four plane bytes and front opacity per
  line; it lives in the general renderer's composite buffers, which that renderer builds again when it takes over);
  a miss composes the cell (the first tile written as it is, the others merged) and keeps it.  The maps (`sr_maps`) are built again when a column, its x or
  its layer changed (sprites coming or going between the two sets move the front set to the back).
* The screen is handled in blocks of 16 pixels (one plane word group) x 4 lines.  Per object a record (`sr_recs`, 64
  bytes) of what the last frame drawn here saw; `sr_scan` compares: a sprite whose entry, tile entries (the page flags of
  `rf_vdiff`) or colours changed (a pen its tiles use changed slot this frame: `sr_penhit`) puts its old and new blocks
  into the set; one that only moved keeps its tiles' keys.  The visible sprites are listed (`sr_vlist`); empty objects
  take a short loop.
* Closure: a sprite with a block in the set is drawn whole and its blocks join the set, until nothing changes.  The
  screen to draw gets: the blocks it lacks outside the set copied from the screen drawn last, the set restored from
  `sr_img`, the set's sprites in list order, the front columns again through `sr_msk` where a back sprite was drawn
  (blocks of `sr_s1` and `sr_any`), the sprites after the front columns.
* A sprite is drawn whole with the Blitter from an unshifted image (`sr_cache`, 512 entries of 212 bytes,
  keyed by four tile keys, validated by a palette stamp). Its 16 rows are grouped by identical opacity masks,
  following `stefastbobs2`; offset pairs retain original destinations (a group's first row carries the mask, the
  others 0; the opaque rows' count is in the entry); contiguous plane rows let the Blitter advance its source
  automatically. The Blitter supplies the skew, so moving across any of the 16 shifts reuses the same cache entry.
  Block copies find their runs of groups with two byte tables (`sr_tz`, `sr_to`): one to three groups by the CPU,
  longer runs (up to 8 groups) in HOG passes of one line, at most 256 bus cycles.
* **Palette stamps** (2026-10-12): a change of a pen's slot starts a new palette epoch (`pal_epoch`) and records it for
  that pen and its bank (`pen_epoch`, `bank_epoch`).  A baked tile (`tcache`), a sprite image and a cell composite
  carry the epoch they were made under; a lookup with an older stamp checks only the pens its tiles use against
  `pen_epoch` (`get_tile`'s `.stamp`, `sr_valid`) and refreshes the stamp if none changed.  Nothing is walked at a
  palette change; the keys stay exact (tile, bank, flips); the epoch wrapping flushes everything (`pal_wrapped`).
* The virtual screen is 512 pixels wide (256 bytes per row). The 320-pixel hardware window starts at x=96,
  centring the 256-pixel game picture at x=128. The sprite renderer's Blitter path (`sr_draw1`) clips a sprite
  across the left or right picture edge (2026-10-12): the edges lie on 16-pixel groups, so the word outside gets an
  end mask of 0 (the Blitter leaves it untouched; a second loop, used only for such sprites, ANDs the row masks
  with $0000ffff or $ffff0000), and the 32-pixel visible side bands stay clean.  Top and bottom: whole sprites into
  the guard rows, restored before drawing.  The general renderer still draws whole sprites into all four guards.
  Each screen remembers which guards it was drawn into (`sr_guard_pages`: bits left, right, top, bottom); only
  those are cleared (the sprite renderer now sets only top and bottom).

Exact: `render_test.py seq 100 1500` (attract, coin, start, two rounds, a level transition) 1500 of 1500 frames,
`render_bench.py` 0 wrong pixels.  `render_test.py` also checks the margins and guard rows around the picture: every set
pixel there must lie in a sprite drawn now (no stale damage; it reports the stray pixels).  `render_bench.py ... --step 2` renders every second frame (the pace of 25 pictures a
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
    venv/bin/python tools/sprite_test.py             # whole sprites: all shifts, holes, guard edges, cache collisions
    venv/bin/python tools/sound_test.py              # the sound player against tools/sound.py's model
    tools/bench.sh 1500                              # Hatari: game rounds and pictures per 300 VBLs, border events
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

**Whole-object rule (updated 2026-10-11):** all ports draw partially visible sprites whole. The old
`rf_cleanup` eraser described in the 2026-10-09 experiments below has been removed. Bubble Bobble now uses
a 512-pixel virtual screen and restores previous guard damage before drawing the next picture. The visible
side bands are part of the hardware window, so whole sprites may appear there.  (2026-10-12: the sprite
renderer's Blitter path now clips at the left and right picture edges, see above.)
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

## Edge bands (2026-10-09 experiment, superseded 2026-10-11)

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


## Whole sprites and measurements (2026-10-11)

The renderer now uses the reordered sprite method, caches one unshifted image instead of sixteen positional
variants, and saves about 98 KiB of sprite-cache memory. The two straight-line sprite tile writers mark their
possible video RAM pages once per burst (`BYTEVMARKS=1` retains individual marks for comparison); generator
assertions reject branches or entries inside a burst. Colliding tile entries are copied with their full 72-byte spacing.

`profile.py 1500 --chunk 256 --window 600:900 900:1200 1200:1500`, same scripted inputs and sound player:

| VBL window | Before, pictures/s | After, pictures/s | Game rounds/VBL, after |
|---|---:|---:|---:|
| 600–899 | 3.2 | 4.7 | 0.63 |
| 900–1199 | 11.2 | 13.7 | 0.74 |
| 1200–1499 | 14.0 | 14.8 | 0.57 |

These are Musashi schedule estimates, including Blitter source reads, masked destination reads and writes;
they are not Hatari fps measurements. Steady 25+ fps is still unmet: translated logic and scene rebuilds need
further work. Older measurements above predate the corrected bus accounting.

Validation: 3,000 logic frames match; 1,500 consecutive render frames (100–1599) have zero wrong game pixels;
128 independent whole-sprite cases cover all skews, four borders, transparent holes, colliding tile-cache entries
and a 64 KB destination crossing. Alignment test: zero odd-access sites in 900 frames. The renderer makes
250,730 HOG passes in the sequential test, none longer than 256 bus cycles and none sharing the bus. A 4 MB
pinned Hatari debug build completed 2,500 game rounds, including coin/start gameplay, with no crash file;
`BORDERS.BIN` reports two startup fallbacks and zero late top/bottom events. Normal builds do not stop at that limit.

## Performance plan, implemented (2026-10-12)

`docs/performance-plan.md` (the investigation of 2026-10-11) in its order, each change measured and kept only with
the tests below passing.  Numbers: `profile.py 1500 --chunk 256 --window 600:900 900:1200 1200:1500` (Musashi, the real
VBL schedule; game rounds per VBL / pictures a second) and `tools/bench.sh 1500` (the pinned Hatari, a DEBUG + AUTOPLAY
build with the same input script by VBL).  The game's state in a window differs between the two (boot timing), and
between before and after (a faster renderer changes which pictures are drawn): compare within a column.

(The Hatari columns count only the VBLs the game was not still busy in: too high where it overran, see "Speed, measured
right (2026-10-12)".)

| VBL window | Musashi before | Musashi after | Hatari before | Hatari after |
|---|---|---|---|---|
| 600–899 (coin, start, round 1 intro) | 0.63 / 4.7 | 0.66 / 5.5 | 0.60 / 3.2 | 0.62 / 4.0 |
| 900–1199 (play) | 0.74 / 13.7 | 0.75 / **15.8** | 0.76 / 11.7 | 0.79 / **14.7** |
| 1200–1499 (play) | 0.57 / 14.8 | 0.56 / **17.3** | 0.86 / 17.5 | 0.94 / **25.0** |

A play picture (900–1199) costs ~285k renderer cycles, from ~330k (with the block copies counted as renderer: the
profile used to charge `sr_blocks_group` to the runtime).  The fixed-state bench (`render_bench.py 900 40 1200 40
--step 2 --prof`, means): 735,903 / 391,036 -> 681,616 / 362,382 cycles; its means are dominated by the map rebuilds
(~3.6 M cycles each).  25 pictures a second at the full game pace is **not** reached: the play's game work is ~93k
cycles a round (Musashi), so a picture would have to cost ~125k.

What was done, by the plan's steps:

1. **Palette stamps** instead of whole-bank generations and walks (see "Sprite renderer"): a pen slot change costs
   roughly 50k instead of ~225k cycles (profile estimate) (the 4,096-slot tile cache walk and the 3,584-slot map walk are gone), sprites are drawn
   again only when a pen their tiles use changed slot.
2. **Cell composite cache** (1,024 entries, exact keys, stamped, front opacity cached) and the first tile written
   without the clear and merge; `sr_key` decodes a key in half the instructions.  Not done: per-cell recipes (a cell
   drawn again because its tile entry changed must decode it anyway; the memory is not there) and the coherent
   scene-change generations (they move the cost of a transition, they do not remove it).  Found: the start and round
   screens cycle colours (bank 11's pens 0, 4, 7 through slots 1, 4, 8), so every step recomposes the same ~175 cells;
   a cache keyed by the bank's mapping (interned, exact) would hit there, at the cost of the per-pen precision.
3. **Object scan**: the object RAM writer marks were not added: the game copies its 90 sprite entries (`$04B6`, 360
   bytes from `$E1CD` to `$DD00`) every round, so a mark would flag every sprite every round, and a fused copy-and-compare
   costs more per byte than the misaligned byte copy.  Instead: a short loop for empty objects, the last object found
   with `dbne`.  Block copies: runs found by table (`sr_tz` / `sr_to`), 8% cheaper; the sprite draw loop 15% cheaper
   (mask only at a group's first row, the Blitter registers through an address register).  The guards: per screen and
   edge.  The video RAM diff: `dbne`, `tile_dirty` cleared only in the pages flagged before, the marks tested four at a
   time.
4. **Logic**: the MCU firmware reaches the bus routines from ~130 straight-line sites (no loops to replace natively);
   the translated `jsr $F1BF` / `$F1DB` now calls `mcu_bus_read` / `mcu_bus_write` directly (`m6801x.py`) and they take
   X's high byte from `$4A` instead of shifting.  The main CPU's time is a flat tail of small helpers (`$0D50`-`$0DBD`,
   `$147D`, `$26A4`-`$2772`, `$03FD`); the sub CPU's object loop (`$03CF`, up to 11k cycles a VBL in later rounds) keeps
   exact flags after every `bit` because a `push af` at its head makes them live (a liveness proof across the
   `pop af` would remove five instructions a test).  Sound: `bb_step` clears the tracks' flags at once and picks the
   channels inline: 13,863 -> 11,909 cycles a VBL (`sound_test.py`, 6,000 VBLs identical).

Measuring: `profile.py` prints, per window, renders started / completed / shown and per completed render the cells
composed, composite cache hits, palette-marked cells, pens invalidated, sprite lookups / bakes, visible / drawn
sprites, blocks copied / restored, map builds and palette changes (the `--sim` build's `sim_*` counters), and the
logic and logic + runtime cycles per game round; `--bucket NAME` lists one area's routines.  `render_bench.py`
attributes samples to code labels only.

Validation (all on the final build): `sprite_test.py` 128 cases exact; `render_test.py seq 100 1500` 1500 of 1500
frames exact, no stray pixels around the picture (the check finds 14 at frame 514 with the guard restore disabled);
`logic_test.py 700` 0 differences; `align_test.py 900` 0 sites; `mcu_test.py 2600` 0 mismatches; `sound_test.py` 0 of
6,000; `BLIT_STATS=256` over 300 frames: 28,117 HOG passes, the longest 256 bus cycles, none sharing the bus;
`tools/bench.sh 1500` in Hatari: no late border event, no pass in pieces, no crash file.  Memory: 3,931,904 bytes
(+4 KB: the epochs and the cells' bank masks).

Memory (2026-10-15): 3,942,912 -> 3,659,008 bytes, 393 KB left from the desktop (4,061,212 on a 4 MB STE with TOS
2.06; a tester's Mega STE with a hard disk driver and accessories had 3,831,554: TOS refused to start it).  What start
reads once lies under the tile cache: the CPU ROMs (`load_roms` copies them, 132 KB) and the dispatch entries (`gen.py`'s
`bb_entries_data`, 145 KB, read by `init_table`) are the last thing in the data section, from `tcache` on, and the rest
of the cache is the first thing in the BSS (`tcache_tail`; the data's end is aligned to the BSS's 256 so that the two
meet, which the start checks).  The tables are built right after `load_roms`, before `init_render`'s `tc_flush` marks
every cache entry empty.  The game runs unchanged.

## Native routines (2026-10-12)

`src/natives.s` holds hand-written 68000 routines that replace Z80 code (`tools/gen.py` `MAIN_NATIVES` /
`SUB_NATIVES`, the engine's `natives`, see docs/architecture.md; `BB_NO_NATIVES=1` builds the translation alone).
`tools/native_test.py` runs each against the translation it replaces (`y_near`: 3,000 random object tables, memory, IY,
the registers, S Z C; the dispatches: every combination of their tested bits, the handler reached, A, F, the CCR, the
Z80 stack); `logic_test.py` in `port.py test` now runs 2,000 frames, into the play where they run.

* `y_near`, the sub CPU's `$0849`-`$089B` (from the object loop `$03CF` through the jump table at `$0785`): for each of
  the `($E76B)` objects, is it near IX (same +29 excluded, |dx| < 13, dy 0..12): `+19` counts up.  The translation
  pays ~210 cycles an object (IY lives in memory, `add iy,de` keeps C for the `bit`s after it); native ~50: IY in an
  address register, IX+33's bits 4/5 tested once (the loop writes only +19 of objects 40 bytes apart), C of the last
  `add iy,de` is 0 (objects past `$FFFF` run the translation).
* `z_state` / `y_state`, the objects' state dispatch of the main CPU (`$5C37`-`$5C75`) and the sub CPU
  (`$03CF`-`$03F9`): after the loop counter's `push af`, the first set bit of a list of bits of (IX+33) and (IX+0)
  picks the handler.  Translated, each `bit` merges Z into F and each `jp nz` loads the CCR from it (~58 cycles a test,
  11 / 7 tests for an object with none set); native, an object with none set costs two tests, and F, A and the CCR
  are left as the translation leaves them.

`engine/xprof.py bublbobl --frames 300 --skip 900` (cycles a game frame): translated code 170.8k -> 115.8k (main CPU
108.6k -> 92.1k, sub CPU 54.5k -> 15.9k), the natives 16.0k (`y_near` 8.5k, `y_state` 3.8k, `z_state` 3.8k): 39k less of
the ~320k a game frame.  `tools/profile.py 2400` (Musashi, the real VBL schedule; game rounds per VBL / pictures a
second; the windows are VBLs, so after a faster window the game is further on):

| Frames | Before | `y_near` | All three |
|---|---|---|---|
| 900–1199 | 0.75 / 15.7 | 0.75 / 15.7 | 0.75 / 15.7 |
| 1200–1499 | 0.56 / 18.5 | 0.56 / 19.2 | **0.67** / 15.3 |
| 1500–1799 | 0.50 / 17.2 | 0.50 / 19.8 | **0.59** / 19.3 |
| 1800–2099 | 0.50 / 16.5 | 0.50 / 20.3 | **0.70** / 16.7 |
| 2100–2399 | 0.50 / 17.8 | 0.50 / 20.8 | **0.59** / 20.3 |

The scheduler puts the game's pace first: with `y_near` alone the saved time went to the pictures, with all three the
game runs 18-40% more rounds a VBL in these windows.  `tools/bench.sh 3000` (Hatari; rounds per VBL / pictures a
second, before -> after): VBLs 1200-1499 0.95 / 27.5 -> 0.95 / 34.0, 1500-1799 1.00 / 31.3 -> 1.00 / 40.3, 1800-2099
0.98 / 21.0 -> 1.00 / 34.2, 2100-2399 0.87 / 14.8 -> 1.00 / 29.7; later the faster build is in a heavier scene (2400-2999:
0.98 / 23.0 and 0.97 / 27.3 before, 0.89 / 14.0 and 0.82 / 11.2 after).  Next candidate: the object table copy `$04B6`
(`ldir`, 5k).

### The MCU (2026-10-12)

`src/mcu_native.s`: the MCU's VBL interrupt (`$F046`) as 68000 code, in place of the translated firmware
(`mcu_irq` calls `mcu_native`).  The firmware does its work in 20 routines that reach the Z80 side only through its
two bus routines; translated, each bus cycle is a dozen port writes the runtime emulates (`mcu_bus_read` /
`mcu_bus_write`, ~340 cycles a call, ~56 calls a game frame: 19k cycles, the firmware's own code 7.7k).  Native, a
bus read is a move from the shared RAM or the DIP switches / inputs and a write a move into it; what the ports keep
afterwards is set once at the end (the handler always ends with the read of `$0F96`).  The routines: the inputs and
DIP switches to `$0C1F-$0C23`, the coins and credits (the coinage table at `$F187`), the coin lockout, three counters
the Z80 asks to change (and the firmware's checks of their copies), two position scans against 7 objects (`$F48F`,
`$F585`), four sequences (the tables at `$F717`), a 16-bit countdown, three table lookups (`$F9B1`), the main CPU's
interrupt (P1 bit 6 low-high-low) and the reset request.  Not reproduced (nor by the translation): the stack push of
a counter check that fails (on the board the rts after it returns into nothing) and the delay loop of `$F089`.  The
ports' directions must be the init's (P1 `$F0`, P2 and P4 `$FF`); otherwise the translation runs.

Tests: `tools/native_test.py` runs it against the translated firmware with the runtime's bus routines (3,000 random
states in `port.py test`, 20,000 checked once, the request bytes biased to every path: the MCU's memory `$00-$EF`,
the shared RAM, `p1_out` / `p2_out` / `p3_in`, the main CPU's interrupt, a reset); `logic_test.py` (the game against
the Z80 / 6801 reference) 4,000 frames without a difference; `mcu_test.py` still checks the translation.

`engine/xprof.py bublbobl --frames 300 --skip 900` (the same game frames, inputs by game frame): the MCU 27k -> 3.9k
cycles a game frame; with the other three natives the 300 game frames take **398 VBLs instead of 601**.

Hatari: see "Speed, measured right (2026-10-12)" below (the numbers first given here counted only the VBLs the game
was not still busy in, and were about twice too high).

## Speed, measured right (2026-10-12)

`tools/bench.sh` counted VBLs with `frame_counter`, which a VBL that arrives while the game's interrupts of the last one
still run (`vbl_late`, counted in `cnt_late`) does not advance.  A play round costs more than a VBL in Hatari, so about
every other VBL was missing and the rates were about twice too high (all Hatari rates in this file before this section,
and the release text of 0.3: "67-80% of the arcade's speed and 15-27 frames a second").  COUNTERS.BIN now counts every
VBL.  `ROUNDS=1 tools/bench.sh 3600` (the same game in every build), rounds 1200-2700 (play):

| Build | Game rounds per VBL | Of the arcade's speed | Pictures a second |
|---|---|---|---|
| translated only (`BB_NO_NATIVES=1 BB_NO_INLINE=1`, one round a VBL) | 0.455 | 38% | 7.2 |
| natives, native MCU, leaf inlining, cheaper video RAM marks (one round a VBL, the default) | 0.532 | 45% | 12.2 |
| the same with `-D TICK60` (59.19 rounds a second as the arcade: six to five VBLs) | 0.668 | 56% | 5.2 |

Leaf inlining (`z80x` `Config.inline_leaves`, 16 here: a call of a short leaf function is emitted in place, no return
address, no dispatch) and the video RAM marks without the CCR save where the next instruction expects no flags in it
(`ccr_kept`): `engine/xprof.py bublbobl --frames 600 --skip 900`, the main CPU's translated code 92.5k -> 80.7k cycles
a game frame, the 600 game frames 909 -> 775 VBLs.  `logic_test.py` 4,000 frames identical after each step.

`-D TICK60`: a VBL adds one round due (every fifth two), at most `MAX_PENDING` (2) due, at most two run in a VBL; the
late VBLs count too.  The game's logic is the limit: a play round costs 85-160k cycles on Musashi (~1.35 times that in
Hatari) of the 160k a VBL has, so the extra rounds take the pictures' time.  It stays an option until a round is much
cheaper.

