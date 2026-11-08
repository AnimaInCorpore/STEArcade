# Super Basketball (Konami, 1984) on the Atari STE

![Super Basketball on the STE (Hatari)](docs/screenshot.png)

MAME set `sbasketb` (Konami GX405, version I, encrypted; `konami/sbasketb.cpp`).  The main CPU, a KONAMI-1 (an MC6809
with encrypted opcodes, 40 KB of ROM), is statically translated to 68000 code (`engine/m6809x.py`) and checked
against a reference board in lock-step; its foreground loop's head is a native that delivers the IRQ.  The sound board
(a Z80 with an SN76489A, a VLM5030 and a DAC: the Track & Field / Hyper Sports board with its own driver ROM) is not
run: MAME plays each sound command alone and the recording is played on the STE's DMA channel (`src/sound.s`, as Mario
Bros. does).  The picture
is MAME's ROT90 picture, 224 x 256 (portrait, not the 256 x 224 of the other Konami sports games), centred in the
320-pixel screen with the top and bottom borders open, sprites by generated code (`engine/sprite_programs.py`), exact
against the reference in the shown colours; one 16-colour palette by the shared default fitter, flat.  Status:
**Incomplete** (sound by recordings, one clip at a time, heard in Hatari's audio capture for one phrase; ~83-90% of the
arcade's speed and 19-31 pictures a second in Hatari; no full-game verification).
Speed: 49.6 arcade frames a second (83%), 19.4 pictures a second over 5,000 VBLs of the AUTOPLAY script, 54.0 (90%) and
30.6 over 9,000 VBLs (Hatari, `tools/hatari.ps1 -Frames N`, sound build with its audio off, DEBUG build, 4 MB, 2026-11-08).

## Build and run

```sh
python port.py cover sbasketb               # coverage: ref/cover.py seeds 1-21 (~8 min in parallel)
python port.py build sbasketb               # -> run/sbasketb/SBASKETB.PRG
python port.py test sbasketb                # lock-step (seeds 1, 4, 6, AUTOPLAY), render (seed 1), sprite edges, sound
python port.py mame sbasketb                # the reference against MAME (ref/mame_cmp_sbasketb.py)
python games/sbasketb/tools/prepare.py      # verify assets/roms/sbasketb.zip, unpack to assets/roms/extracted/sbasketb/
python games/sbasketb/tools/build.py        # -> run/sbasketb/SBASKETB.PRG (--sim: run/sbasketb_sim; --assets: colours again)
python games/sbasketb/tools/logic_test.py 20000 --seed 1   # the translation in lock-step with the reference
python games/sbasketb/tools/render_test.py 3000 --seed 1 --start 300 --every 3   # the STE picture against the reference
python games/sbasketb/tools/sprite_test.py                 # edges, 16 shifts, holes, banks, guards, 64 KB crossings
python games/sbasketb/tools/sound_capture.py --all         # MAME records each sound command (build/sbasketb/sound/)
python games/sbasketb/tools/sound_convert.py               # -> build/sbasketb/sb_sound.s / .bin (the DMA clips, 12,517 Hz)
python games/sbasketb/tools/sound_test.py 3000 --seed 1    # the DMA driver against the game's sound commands
powershell -File games/sbasketb/tools/hatari.ps1 -Frames 4000 -Every 250   # Hatari hidden, AVI stills, counters
python games/sbasketb/ref/mame_cmp_sbasketb.py [frame ...]  # the reference against MAME
```

Supply `assets/roms/sbasketb.zip` (MAME's parent set; `docs/rom_manifest.json` has the 14 files' sizes, CRCs and
SHA-1s).  Nothing ROM-derived is in git: the graphics, colours and ROM image are made into `build/sbasketb/` and
assembled into the program.  Paths are relative to this folder; `engine/`, `tools/`, `port.py` and `docs/` at the top
are the repository's.

## Controls

**5/6** coin 1 / 2, **1/2** start, **arrow keys** move, **Space / Control / Z** button 1 (shoot, jump), **X** button 2
(pass), **C** button 3, **Esc** quits.  Joystick port 1 player 1, port 0 player 2 (fire = button 1).  Jaguar pad / PowerPad:
pad A player 1, pad B player 2, the D-pad moves, **A** button 1, **B** button 2, **C** button 3, **Option** coin,
**Pause** start.  DIP switches: the 0.286 source's defaults (60 s game, upright, starting score 100-115, ranking data
kept, easy, demo sounds on).

