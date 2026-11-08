# Rolling Thunder (Namco System 86, 1986) on the Atari STE

![Rolling Thunder on the STE (Hatari)](docs/screenshot.png)

MAME set `rthunder` (rev 3; `namco/namcos86.cpp`).  Two MC6809E (the main program and the sub program) are statically
translated to 68000 code (`engine/m6809x.py`) and run in lock step with a reference board; the HD63701 MCU, which keeps the
inputs, the coins and the credits and runs the sound engine, is a **native model of its mailbox** (checked against its
firmware); the CUS42 / CUS43 tilemaps scroll by the Shifter (video address, fine scroll, line width) over display buffers made
incrementally from the tile RAM, the sprites and the fixed layer (HUD, text) are drawn over them with HOP 2 / OP 3 Blitter
passes (`src/render.s`, `src/sprites.s`); 288 x 224 picture in a 320-pixel window, one fixed 16-colour palette.
Status: **Not playable** (see State): exact picture and logic in the tests, but about a third of the arcade's speed, a few
pictures a second, no sound, and the translation does not cover everything a long game runs.

## Build and run

```sh
python port.py cover rthunder              # coverage: ref/cover.py seeds 1-9 (random play) and 100 (the benchmark's play), --port
python port.py build rthunder              # -> run/rthunder/RTHUNDER.PRG
python port.py test rthunder               # lock-step (+ tile-row marks, MCU mailbox), the picture against the model, the MCU model
python games/rthunder/tools/prepare.py     # verify assets/roms/rthunder.zip, unpack to assets/roms/extracted/rthunder/
python games/rthunder/tools/build.py [--sim] [--debug] [--frames N] [--tag T] [-D AUTOPLAY=1]   # (--snap: the start state again)
python games/rthunder/tools/logic_test.py 3000 --seed 1 [--render] [--mcu] [--autoplay]
python games/rthunder/tools/render_test.py 3000 --seed 1 --every 20 --sprites          # the whole picture against tools/stemodel.py
python games/rthunder/tools/mcu_model.py 3000 --seed 2 [--random]                       # the mailbox model against the firmware
python games/rthunder/tools/perf_test.py 1190 --seed 1 --skip 1100 [--profile]          # 68000 cycles per routine on Musashi
python games/rthunder/tools/parts.py collect 3000 --seeds 1,2,3 ; parts.py build        # the sprite parts made at build time
powershell -File games/rthunder/tools/hatari.ps1 -Frames 3000 -Autoplay 1                # hidden Hatari: counters, SCREEN.BIN, RATE.BIN
python games/rthunder/tools/screen.py run/rthunder_hatari/SCREEN.BIN shot.png            # the shown picture as a PNG
MAME=.../wolfmame-0248/mame.exe python games/rthunder/ref/mame_cmp_rthunder.py [--logic] [frame ...]   # the reference against MAME
```

## Controls

| | Keyboard | Joystick / pad |
|---|---|---|
| Move | arrows (left / right; up / down: the upper floor, duck) | stick (port 1: player 1) |
| Fire (button 1) | Z, Space, Control | fire, pad A |
| Jump (button 2) | X, Alternate | pad B |
| Button 3 (unused by the game) | C | pad C |
| Player 2 | J / L left / right, I / K up / down, B fire, N jump | stick port 0, pad B |
| Coins / starts | 5 / 6 (coin 1 / 2), 1 / 2 (start 1 / 2) | pad Option / Pause |
| Service | F1 (service), F2 (service coin) | |

IN0 / IN1 / IN2 are the arcade's (active low); the MCU model turns them into the mailbox bytes the main CPU reads (below).
Left and right (up and down) pressed together count as neither: the game's loops run on when a stick reports both (found
by random-input runs: cpu2 never leaves `$CED8`).  Verified: that each of the 20 input bits reaches its mailbox byte
(`tools/mcu_model.py`, against the firmware); not verified: the keyboard / stick / pad path in Hatari (the AUTOPLAY build
injects the arcade bytes), nor player 2's game.  The DIP switches are fixed at the driver's defaults (`DSWA` = $FF, `DSWB` =
$D7: 3 lives, 1 coin 1 credit, no level select).

