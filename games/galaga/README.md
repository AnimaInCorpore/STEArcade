# Galaga, Atari STE

![Galaga on the STE (Hatari)](docs/screenshot.png)

Second port (started 2026-10-08), the first with several CPUs: three Z80s translated into one 68000 program, the
Blitter sprite renderer of Donkey Kong extended to double-size sprites and a starfield.  Paths in this file are
relative to `games/galaga/`; the shared pieces are described in `docs/architecture.md` and the method in
`docs/porting-guide.md`.

* `src/` the runtime and renderer (`galaga.s`, `render.s`, `sprites.s`, `stars.s`)
* `tools/` `machine.py` (reference machine), `gen.py` (translation), `assets.py` (graphics), `build.py`
* `ref/` coverage (`cover.py`) and the MAME comparison, one-off probes in `ref/probes/`; the coverage pickles go to `build/galaga/`

Build and run from the repository root: `python port.py build galaga`, `python port.py run galaga shot@30`.

Controls: **5** coin, **1/2** start, **left/right** move, **Space/Ctrl/Alt** fire, **Esc** quits.  Players take turns:
both joysticks and both pads move the fighter.
Jaguar pad / PowerPad (STE enhanced ports, `docs/architecture.md` "Input"): either pad, the D-pad moves, **A / B / C** fire, **Option** coin, **Pause** start, keypad **1/2** start, **5** coin, **\*** + **#** quit.

State: the attract mode runs at the game's
full speed (frame counter = VBL counter, no skipped interrupts) with everything drawn
(tiles, the formation, explosions, the starfield, the high score table); the display
drops frames: 25-28 fps in the title phases, 8-15 fps with the full formation.  Build
`python port.py build galaga [--debug] [--full-selftest]` -> `run/galaga/GALAGA.PRG` (needs the six ROM
files of the `galaga` set extracted to `assets/roms/extracted/galaga/`).  The main CPU's boot
RAM test (about 600 of the 850 frames to the attract mode) is patched out of the translation
(`machine.skip_ram_test`, the bank checksum byte compensates; `--full-selftest` keeps it).
`python port.py run galaga shot@30` (`tools/hatari.sh`) runs the port in the F030Arcade Hatari and grabs
screenshots at the given times (`/tmp/hrun`); the display starts at buffer line `CROP_TOP` = 24.

Reference: `tools/machine.py` models the arcade from MAME's galaga.cpp: three Z80s at
3.072 MHz with the shared map (ROM per CPU at 0-3FFF, switches/latches/06XX at 6800-7100,
RAM 8000-9BFF with the sprite table at the end of each 1 KB, video latch A000), IRQ to
CPU1/CPU2 at the vertical blank when enabled, NMI to CPU3 at lines 64 and 192, the 06XX's
NMI clock to CPU1 during transfers, the 51XX simulated the way old MAME did (coins,
credits, start buttons, joysticks with the fire edge; the MCU ROM is not in the set), the
05XX starfield (LFSR period walked once per frame), the renderer (tiles 36x28 through
tilemap_scan, 64 sprites with the double sizes, stars under them, characters over them,
rotated 90).  It boots to the attract mode in 1500 frames at ~45 frames/s; coin, start and
play work (`ref/probes/galaga1.py`).  Probes: `ref/probes/galaga2.py` (the sound CPU can be stopped
after its boot: screens identical over 2400 frames; it only posts its test result $9101
and clears $9A00-$9AFF), `ref/probes/galaga3.py` (sprites changed per frame mean 4.9, 90% 13,
tiles 1.5; every I/O access is a static address except the NMI handler's `ldi` through
hl' and the video latch through hl), `ref/probes/galaga4.py` (13 colours plus black are drawn,
so the STE palette has two entries for the stars), `tools/schedule_test.py` (the port's schedule,
below, against the interleaved reference: same game, stars one scroll step apart, up to about frame 2000; once the
scripted player shoots the two drift into different games: frame 2500 scores 1110 / 1030),
`ref/cover.py` (coverage pickles for the translation, `build/galaga/`).

