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
  (`tools/logic_test.py`; attract and play, the work RAM, video RAMs, palettes, sprite RAM and registers equal every
  frame).  Since 2026-11-01 through all eight stages and the ending: coverage seeds 10-12 to 86000 frames
  (`ref/cover.py`, Invulnerability), seed 10 in lock-step 45000-84000 with the stage build's natives.  The broad
  phase of the enemy collision test (`src/natives.s` es_build) dropped a box with only its right (or bottom) edge 0
  as dead; the arcade still hits it from the left (stages 7 and 8): only L = R = 0 or T = B = 0 is dead now.  The reference board (`engine/m72board.py`) equals MAME 0.289 in all RAM.
* The port starts after the boot (the ROM and RAM tests are not translated): `tools/snapshot.py` takes the reference's
  state at frame 400 (the title, the CPU idle), embedded in the program.
* The display is the centred 320-pixel window of the 384-pixel picture (x 32-351): the left part of "1P-" and of the
  title's "R" are cut.  The status bar (lines 240-255, a raster split at line 239) gets its own palette.
* Speed of the first renderer (`engine/rt/m72render.s`, before the stage renderer; Hatari, STE 4 MB): attract ~23
  arcade frames a second, play ~16, 5.5-6.5 pictures a second.  The stage renderer's numbers: "Speed on the STE" below.  The game slows down evenly (frames are dropped when the logic falls behind,
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

## Speed on the STE: what is needed

The goal (the user): a steady 25 pictures a second at the arcade's full speed (50 arcade frames a second in the port's
schedule).  The rule: keep the gameplay, drop what only costs work (effects, parallax, colour cycling); the logic stays
exact.  Development targets the 14 MB machine.

Measured 2026-10-31 / 11-01 (Hatari, `tools/bench.sh` REPLAY=seed:start:end FAST=true, recorded play; the stage
renderer `src/stage.s`):

| stage (recording) | arcade frames / s | pictures / s | where the time goes |
|---|---|---|---|
| 1, BG middle section (seed 8 3000-8000) | 36.4 | 19.8 | logic 40%, sprites 22%, sync 16% |
| 2, tunnel (seed 10 11000-13000) | 34.1 | 17.1 | |
| 3, warship (seed 1 12600-14400) | 25.3 | 14.4 | the slowest: the layer drawn as pieces |
| 4 (seed 10 33000-36000) | 40.9 | 22.9 | |
| 5 (seed 10 46500-49500), BG locked | 19.2 | 14.4 | compose 42%: 165 whole recompositions (the BG lock) |
| 5, BG as a strip (2026-11-01) | 32.5 | 25.3 | waiting 36%, compose 19%, logic 15%: 36 whole recompositions |
| 6, 7, 8 (seed 10 56000- / 64500- / 74000-) | - | - | crashed: an address error at the ranking (below); measured again with `-D INVULN` |

Musashi, a picture (CPU + Blitter) median / 90th percentile, before -> after the strips, no BG and frozen rows:
stage 5 198k / 1.07M -> 174k / 404k; stage 6 198k / 6.0M -> 159k / 244k; stage 7 213k / 366k -> 212k / 335k (its
recording is mostly the boss, the scroll stopped); stage 8 458k / 7.8M -> 144k / 529k.  Logic, stage 7 (seed 10
65000-65030, profile.py): 122k -> 98k cycles an arcade frame - the collision broad phase no longer switched off by a
box with L > R (31k -> 13k), the movement script native (`src/natives.s` nat_mscr, 0040:F5C1: 15k -> 8k).

**Benches of seeds 8+ need `-D INVULN`**: their recordings play with the Invulnerability switch; without it the
player dies in Hatari, the replay ends in a game over.  That showed a bug: **the ranking's records (11 bytes from
2F51h) put a rank's words at an odd address, and the coverage had never run the ranking** - the translation took the
word stores as even, the STE raised an address error (Musashi has none, so the lock-step never saw it).  `tools/gen.py`
ANY_PARITY: the ranking and name entry's word accesses test their parity at run time, their byte accesses too.
`logic_test.py --mortal-at F` / `ref/cover.py SEED FRAMES MORTAL_AT`: the switch off from frame F - the late stages'
deaths, game over, ranking and name entry, which the invulnerable coverage never reached (badpc 0592E).