## State

* **Logic**: exact against the reference's port schedule.  `tools/logic_test.py`: RAM $2000-$3BFF (video, colour and
  sprite RAM too), the sprite palette bank $3C20, the scroll $3F80, the latch (Q0, Q1, Q5), the sound commands (each
  write of $3D80).  Seed 1 20,000 frames, seeds 2-20 8,000 frames each (attract; coin, start, random play with the stick
  and three buttons; two players; 30 / 40 / 50 s games, other DIP switches; the service mode with its test screens; no
  coin at all: the whole attract cycle; fixed stick and button patterns) and seed 21, the runtime's AUTOPLAY script, 16,000
  frames.  The reference's self-test is skipped (below), so those are the game's own paths from `$6000` on.
  **The translation covers what the coverage ran** (21 seeds, 12,787 instructions), the entries of 22 jump tables and 42
  more roots (`gen.data_roots`: words of the data and 16-bit load immediates that name a code address not run, right
  after an executed return or jump or as a loaded state, decoding as ordinary code on every path up to run code; the
  object scripts and the `JMP ,U` state machines name their handlers so).  A handler that is neither run, in a table nor
  found so is not translated, and a play pattern that reaches it stops at `main_badpc`; there is no full-game proof
  that none exists (the AUTOPLAY script did reach two before the tables and these roots were added).
* **Picture**: exact in the shown colours.  `tools/render_test.py`: 0 differences in 700 sampled pictures of seed 1's play
  (frames 1000-2400, every 2nd), 740 each of seeds 1, 4 and 6 (frames 300-4000, every 5th) and 675 of seed 5 (two players,
  frames 300-3000, every 4th), and in 400 consecutive pictures (frames 1000-1400) with the generated sprite code and
  again with the row path only (`-D REN_GEN=0`); `tools/sprite_test.py`: 154 made-up pictures exact (both
  side edges at every shift, holes, flips, overlaps, both sprite banks, palette banks 0-255, the guard lines, 64 KB
  crossings, 60 pictures in a row with moving sprites, scrolls and tiles).  `BLIT_STATS=256`: every pass HOG, the longest
  116 bus cycles.  The reference equals MAME (How it works).
* **Sound**: `tools/sound_test.py`: the DMA frame start and control registers of the simulator name the clip the game's
  commands call for after every frame (seeds 1, 4, 6 6,000 frames, seed 21 5,000: 84-195 clip starts each, 0 mismatches).
  Hatari with its audio on (`hatari.ps1 -Sound 44100`: SDL's dummy audio driver, the audio is in the AVI, extracted with
  ffmpeg; 1,200 VBLs, the AUTOPLAY script): 4 sound bursts at the times of the game's four phrases ($AD, $A8, $A7, $A8);
  the first burst's 100 ms level envelope follows clip $AD's shape (9 7 5 2 5 1 1 10 9 against 794 735 671 177 489 267 19
  764 1131), its waveform correlates 0.39 (the clip is resampled and filtered by Hatari).  The other three bursts were
  not matched to their clips individually, the sound was never heard by a person, and nothing was compared to MAME's
  mix.
* **Hatari** (F030Arcade build, STE, 4 MB, TOS 2.06, sound off): boot, attract, coin, start, the AUTOPLAY player's games
  (two starts); no crash, 3 border fallbacks and no late border event in 5,000 VBLs.
* Not done, most important first: a full-game playthrough and any playtest beyond the AUTOPLAY script; the sound's
  fidelity (Sound); speed (Speed); the cocktail flip (`flip_screen` raises `NotImplementedError` in the reference renderer, the runtime
  ignores latch Q0); the arcade's self-test is not run.

## How it works

### The board and the reference

