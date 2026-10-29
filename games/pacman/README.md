# Pac-Man, Atari STE

Port started 2026-10-29.  Set: MAME `pacman`, Pac-Man (Midway), 1980; one Z80, the closest existing port is Galaga
(same Namco tile and sprite hardware, same WSG sound chip).  Paths in this file are relative to `games/pacman/`; the
method is `docs/porting-guide.md`.

State (2026-10-29): the reference machine's picture equals MAME's frame for frame; the Z80 program is translated and
runs on the 68000 in lock-step with the reference (every frame exact, every seed); the picture is drawn (equal to the
reference in every checked frame, 274 of the 288 lines shown) and runs at full speed in Hatari, in the attract mode and
in play; the sound plays the WSG's three voices on the YM2149.  No pads; not in `port.py`'s list.

* `src/pacman.s` the runtime (schedule, IRQ delivery, borders, inputs, crash dump); `src/render.s` the picture
* `tools/prepare.py` the ROMs; `tools/machine.py` the reference machine (`Pacman`) and the port's schedule
  (`PacmanPort`); `tools/gen.py` the translation; `tools/assets.py` the graphics; `tools/sound.py` the sound model;
  `tools/build.py`; `tools/logic_test.py` the lock-step test, `tools/render_test.py` the picture,
  `tools/sprite_test.py` the sprites at the edges, `tools/sound_test.py` the sound; `tools/hatari.ps1` a hidden Hatari
  run (AVI with sound, counters; `-Extra -DAUTOPLAY=1`: a coin, start and play from the VBL)
* `ref/cover.py` coverage; `ref/mame_cmp_pacman.py` the reference against MAME's picture

From the repository root: `python games/pacman/tools/prepare.py`, coverage
`python games/pacman/ref/cover.py <seed> 20000` for seeds 1-12 (`build/pacman/cover<seed>.pkl`, needed by the
translation and the sprite code), `python games/pacman/tools/build.py --sim` (`run/pacman_sim/PACMAN.PRG`), then
`python games/pacman/tools/logic_test.py 12000 --seed <n>`, `render_test.py 3000 --seed <n> --every 3`,
`sprite_test.py`, `sound_test.py 4000`.  `build.py` without `--sim` builds `run/pacman/PACMAN.PRG`.  Controls: arrows or joystick move,
**5** / **6** coin, **1** / **2** start, **Esc** quits.

## ROMs

`python games/pacman/tools/prepare.py` verifies the ten files against `docs/rom_manifest.json` and writes them with
MAME's names to `assets/roms/extracted/pacman/` and `build/pacman/mame_roms/pacman/` (MAME's `-rompath`).  The archive
is `assets/roms/puckman.zip`, MAME's merged Puck Man set: the Midway set's files are in three clone folders
(`pacman/`, `newpuckx/pacman.6f`, `hangly/pacman.5e`, `hangly/pacman.5f`) and the parent's PROMs (`pm1-1.7f` =
`82s123.7f`, ...).  The manifest's `member` names each one's path; `engine/roms.extract` reads it (added for this set).

## Reference machine

`tools/machine.py` (`Pacman`), from MAME's `pacman/pacman.cpp` and `pacman_v.cpp`:

* Z80 at 3.072 MHz, 192 cycles a line, 264 lines, 50688 cycles a frame (60.606 Hz).
* ROM 0000-3FFF; video RAM 4000, colour RAM 4400, RAM 4C00-4FEF, sprite RAM 4FF0 (code/flip, colour) and 5060 (y, x;
  write only); A15 is not decoded, A13 is ignored above $4000.  Latch 5000-5007 (IRQ enable, sound enable, flip, coin
  counter), WSG registers 5040-505F (kept in `.sound`), watchdog 50C0; inputs IN0 5000, IN1 5040, DSW1 5080 (default
  $C9: 1 coin 1 credit, 3 lives, bonus 10000), DSW2 50C0 ($00).  4800-4BFF reads $BF.
* IM 2: the vector is the byte last written to I/O port $00.  The boot writes $FA ($3FFA -> $3000, the RAM/ROM test
  with its grid), the game $FC ($3FFC -> $008D, the frame handler).  The IRQ is a level from the vertical blank (line
  224), held until the program writes latch bit 0 = 0.
