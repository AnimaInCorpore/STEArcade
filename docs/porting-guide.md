# Porting guide

How a game goes from a ROM set to a running STE port, and what the first three ports taught.  The architecture
is in `architecture.md`; `port.py` runs every step (`port.py cover|build|test|run|mame <game>`).

## Steps

1. **Read the MAME driver** (`F030Arcade/third_party/jsm68kdisassembler/third_party/mame`, see PORTING there; the
   installed `mame` binary is newer than that source, so it is the truth for colours): memory map, interrupts,
   video RAM layout, sprite format, palette PROMs, helper chips.  Chips with their own program (Bubble Bobble's
   MC6801, Galaga's 51xx/54xx) are either run (translated, preferred when the ROM is in the set: "run the device,
   don't replay its answers") or simulated at the register interface.
2. **Reference machine** (`games/<game>/tools/machine.py`): CPUs, memory map, interrupts, renderer (`render_raw`).
   Keep a `run_frame_port` that follows the runtime's schedule.  Boot self-tests are skipped with patches
   (`skip_tests`) that keep any running checksum intact.
3. **Check the reference against MAME** before building graphics (next section).
4. **Coverage** (`ref/cover*.py`, random input, several seeds; `port.py cover <game>`): the program counters seen executing,
   the I/O and banked-window sites.  Discovery adds jump tables (`rst $28` tables, `ld hl,T ... jp (hl)`) and
   what static recursive descent finds; anything coverage found but discovery missed is a hook or a table.
5. **Translate** (`tools/gen.py` of the game, config in `engine/z80x.py`): memory model, hooks for I/O writes and
   yields, window/bank handling for banked ROMs.  `port.py test <game>`: lock-step against the reference (RAM every frame).
6. **Runtime** (`src/<game>.s`): loader, dispatch tables, VBL schedule, input, border removal, hooks.
7. **Renderer**: exact against the reference bitmap through the colour table first (`render_test.py` style:
   copy the reference RAM in, call `render_frame`, compare pixels), fast second.
8. **Hatari** (`tools/hatari.sh`, F030Arcade build): look at the screen, then compare frame counters/skips from the `--debug` build.
   Looking found most bugs that the tests did not (wrong colours, missing sprites, bus errors on odd accesses).

## Lessons

* **Musashi is not a 68000 for faults and timing**: it executes odd word accesses silently (Hatari takes an address
  error) and has no MFP timers or border removal.  Test for odd accesses (`games/bublbobl/tools/align_test.py`) and
  build the simulator variant with `-DSIM`.  Crashes that appear only in Hatari have been: stack overflow by nested
  VBLs, window-read sites coverage missed, odd word loads in translated MCU code.
* **Self-tests flood the renderer** (video RAM test) and run ~700 frames: skip them in the reference and the
  translation, compensate any ROM checksum the game runs later, load the patched ROM files in the runtime.
* **Palette**: 16 STE colours against 22-26 on screen.  Keep the colours in order of appearance while they fit;
  otherwise the background, "volatile" entries (changed >= 4 times: flashing, they own a slot), and the heaviest by
  weight capped per bank.  Re-mapping must only rewrite the STE palette when the mapping is unchanged.
* **Throttle the logic when it cannot keep up** so the renderer still runs; never let a pending VBL nest.
* **Reference renderers can be wrong in ways "port equals reference" cannot see** (plane order, palette weights,
  a sprite row off by one): the MAME check below is not optional.
* **Verify claims about other work by running it**: a summary that says a renderer is a stub may be stale.
* Script names in `ref/` and `tools/` must not shadow the standard library (`dis.py` broke `import inspect` inside numpy).
* Branch-out-of-range and `lea` displacement warnings in vasm are normal at this size; real errors stop the build.

## Checking a reference against MAME (applies to every port)

"The port equals the reference renderer" only means something if the reference equals the arcade.
Compare the reference with MAME's own screenshot, pixel by pixel, before trusting it.  Donkey Kong's
reference had two errors that this found on 2026-10-08, neither visible in a Hatari-vs-reference test:

* **Sprites were one raw row off**: `top = 246 - y`, MAME's `draw_sprites` gives `247 - y` (its
  line buffer fetches the sprite one scanline ahead, hence the `+ 1` in `y + add_y + 1 + scanline`).
  Fixed in `games/dkong/tools/machine.py` and `games/dkong/src/sprites.s` (`u0 = y - 23`).  Every sprite was one pixel shifted
  along the arcade's raw Y axis.  Positions derived from the MAME source need a snapshot to confirm
  them (here the derivation and the snapshot agree: 0 pixels differ with 247, about 900 with 246).
* **The palette was wrong** (up to 75 levels per channel, e.g. skin 255,184,85 vs 245,188,160, blue
  0,0,170 vs 4,2,220): the Galaxian style weights 0x21/0x47/0x97 and 0x55/0xAA are not what current
  MAME computes.  Its colours come from resistor network models (`compute_res_net`: darlington stages,
  tri-state black) and are not a per channel sum of weighted PROM bits, so take the numbers from MAME
  itself: `games/dkong/tools/dkong_pens.py` is a dump of `pen_color()` for the 256 pens.  Do the same for any
  game whose reference computes colours from PROM weights; Galaga and Bubble Bobble should be checked.