`tools/machine.py` follows MAME's `konami/sbasketb.cpp`: the KONAMI-1 at 18.432 MHz / 12 = 1.536 MHz, 60 Hz, 256 lines,
the IRQ (HOLD_LINE) at the VBLANK (line 240) while the LS259 latch's Q1 is 1; RAM $2000-$2FFF, colour RAM $3000-$33FF
and video RAM $3400-$37FF (a 32 x 32 tilemap of 8 x 8 4 bpp tiles, 512 of them; the columns 6-31 scrolled in y by $3F80,
columns 0-5 fixed: the scoreboard), sprite RAM $3800-$39FF (two banks of 64 sprites by latch Q5, 16 x 16, 384 in ROM, the
last on top, none where x and y are both 0), the sprite palette bank $3C20, ROM $6000-$FFFF.  Colours: three 256 x 4
palette PROMs (a 2k / 1k / 470 / 220 ohm network each) as indirect colours; tiles by one lookup PROM, sprites by the other
with the palette bank in the high nibble.
`ref/mame_cmp_sbasketb.py` (2026-11-07, WolfMAME 0.248 of the F030Arcade checkout, run through `engine/mamewin.py`):
**0 of 4,352 pens and 0 pixels differ** at frames 60-12,000 (attract mode, scrolling, the ROT90 picture); the reference
machine's RAM equals MAME's but for 1-3 stack bytes.  The binary differs from the authoritative 0.286 source in two
places, which the comparison accounts for and the port does not use: it runs the CPU at **1.4 MHz** (the source:
18.432 MHz / 12 = 1.536 MHz; found because the boot's delay loops took 9.7% more frames) and its DSW2 default has
"Starting Score" 70-78 (`$68`; the source: 100-115, `$60`).  `SBasket(dsw2=0x68, hz=1400000)` is the machine MAME 0.248
runs; the default is the source's.

### Translation

`tools/gen.py`: the 6809's 64 KB are one block (`sb_mem`: RAM, video RAM and the ROM at their addresses), so every slot's
base is the same and an indexed access needs no slot.  The sites the coverage saw touch the I/O ($3C00-$3FFF, the
write-only registers) or store to the video and colour RAM go through `main_io_r` / `main_io_w`, except the byte stores
whose address is in $3000-$37FF (`video_inline`: they write the byte and list the cell for the renderer themselves).
Since every slot holds one page for good, no jump, call or return checks a page (`fixed_slots`); the 68030 forms run
(`fast_forms`).  **DP moves**: `TFR A,DP` takes $24 in the player routines ($8EB6, $9A77-$9C25) and the code otherwise
uses $20; the translator wants one DP per instruction, so the coverage records DP at every instruction (`ref/cover.py`
`dp`, `gen.py` `dp_sites`).  A routine called with either ($99FA-$9A0F) addresses nothing through DP and is accepted
as it is.  A first version without `dp_sites` was exact for 238 frames and then wrote the player's state to the wrong
page.

### Schedule

The port (`machine.SBasketPort`, `src/sbasketb.s`): the foreground is a task loop ($60F9 `TST <$22` ... $611E
`LDX <$1A; LDD ,X; ASLA; LBCS $60F9`: the queue at $2100, its read pointer at $201A, an empty entry has bit 7); the IRQ
handler ($62D9) plays the game and queues tasks.  The loop head $60F9 is a native (`sb_idle`, gen.py NATIVES): the
picture is drawn when due, the next arcade frame awaited and the IRQ delivered (Q1 1) with $60F9 as its return address,
when the queue is empty **or the loop has come back 8 times since the last IRQ**: in the two-player menu the loop
queues a blinking text every pass while the frame counter $2014 has not moved (one entry a pass, one always waiting), so
an "empty queue" rule never delivers the IRQ there (the arcade's IRQ comes by time).  Six arcade frames to five VBLs;
MAX_SKIP 3.  **The boot skips the self-test**: the reset vector's code ($D582: delay loops of ~60 frames each, a RAM
test, then $D640 reads SYSTEM and sets $2FF0 to 3 when start 1 and 2 are held: the service mode) is not run: the
reference and the runtime start at `$6000` with $2FF0 set that way.

### Picture

* **Turned** as MAME's ROT90 turns it (`tools/assets.py`): picture pixel (X, Y) is the raw pixel (x = Y, y = 239 - X);
  the tile and sprite graphics are turned once at build time (the sprite 16 x 16, 4 bpp, 384 of them; the tiles 512).
  Raw flip x reverses the turned rows, flip y the columns.
* **The playfield**: 256 lines of 240 bytes: the 6 fixed tile columns (picture lines 0-47) at X = 232 - 8 ty, the 26
  scrolled ones (lines 48-255) in a 256-pixel ring at P = 248 - 8 ty, the first 224 pixels again at 256-479 so a window at
  any scroll never wraps; picture X shows P = (X + 16 - scroll) mod 256.  A changed cell (`main_io_w` lists it) is
  converted on first use per (code, colour, flips) into a tile cache (a long a row, `movep.l`).
* **Rows**: a display buffer's tile row (8 lines) is copied from the playfield (one HOG pass per plane and line: 14 words,
  FXSR and the skew for the scrolled rows) when the buffer's scroll differs from the picture's (all rows), a cell of it
  changed, or the buffer's last sprites covered it; the rest stay.
