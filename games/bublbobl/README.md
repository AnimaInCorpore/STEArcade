# Bubble Bobble, Atari STE

Third port; paths in this file are relative to `games/bublbobl/` (`src/` runtime and renderer, `tools/` reference machine,
translation, build and tests, `ref/` analysis scripts; generated files in `build/bublbobl/`).  Shared pieces:
`docs/architecture.md`; method: `docs/porting-guide.md`.

Started 2026-10-08.  The `bublbobl` set (Taito 1986, with the protection MCU): three Z80s (main, sub, sound) and
an MC6801 whose own firmware (`a78-01.17`) is in the set.  Built the way the Galaga port is: a reference machine,
a static translation of the programs, and a runtime around them.

## What runs

* **Main CPU** (6 MHz, 11.5k translated instructions, `tools/gen.py`): the 32 KB fixed ROM plus a window
  ($8000-$BFFF) onto four 16 KB banks.  Window code is translated per bank (virtual pc `$10000 + $4000 * bank +
  offset`), a jump from fixed code into the window goes through a stub that picks the bank's label, `ret` and
  `jp (hl)` through the dispatch table of the current bank (`a4` follows the bank register `$FB40`).  Reads of the
  window as data use `g_winbase` (the translator keeps A' BC' DE' HL' in a3 a0 a1 a2, so there is no address
  register left: the wrapper saves a0 around the instruction); the sites are those the coverage runs and
  `tools/window_audit.py` found.
* **Sub CPU** (1.4k instructions): the same shared RAM (`g_ram`), "long" memory model.
* **MCU** (`engine/m6801x.py`, 940 instructions): the firmware translated 6801 -> 68000, the self-test that
  can never pass on the board skipped (reset = `$F003`), the two bus routines (`$F1BF` read, `$F1DB` write)
  native in the runtime.  It reads the inputs and DIP switches, moves bytes to and from `$FC00-$FFFF` and
  raises the main CPU's interrupt (IM 2, the vector byte is in `$FC00`, the page in the I register).
* **Sound CPU**: not translated (no sound); its commands go nowhere.
* **Boot self-tests** are patched out of the ROMs (`machine.skip_tests`, also in the reference): the RAM
  tests, the delay loop, the sub CPU's ROM checksum.  The game checksums `$0001-$0EDC` of its ROM while it runs
  (one byte per frame, `$484B`); a dead byte of the old RAM test makes the sum the original's.  `tools/build.py`
  writes the patched ROM files next to the program.

Schedule (`src/bublbobl.s`): at every VBL the MCU's IRQ1 handler, then the main CPU's interrupt handler and the sub
CPU's, each to completion, then the frame is drawn behind them (the VBL nests into the renderer: the game
keeps its pace, the display drops frames).  The CPUs' foreground threads only boot to their idle loops (the
boot waits for the MCU's handshake at `$0158`: a hook gives the MCU and the sub CPU a turn).

## Renderer (`src/bb_render.s`)

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
* Double buffer: the screen being drawn also lacks the last frame's changes.  The cells of those that this frame
  does not draw are **copied from the screen shown** (`rf_copy`: one `movep.l` per line, ~500 cycles a cell
  against ~7000 to draw it): that screen holds the last frame complete, and nothing changed in them since.
* Game rows 16-239 at screen pixel 32, borders removed (277 lines, the picture centred).

## Reference captures, palette, ROM manifest

`docs/` (see `docs/README.md`): 64 MAME attract-mode frames with all 68 on-screen colours, the 16-colour Oklab palette
adopted from the JsOklabQuantizer default (`docs/palette16.json`, not yet checked against gameplay frames; it has no
green), the CRC manifest of the `bublbobl` (Japan) and `bublboblr` (US / Romstar) sets, and hardware notes with
evidence grades.  The scripts that produce them are in `ref/`: `mame_attract_collage.py`, `quantize_collage.py`
(+ `oklab_quantize.mjs`), `palette16.py`, `rom_manifest.py`.  The port itself is built on the `bublbobl` set; the US set
differs only in the two main-CPU ROMs and has not been run through the translator.

## Tests

Paths relative to `games/bublbobl/`; from the repository root `python port.py test bublbobl` runs the sequence below.

    python port.py build bublbobl --sim              # run/bublbobl_sim, with the hooks the tests use
    python port.py build bublbobl                    # run/bublbobl/BUBBLE.PRG (+ the patched ROM files)
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

Next, in order: the steady cost of the play, i.e. the per-cell work (the aligned tile: ~300 cycles of set-up before
its first row, `get_tile`'s hash, the clearing of a cell an opaque tile overwrites anyway, `rf_redraw`'s object loop),
fewer dirty cells (an object marks all its tiles, old and new), table driven `obj_slots`; the scene change (draw the
tiles of the banks that changed over several frames, or fade through the old colours); the video RAM diff (4%, a write
barrier would remove it; 106 store sites) and the shifted tiles (77 a frame, 2.7k cycles each: **not** the main cost as
the earlier estimate had it, so the Blitter is not the first thing to try); cheaper translated code (the Z80 handler
is 40-70% of the logic, the `ld a,r` / `ex af,af'` / `exx` register shuffles are in the hot paths).
Open: `logic_test.py 1500` differs in one byte (`$E0A8`) from frame 923 on this checkout, with or without the renderer
changes (so not a renderer matter; 700 frames pass); the coverage run of seed 4 stops at frame ~18000 with
`handler of 01ED did not return` in the reference machine (`ref/cover.py 4 20000`), so five seeds were used.
Not done: sound, the 16 sprites per line limit, screen flip (`$FB40` bit 7), test / service modes, a keyboard
check of coin / start in Hatari (the scancodes: `5` coin 1, `1` start 1, `6` coin 2, `2` start 2, arrows, space
= jump, alt = bubble), per-band palettes (22-26 distinct colours on a screen, the STE shows 16: the 15 most used
per bank weight are kept, the rest map to the nearest).