* A frame starts at the vertical blank (`frame_line=224`, MAME's phase): `render_raw` after `run_frame` is the picture
  MAME draws at that frame's end.  Starting frames at line 0 left about one frame in ten of the demo different from
  MAME: the foreground task writes the screen between line 0 and the blank.
* The boot reaches the game's vector at frame 250; there is no long RAM test to skip (Galaga's was 600 frames).
* The foreground is a task queue: the program spins at `$238D` (`ld hl,($4C82); ld a,(hl); and a; jp m,$238D`) until
  the IRQ handler posts a task in the ring at $4CC0.  That spin is where the STE runtime's schedule hands over (the
  idle hook of 1942's schedule, `docs/porting-guide.md`).
* No `ld a,r` in the program: no random source to replace.

Renderer: 36 x 28 tiles with the Namco column/row mapping (Galaga's), 8 sprites of 16 x 16 drawn 7 down to 0, sprites
0-2 one raw line lower (MAME's `xoffsethack`), clipped to raw x 16-271 and also drawn at x - 256.  A sprite pen is
transparent where its colour lookup entry is 0 (`transpen_mask`); tiles are opaque.  Colours: MAME's
`compute_resistor_weights` (red and green 1k / 470 / 220 ohm, blue 470 / 220, scaled to the largest net), rounded as
`combine_weights` does.  `python games/pacman/tools/machine.py 900 out.png` boots and saves a picture.

## Checked against MAME

`python games/pacman/ref/mame_cmp_pacman.py [seconds]` records MAME's attract mode with F030Arcade's WolfMAME 0.162
(`-aviwrite`; this machine has no MAME 0.289) and looks every MAME frame up among the reference's frames by its exact
RGB picture.  2026-10-29, 45 s (2701 frames):

* 2638 frames equal a reference frame; all 11 colours on screen are exactly MAME's.
* 62 others are the boot's RAM test (its patterns caught mid-test: they depend on the exact Z80 cycle timing).
* 1 is an energizer's blink one frame apart (MAME frame 1495, 30 pixels): a write near the blank, the same timing cause.
* The AVI is 60 fps from a 60.606 Hz board: WolfMAME drops about one frame in 99, so the frame offset grows; the
  lookup by picture is independent of it.

Not checked yet: play with input (the reference's play against MAME's: a WolfMAME `.inp` or the MARP recordings,
`docs/porting-guide.md`), the flip screen (cocktail; the port is upright), sound.

## The port's schedule

`machine.PacmanPort` (the reference) and `src/pacman.s` (the runtime) do the same.  The foreground waits at two
places: the task loop's spin at `$238D` while the task ring's read entry (the byte at the address in `$4C82`) has bit 7
set, and the boot's `halt` at `$234A` (the program's only one).  There an arcade frame ends.  The next one delivers the
IRQ when latch bit 0 (`$5000`) and IFF1 allow it: the address the foreground waits at is pushed on the Z80 stack and
the IM 2 vector's target entered (the word at `$3F00` + the vector: `$3000` at boot, which never returns; `$008D` the
frame handler, whose `reti` goes back to `$238D` through the dispatch table, where the hook looks at the ring again).
Without the IRQ the frame passes.  The runtime resets the 68000 stack before it enters the IRQ (the foreground waits
at its top level); the boot's push at SP `$FFFF` is written byte by byte (an odd address).

Unlike the arcade, the IRQ never cuts into a running task, and the boot's ROM / RAM test runs inside frame 0 (it
never waits): the attract mode starts 250 frames earlier than on the board, the game is otherwise the same.  A task
that took longer than a frame on the arcade makes a longer frame here.

## Coverage

`ref/cover.py <seed> [frames]` (20000 frames each, about 3 minutes; the seeds in its docstring): random 4-way play to
the game over, MAME's cheats (infinite lives `$4E14`, "finish this level" `$4E0E` = `$F4`, the level `$4E13`) for
levels 1-28 and 250-255 and the intermissions, two players, the other DIP switches, the rack test.  2026-10-29: 4973
pcs.  The service mode is left out: its tests never wait for a frame, and the port has no switch for it.

What it found:

* The text printer (`$2C5E`) takes screen positions with bit 15 set from its string table (the top and bottom rows):
  A15 is not decoded, so they are video RAM.  `gen.py IX_A15`: IX loses bit 15 after `add ix,de` at `$2C69`.  No other
  access to a mirror.
