# R-Type (Irem, 1987)

2026-10-19: the shared M72 renderer uses cheaper contribution-bitmap rotations and reuses its access-count
table in transfer fallback paths. This also serves Mr. HELI. See [measurements](../../docs/virtual-scroll-performance.md#implementation-results).

![R-Type on the STE (Hatari)](docs/screenshot.png)

STE port of MAME set `rtype` (Irem M72): the main CPU's NEC V30 program statically translated to 68000 code
(`engine/v30x.py`), the M72 picture drawn by the shared renderer (`engine/rt/m72render.s`).  No sound yet.

**Memory: development targets a 14 MB ST RAM system** (the user, 2026-10-31; `tools/bench.sh` runs Hatari with
`--memsize 14`).  R-Type alone may use it, for speed (e.g. sprites coloured at build time instead of at run time).
A 4 MB STE is not a target for now; how to fit the game back into 4 MB (per-stage loading, packing) is decided later.
`tools/release.py` lets RTYPE.PRG pass the load limit with a warning (`OVER_LOAD`).

**Guard rows are never erased** (the user, 2026-10-31): the stage renderer (`src/stage.s`) draws sprites whole into
the 64 guard lines above and below the picture but erases only the visible lines 0-255; the display never shows the
guard rows.  Hatari (14 MB, recorded play): stage 2 34.1 -> 34.9 arcade frames/s, 17.1 -> 17.4 pictures/s; stage 1
unchanged (38.3, 21.6).  A 16x8-cell column erase (one long per 16-pixel column) was tried and measured slower
(34.4 / 17.2): its marking and scan cost more than the words it saves; 16x16 cells erase more words than rectangles.

**Stage 3: the warship as the scrolling layer** (the user, 2026-10-31).  In stage 3's scene (`tools/stage_assets.py`
BG_SCROLL_SCENES) the renderer switches to its BG scroll mode once the BG map holds a tile that is not empty (frame
12618 of the attract demo): the buffers hold the BG map at its own x and y scroll (512 lines, the first 256 again below:
896-line buffers), and the FG walls are drawn over it each picture like sprites - stefastbobs2's copy passes from a FG
image with the opaque pixels as end masks, a pass list per FG row made again when the row or the window's first chunk
changes (`src/stage.s` st_fgdraw, st_fgbuild).  Sprites and FG rows are erased whole there (the lines outside the window
scroll into it).  `tools/stage_model.py` (bgscroll) draws both layers at their own scroll.  `stage_test.py
build/rtype/stage_states_3.pkl` (seed 1 attract, frames 11400-14400: `logic_test.py 14400 --seed 1 --start 11400 --snap
--list --record ...`): every picture exact.  Hatari, the demo's warship part (REPLAY=1:12600:14400): 23.6 arcade
frames/s, 13.4 pictures/s (before: 32.6 / 18.9 without the warship).