How (`engine/mame_dump.lua`, `games/dkong/ref/mame_cmp_dkong.py`; MAME is `/opt/homebrew/bin/mame`, 0.289, the ROM zips
are in `assets/roms`): start MAME with **`-window`** (with `-video none` there is no snapshot), run a Lua
script at frame N that writes the pens (`palette:pen_color(i)`), a memory range and `video:snapshot()`, render
the same memory with the reference and count differing pixels.  `venv/bin/python games/dkong/ref/mame_cmp_dkong.py 700 1500 2500 4000`
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

#### Frames from an old MAME without Lua snapshots (F030Arcade `wolfmame-0162`, Windows)

`F030Arcade/third_party/wolfmame-0162/mame.exe` knows Bubble Bobble (`bublbobl` Japan Ver 0.1, `bublboblr` US Ver 5.1;
`-rompath assets/roms -verifyroms bublboblr` passes with the zips as shipped); the sibling `wolfmame-0184` build does
not.  Its Lua is the old API, so `engine/mame_dump.lua` and the `mame_cmp_*` scripts (written for 0.289) do not run on it:
the only per-frame hook is `emu.sethook(fn, "frame")`, `screen:frame_number()` and `manager:machine():exit()` exist,
`register_frame*` and `video:snapshot()` do not.  What works is MAME's own recording:

* `-aviwrite name.avi` writes **uncompressed RGB24 at the native size** (Bubble Bobble 256 x 224; the container says
  60 fps whatever the board runs at), so the pixels are exactly what MAME draws.  The file lands in MAME's `snap/`.
* The AVI writer is 32-bit: record ~300 s segments (3.1 GB each for 256 x 224) and chain them with `-autosave`;
  `-seconds_to_run` is the **cumulative** emulated time, so segment k uses `(k+1) * 300`.  `-sound none -nothrottle
  -frameskip 0 -skip_gameinfo -window`; about 25 s of wall clock per segment.
* Read the frames with `ffmpeg -i x.avi -an -f rawvideo -pix_fmt rgb24 -` (`-fps_mode passthrough`; newer ffmpeg
  has no `-vsync`), counting colours per frame as packed RGB: that is exact, no sampling.
* Run MAME from a scratch directory (it writes `cfg/`, `nvram/`, `snap/`, `sta/`), and **check the recording for stray
  input**: a key reaching the window registered a coin 27 s into the fifth segment of the Bubble Bobble run (the screens
  then read `CREDIT 1` / `PUSH ONLY 1 PLAYER BUTTON`); frames from there on were dropped.
* Example, `games/bublbobl/ref/mame_attract_collage.py`: 20 minutes of attract mode, 68 distinct colours, a 64 frame
  collage that contains every one of them.  The attract loop does not repeat exactly (the demo levels change per loop),
  so "all colours" means all colours seen, with the last new one at 12.3 minutes.

Colour budget for a 16 colour target: take that colour count, then reduce with the JsOklabQuantizer strategy
(`C:\Arbeit\jsoklabquantizer`, shared palette in Oklab, lightness ladder + k-means on a/b;
`games/bublbobl/ref/quantize_collage.py`).  Look at the worst-mapped colours before accepting a palette: Bubble Bobble's
default result has no green (Bub's `#00bb00` maps to a teal).

Results, 2026-10-08 (all with 0 differing pixels now, `games/dkong/ref/mame_cmp_dkong.py`, `games/galaga/ref/mame_cmp_galaga.py`,
`games/bublbobl/ref/mame_cmp_bublbobl.py`):

* **Donkey Kong**: sprite position and palette, see above.
* **Galaga** (found by the check): (1) `decode_gfx` made the first plane the *least* significant bit, MAME the
  most significant one: pixel values 1 and 2 of every character and sprite were swapped (the enemies were orange
  instead of teal, the ship blue instead of red, the NAMCO logo white instead of red); text only looked right because
  most character colour tables are symmetric in pens 1 and 2.  (2) Blue was 0x47/0x97 (maximum 222), MAME 0x51/0xAE
  (maximum 255; the star palette's blue likewise 0, 0x51, 0xAE, 0xFF).  Both are in `games/galaga/tools/machine.py`, so
  `games/galaga/tools/assets.py` (the STE graphics and palette) picks them up on the next `python port.py build galaga`.  The
  starfield is not verified (MAME's starfield was off in the frozen frames).  MAME can not run Galaga from the ROM set:
  the Namco 51xx/54xx MCU ROMs are missing, a blank 1 KB stand-in (`namco51.zip`, `namco54.zip`, wrong checksum,
  MAME warns and runs) ends in the test screen, so `engine/mame_dump.lua` with `INJECT=` writes the reference's RAM
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