* `$205D` reads the empty `$4800-$4BFF` ($BF): the runtime fills those bytes of the block, nothing writes them.
* Inputs are read with `ld a,(nn)` only: `IO_IN` redirects them to `$5100-$5103`, the runtime's input bytes (the
  stores to `$5000-$50FF` stay plain stores: latch, WSG, sprite coordinates, watchdog).

## Translation

`tools/gen.py` (`engine/z80x.py` FAST, signed 64 KB block, `translate.compile_code`): 5419 instructions (the coverage's
4973 and what discovery adds), nothing unsupported, nothing missing.  The restarts that take data after the call are
`discover`'s new `rst_data` (2026-10-29; the default leaves other ports unchanged): `rst $20` (32 sites) jumps through
the word table after it, indexed by A; `rst $28` (76) posts a task, 2 inline bytes, into the ring at `$4CC0` and returns
past them; `rst $30` (33) puts 3 inline bytes in a free slot of the 16 timed tasks at `$4C90` and returns past them
(with all slots full its `ret` at `$005A` would return into the data: never seen).  The continuations are joins.  21
jump tables; `$2F01`'s ends in entries that are single `ret`s (empty sound handlers).  `out ($00),a` stores the
vector (`pm_vector`), `ei` / `di` IFF1 (`pm_iff`), `halt` jumps to `pm_halt`; the 102 stores to the video and colour RAM
mark their cell (`pm_mark_*`) for the renderer.

## Lock-step test

`tools/logic_test.py [frames] --seed N` runs `run/pacman_sim/PACMAN.PRG` on Musashi against `PacmanPort` with the
coverage's inputs and cheats, and compares every frame: RAM `$4000-$47FF` and `$4C00-$4FFF` (the dead stack below SP
left out), latch bit 0, the vector, IFF1, the WSG registers, the sprite coordinates; every changed video RAM cell must
be marked.  2026-10-29: seeds 1-12 pass (seed 1 3000 frames, 2-12 12000 each), the logic takes 34-44k 68000 cycles an
arcade frame on Musashi (Hatari counts about 1.35 times that: 46-60k; at 60 arcade frames to the STE's 50 VBLs 35-45%
of the 160k cycles of a VBL, an estimate to be measured in Hatari).  Seeds 13 and 14 (random play the coverage never
ran, 15000 frames each) pass too: no code outside the coverage's was reached (it would stop at `z80_badpc`).

## The picture

`src/render.s`, after Time Pilot's renderer.  The arcade's 224 x 288 picture is turned as MAME's ROT90 turns it and
sits at screen x 48-271 (black side bands of three 16-pixel groups: the edges lie on group boundaries), the top and
bottom border open (`engine/rt/borders.s`, Galaga's timing, one palette).

**The lines.**  Hatari shows 274 lines from the video base with both borders open: measured 2026-10-29 by matching a
recorded picture with the reference line for line (the picture's first line at the window's first; its last two lines
black).  Which 14 of the 288 to leave out was measured over the coverage's play (every line's use, 4 seeds x 8000
frames): lines 7, 8 and 272 are never drawn; row 2 (lines 16-23) and line 273 only on the level-256 split screen; line
287 hardly ever (393 of 10664 pictures); 274 is the top line of the life and fruit icons (the least visible loss: every
text row stays whole).  Shown: lines 0-6, 9-15, 24-271, 275-286 (`tools/assets.py SHOWN`).  The maze and every sprite
keep one offset: buffer line = arcade line (10 guard lines above the display); the HUD rows move (`hud_line`).  MAME
clips sprites to lines 16-271, so a sprite's lines in the HUD bands are copied back from the clean screen
(`band_restore`); MAME's second copy of each sprite 256 lines up is drawn where it reaches the maze.

**Colours.**  The STE pixel is the arcade's colour index: the colour lookup PROM only ever selects the palette PROM's
first 16 colours (and never its black duplicates 4, 8, 10), so `pm_pal` is that PROM on the STE's 4 bits a gun.  A
sprite pen is transparent where its colour is black: three patterns ({0}, {0, 2}, {0, 3}); 11 colours draw nothing.