Hatari 2026-11-01 evening, every stage (seeds 8+ with `-D INVULN`, as recorded; VBLs sampled):

| stage (recording) | arcade frames / s | pictures / s | logic | sprites | sync | compose |
|---|---|---|---|---|---|---|
| title + demo (1 600-3600) | 41.7 | 29.4 | 17% | 16% | 12% | 11% |
| 1 (8 3000-8000) | 36.8 | 20.1 | 42% | 23% | 15% | 6% |
| 2 (10 11000-13000) | 35.1 | 17.5 | 33% | 30% | 20% | 8% |
| 3 warship (1 12600-14400) | 26.3 | 15.0 | 36% | 23% | 15% | 11% |
| 4 (10 33000-36000) | 41.5 | 23.4 | 37% | 18% | 16% | 8% |
| 5 (10 46500-49500) | 35.6 | 19.2 | 38% | 22% | 16% | 10% |
| 6 (10 56000-59000) | 38.9 | 20.6 | 46% | 19% | 15% | 5% |
| 7 (10 64500-67500) | 30.3 | 15.2 | 45% | 23% | 16% | 7% |
| 8 (10 74000-77000) | 34.9 | 18.2 | 30% | 20% | 20% | 16% |

The logic is now the largest share in every play stage: the next gains are natives for each stage's busiest routines.
Then (8a75fce): the collision broad phase for offset boxes (stage 3's logic 119.9k -> 110.0k cycles a frame) and the
fade rows at their target compared in longs (stage 6 80.4k -> 75.5k): Hatari stage 3 26.9 / 15.4, stage 6 39.9 / 21.6.
Logic profiles of every stage (profile.py, 30 frames): stage 1 86k (the cave crawler's handler 19%: four tile probes a
crawler a frame), 2 73k, 3 109k, 4 86k (fades whose targets change every frame), 5 98k, 6 80k, 7 98k, 8 60k cycles an
arcade frame; the object loops' computed CALL / RET (0040:0600-06FF) 7-10% everywhere, the game's own dispatch.

**Game speed first** (the user, 2026-11-01; `src/rtype.s` PIC_EVERY 8, MAX_BEHIND 12, before 2 / 3): a picture when
the logic has caught up, at least every 8 arcade frames.  Hatari, the same recordings (arcade speed, pictures / s):
title 89% / 27.3, stage 1 95% / 14.8, 2 97% / 11.9, 3 78% / 8.4, 4 97% / 19.7, 5 93% / 14.5, 6 97% / 16.0, 7 85% / 7.2,
8 94% / 10.0.  Stages 3 and 7 still drop arcade frames: their logic and minimum pictures do not fit.  Measured and
dropped: the collision summary's boxes by 64-pixel column (stage 7's logic 108.4k -> 110.4k: the filling costs more
than the shorter scans save).

What costs most, and what is done about it:

1. **A BG at its own speed.** The renderer composes the BG with the FG cell by cell, locked to the FG; when the
   arcade's offset drifts more than 4 pixels the lock is taken again and everything is composed again (~1-6M cycles).
   Stage 5's BG runs at 1/2 of the FG's speed, stage 6's at 2x, stage 7's at 3/4: relocks every few frames.  The cure
   (the user, 2026-11-01): no parallax.  Stage 6: no BG (decorative; `stage_assets.py` NO_BG_SCENES, flag bit 5).
   Stages 5 and 7: the BG as a strip locked to the FG, as stage 2's tunnel (`tools/stage_bg.py`; BG_STRIP_SCENES,
   the strip's index in flag bits 6-7); while the BG map holds walls (codes below 7D0h: stage 7's boss) the locked BG
   instead, so walls are never drawn where they are not.
