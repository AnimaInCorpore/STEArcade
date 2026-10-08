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
  that leaves the mapping alone only rewrites the STE palette.
* Tiles are baked per (code, bank, flips) into planar rows + inverted mask (`tcache`); an aligned tile is one
  `movep.l` per row, a shifted one is merged into two cells.
* Dirty cells (8 x 8): an object that changed marks the cells of its old and its new tiles, a tile entry that
  changed (diff of the video RAM against a copy) its cells; the screen being drawn also lacks the last frame's
  changes (double buffer); a shifted tile that touches a dirty cell makes all its cells dirty; the dirty cells
  are cleared and every object's tiles on them are drawn in list order.  Exact: the result is the reference's
  bitmap through the colour table.
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
    python port.py run bublbobl shot@20              # Hatari (F030Arcade), screenshots
    python port.py run bublbobl key:5@20 key:1@26 shot@60   # ... with keys (5 = coin, 1 = start)
    python port.py run bublbobl dump:0xADDR:0xSIZE@50       # ... and memory dumps (savebin)

Reference: `tools/machine.py` (three Z80s + the 6801 running its ROM, 30 frames/s; `run_frame_port` is the
runtime's schedule, identical RAM).  Coverage for the translator: `ref/cover.py <seed> <frames>` (`port.py cover bublbobl`).

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

Next, in order: a write barrier instead of the video RAM diff (83k a frame; 106 store sites), the shifted
tiles (2.7k cycles each: bake the sprites as composites or use the Blitter as the other ports do (halftone/endmask merge of a baked tile, `docs/architecture.md`)), table driven
`obj_slots`, skipping the rows of the big strips without a dirty cell, cheaper translated code (the Z80 handler
is 40-70% of the logic, the `ld a,r` / `ex af,af'` / `exx` register shuffles are in the hot paths).
Not done: sound, the 16 sprites per line limit, screen flip (`$FB40` bit 7), test / service modes, a keyboard
check of coin / start in Hatari (the scancodes: `5` coin 1, `1` start 1, `6` coin 2, `2` start 2, arrows, space
= jump, alt = bubble), per-band palettes (22-26 distinct colours on a screen, the STE shows 16: the 15 most used
per bank weight are kept, the rest map to the nearest).
