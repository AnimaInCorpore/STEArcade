# Mikie (Konami, 1984) on the Atari STE

![Mikie on the STE (Hatari)](docs/screenshot.png)

MAME set `mikie` (Konami GX469; `konami/mikie.cpp`).  The main CPU, a plain MC6809E (not KONAMI-1: the opcodes are not
encrypted), is statically translated to 68000 code (`engine/m6809x.py`) and checked against a reference board in
lock-step.  The picture is MAME's ROT270 picture (**the monitor is turned: 224 x 256, portrait**), centred in the
320-pixel screen with the top and bottom borders open, sprites by generated code (`engine/sprite_programs.py`), exact
against the reference in the shown colours; one 16-colour palette by the shared default fitter, flat; the sound board's Z80
driver translated too, its two SN76489As on the YM2149 (three of the eight voices at a time).  Status: **Incomplete** (root README): the
picture, the logic and the sound driver are verified (below), the YM mix-down (three voices of eight) is a reduction by
design, and no full-game play has been verified.

## Build and run

```sh
python port.py cover mikie                  # coverage: ref/cover.py seeds 1-9 (30000 frames each, ~10 min in parallel), ref/cover_sound.py
python port.py build mikie                  # -> run/mikie/MIKIE.PRG (-D NOSOUND=1: without the sound)
python port.py test mikie                   # lock-step (seeds 1, 4, 7), render (seed 4), sprite edges, sound (game and random commands)
python port.py mame mikie                   # the reference against MAME (ref/mame_cmp_mikie.py)
python games/mikie/tools/prepare.py         # verify assets/roms/mikie.zip, unpack to assets/roms/extracted/mikie/
python games/mikie/tools/build.py           # -> run/mikie/MIKIE.PRG (--sim: run/mikie_sim; --assets: colours again)
python games/mikie/tools/logic_test.py 20000 --seed 4     # the translation in lock-step with the reference
python games/mikie/tools/render_test.py 3000 --seed 4 --start 500   # the STE picture against the reference
python games/mikie/tools/sprite_test.py                   # edges, all 16 shifts, holes, guards, 64 KB crossings
python games/mikie/tools/sound_test.py 6000 --seed 4 [--random]   # the STE's sound player (Musashi) against tools/sound.py, every frame
python games/mikie/ref/sound_cmp.py 1 4000                # the STE's tick schedule against the timed Z80 board (SN voices' states)
python games/mikie/ref/mame_sound_cmp.py 1500             # the timed Z80 board against MAME's SN writes (attract, 100.00%)
powershell -ExecutionPolicy Bypass -File games/mikie/tools/hatari.ps1 -Frames 3000 [-Sound 1]   # hidden Hatari (F030Arcade build), AVI stills (and its audio: mikie.wav) in run/mikie_hatari
```

Supply `assets/roms/mikie.zip` (MAME's parent set; `docs/rom_manifest.json` has the files' sizes, CRCs and SHA-1s).
Nothing ROM-derived is in git: the graphics, colours and ROM image are made into `build/mikie/` and assembled into the
program.  Paths are relative to this folder; `engine/`, `tools/`, `port.py` and `docs/` at the top are the repository's.

## Controls

**5/6** coin 1 / 2, **1/2** start, the arrows move, **Space / Control / Z** button 1, **Alternate / X** button 2, **Esc**
quits.  Player 2 on the keypad: **4 6 8 2** move, **0** button 1, **.** button 2.  Joystick port 1 player 1, port 0 player 2 (direction, fire = button 1).  Jaguar pad / PowerPad: pad A player 1,
pad B player 2, the D-pad, **A / C** button 1, **B** button 2, **Option** coin, **Pause** start.  DIP switches: MAME's
defaults (3 lives, upright, bonus 20k 70k 50k+, easy, demo sounds on; DSW3 flip off).

## State

