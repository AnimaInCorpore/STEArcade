# Roc'n Rope (Konami, 1983) on the Atari STE

![Roc'n Rope on the STE (Hatari)](docs/screenshot.png)

MAME set `rocnrope` (`konami/rocnrope.cpp`, MAME 0.286 source).  The main CPU (KONAMI-1, a 6809 with encrypted opcodes,
40 KB at $6000) is statically translated to 68000 code (`engine/m6809x.py`) and checked against a reference board in
lock-step.  The sound board (a Z80 with two AY-3-8910s, Time Pilot's) is translated too (Pooyan's method: the driver runs
on the STE, its two AYs are register files, their six channels go to the YM2149 each arcade frame).  The picture is MAME's ROT270 picture, 224 x 256, centred in the 320-pixel screen with the top and bottom
borders open, drawn by `src/render.s` (tile cache, sprite cache, generated Blitter code from `engine/sprite_programs.py`);
one flat 16-colour palette (the arcade's lookup PROMs use palette entries 0-15 only, so the fit is near exact: mean
error 0.9 a channel).  Status: **Playable with the cheats' help**: a 20000-VBL Hatari run (2026-11-08, `-D AUTOPLAY=1 -D CHEATS=1`: the cheats of the MAME pack and the stage finished by the stage-clear state bytes three times in each 4000-VBL period) went through stages 1-7 (the cliffs, the waterfall, the rotating cross, the cave / mountain, the ice stage) without a crash or bad pc; the sound was on (nobody listened).  No stage is finished by play alone (the AUTOPLAY walk is not a player).
Speed (Hatari, STE, 4 MB, TOS 2.06, DEBUG build, sound on, that run's 20001 VBLs: boot and attract included): 21623 arcade frames = 54.1 a second (90% of 60) and 10985 pictures = 27.5 a second, no late border events; stage 1 play alone 55 frames and 29 pictures a second; without the sound (`-D NOSOUND=1`, 2026-11-07) 60 frames and 48 pictures.  Busy stretches (stage 3's pillar and cross, stage 6 ice) were not timed separately: the simulator's logic is 68-76k cycles a frame there against ~60k in stage 1.
**Speed audit** (2026-11-08; Musashi cycles, the tests' frames; Hatari: play window of an AUTOPLAY run with sound, 55.0 arcade frames = 92% of 60 and 29.3 pictures a second, before and after the same within the noise).
Profile: logic 58-88k cycles a frame (stage 1 ~60k, stage 3 ~67k; the 6809 side is flat: the top 64-byte block, $6A00's
table scan for a tile copy, is 12%, nothing else over 8%); a picture 55-64k CPU + 12-15k Blitter bus cycles: the cells
the game changes (tile_changed 28%, copy_cells 21%, render_tiles 11%), sprites (draw_one 13%, restore_damage 6%,
bake_sprite 4%).

| Technique | Status | Result |
|---|---|---|
| fixed slots, fast forms, ret weights, call summaries (6809) | applied from the start | - |
| video_inline (tile stores list their cells) | applied; PSHU fills added (`video_push`) | correctness: stage 3 |
| writer marks instead of RAM comparison | applied (cell list + `cell_dirty`, one compare per listed cell) | - |
| leaves in place, 6809 `inline_calls` | n/a (the option takes hand-written code, no automatic leaves); the sound Z80 uses `inline_leaves=6`, `inline_rst` | - |
| window guards | n/a (flat 64 KB) | - |
| flags_at at the idle hook | n/a (the idle point is a native, `rr_idle`) | - |
| natives at hot routines | not done: flat profile (best candidate `$6A0B`, ~6% of the 6809 time, ~4% of the logic) | - |
| sound work | sound Z80 translated with leaves/rst inline, tick schedule 5.8 a frame; build-time recordings rejected (the driver is the game's own and short) | sound ~12% of the logic |
| sprite_programs reordered-source passes | applied (the generated code per shape) | - |
| per-slot sprite cache, drawn-lines damage (restore_damage copies the last rectangles) | applied | - |
| tile key from a 256-entry table (`tile_attr`) | applied | picture -3.0% (58.7k -> 56.9k, seed 17), tile_changed -3.6% |
| `main_vlist` clipped once, no per-byte range checks | applied | PSHU list 4.5k -> 3.4k cycles in stage 3, logic -1.4% |
| render_tiles' constant addresses hoisted | applied | -0.4% |
| hardware scroll, palette epochs / DEDICATED, frozen colour cycling, second layer as pieces, contour restores, HUD as its own image | n/a (one tile layer, no scroll, one flat palette, no cycling) | - |
| erase only what can be seen | not applied: sprites are clipped at the group-aligned edges and drawn whole into the guard rows, which are erased with the rest | - |
| pictures-per-second schedule | the runtime's (3 buffers, one picture per two arcade frames when slow) | - |

No effect has to go; the biggest remaining costs are the 6809 logic (flat) and the cell churn of the animated tiles
(a blinking 3 x 4 block every frame in stage 1), which the arcade rewrites by design.

Started 2026-11-07 from Track & Field's runtime and logic tests and Time Pilot's vertical renderer.

## Build and run

```sh
python port.py cover rocnrope               # coverage: ref/cover.py seeds 1-19 (60000 frames for 12-15), ref/cover_sound.py
python port.py build rocnrope               # -> run/rocnrope/ROCNROPE.PRG
python port.py test rocnrope                # lock-step (seeds 1, 4, 10, 12, 17-19), render (seeds 4, 17, 18), sprite edges, sound
python port.py mame rocnrope                # the reference against MAME (set MAME to a binary that knows rocnrope)
python games/rocnrope/tools/prepare.py      # verify assets/roms/rocnrope.zip, unpack to assets/roms/extracted/rocnrope/
python games/rocnrope/tools/build.py --sim  # -> run/rocnrope_sim (Musashi, for the tests); --debug, --frames N, -D AUTOPLAY=1
python games/rocnrope/tools/logic_test.py 3000 --seed 4        # the translation in lock-step with the reference
python games/rocnrope/tools/render_test.py 3000 --seed 4 --start 900   # the STE picture against the reference
python games/rocnrope/tools/sprite_test.py                      # edges, 16 shifts, holes, guards, 64 KB crossings
python games/rocnrope/tools/build.py --sim --tag rocnrope_snd && python games/rocnrope/tools/sound_test.py 3000 --seed 4 --tag rocnrope_snd
python games/rocnrope/ref/sound_cmp.py 1 4000                   # the STE's sound schedule against the reference board
powershell -ExecutionPolicy Bypass -File games/rocnrope/tools/hatari.ps1 -Frames 3000 -Every 250   # hidden Hatari + stills
```

Supply `assets/roms/rocnrope.zip` (MAME's parent set; `docs/rom_manifest.json` has the 16 files' sizes, CRCs and
SHA-1s).  Nothing ROM-derived is in git.  The MAME comparison needs a binary that knows `rocnrope`
(`F030Arcade/third_party/wolfmame-0248/mame.exe` does), started through `engine/mamewin.py`.

## Controls

**5/6** coin 1 / 2, **1/2** start, **arrow keys** move / climb, **Space / Z** button 1, **Control / X** button 2; player 2 (the second player's turn) **A D W S** move, **Q** button 1, **E** button 2; **Esc**
quits.  Joystick port 1 player 1, port 0 player 2 (fire = button 1); Jaguar pads as in the other ports (A, C button 1,
B button 2).  DIP switches: MAME's defaults (3 lives, difficulty 5, bonus 20000 / 60000, demo sounds on); upright only
(the cocktail's flipped screen is not drawn).

## State

* **Reference board**: equals MAME 0.286's `rocnrope` (WolfMAME 0.248 binary): 0 differing pixels and 0 differing pens at
  frames 600-3600, and 0 differing bytes of $4000-$5FFF at the same frames (`ref/mame_cmp_rocnrope.py`).  At frames 60
  and 300 (the boot's RAM test) the pictures differ (not investigated: the test fills the RAM pseudo-randomly) and
  the RAM differs in two bytes at frame 60.
* **Logic**: exact against the reference's port schedule: `tools/logic_test.py`, seeds 1, 4, 7, 9, 10 for 3000 frames
  each (attract, coin, start, play, deaths; infinite lives; stages poked via $50C1; two players): RAM $4000-$5FFF,
  the RAM vectors, latch Q0 / Q7 and the sound commands, every frame.  About 40-55 K 68000 cycles a frame (Musashi).
* **Picture**: exact in the shown colours: `tools/render_test.py`, 0 differences in 2100 pictures each of seeds 1, 4, 7
  and 9 (frames 900-3000); `tools/sprite_test.py`: 154 made-up pictures exact (both side edges at every shift, flips,
  holes, guard lines, 64 KB crossings, sequences).  Sprites clip at the picture's group-aligned left and right edges
  ([AGENTS.md](../../AGENTS.md)).
* **Hatari** (F030Arcade build, STE, 4 MB, TOS 2.06): boot, attract (title, ranking, demo), play, the bird's scene; no
  crash.  Looked at 14 stills of one run only, with the AUTOPLAY input.
* **Sound** (2026-11-08): the driver's translation runs the driver's own commands in the simulator and equals its
  model (`tools/sound.py` STEBoard) every arcade frame: sound RAM, both AYs' registers, the YM's registers and channel
  choice (`tools/sound_test.py`, seeds 1, 4 and 10, 3000 frames each: 220 / 225 / 142 commands).  The STE's tick schedule
  against the reference board (the sound CPU at its clock, commands at the main CPU's instants):
  99.25% of the audible channel states equal over 4000 frames (`ref/sound_cmp.py`; the rest: an effect that starts up
  to a frame later, or in another free slot).  Heard only as a recording: Hatari with its sound on (`hatari.ps1 -Sound 1`) saved
  44.1 kHz audio of an AUTOPLAY run: silent before the coin, then the intro's tune (peaks change between 220 and 1170 Hz),
  then a steady low tone (peak 84-93 Hz, RMS about 1500) for the 18 s of play; nobody listened to it.  The AY mix-down
  onto three YM voices is lossy by design (loudest three of six).  The model is not compared with MAME's audio.
* **Stages finished** (2026-11-08): `$7AA9` is the stage-clear handler (`$5005` = 3 selects it, `$5008` = 0 starts its sequence, `$7AE3` counts `$50C1`).  Coverage seeds 20-23 (cheats, a stage finished every 900-2500 frames, 60000 frames each) add 679 pcs; `logic_test.py` seeds 20-23, 20000 frames each, and `render_test.py` seed 21 (1858 pictures) are exact.
* **Real play to a stage's end: not reached** (2026-11-08): `ref/explore.py` is a Go-Explore search (docs/go-explore.md) on the reference machine: cells of 8 x 8 pixels of the player (sprite slot 0), snapshots restored, random 6-frame segments of direction and buttons.  Three 40-minute runs (1.59 million simulated frames each, 137-186 cells) got the player at best to row 127 of 255 on stage 1 (about halfway up the cliffs), none to the stage's end; the stage clears above stay forced through the state bytes.  A guided search (jump timing onto the ropes) or recorded human input is still needed.
* **Sound against MAME** (`tools/sound_mame.py`, 2026-11-08): the commands the game sends, written into MAME's sound latch at known frames (Demo Sounds off) and into the STE's board model; semitone spectra per piece: 13 of 23 alike (cosine > 0.7); the others are noise effects (the comparison renders tones only), pieces MAME's own game sounds overlap, or effects silent in both.  Levels and timing were not compared.  Nobody listened.
* **Later stages** (2026-11-08): the stage index is **$50C1** (0-based; the HUD prints it + 1 at the start of a game, a
  few hundred frames after the coin: poked later it is reset).  Poked before the HUD draws it, the game plays that stage:
  the scenery repeats every four stages (1: the cliffs, 2: the waterfall, 3: the rotating cross, 4: the cave), and
  stage 8 plays like 4.  Coverage seeds 7-9 (stages 2-4, lives kept) and 16-19 (MAME's cheats: lives $50C0,
  invincibility $51C0 = 2 / $51DE = 0, bonus $509B; stages 2, 3, 4 and 8) add 920 pcs to those of seeds 1-15; seeds
  12-15 alone play 60000 frames of stage 1 with the cheats (XNC at $B610 translated).  Lock-step (`logic_test.py`):
  seeds 17, 18 (3000 frames) and 19 (12000 frames) exact.  The render test found a real bug in stage 3: the game fills
  the pillar's tiles with `PSHU` (U pointing into the video RAM), whose stores the translation did not list as changed
  cells (stale tiles, 400-700 differing pixels from frame 3820); `Program.video_push` / `main_vlist` list them now
  (engine/m6809x.py, backwards compatible), and the render tests of seeds 16-19 (1667 pictures each) and 17 (1000)
  are exact.  Not reached: the stage *completing* (random play never gets the player to the top: the exit, the
  bonus count and the stage change happen only by the poke), so the code after a stage's end, and a stage poked above 8
  (the indexes' tables), are covered only as far as the pokes got.  MAME was not run with the poke: the reference's
  pictures of stages 2-4 are the reference machine's, whose rendering equals MAME's only where stage 1 shows it.
* **Not done / not verified**: the cocktail flip; the Mega STE; the full game (no stage is completed; stages above 8 and the code after a stage's end are not covered); a real controller
  run; `docs/sprite-preparation.md`'s reordered-source measurements (the sprite code is the shared generator's
  output, not measured against alternatives here); the speed in busy scenes; release packing (`tools/release.py` lists it).

## How it works

* **Board**: KONAMI-1 at 1.536 MHz, 256 x 256 total / 224 visible lines, 60 Hz, ROT270.  One 32 x 32 tilemap of 8 x 8 4 bpp
  tiles (colour RAM $4800, video RAM $4C00; code = byte + 256 x colour bit 7) and 24 sprites of 16 x 16 4 bpp (RAM
  $4000 / $4400: attribute, y / x, code), pens through two lookup PROMs into a 16-entry palette.  The IRQ vector is in
  RAM ($FFF2-$FFFD, written through $8182-$818D); MAME's driver init patches one ROM byte ($703D), as does `rom_image()`.
* **Reference** (`tools/machine.py`): `RocnRope` is the board in MAME's schedule; `RocnRopePort` the STE's.  The
  foreground is a task loop ($6065: queue at $5100-$513F, read pointer $501A); with the queue empty it calls $6094 (the
  coin text's blink) round and round; the IRQ ($70A0) plays the game.  The port's idle point is the BSR at $6070: the
  IRQ is delivered there (return address $6070).  Two CWAI #$EF sites ($6451, $69FC: the intro's screen clears) wait for
  the next interrupt: they are hooks (`rr_cwai_*`) that do the same wait.  One empty round runs per frame after the
  tasks (the arcade runs it thousands of times; it is idempotent).
* **Translation** (`tools/gen.py`): flat 64 KB (`rr_mem`), DP $50 (sites that ran with another DP, e.g. the sprite
  copy routine's $40, are `dp_sites` from the coverage), the I/O ($3000-$3100 inputs, $8000-$81FF writes) through
  `main_io_r` / `main_io_w`, byte stores to the tile RAM inline (they list the changed cell).  The task table at $6074
  has 16 handlers: $67FE was never reached by a coverage run and is a root.  One instruction, the undocumented XNC at
  $B610 (opcode $02, in code no seed reached), is not translated (it stops at `main_unsupported`); `engine/m6809x.py` got
  its flag liveness for it (the only engine change).
* **Picture** (`src/render.s`): after Time Pilot's renderer with Track & Field's 4 bpp tile and sprite baking: three
  display buffers and a clean screen holding the tiles; changed cells are drawn into it (`movep.l`) and copied to each
  buffer; sprites by the generated Blitter code (HOP 2 / OP 3, one end mask per row, no AND + OR pairs), damage rectangles
  restored from the clean screen.  The turn is in the assets (`tools/assets.py`: tiles and sprites as `np.rot90(raw, 1)`;
  raw flip x is the picture's flip of the rows, raw flip y of the columns).  No layer is drawn over the sprites.
* **Sound** (`tools/sound.py`, `tools/sndgen.py`, `src/sound.s`, all after Pooyan's: the same driver family): a Z80 at
  1.789772 MHz with ROM `rnr_7a.snd` + `rnr_8a.snd` at $0000-$1FFF, RAM $3000-$33FF, two AY-3-8910 at $4000-$7FFF.  The
  driver's loop head is $00C2 (`ei`), the timer waits end at $00D1; the command handler is $0038.  Each arcade frame the
  commands the main CPU wrote (latch Q1's rising edges, the byte at $8100: `snd_ring`) run the handler, then 5.83 ticks
  run the loop once each; `snd_ym` picks the three loudest of the six AY channels for the YM2149.  The RC filters
  ($8000-$FFFF stores) are not modelled.

## Speed

Logic about 40-55 K 68000 cycles an arcade frame in the lock-step runs (Musashi); a picture about 55-70 K CPU cycles
and 10-15 K Blitter bus cycles (`render_test.py`).  Hatari: see the summary.  Nothing was optimised or measured beyond
that (no natives; every pass is a short HOG pass from the shared generator).  `docs/speed.md`'s checklist has not been
gone through for this port.

## Tests and tools

`tools/prepare.py` (manifest), `tools/machine.py` (reference), `ref/mame_cmp_rocnrope.py` (against MAME), `ref/cover.py`
(coverage: seeds 1-3 play, 4-6 infinite lives ($50C0), 7-9 with $50C3 poked to 2 / 5 / 7, 10 two players, 11 DIPs),
`tools/gen.py`, `tools/assets.py`, `tools/build.py`, `tools/logic_test.py`, `tools/render_test.py`,
`tools/sprite_test.py`, `tools/hatari.ps1`.  `python port.py test rocnrope` runs them.

## Lessons

* 2026-11-07: **CWAI is a wait**: the intro's screen clears use CWAI #$EF; a port schedule that treats only the task
  loop as idle never leaves the first CWAI.  The reference core pushes the whole state at the CWAI; the lock-step test
  ignores those 12 stack bytes (the runtime pushes them at the IRQ).
* 2026-11-07: **Where the IRQ's RTI lands matters**: it lands on the BSR of the empty-queue round; with tasks queued that
  BSR runs before them (the real CPU does the same).  The runtime's idle hook therefore runs the translation on when the
  queue is not empty, and lets the round run once when it is, as the reference's order (IRQ, tasks, one round) says.
* 2026-11-07: **A routine that sets DP** ($70CC: `LDA #$40; TFR A,DP` for the sprite copy) breaks the translation's DP
  assumption silently: the coverage records the DP of every pc (`dps`) and gen.py turns it into `dp_sites`.
* 2026-11-08: **Odd word accesses** only fault in Hatari: a `ds.w` after an odd number of bytes (`wait_pc`, after the
  sound moved `snd_latch` out of this file) crashed the first Hatari run with the sound (CRASH.TXT: address error,
  PC in `rr_idle`).  The simulator never sees it; `even` before every word after byte variables.
* 2026-11-08: **Invincible random play finds code that plain play does not** (312 pcs in 60000 frames), among it an
  undocumented-opcode routine; the translator got XNC (`m6809x.py`, memory forms).
* The boot's RAM test takes about 360 arcade frames of CPU time (9.3 M cycles of the 6809 in the reference).

## Verification

Evidence is above (MAME comparison, lock-step seeds, render and sprite tests, one Hatari run with stills).  No
recorded or PPO play, no full-game run, sound only as register streams (never heard): see the [status policy](../../docs/port-status.md); the port is
**Incomplete**.