* **Sprites**: baked on first use per (code, colour, flips) into a cache slot (flushed when the palette bank changes);
  generated code for the coverage's 348 shapes (5,192 routines, 534 KB of end mask streams: `engine/sprite_programs.py`,
  [sprite-preparation.md](../../docs/sprite-preparation.md)), the row path for the others and 64 KB crossings.  Clipped
  at the picture's group-aligned left and right edges (screen x 48 and 272), whole into 16 guard lines below (cleared
  before the buffer's next picture).  Drawn from the first to the last entry (MAME's order: the last on top; Track &
  Field's loop runs the other way).
* **Colours**: 199 of the 4,352 pens are shown in the coverage; black and 15 by the shared default fitter, flat
  (`engine/palette_native.py`; mean channel error 5.7 over the shown pixels).

### Sound

The board is the Hyper Sports one (`hyperspt_sh_timer_r`, `hyperspt_sound_w`, SN76489A through the $E001 latch and the $E002
strobe, the DAC at $E000, the VLM5030 with 8 KB of speech ROM) with its own driver (405e13.7a, 8 KB, RAM $4000-$43FF).
The main CPU writes a command to $3D00 and then the trigger $3D80 (each write raises the Z80's IRQ, HOLD_LINE, vector
$FF).  The commands the game sends (coverage): 0, effects $01-$40 (17 values), phrases $80-$AD, $FE, $FF.

* **Recording** (`tools/sound_capture.py`): MAME (WolfMAME 0.248, `-video none -wavwrite`) with the main CPU parked in
  the first delay loop of its boot (`$D585` patched to `BRA *` in the ROM region; the KONAMI-1 opcode byte is
  encrypted) and a Lua frame callback that writes the latch and the trigger and kicks the watchdog.  One capture a
  command: 17 effects alone, the 47 phrases as the game sends them (`$FE, phrase, $FF`), a silent baseline.  The
  recordings have a DC offset (the DAC at rest) that the converter removes.
* **Clips** (`tools/sound_convert.py`): 8 bit signed mono at 12,517 Hz for the DMA, low-passed, one scale for all: 58
  clips (14 effects, 44 phrases; the board makes no sound for $0A, $1F, $FE, $FF and a few phrases), 579 KB.  The two
  looping effects ($09, $20, sounding until the next command) are cut at a period of their own and replayed repeating.