## State

2026-11-08 (this port was started, finished as far as it goes, and measured on that day).  What is checked and what is not:

| Stage | Result |
|---|---|
| ROMs | `tools/prepare.py` verifies `rthunder.zip` against `docs/rom_manifest.json` |
| Reference board | `tools/machine.py`: two MC6809E, the HD63701 with its real firmware, the CUS30 mailbox, MAME's scheduler, the tilemaps, the sprites, the palette PROMs.  Against WolfMAME 0.248 (`ref/mame_cmp_rthunder.py`): 0 differing pixels and pens at ten frames of the attract mode, the RAMs equal (`--logic`) except the stack area `$57E0-$57FF`.  MAME 0.286's source and the binary differ in the palette (integer-rounded resistor weights); the binary's are used |
| Two-CPU schedule | `RthunderRule`: both IRQs at the idle points, the CPU with `$1604 != $1605` first, a CPU gives way at a semaphore store, a taken spin branch and its idle point (the board's real concurrency is not reproduced: the programs also depend on timing; one flip in 12,000 attract frames) |
| Translation | 4689 + 6411 instructions, none unsupported; **lock-step identical to the reference for 3000 frames, seeds 0-5** (RAMs, registers, banks every frame); the benchmark's play (seed 100): see below |
| Picture | the painter's-order model (`tools/stemodel.py`, sprites by priority below the fixed layer) differs from the reference's per-pixel rule by 0-16 pixels in sampled frames; **the STE renderer equals that model: 0 pixels differ, every 20th frame of 3000 frames for seeds 1-5, and every frame of 760 frames of seed 1** (the 288 x 224 picture inside the 320 x 224 window) |
| MCU model | `tools/mcu_model.py` equals the firmware on every byte the main CPU reads: coverage seeds 2-5 0 differences in 3000 frames; random inputs 0-1 differences in 3000 frames (a held service coin; a start in a continue prompt); not checked: continue handling, service mode (it deadlocks the reference board) |
| STE program | boots from the reference's state at arcade frame 200 (`build/rthunder/snap.bin`: no boot code runs), runs in Hatari (STE, 4 MB, TOS 2.06) through the attract mode, a coin, the start and into the first area |
| Sound | **none** (the YM2151, the CUS30 wave voices and the 63701X PCM are not played; the commands the main CPU sends are kept: `snd_ring`).  What exists: the MCU model acknowledges commands and clears a finished jingle's byte at the firmware's time (`tools/cmdscan.py`: 9 of 254 commands end by themselves: $01 192 frames, $02 61, $03 110, $04 28, $05 508, $07 293, $0C 220, $11 28, $C3 248) |
| Registration | `port.py` (cover, test); left out of the release (`NOT_RELEASED`) |

**Not done / not verified (the long run in particular):** the translation covers what the coverage runs executed (seeds 1-9
random play, 6000 frames each; seed 100, the benchmark's play); a run that goes further finds code nobody has run
(`cpu_badpc`: the autoplay play reached such a place about 1,380 frames after the start, at 6809 pc `$6338` in a banked page
of the sub program: found by `logic_test.py --autoplay` and by Hatari, closed by coverage seed 100); no run of 20,000 VBLs
reaching later stages exists, no cheat or recorded play reaches the later areas, no sound, no speed near the targets.

## How it works

### The board and the reference

`tools/machine.py` (`Rthunder`): cpu1 (main: ROM `$8000`, banked ROM `$6000-$7FFF` (cus115 bank select at `$6800`), shared RAM
`$5800` / sprite RAM `$5000`, tile RAMs, CUS30 mailbox at `$4000`), cpu2 (sub: shared RAM at `$0000`, tile RAMs at `$2000-$5FFF`,
bank `$D803`), the HD63701 MCU.  The tile ROMs are shuffled by `init_namco86`; four tilemaps (CUS42 pair 0 and 1, CUS43 pair 0 and 1)
with priority in bits 9-11 of the X scroll; sprites (CUS39) latched at a write to sprite RAM offset `$7F2` at the vertical blank;
a 2048-colour PROM palette.  See the docstring there and MAME's `namcos86.cpp`.

### Translation, runtime and schedule

`tools/gen.py` -> `build/rthunder/code_*.s`, tables, hooks; `src/core.s`: the contexts, the dispatcher, the I/O (CUS30 mailbox, bank
selects, scroll / tile bank / back colour registers in `hwregs`), `port_frame` (the schedule as 68000 code).  Two things added to
the translator for this board: read-modify-write (`TST`, `INC`, `DEC`) at I/O sites, and **tile-row marks**: every store into tile
RAM leaves its 128-byte row in `tile_dirty` (computed from X, Y or U where the instruction names them; the layer flag
`tile_written` where it does not) so the renderer compares only those rows with its shadow (`ren_update`); `logic_test.py
--render` checks after every frame that the shadow equals the tile RAM (a store without its mark fails).

### The MCU

The firmware (4 KB internal + 32 KB program, ~25k MCU cycles a frame) is the mailbox to the CPUs; translating it would cost
more than the whole logic.  `tools/mcu_model.py` / `src/mcu.s`: every input has a pair of bytes (level = the input one frame
ago, pulse = two frames pressed, the second the first of them); a coin counts when its line was low two frames and rises;
credits, the coin counter and the two digits; a start takes the credit(s) while no start is taken; a sound command is
acknowledged with `$FF`, a jingle clears the byte after its length.  Found by single-bit and sequence experiments against the
firmware (`tools/mcuexp*.py`-style scripts, one-off), then checked on random inputs.

### Picture

* **Layers.**  The three scrolling layers move together (same scroll); `ren_cell` composes the 8 x 8 cell of the map (back colour +
  layers by priority, tiles made on first use: `tile_get`) into the clean buffer `ren_bg` (R-Type's layout: the map twice across
  and down with 64 pixel and 32 line margins, 68 x 8 lines of 544 bytes), `ren_sync` copies the cells that changed (a log) and
  those that scroll into the window to the display buffer to be shown (three of them); the Shifter scrolls by video address,
  fine scroll and line width (`vbl_video`).
* **Sprites and the fixed layer** (`src/sprites.s`): a part (a sprite's sub-rectangle with flips and colour row) is converted to row
  groups of identical opaque masks and planes in pass order (made at build time for every part the coverage's runs show:
  `tools/parts.py`, 702 parts, 256 KB; the rest on first use: `part_make`); one HOP 2 / OP 3 pass a row (X count c + 1, Y count 4,
  skew = the shift, NFSR, the end masks the shifted opaque mask), the source address runs on from row to row.  The fixed layer's cells
  are drawn as runs of up to four neighbours (`rpcache`).  The rectangles drawn are copied back from the clean buffer before the
  buffer is used again.  Order: the scrolling layers, the sprites of priority 0-6 (the lowest entry first), the fixed layer, the
  sprites of priority 7.
* **Colours:** one 16-colour palette fitted to frames of seeds 0-5 (`tools/palfit.py`, `engine/palette_quantize.py`); 154 of the 512
  indirect colours occur, 60-73 in a picture: a per-scene palette would look better.  Not done.
* The picture is 288 x 224 inside the window of 320 x 224 (16 pixels either side show the neighbouring map; the sprites are drawn
  whole into the margins); the top and bottom borders are open (`engine/rt/borders.s`).

## Speed

All figures 2026-11-08.  Musashi (`tools/perf_test.py`, translation + renderer, 68000 cycles; an STE frame is 160k, one
arcade frame 132k): logic 55-84k (both CPUs, a stage-1 stretch 84k), the MCU model 13k, a picture 300-350k (renderer 22-26k,
sprites + fixed layer 220-260k, Blitter 60k) in play-like frames with 8-12 sprites, ~1M with the 127-sprite title logo.
**Hatari** (STE, 4 MB, TOS 2.06, AUTOPLAY build, 3000 VBLs): 6001 VBLs of the AUTOPLAY script (coin, start, then moves and shots; 2026-11-08, with coverage seed 100): 3614 arcade frames = **30.1 a second (50% of 60.6)**, 930 pictures made = 7.7 a second, no crash; from VBL ~2100 to 6000 (the game running) 42 arcade frames a second (70%) and about 10.6 pictures a second.  Not yet run: the 20,000 VBLs the brief asks for.  The attract mode's 127-sprite logo screens are the slowest stretches (~1M cycles a picture)

Where a picture's time goes (the profile, a stage-1 stretch): sprite passes (`spr_blit`) 35%, the sprite list (`spr_build`, 127
entries every picture) 13%, the fixed layer 12% + 5%, the damage list and restore 8%, the tile marks and sync 10%.  What was tried
and kept (all exact): tile-row marks instead of whole-layer compares (ren_update 138k -> 22k), build-time parts (no conversion in
play), fixed-layer runs (-150k), the y-visibility table, a 2-way run cache.  What would still help: a per-row stream
interpreter for the sprites (R-Type ~107 cycles a row against ~200 here), the sprite list decoded while the latch is copied, the
fixed layer kept when the window and the layer did not change, drawing the HUD's text from an image of its own (BD_VSWITCH, but
the HUD is transparent over the map: that changes the picture, to be agreed), the translation's logic (84k).  **Nothing here
reaches the 90% / 20 pictures targets**: at 100% logic (~6M cycles a second) about 2M are left for pictures, 6 a second.

## Tests and tools

`tools/`: `prepare.py`, `machine.py` (the reference), `gen.py`, `build.py` (`--sim`, `--debug`, `--frames`, `--tag`), `logic_test.py`
(`--render`, `--mcu`, `--autoplay`, `--steplock F`, `--watch`), `render_test.py` (`--update`, `--sprites`, `--dump`), `mcu_model.py`,
`cmdscan.py`, `parts.py`, `assets.py`, `palfit.py`, `stemodel.py`, `perf_test.py`, `screen.py`, `hatari.ps1`; `ref/cover.py` (coverage),
`ref/mame_cmp_rthunder.py`.  Temporary files (logs, pickles of the experiments) go to `F:\claude\tmp\rthunder`.

## Lessons

* **Two CPUs that depend on timing.**  A cooperative schedule needs the rule found by search (cpu1 first iff `$1604 != $1605`) and
  semaphore yields; a cycle-counted interleave was worse.  A spin wait that writes the watchdog every pass must not count as progress.
* **A mailbox chip is smaller than its firmware.**  What the main CPU reads (about 40 bytes) follows from the inputs by simple
  rules (levels and pulses with one and two frames of delay, a debounce for coins); find them with single-bit experiments against the
  real firmware and check on random inputs.  Random inputs also found the game's own bug: opposite directions at once.
* **Writer marks must be exact and cheap**: a mark per stored row from the address register, a test that the shadow equals the tile
  RAM after every frame.
* **Parts made at run time cost 100k cycles each**: make the ones the coverage shows at build time (1700 conversions in 3000 frames
  of attract mode became zero), and give the run cache a good hash (a multiply-add over the full keys) and two ways.
* **Memory:** 4 MB is tight: the PRG is 1.9 MB with ROMs, tile pens (a byte a pixel), sprite ROM (a nibble) and the parts, 1.5 MB of
  buffers; the tile cache, the dynamic part cache and the damage lists were cut to fit.
* Hatari's Blitter is only run in the simulator when its trace mode is on (`render_test.py` switches it on around the sprite calls).
* Scripts must not shadow standard modules (`dis.py` broke numpy).

## Verification

* Reference against MAME: attract mode, 0 pixels (WolfMAME 0.248).
* Translation: lock-step 3000 frames, seeds 0-5; `--render` (marks) 3000 frames seeds 1, 2, 3, 5; `--mcu` 2600 frames seed 1.
* Picture: `render_test.py --sprites`, every 20th frame of 3000 for seeds 1-5, every frame of 760 for seed 1: 0 pixels differ from
  `tools/stemodel.py`; the model against the reference per-pixel rule: 0-16 pixels in sampled frames of seeds 1 and 3
  (sprites hidden under a higher-priority scrolling layer).
* MCU model: see State.
* Hatari: see Speed.  Nobody has listened to anything (there is no sound).