**Stage 3: the warship as sprites** (the user, 2026-10-31; the default now: `stage_assets.py` BG_PIECE_SCENES, scene
flag bit 3).  The FG walls stay the buffer's layer; the warship (BG) is drawn over them each picture with the same
pieces (`src/stage.s` ST_LAYER bg: a BG image, a non-empty BG cell is opaque as a whole), then the walls' opaque pixels
are copied again from the clean buffer where a warship row meets wall chunks (st_wallfix: the layers' order).  A
warship row over no wall chunks is erased by clearing (zeros, no source reads: st_sync clears those before it copies
the log).  The BG scroll mode stays (flag bit 2 alone).  Hatari, the warship part: 24.0 arcade frames/s, 13.7
pictures/s; the BG scroll mode with its switch fix 24.3 / 13.8.  Musashi, a picture (CPU + Blitter): warship coming in
behind the full walls (12900-13100) 316k as sprites, 452k scrolling; warship filling the screen (13400-13600) 394k as
sprites, 284k scrolling - drawing the smaller layer as pieces (switching at the crossover) would take the better of
each.

**Stage 3: the smaller layer as sprites** (the user, 2026-10-31; `stage_assets.py` BG_HYBRID_SCENES, flag bit 4).  In
the FG mode the warship is drawn as pieces until it has more 16-pixel chunks with pixels in the window than the walls
(`src/stage.s` st_meas over st_fgrc / st_bgrc, every picture), then the BG scroll mode with the walls as pieces for the
rest of the scene (frame 13326 of the demo; the switch picture ~1.2M + 0.27M cycles).  Musashi: the stage-3 recording's
median 206k -> 187k cycles a picture, 90th percentile 412k -> 338k.  Hatari, the warship part: 25.5 arcade frames/s,
14.5 pictures/s (24.0 / 13.7 as sprites only, 24.3 / 13.8 scrolling only); the whole stage-3 demo 29.4 / 19.1.

**Stage 1's middle section: the BG drawn** (the user, 2026-10-31).  From frame ~3000 of seed 8 the BG fills the picture
locked to the FG (offset 128-129 pixels): it is composed into the buffer with the FG, cell by cell (the FG tile over the
BG tile through its opaque pixels, `src/stage.s` st_cell as stage 2's strip), composed again when its cells change.
The model's lock is now in whole cells (`stage_model.py` Lock: the offset rounded to 8 pixels, taken again when off by
more than 4, free while the BG map is empty).  The BG's colour row (tile row 7) fades in, changes and fades out; its
changing pens 1, 2, 3, 5 have dedicated STE indices in scene 6 (`stage_assets.py` DEDICATED: 12 colours for the rest)
whose colours `st_palette` sets from the row's target - no cells composed again (before: ~6M cycles each).  Seed 8 is
now exact to its end (3500 pictures; before: every picture from 3662 failed).  cols_*.json recorded again for the new
scene 6 palette (1573 pre-coloured pairs).  Hatari seed 8 3000-8000: 36.4 arcade frames/s, 19.8 pictures/s (37.7 /
20.9 without the BG).

```sh
python port.py build rtype            # verify ROMs, translate, build assets, the snapshot and RTYPE.PRG
python port.py test rtype             # the translation in lock-step with the reference, the renderer's pictures
python port.py mame rtype 1000        # the reference renderer against MAME's picture
python port.py cover rtype            # coverage (random play, attract and the Invulnerability switch)
games/rtype/tools/bench.sh shot@20 tap:06@25 tap:02@28 shot@60       # its own Hatari: rates, screenshots
games/rtype/tools/profile.py          # Musashi: 68000 cycles per V30 instruction, mnemonic, 256 bytes of code
```

Supply `assets/roms/rtype.zip`; preparation checks it against the manifest and fills `build/rtype/mame_roms/` (the
two PROMs and three PALs MAME wants but the driver never reads, as zero stand-ins).  The executable is
`run/rtype/RTYPE.PRG`; the ROMs, the graphics and the start state are embedded.

Controls: **5/6** insert coins, **1/2** start, **arrow keys** move, **Space/Ctrl** fire (hold to charge the beam),
**Alt** the Force (detach / call back), **Escape** returns to the desktop.  Joystick fire fires (port 1 player 1, the
mouse port player 2).  Jaguar pad / PowerPad: pad A player 1, pad B player 2, the D-pad moves, **A** fire, **B** the
Force, **Option** coin, **Pause** start, keypad **1/2** start, **5/6** coin, **\*** + **#** quit.  For scripted
Hatari events use scancodes: coin `06`, start `02`, Space `39`, Alt `38`, cursor keys `48 50 4b 4d`, Escape `01`.
DIP switches: MAME's defaults (3 lives, demo sounds on, coin mode 1).

## State

* The logic is exact: the translation runs in lock-step with the reference board's port schedule
  (`tools/logic_test.py`; attract and play, up to 40000 frames, the work RAM, video RAMs, palettes, sprite RAM and
  registers equal every frame).  The reference board (`engine/m72board.py`) equals MAME 0.289 in all RAM.
* The port starts after the boot (the ROM and RAM tests are not translated): `tools/snapshot.py` takes the reference's
  state at frame 400 (the title, the CPU idle), embedded in the program.
* The display is the centred 320-pixel window of the 384-pixel picture (x 32-351): the left part of "1P-" and of the
  title's "R" are cut.  The status bar (lines 240-255, a raster split at line 239) gets its own palette.
* Speed (Hatari, F030Arcade build, STE 4 MB): attract ~23 arcade frames a second (41% of the arcade's 55), play
  ~16 (29%), 5.5-6.5 pictures a second.  The game slows down evenly (frames are dropped when the logic falls behind,
  not skipped by the game itself).
* Palette fades are left out (2026-10-29, `src/natives.s`, FADE_SNAP): the fade loop sets each colour to its target at
  once; the fade's counter still runs, so the game sees each fade end at the same frame.  `logic_test.py --snap` checks
  such a build: everything but the palettes, the work RAM's palette copies and fade records and the stack page stays
  equal to the reference (seeds 1, 4, 8: 3000-4000 frames).  Logic 119k -> 110k cycles an arcade frame (seed 4);
  Hatari play 15.0 -> 16.4 arcade frames/s, 4.6 -> 5.3 pictures/s.  `-D FADE_EXACT=1` builds the arcade's fades.
* The sprite emitters are native (2026-10-29, `src/natives.s`: 0040:1BCC / 1C1B / 1CA6 and the fill 0040:0653): an
  object's sprites come from a definition in ROM (DS1:[BW]) plus its colour and position.  Without SPRITE_LIST they
  write the sprite RAM as the arcade (lock-step identical); with SPRITE_LIST (for the stage renderers, not used by the
  program yet) they write one record per object (definition, colour, x, y) at its first slot, and the DMA copies the
  records (`logic_test.py --list` expands them through the ROM and compares them with the reference's sprite list every
  frame).  Logic with FADE_SNAP + SPRITE_LIST: seed 4 play 119k -> 95k cycles an arcade frame, seed 1 attract 93k -> 82k.
  `tools/stage_model.py`: the picture the stage renderers will draw (no stars - BG star tiles and the star sprites
  $AF2-$AF7 -, BG locked to FG within 2 pixels, sprites over the tiles, fixed colours).
* No sound: the main CPU's commands to the sound CPU (port $00) are kept in a ring (`src/core.s`), for a player.

## Method

* **Translation** (`tools/gen.py`, `engine/v30x.py`; the design in the module's docstring and
  `docs/architecture.md`, "The V30 translator"): one snippet per V30 instruction; the V30's registers in d0-d6, the
  segment bases in a2-a4, SS:SP in a5; the V30's 1 MB as one image with the bytes of each word swapped (words are
  native moves); flags in the CCR with backward liveness; returns through a 64K-long table by IP.  The code the
  coverage (`ref/cover.py`) never ran is taken from the program: jump tables in ROM, the object handlers it stores
  (`mov word ptr [bp+0h], imm`), code after RETs that nothing refers to.
* **Schedule** (`src/rtype.s`, `src/core.s`): an arcade frame is the VBL interrupt's handler (the game's logic, at the
  main loop's idle point 0040:00D0) and then the raster interrupt's (the status bar's scroll), each to the idle point
  again (`tools/machine.py` RType.run_frame_port is the same in Python).  The VBL counts 11 arcade frames per 10 fields;
  the main loop runs one arcade frame per count and a picture after every second arcade frame (`PIC_EVERY`, or when no
  frame is waiting); more than 3 frames behind are dropped.
* **Picture** (`src/video.s`): the translated stores into the video RAMs and palettes mark their 256-byte blocks
  (`tools/gen.py` store_marks; logic_test checks that every changed block is marked); before each picture the marked
  blocks are copied to the renderer's video state in the V30's byte order, the sprite list after each DMA, and the
  bands from the scroll registers before and after the raster interrupt.  The renderer: `engine/rt/m72render.s`
  (its header; `tools/render_test.py`, `tools/sprite_test.py`).

## Measurements

68000 cycles per arcade frame of the translated logic (Musashi, `tools/logic_test.py`): play 92-125k, attract with the
demo ~105k, heavy invulnerable play 150-176k; the picture 0.7-1.7M (the renderer's header).  Hatari (`tools/bench.sh`):

| PIC_EVERY | arcade frames / s (play) | pictures / s |
|---|---|---|
| 1 | 13.4 | 6.7 |
| 2 (default) | 15.7-16.9 | 5.6-6.1 |
| 4 | 22.7 | 4.3 |

Memory: text 233 KB (the translation), data 1.2 MB (the renderer's graphics 836 KB, the ROM 256 KB, the snapshot, the
dispatcher's tables), BSS 2.2 MB (the V30 image's RAM and video part 640 KB, the IP table 256 KB, the renderer's layer
images, buffers and caches 1.17 MB).

## Standard PPO exploration

Use `venv/bin/python port.py ppo rtype test --steps 256 --frames 2100` to check the shared training/recording/replay workflow. See [the common PPO guide](../../docs/ppo.md). PPO supplements the existing scripted coverage; canonical replay fixtures are preserved.

## Full-game verification status

Automated players such as Dreamer can attempt a full playthrough once this port's
adapter and native Hatari replay transport are verified. An attempt or assisted
stage visit does not establish completion; a successful natural Hatari playthrough
and graphics, sound and control checks are required for green **Complete** status.
See the shared [status and verification policy](../../docs/port-status.md) and
[current port status](../../README.md). Existing test results above retain their
stated scope; this note does not claim a new successful run or Dreamer integration.