Schedule of the port (`run_frame_port` in tools/machine.py is the model): the main CPU's program
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
  before trusting `tools/machine.py` or the renderer.
- Hatari: use the F030Arcade build (`tools/hatari.sh galaga shot@N`: runs the port,
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
- Sprite path (2026-10-09, Hatari's profiler, VBL 3500-3800, the formation): 242.7k -> 208.0k cycles a render, 81 ->
  93 renders in the 300 VBLs.  entry_loop calls draw_part only for the parts the size flags give (`part_masks`) and
  copies the entry only into the records it draws (phase A has already taken the rectangles of a changed entry);
  draw_part takes the part's graphics offset, flip y and offsets from `ga_part_tab` (assets.py) instead of the bit
  arithmetic.  Checked with `-D FREEZEAT=N -D NOSTARS=1` (from VBL N the game's interrupts stop, the renderer goes
  on): both screens against `render_raw()` of the frozen arcade RAM, 0 pixels at N = 2200 and 3600.  N = 5200 (the
  boss row over "HIGH SCORE") differs by 60-120 pixels before and after the change.
- Frame rate without the FIFO (Windows): `python port.py build galaga --debug -D RATE=500 --frames 9000
  --out <dir>/GALAGA.PRG`, Hatari `--fast-forward true --run-vbls 9600`: `cnt_vbl` and `cnt_render` (words) every
  500 VBLs in `RATE.BIN`, written at the quit; renders per VBL * 50 = fps.  Measured 2026-10-09 (attract mode and
  demo, 10 s steps): 13.4-15.2 fps with the formation, up to 50 in the title phases, 27.2 from 20 s on; the build
  before the translator speed-up 10.2-13.7 / 49 / 24.5 (the phases fall differently in the two runs).
- Frame rate (VBLs vs renders from the debug counters, 10 s steps from 20 s, the attract
  mode with its demo play): with the starfield 25 fps in the title phases and 7-14 fps with
  the formation (14.3 average); `-D NOSTARS=1` (no erase_stars/draw_stars): 48-49 fps in the
  title phases, 9-22 with the formation (23.8 average).  So the stars cost half of a light
  frame but the heavy phases are bound by the sprites and the translated code (the game's
  two IRQ handlers take ~63% of every VBL, the renderer gets the rest).
- Render throttle (`src/stars.s`, `-D NOTHROTTLE=1` switches it off): every render is
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

## Translator speed (2026-10-08)

CPU1 `z80x.FAST`, CPU2 / CPU3 `z80x.FAST_LONG`; `g_ctrl06` reads DE' from the upper word of d2 (it read a1).  The
clears (`ld (hl),n; ldir` over $37F bytes) are long fills now, the cost of the half registers (`ld d,(hl)` 48 -> 34
cycles, `ld a,c` 30 -> 16) and of `adc` / `rl` (the carry into X without a branch) went down.  `engine/xprof.py galaga`
(game frames 800-1200, attract): translated code 47.6k -> 27.6k cycles a game frame (1.73x).  There is no lock-step test
of Galaga's translated code against the reference (`tools/schedule_test.py` checks the reference only); the change was checked
with `engine/xdiff.py galaga <the old build>`: the arcade's RAM is the same at all 400 game frames (interrupts on a
clock of translated instructions, so a faster build is not ahead in the foreground).

## Renderer experiments (2026-10-09)

Stars are now erased before any screen updates and plotted after `chars_over`.
Every recorded star therefore owns its pixel until the next erase, avoiding the
four-plane colour reconstruction on erasure. All existing star colours are retained.

`-D CACHESPRITES=1` enables prepared sprite records (12 KB extra RAM across both
buffers). Unchanged damaged parts reuse their coordinates, source and routine
pointers; changed parts rebuild the record. It is disabled by default: despite
saving 23.0% in a forced-repaint workload, the moving formation does not benefit
enough to pay for preparing the records.

Measured against the working checkout before these experiments, including its
existing border changes: 9000 VBLs in cycle-exact 8 MHz STE Hatari, RATE=500,
4 MB, default star throttle, attract mode. The VBL 3000-5500 windows were:

| Variant | fps in successive 500-VBL windows |
|---|---|
| Before | 15.9, 15.1, 15.4, 17.0, 15.4 |
| Star erase only (default) | 15.6, 15.0, 15.4, 17.0, 15.4 |
| Stars + prepared sprites | 15.3, 15.0, 15.5, 16.8, 15.3 |

There is no material frame-rate gain in the heavy formation, and **25 fps is not
achieved**. Stars are already throttled in expensive scenes. A larger reduction
in formation drawing or translated game logic is needed; these results do not
support enabling the sprite cache by default.

Validation: 48 complete sprite comparisons with random shapes/colours/flips and
64 KB crossings passed. The added `tools/render_opt_test.py BEFORE_DIR AFTER_DIR`
compares 48 complete double-buffered frames with stars, character changes and
partially moving sprites, plus 48 forced-repaint frames. All screen bytes match.
Simulator CPU+bus cycles for complete frames: 39,962,194 before,
39,536,218 star erase only (-1.1%), 38,114,802 with caching (-4.6%). Forced
repaints: 18,009,742 before, 13,860,192 cached (-23.0%). These synthetic workloads
exercise correctness and individual costs; they are not gameplay fps estimates.

Reproduce Windows timing with `tools/bench.ps1` (relative to this game directory),
or `tools/bench.ps1 -Name galaga_cache_bench -Extra '-D','CACHESPRITES=1'`.
Each output directory contains `GALAGA.PRG`, `galaga.map`, and `RATE.BIN`;
pass the before/after directories to the renderer comparison script.

## Renderer speed (2026-10-09, later)

Measured on a fixed workload: the `--sim` build under `engine/xdiff.py`'s schedule (interrupts on a clock of
translated instructions, so every build is in the same game state and draws the same renders), the Blitter's cycles
included, game frames 3200-3400 (86 renders): 137.4k -> 111.7k cycles a render (-19%).  The steps:

* `blit_go_lines` (engine/rt/borders.s): the restores pass the lines a piece (32 / their 4 or 8 words), no `divu`.
* `entry_loop` keeps its state in registers (saved around `draw_part` only) and draws a one-part changed entry
  without walking the other three records.
* `draw_part`: the colour data from `ga_spr_vdata` (assets.py: per shape v * variant + first line * 8, no `mulu`),
  the cell marks of both bitmaps from one register (the record's row masks are the row mask or 0).
* `spr_entries` hold the arcade's byte order (code, colour, y, x low): no `ror` in the gather.
* The video RAM is compared per block of 32 bytes its writers mark (as 1943's character RAM): `ref/cover.py` records
  the instructions that write $8000-$87FF (71, all on the main CPU), `gen.py`'s Emitter marks the block of a store's
  address, a block instruction's blocks from DE before to DE after (`vblock_range`), `push` / `call` all of it;
  `scan_cells` compares the marked blocks and 128 bytes a render in case a writer is missing (DEBUG: `scan_missed`).
  The game rewrites its credit text every frame with the same bytes, so a single "written" flag would scan the
  whole RAM every render: 19.4k -> 7.6k cycles a render.  Checked: no unmarked block changed in 3594 scans (6000 game
  frames), `xdiff` against the build before: the same memory at all 4000 game frames.

Pictures: `render_opt_test.py` (identical bytes), and both screens of `-D FREEZEAT=N -D NOSTARS=1` sim builds,
before and after, byte-identical at N = 2200 and 3600 (the README's reference points).  Hatari (RATE=500, 9000
VBLs, attract mode; the phases fall differently in the two runs): 28.7 -> 35.6 frames a second on average, the
heaviest 500-VBL windows 15.0-15.6 -> 19.5-20.9.  Musashi does not fault on odd word accesses: two bss words of
this change were odd and only Hatari showed it (address errors), so run a Hatari build after a bss change.