* **Reference board** (`tools/machine.py`, from `mikie.cpp`; MAME's source tree of F030Arcade, 0.286): the picture and
  the pens equal MAME's: `ref/mame_cmp_mikie.py` at frames 60 / 300 / 600 / 900 / 1500 / 2400 / 3600 / 5000 / 7000 /
  9000 / 12000: **0 of 4096 pens and 0 differing pixels** in every frame (palette banks 0 and 7 seen), and the RAM
  ($0000-$00FF, $2800-$3FFF) equal except the bytes the interrupt pushes on the stack (frame 3600).  MAME was
  WolfMAME 0.248 (`F030Arcade/third_party/wolfmame-0248`, through `engine/mamewin.py`); no difference to the 0.286 source
  was found.  Found by this check: the tilemap has no transparent pen (a front tile covers its whole 8 x 8; sprites'
  pen 0 is transparent), and ROT270 turns the 256 x 224 raw picture a quarter counter-clockwise.
* **The port's schedule** (`MikiePort`): the boot self-tests (RAM / ROM checks, the test grid: 692 frames) are skipped,
  the program starts at its own initialisation `$6093`.  This part of the reference is **not compared with MAME** (the
  timing differs); only the unpatched board is.  The foreground is a task loop (`$61BC`, queue `$2A40`); its idle point
  `$61C5` and the `CWAI #$EF` of `$6FFF` (a task waiting for the frame) are natives that deliver the IRQ at the vertical
  blank (`mk_idle`, `mk_cwai` in `src/mikie.s`; the CWAI pushes its state at once as the 6809 does).
* **Translation** (2026-11-08): 12159 instructions, none unsupported or missing (8540 before the later rooms were covered) (the CWAI is the native).  One instruction that
  static descent reached, an `LBRA $D791` into zero padding at `$6E80` that never runs, is a `main_dead` hook
  (`gen.py` DEAD); this needed a small, backwards compatible addition to `engine/m6809x.py` (`Program.no_follow`: pcs whose
  successors discovery does not follow).
* **Logic**: exact against the reference's port schedule.  `tools/logic_test.py`: RAM $0000-$00FF and $2800-$3FFF (sprite
  RAM, RAM, video and colour RAM), the latch (Q6, Q7), the palette bank, the sound commands (Q2's rising edges).  Seeds 1-9
  20,000 frames each (attract, coin, start, random play with and without kept lives, two players, other DIP switches), all
  PASS.  (The pushed CC's H bit is ignored on the stack: the translation keeps H only where DAA reads it.)
* **Coverage** (`ref/cover.py`, 30,000 frames x 12 seeds, 2026-11-08): seeds 1-9 random play reach the title, the attract mode
  and room 0 only (the palette bank stays 0 for 30,000 frames of play).  The later rooms are reached by hand: the room is
  RAM `$2971` (0-6; its palette bank comes from the table at `$D1C6`) and `$2908 = 1` starts a room, so seeds 10-12 start
  the next room every 700 / 950 / 1200 frames of play, in the orders +1 / +2 / +3 (mod 7), with player 1's lives kept.  They
  add about 3300 executed instruction addresses (8994 in all).  Jump tables (`JMP / JSR [A,U]`, 51 sites) were only partly
  used by random play (the first Hatari run of room 3 stopped at `main_badpc` on a direction no seed's enemy had taken): `gen.py`
  `complete_tables` adds every entry of such a table, and the tables of the sites in that code, as targets (entries from the
  table's base while they are ROM addresses within $300 of each other and not inside an executed instruction).  Not
  reached by any play: the ending, the high-score entry, the service mode (their code is translated only where the tables
  or descent found it).
* **Picture**: exact in the shown colours.  `tools/render_test.py`: 0 differences in 280 sampled pictures of seed 1 (frames
  100-1500) and 656 each of seeds 2, 4 and 6 (frames 100-6000), and 786 of seed 10 (all seven rooms, frames 500-6000); `tools/sprite_test.py`: 154 made-up pictures exact (both
  side edges at every shift, holes, flips, overlaps, the guard lines above the picture, 64 KB crossings, 60 pictures in
  sequence).
* **Sound** (`tools/sound.py`, `tools/sndgen.py`, `src/sound.s`, after Track & Field's; the board: a Z80 at 3.58 MHz, ROM `n10.6e`,
  two SN76489As, the main CPU's command latch, a timer read; no speech, DAC or tune loops).  The Z80 driver is translated to
  68000 code (`engine/z80x.py`; coverage `ref/cover_sound.py`: the game's commands of seeds 1-9 and random commands, 1049
  instructions, none unsupported) and runs in the schedule of a tick (the driver's main loop waits for the timer's bit 2:
  every 4096 Z80 cycles, 14.4 a frame): each arcade frame the commands the game wrote since the last frame run the IRQ
  handler, then the frame's ticks.  Its writes fill two SN76489A register files; each frame their eight voices go to the
  YM2149's three channels (the three loudest, a voice keeping its channel; the noise as the YM's; one noise period).
  Verified: (1) `ref/mame_sound_cmp.py`: MAME's two SN chips' writes in 1500 attract frames (1467 and 1461 bytes, 21
  commands) equal the timed Z80 reference's, **100.00%, in order**; (2) `ref/sound_cmp.py`: the tick schedule's SN voice
  states against the timed reference, 99.2% of 10028 states equal in order (an effect starts up to a frame late); (3)
  `tools/sound_test.py`: the STE's player (Musashi) against its model every frame (sound RAM, both chips' registers, the
  YM's registers and channel choice, the schedule's time): seeds 1, 4 and 7 (4000-8000 frames) and random commands (seeds
  1-3, 6000 frames, added to the game's own): PASS; (4) Hatari (`-Sound 1`, the AVI's audio): music-like tones at the pitches
  MAME's audio shows in the attract (about 782, 590, 528, 132 Hz), silence between; **not heard by a person, and no
  waveform comparison with MAME was made**.  Reductions by design: three of the eight voices at a time (the YM has three
  channels: the loudest win; a tone's pitch is on the YM's period grid), the YM's
  levels by a coarse table (3 dB steps); the SN's noise on one YM noise generator at the chip's nearest period (periods
  above 31 are clamped); the main loop's `ei` windows are not interrupt points (a command waits for the next tick: up to
  a frame later than the arcade).  The driver's own self-test and boot RAM test are skipped (it starts at `$0156`).
  Speed: the sound adds about 6000 68000 cycles an arcade frame (the schedule's idle ticks and each channel's counting
  ticks are natives: a quiet tick is free, a counting-only run of ticks is skipped in one step).
* **Sprite list sort** (`mk_sort`, a native at `$9933`: the game's bubble sort of its 3-byte sprite records, the largest single
  cost in a profile of the logic, replaced by an equal stable insertion sort; lock-step equal, seeds 1-9 x 20000 frames, below).
* **Hatari** (F030Arcade build, hidden, `tools/hatari.ps1 -Frames 3000 -Sound 1`, AUTOPLAY build: a coin, start, walking and
  hitting): the title, the attract picture and the first classroom run and look right in the AVI stills (colours,
  turned picture, sprites, the heart and flag HUD); 3001 VBLs with the sound on: 3290 arcade frames (54.8 a second, 91% of
  60), 2090 pictures (34.8 a second), 2 border fallbacks, no late border events (before the sound and the sort native:
  55.8 a second without sound; the cost of the sound is about 2 points of rate, the sort gained back about 1).  The game
  does not reach the full arcade rate: **it runs at 92% in Hatari's attract and first room** (55.8 arcade frames a second, 35.4 pictures, after the speed audit below; 91% before it).
* **Later rooms in Hatari (2026-11-08, no AVI, `tools/hatari.ps1 -Frames 3900 -Room k`, sound on, the room started by hand at frame 900 of
  the play, rates over the whole 3900 VBLs, the first ~900 frames being attract)**: room 0: 57.0 arcade frames a second
  (94%), 31.7 pictures; 1: 56.6 / 44.7; 2: 57.2 / 22.9; 3: 55.8 / 40.9; 4: 57.3 / 26.7; 5: 55.8 / 32.4; 6: 53.5 / 20.5 (room 6
  before the table fix, not re-measured).  A **long run** of 20,001 VBLs (`-Frames 20000`, the AUTOPLAY build: coin, start,
  walking and hitting, lives kept, a room started by hand every 500 frames from frame 900 of each 4000, rooms 0-6 five
  times): **no crash or bad pc**, 20,553 arcade frames (**51.4 a second, 85%**), 10,550 pictures (**26.4 a second**), 2 border
  fallbacks, no late border events.  The 85% is the busy figure (a room start clears the screen over 28 frames and redraws
  everything; in the later rooms a picture costs ~112k CPU + 42k Blitter cycles against ~67k + 30k in room 0).  Typical play
  in one room is the 92-94% above.  This is play by a fixed script with a room cheat, **not a played game**: nobody finished a room.
* **Sound against MAME, Hatari's audio (2026-11-08, `ref/wav_cmp.py`, 30 s of attract, windows of 0.25 s, best alignment
  of the two recordings)**: the SN write streams are equal (above), but the audio itself differs by design: of 34 windows with
  a dominant pitch in both, 26% agree within 3% (the YM plays the three loudest of eight voices; MAME mixes all); Hatari's level is
  about 6.6 dB higher than MAME's; both show the same pitches (782, 700, 590, 528, 132 Hz).  **Nobody has listened to it.**
* **Controls** (the IKBD scan codes and `compose_inputs`, checked against the table; not tested key by key on a machine):
  coin 1 / 2 on 5 / 6, start 1 / 2 on 1 / 2, player 1 on the arrows with Space / Control / Z and Alternate / X, player 2
  on the keypad (4 6 8 2, 0, .) or joystick port 0 (one fire button = button 1), pads A / B.
* **Not done / not verified**: the cocktail cabinet and the flip screen (`render_raw` raises `NotImplementedError` for the flip
  latch; the STE renderer ignores it); the service mode, the ending and the high-score entry; a game played to the end by a person; the other sets (`mikiej`, `mikiek`, `mikiehs` share the
  main program: the graphics ROMs differ); the driver's paths no seed's commands reached (random commands 0-$7F reach most
  of the effect range; a jump through a table entry nothing used would stop at `snd_badpc`); sprite preparation
  measurements against the other methods (`docs/sprite-preparation.md`: this port uses the shared generated code as Track
  & Field does, not measured separately); the Mega STE; hearing the result on real hardware or an emulator by a person.

## Speed audit (2026-11-08; docs/speed.md checklist)

Profiles (`tools/logic_test.py N --seed S --profile`: every 68000 instruction charged to its 6809 block or runtime label;
`tools/render_test.py ... --prof`): the logic is flat (largest blocks: the sprite list's copy 7%, the record emitter 8%,
the sound 8%, the sort 4%); a picture (CPU 74.3k + Blitter 29.8k cycles before) spends 21% in `draw_one`, 17% in
`draw_sprites`, 9% restoring damage, 6% baking, 5% each in `copy_cells` / `tile_convert`.

| Technique | State | Before -> after |
|---|---|---|
| Register maps, second pass, `fixed_slots`, `fast_forms`, `ret_weights`, `call_summaries` | applied (gen.py) | - |
| `video_inline` writer marks (cell list), no RAM comparisons | applied | - |
| Window guards, leaves in place (Z80 side), `flags_at` at the idle hook | n/a (flat 6809 map; the idle point is a native) | - |
| Natives at hot routines | applied: sort (`mk_sort`), sprite-list copy (`mk_sprcopy`, $6253), idle, CWAI | the translated copy loop ~5k cycles a frame -> 2.8k (profile of seed 4) |
| 6809 `inline_calls` | applied to the record emitter $998B (`mk_emit`, 20 calls a frame; flags dead at all three sites) | emitter ~3.4k a frame in its inline form; with the copy: seed 4 logic 71670 -> 65459 cycles a frame (-8.7%); logic lock-step exact on seeds 1, 2, 4, 5, 7, 9 (3000-20000 frames; seeds 3, 6, 8 not rerun) |
| Sound work at build time | partly: the driver is translated, the ticks of idle channels are skipped by natives; recordings per effect not tried (the effects depend on the game's commands in time) | sound ~6k cycles a frame |
| Sprite key by two table lookups (code, attribute) instead of bit tests | applied | `draw_sprites` 12.5k -> 10.2k cycles a picture |
| Cell rows a sprite touches by a table per Y (front-tile test) | applied | `row_mask` 3.2k per picture -> a lookup; a picture CPU 74.3k -> 68.8k (-7.4%) |
| `sprite_programs` reordered-source passes, end masks = opaque pixels, no AND + OR | applied (shared generated code) | - |
| Drawn-lines damage, clean-screen restore | applied (damage list per sprite) | - |
| Per-slot sprite cache, palette epochs / stamps, scroll, parallax, colour cycling | n/a (no scroll or parallax; one palette bank; no cycling) | - |
| HUD as its own image, spreading big redraws, picture schedule | not tried (no profile shows them) | - |
| Fill of the video RAM at a room start ($6FE8, 28 rows x 32 cells, one row a frame) as a native | rejected: only the 28 frames of a room start, not in play | - |

Hatari (`tools/hatari.ps1 -Frames 3000 -Sound 1`, attract, coin, first room): 54.8 -> **55.8** arcade frames a second
(92% of 60), 34.8 -> 35.4 pictures a second.  Logic and picture are exact as before (see State); the remaining cost is
spread over sprites (36 entries a picture), the sound and the damage restore.

## How it works

* **Memory** (`machine.py`): RAM $0000-$00FF, sprite RAM $2800-$288F (36 sprites of attribute, y, code, x), RAM
  $2890-$37FF, colour RAM $3800-$3BFF, video RAM $3C00-$3FFF, ROM $6000-$FFFF; the LS259 latch at $2000-$2007 (Q0 / Q1 coin
  counters, Q2 sound trigger, Q6 flip, Q7 IRQ enable), the palette bank at $2200, the sound latch at $2400, inputs at
  $2400-$2403 and the DIP switches at $2500 / $2501.
* **Video**: a 32 x 32 tilemap of 8 x 8 4bpp tiles, category 1 (colour bit 4) drawn over the sprites; palette PROMs by a
  2.2k / 1k / 470 / 220 ohm resistor network (`machine.mikie_pens`); the palette bank (0-7) selects the colour sets; the
  renderer flushes its caches and draws every cell again when the bank changes.
* **Picture on the STE** (`src/render.s`, after Time Pilot's and Track & Field's): three display buffers and a clean screen;
  changed tiles are converted per (code, colour, flips) into a tile cache and drawn with `movep.l`; sprites are baked per
  (code, colour, flips) into the sprite cache and drawn by generated Blitter code (HOG passes of one or two words, end masks
  = the opaque pixels, no AND + OR passes), edges clipped on 16-pixel groups, whole sprites into the guard lines (eight
  hidden lines above the picture hold the sprites that leave it at the top); the damage is restored from the clean screen.
* **Assets** (`tools/assets.py`): the tiles and sprites are turned (the picture's frame; MAME's flip x is the picture's row
  flip, flip y its column flip), the 4096 pens fitted to 16 colours (`engine/palette_native.py`).
* **Shared code changed**: `engine/m6809x.py` only (the `no_follow` set, above).  Everything else is this folder, the
  registration lines in `port.py` / `tools/release.py` (fixed here: the first commit's Mikie entry had real line breaks inside
  its strings) and the README's table.