2. **Colour cycling.** A palette row that switches its target recomposes every cell drawn with it.  Stage 8 switches
   tile row 2 (82h / 8Ah) 254 times in 3000 frames.  The cure: frozen rows keep their scene's reference target
   (FROZEN_ROWS, the scene's SC_FRZ word; `st_palette`).  Fades the game makes in a scene that must show them keep
   dedicated pens instead (stage 1's middle: DEDICATED - colours set, nothing composed again).
3. **The logic.** 68-150k 68000 cycles an arcade frame (stage 7 117-150k, near a whole STE frame).  Next: profile
   the heavy stages (`tools/profile.py`, `logic_test.py --render-profile`) and make their hot routines natives or
   leaf calls (`src/natives.s`, `tools/gen.py` NATIVES / LEAF_CALLS), each checked in lock-step.
4. **Stage 3's warship.** The scene with two full layers; already the smaller layer as pieces (hybrid).  Next after
   the logic.
5. Then the smaller shares: the sprites (6-22%), the log copy into the three buffers (16-17%).

How each change is checked: `logic_test.py` in lock-step (with `--snap --list` for the stage build); the pictures
against the model (`tools/stage_test.py build/rtype/stage_states_*.pkl --quiet --stop 0`, recordings of every stage:
`logic_test.py END --seed S --start F --snap --list --record ...`); speed in Hatari, logic and picture rates kept
apart.  For an instruction-level comparison (`logic_test.py --steplock F`) build with `NO_NATIVES=1 NO_INLINE=1`
(natives and inlined calls skip the labels the interpreter stops at).

Memory: with every stage's sprites pre-coloured (1112 definitions, 3437 colourings) RTYPE.PRG is 5.9 MB - fine on
the 14 MB machine, far over the 3.7 MB release limit (per-stage loading or packing, decided later).

Renderer experiments, 2026-11-01: damage coalescing saved only 0.6% over the full stage-5 recording and did not improve
Hatari's picture rate; unrolled secondary-layer loops were neutral and cached shifted masks slower. No runtime change
kept. See [the audit, bounds and measurements](docs/renderer-audit.md), including sample windows in all eight stages.

Prepared secondary-layer prototype, 2026-11-02: native source packing, generated row routines and lazy masks for
all 16 shifts, including preparation costs. Stage 3: 266,396 -> 268,203 cycles a picture (+0.68%) drawing every
second arcade frame; 230,692 -> 229,140 (-0.67%) drawing consecutive frames. Both runs are exact; 113 focused
cases pass. The 512 KB cache does not supply a consistent win; production renderer unchanged. See
[implementation, measurements and reproduction](docs/prepared-layer-prototype.md).

Avoiding redraws/copies, 2026-11-03: an eight-stage transfer audit and an isolated late-full-refresh prototype.
Refresh the visible window and fill incoming strips on buffer reuse: exact, stage 3 −2.50% renderer cycles,
stage 4 −1.58%, stage 6 −0.81%; smaller gains on consecutive pictures. Pinned Hatari stage 3: 28.18 -> 28.66
logic ticks/s, 19.17 -> 19.68 pictures/s, with remaining late palette events. No 2x route demonstrated;
production unchanged. See [bounds, implementation, correctness and timing](docs/route1-results.md).

Native logic optimizations integrated, 2026-11-03: correct cached red-channel words (the ROM offset's high byte leaked into
4,010 entries), combine the E5CD object's movement/emission, and fill/mark tile-RAM clears in bulk. Early play
and restarts: −16–23% logic cycles; eight later-game samples: −0.3–3.0%. Pinned Hatari seed 4 600–3600:
39.54 -> 41.95 logic ticks/s, 29.71 -> 33.94 pictures/s; zero late border/palette events. Independent reference
lock-step reruns pass seed 4 to 9000 and seed 1 to 14400; all 6,600 production/baseline frames match. See
[native results, limitations and reproduction](docs/native-results.md).

Later-stage native follow-up, 2026-11-03: movement-script leaf returns, tile runs/BG patches and the breakable-FG
helper give another 0.49–2.54% fewer logic cycles in stage-3–8 samples. Native box tests and fused object dispatch
add little or regress. Pinned Hatari stages 7/8: +1.66%/+2.58% logic throughput, picture rates essentially
unchanged; zero late border/palette events. These prototypes remain isolated; see
[measurements, exactness and reproduction](docs/later-native-results.md).

Sprite DMA scheduling fix, 2026-11-03: with `PIC_VBLS` enabled, capture every sprite DMA. The former skip predicted
that no picture could follow, but the deadline scheduler could then draw current scrolling with an old object list.
The skip remains available with `PIC_VBLS=0`. A non-SIM regression test is part of `port.py test rtype`;
instrumented Hatari stage-3/7 replays reduce pictures with an uncaptured latest DMA from 1,047/1,568 to zero.
Updating the actual sprite poses costs more than repeatedly drawing the old list, so earlier timing numbers are
not representative of the corrected picture workload. See [the checks and timing](docs/sprite-dma-results.md).

Short Blitter passes in `st_sync` and the FG/BG pieces, 2026-11-03 (the stage-3 late palette events): a restore or
cleared rectangle wider than 32 words went out as one HOG pass a line (92 words: 736 bus cycles), the log's masked
copies as 8 lines of 4 words (they read the destination: 384), full FG/BG runs of 7 chunks as 8 words (272).
Now `st_rect` cuts rectangles into column strips of at most 32 words, masked log passes take 4 lines (8 when the
mask is `$FFFF`), `ST_RUN` is 6. `BLIT_STATS=256 renderer_audit.py` over the stage recordings (3, s2, s4-s8, 1, 8;
every picture exact): longest pass 256 bus cycles, none over. Stage-3 simulator cost 242.9k -> 246.8k cycles a
picture (+1.6%: more passes). Pinned Hatari, the same replays as above: stage 3 (seed 1, 12600-14400) border report
`(1,0,22,0,0)` -> `(1,0,0,0,0)`, 22.22 -> 21.80 logic/s, 17.31 -> 17.23 pictures/s; stage 7 (seed 10, 64500-67500)
26.57 -> 26.28 logic/s, 17.17 pictures/s both, no late events either way. `render_test.py` and `sprite_test.py`
pass on this code.

Higher-level logic audit, 2026-11-04: exact shared collision queries, compiled two-command motion transitions and
query construction hoisted out of collision scans give **2.13%** fewer logic cycles over the stage-3 warship replay,
**3.22% / 3.47%** in the seed-10 stage-3/7 samples. All 6,600 production/prototype comparison frames and 1,152 focused
cases match. The hottest stage-7 handler accounts for 37% of sampled logic, but only 10% is its translated code;
27% is already native work. No 2x route demonstrated; prototypes remain isolated. See
[algorithms, conditional bounds, measurements and reproduction](docs/logic-level-results.md).

Native structural improvements retained, 2026-11-04: specialize one-entry sprite emission, reuse collision-query
endpoints on no-hit returns, use PC-relative terrain-cache fields, ADDX for inline 24-bit movement, cached word-pair
copies for changed fades, existing MOVE/logical result flags, and an unrolled DMA copy. Logic cycles −1.06–2.97%
across eight stage samples; warship −1.77%, stage 7 −2.16%. All 6,600 A/B frames, 2,176 focused cases and 72 non-SIM
DMA cases pass; fresh independent reference checks pass seed 4 to 9000 and 1800 warship frames. Hatari logic throughput
+0.64% / +1.52% in the warship/stage-7 replays, zero late border/palette events. Not a 2x gain. See
[retained changes, 68000 choices, rejected variants and reproduction](docs/native-structure-results.md).

## Sound: the plan (agreed 2026-11-01, not started)

R-Type's sound is the YM2151 alone (MAME 0.286 `irem/m72.cpp`: `rtype()` removes the DAC, the set has no samples
region, `rtype_sound_portmap` has only the YM2151 and the latch; the Z80's program is RAM, loaded by the main CPU).
The port keeps the main CPU's sound commands in a ring (`src/core.s`).  The plan:

* **Effects as PCM through the DMA sound**: each effect command rendered once at build time from the exact FM sound
  (MAME, one latch command at a time, `-wavwrite`; or a Python port of ymfm), 8-bit mono ~12.5 kHz (~12 KB a second).
  Starting one is a few DMA register writes, no CPU while it plays.  One DMA channel: a priority rule first (a more
  important effect replaces a lesser one); Kung-Fu Master's mixing ring (`games/kungfum`, `snd_mix`) if overlaps matter.
* **Music on the YM2149**: the driver's register writes with the effect commands left out, through `engine/opm.py`
  (carriers' pitch and loudness, Commando's way: 8 FM channels mixed down to 3).
* **Care**: the driver lends music channels to effects - record effects and music apart; identify which commands are
  effects and which are tunes; check against MAME by ear and by register logs.  Memory: a few hundred KB of effects
  (fine on the 14 MB machine; the release size later).

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