**Drawing.**  Tiles into a clean screen when the translated writers marked their cell and its code or colour changed
(per colour and line range a generated converter, `pm_tconv`), copied into each display buffer (`movep.l`).  Sprites
from a cache baked on first use (rows grouped by opaque mask), drawn with `engine/sprite_programs.py`'s generated code
for the 65 shapes the coverage drew (767 routines, a 55 KB stream) and the row path for the rest; across a side edge
only the inner word, wholly outside culled (`AGENTS.md`).  Three display buffers; damage restored with HOG passes of
at most 32 words.

**Checked** (2026-10-29): `render_test.py` 9000 frames of seeds 2, 4, 6, 7, 11 and 12 (play, levels 1-28 and 250-255,
the intermissions, two players), every third from frame 300: 17,400 pictures equal to the reference, side bands black.
`sprite_test.py`: 168 made-up pictures exact (both edges at every pixel, flips, 40 codes with holes, the black-pen
patterns, 36 pictures with 64 KB crossings, the bands, the wrapped copy, moving sequences in all three buffers).
`BLIT_STATS=256`: 121,916 HOG passes from 691 places, the longest 256 bus cycles, none sharing the bus.
Cost on Musashi: a picture 16-49k CPU cycles (the higher when levels change often: a maze redraw) and 6-7k Blitter bus
cycles, the logic 27-29k a frame.

**Hatari** (`tools/hatari.ps1`, 2026-10-29; the attract mode, no input): 4500 VBLs, 5043 arcade frames, 4181
pictures.  After the boot it runs at full speed: 59.9 arcade frames and 49.8 pictures a second (the last 3000 VBLs).
The boot costs about 6 seconds: its ROM / RAM test runs before the first frame (the arcade's takes about 4).  No
crash, the stills match the reference (attract screens, the demo maze, frightened ghosts, Pac-Man's death).

## Sound

`tools/sound.py` (the model) and `snd_update` in `src/pacman.s` (the same in 68000 code), Galaga's method: the same
Namco WSG at 96 kHz with the same register map (MAME `namco.cpp pacman_sound_w`, checked).  Each voice becomes a
square wave on its YM2149 channel: the period from the WSG frequency (`1365333 / freq`, the formula Galaga checked
against MAME's audio) divided by the waveform's strongest harmonic, the level from the volume and the waveform's RMS
(3 dB a step).  Pac-Man's waveforms (`82s126.1m`) are not Galaga's: their strongest harmonics are 1, 1, 2, 1, 8, 16, 1,
2, so wave 4 (used by voice 1) sounds three octaves above its fundamental and wave 5 four (Galaga's rule followed one
octave only).  Latch bit 1 (`$5001`) switches the sound off.  `snd_update` runs once an arcade frame, as the frame is
delivered, on the registers the previous frame's handler wrote; it writes only the YM registers that changed.

`sound_test.py` (2026-10-29): 4000 frames of a played game (after every frame the YM's registers equal `ym_image` of
the reference's WSG registers) and 2000 random register sets, all equal.  Not checked against MAME's audio: Pac-Man's
attract mode is silent, and the WolfMAME 0.162 on this machine has no Lua input to start a game; the pitch of waves 4
and 5 is the analysis's, not heard.

**Hatari in play** (`tools/hatari.ps1 -Frames 6000 -Sound 44100 -Extra -DAUTOPLAY=1`, 2026-10-29): 6001 VBLs, 6787
arcade frames, 5608 pictures: within about 50 frames of full speed after the boot.  The recorded audio sounds from
the start (12 s) to the game over (66 s), its strongest frequencies 530-890 Hz in play; the stills show the game (the
score, the lives and fruit rows, the game over, the high score kept).

## Next steps

1. The pads (`engine/rt/jagpad.s`) and a check of the keyboard and joystick by hand; perhaps a shorter boot (Galaga
   patches its RAM test out: here about 6 seconds before the first picture).
2. The sound against MAME's audio (a MAME with input: MAME 0.289's Lua, or a recorded `.inp`), by ear too.
3. Register the port in `port.py` (GAMES, COVER, TESTS), `tools/release.py` and the README's tables; a screenshot.
4. Play against MAME with input (a WolfMAME `.inp` or a MARP recording, `docs/porting-guide.md`), then the natural
   playthrough `docs/port-status.md` asks for.