* **Player** (`src/sound.s`, `snd_frame` once per arcade frame before the IRQ that follows the commands): command 0
  stops the clip, $01-$7F start that effect's clip (the newest wins), $80-$FE with a clip are queued (the last one waits)
  and $FF speaks it.  One DMA stream plays at a time: overlapping effects are not mixed (the board's are), and a queue of
  several phrases is spoken as its last.
* **Limits**: the board's music and effects that outlast their command by the driver's own state (a tune that a later
  effect interrupts, a speech that stops on a reset) are only as the single-command recordings have them; the commands
  the coverage never saw have no clip ($41-$7F, the phrases above $AD and $B0-$FD were not recorded).  The Z80 is not
  translated (the sibling ports' tools take the driver's loop, tick, tune and wait addresses per ROM, which this one's
  still lack).

## Speed

| Date | Setup | Logic | Pictures | Musashi cycles |
|---|---|---|---|---|
| 2026-11-07 | Hatari, `tools/hatari.ps1 -Frames 5000` (the AUTOPLAY script: coin, start, moving and shooting; the AVI recorded), DEBUG build, 4 MB, sound build (Hatari's audio off) | 73%, 44.1 arcade frames a second (4,413 in 5,001 VBLs) | 16.2 a second (1,619) | |
| 2026-11-07 | the same without the sound, 4,000 VBLs | 69%, 41.2 | 13.9 | |
| 2026-11-08 | Hatari, natives `$8DD8` and `$64F7`, 5,000 VBLs (same script and build) | 83%, 49.6 (4,961) | 19.4 (1,939) | logic 56k an arcade frame |
| 2026-11-08 | the same, 9,000 VBLs | 90%, 54.0 (9,713) | 30.6 (5,516) | (the rate differs by phase of the script: the first 5,000 VBLs were lower; not analysed further) |
| 2026-11-07 | Musashi, seed 1's play (`render_test.py 1400 --seed 1 --start 1000`, 400 pictures) | | | logic 99.5k an arcade frame; a picture CPU 98.9k + Blitter 103.8k bus cycles |

Where a picture's time goes (`render_test.py 1500 --seed 1 --start 1000 --prof`): `compose` 24%, `draw_cell` 24% (the
generated code and its Blitter waits), `bake_sprite` 15% (the cache filling), `draw_sprites` 13% (its 64-entry loop), the
tiles 10%.  The logic was ~99k cycles an arcade frame in the first build, 78.6k with the first profile's fixes, and is 56k now
(seed 1 frames 1,000+): `PROF=1000 logic_test.py 1600 --seed 1` charges every 68000 instruction to the last symbol before it.
Two hot routines were 38% of it and are natives now (`src/natives.s`, checked in lock-step, see the table): the 16-bit
division at `$8DD8` (12%, a restoring division with quirks of its own: the first bit of the shifted divisor is lost, a
flag carries into the first step) and the sprite list builder at `$64F7` (25%: 64 records of 4 bytes into the sprite RAM,
from the objects' records).  The rest of the profile is flat (the I/O write handler 4%, the return dispatch 3%, none
over 1.5%).

What made it faster (2026-11-07): rows composed only when the buffer's scroll differs, a cell changed or its last sprites
covered them (a picture's Blitter 128k -> 93k bus cycles; the scroll is the same as three pictures earlier in 71% of
the play frames of seed 1); the generated sprite code (a picture 115.0k CPU + 106.8k Blitter -> 98.9k + 103.8k, seed 1
frames 1000-1400, `-D REN_GEN=0` against the default, both exact).

**Speed audit (2026-11-08, against `docs/speed.md`)**.  Profile first: logic 56k cycles an arcade frame (flat after the two
natives; the I/O write handler 4.3%, the return dispatch 2.7%, the I/O read handler 1.9%); a picture 96-100k CPU + 98-114k
Blitter bus cycles (render_test, seed 1 frames 1,000+): `draw_cell` 25% (the generated sprite code and its Blitter waits),
`compose` 24% (the tile rows), `bake_sprite` 14% (cache filling, mostly warm-up: 1,024 slots), `draw_sprites` 13%, tiles 7%.

| Technique | State | Before -> after |
|---|---|---|
| Register maps, second pass | built in (`fixed_slots`, `fast_forms`) from the first build | not A/B measured |
| Window guards at coverage sites | n/a: one flat 64 KB block, no banks | |
| Leaves in place (`inline_leaves`/`inline_rst`/`inline_jumps`) | n/a: the 6809 translator has `inline_calls` only, for hand-made targets; no hand-made leaf here | |
| `call_summaries`, `ret_weights` | applied from the first build | not A/B measured |
| `flags_at=set()` at the idle hook | n/a: the idle point is a native (`sb_idle`) | |
| `video_inline` | applied ($3000-$37FF) | not A/B measured (the I/O write handler is still 4.3%: the other registers and the sprite RAM) |
| Natives at the profile's top routines | applied: `$8DD8` division, `$64F7` sprite list (lock-step exact, 20 seeds + autoplay) | logic 78.6k -> 56.2k (seed 1); Hatari 44.1 -> 49.6 frames/s, 16.2 -> 19.4 pictures/s |
| Sound work at build time | applied (MAME recordings to DMA clips) | |
| Hardware scroll (twin lines / columns) | **not applied; the biggest candidate**: every scroll change recomposes all 26 scrolled rows (compose 24% of the CPU, most of the Blitter); the scroll differs from the last picture's in 29% of play frames.  HSCROLL needs the fixed rows 0-5 composed against the scroll (they stay on screen) and the display address and HSCROLL set per picture; the render test would have to model the hardware | |
| Palette stamps, DEDICATED pens, frozen colour cycling | n/a: one 16-colour palette per picture, no colour cycling (the sprite palette bank is flushed with the picture) | |
| Draw the smaller layer as pieces | n/a: one tile layer plus sprites | |
| Erase only what can be seen | applied: sprites drawn into guard lines below the picture (the display skips them); only rows with sprite damage or a changed cell are recomposed | Blitter 128k -> 93k a picture |
| Per-slot sprite cache, `sprite_programs` passes | applied (1,024 slots, 348 shapes) | 115.0k CPU + 106.8k Blitter -> 98.9k + 103.8k |
| Sprite-only-row restore / writer marks | applied (`row_dirty`, `row_sdirty`: cells marked by the writers) | included above |
| Spreading redraws, HUD as an image, skipping latch copies of skipped pictures | not tried | |
| Pictures-per-second schedule | `MAX_SKIP` 3, `PASSES` 8; not tuned | |

Measured, not kept: nothing yet.  Techniques other ports use that may apply:
[speed.md](../../docs/speed.md#techniques-that-look-applicable-elsewhere-2026-11-07).

## Tests and tools

* `tools/logic_test.py N --seed S`: lock-step against the reference (the compared state: State); the logic's Musashi
  cycles an arcade frame.
* `tools/render_test.py N --seed S --start F [--every K] [--prof]`: the STE picture against the reference, with cycle
  figures; `-D REN_GEN=0` builds put every sprite on the row path.
* `tools/sprite_test.py`: made-up pictures (edges, 16 shifts, holes, flips, overlaps, both banks, palette banks, guards,
  64 KB).
* `tools/hatari.ps1`: the F030Arcade Hatari hidden, the AVI's stills and the counters (`-Frames`, `-Every`; `-Sound 44100`
  records its audio into the AVI, with SDL's dummy driver; the AVI is large (2 GB for 1,200 VBLs): delete it).
* `PROF=<frame> tools/logic_test.py N`: the logic's cycles by symbol.
* `ref/cover.py N`: the coverage (seeds in its header); `ref/mame_cmp_sbasketb.py`: the reference against MAME.

## Lessons

* **A MAME binary's clock and DIP defaults can differ from the source** (2026-11-07): WolfMAME 0.248 runs this board's
  CPU at 1.4 MHz and defaults "Starting Score" to 70-78.  The RAM comparison diverged at the end of the boot's delay
  loops (a pure `MUL` loop of 65,536 turns: 61.4 frames at 1.536 MHz, 67.5 at 1.4 MHz); reading the X register in MAME at
  two frames gave the clock.  The 0.286 source wins for the port (`AGENTS.md`).
* **Write-only registers are not in a MAME memory dump** ($3C20, $3F80, the LS259): tap them (`mame_frames.lua` TAPS and
  `tapstate`) and apply the frame's writes to the last state.
* **DP is a register the translator treats as a constant** (above): a game that moves it needs the coverage's per-
  instruction DP.
* **The idle point of a task loop must also fire when the loop never empties** (above, the two-player menu).
* **Sprite order is the driver's**: Track & Field's loop draws the last entry first; this one draws the first first (the
  render test found it in 67 pixels around the ball).
* **A recording needs the board alone** (2026-11-07): parking the main CPU by writing PC (as Mario Bros.' capture does)
  did not take here and the game's attract sounds played on in every capture (the same sounds in a capture with no
  command at all showed it); patching the boot's first delay loop in the ROM region parks it for good.
* **Random play does not cover a game** (2026-11-07): twelve seeds of random stick and buttons ran 20,000 frames each and
  missed a handler that the AUTOPLAY script reached at frame 3,584 and another at 3,662 (`JMP ,U` through a pointer in
  an object's script record).  Fixed patterns, the AUTOPLAY script as a seed and the no-coin attract cycle are seeds
  now; a harness that stops at the bad pc found it (a stop address range that included a helper's entry gave two false
  alarms first: the stop addresses must be the exact loop).
* **A sprite's colour set wraps modulo 256** (`color = attr & 15 + 16 * palette bank`): the reference masks it.

## Verification

No playtest beyond the AUTOPLAY script (coin, start, moving and shooting) in Hatari; the lock-step seeds play at random
with the stick and the buttons, two players and the service mode included, never a whole game with its ending and the
high-score entry on purpose.  Nothing here claims a complete playthrough.  No PPO profile.

Full-game verification follows the [status policy](../../docs/port-status.md); nothing here claims a complete playthrough.
