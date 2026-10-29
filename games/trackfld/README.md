# Track & Field (Konami, 1983) for Atari STE

![Track & Field on the STE (Hatari)](docs/screenshot.png)

MAME set `trackfld` (Konami GX361).  The main CPU, a KONAMI-1 (an MC6809 with encrypted opcodes, 40 KB of ROM), is
statically translated to 68000 code (`engine/m6809x.py`) and checked against a reference board in lock-step; the
picture is MAME's, 256 x 224, centred in the 320-pixel screen with the top and bottom borders open.  Work in progress:
no sound yet (the sound board's Z80, SN76489A, VLM5030 speech and DAC), one fitted 16-colour palette.  Started
2026-10-29.

```sh
python games/trackfld/tools/prepare.py      # verify assets/roms/trackfld.zip, unpack to assets/roms/extracted/trackfld/
python port.py cover trackfld               # coverage: ref/cover.py seeds 1-12 (~1 min in parallel)
python games/trackfld/tools/build.py        # -> run/trackfld/TRACKFLD.PRG (--sim: run/trackfld_sim; --assets: colours again)
python games/trackfld/tools/logic_test.py 20000 --seed 6  # the translation in lock-step with the reference
python games/trackfld/tools/render_test.py 3000 --seed 6 --start 1000   # the STE picture against the reference
python games/trackfld/tools/sprite_test.py                # edges, all 16 shifts, holes, guards, 64 KB crossings
games/trackfld/tools/bench.sh 6000          # Hatari speed (its own Hatari, killed by PID): logic and pictures a second
python games/trackfld/ref/mame_cmp_trackfld.py [frame ...]  # the reference against MAME 0.289
```

Supply `assets/roms/trackfld.zip` (MAME's parent set; `docs/rom_manifest.json` has the files' sizes, CRCs and
SHA-1s).  Nothing ROM-derived is in git: the graphics, colours and ROM image are made into `build/trackfld/` and
assembled into the program.

Controls: **5/6** coin 1 / 2, **1/2** start, run with **Left / Right** (or **Z / C**) in turn, the action (jump,
throw, the angle: hold) with **Up / Space / Control / X**, **Esc** quits.  Joystick port 1 player 1, port 0 player 2:
left and right run, up and fire act.  Jaguar pad / PowerPad: pad A player 1, pad B player 2, the D-pad's left / right
and **A / C** run, **B** and up act, **Option** coin, **Pause** start.  DIP switches: MAME's defaults (1 life, the
game continues after the last event, no bonus, the records kept, normal difficulty, demo sounds on).

## The board and the port's schedule

`tools/machine.py` follows MAME's `konami/trackfld.cpp`: the KONAMI-1 at 1.536 MHz, 60.6 Hz, the IRQ at the VBLANK
while the LS259 latch's Q7 is 1; RAM $1800-$1FFF (the sprite RAMs and the row scrolls in it), NVRAM $2800-$2FFF, video
and colour RAM $3000-$3FFF (64 x 32 tiles of 8 x 8, 4 bpp, x scrolled per tile row), 32 sprites of 16 x 16 (4 bpp,
transparent where the lookup PROM's entry is 0), ROM $6000-$FFFF.  `ref/mame_cmp_trackfld.py` (2026-10-29): 0 of 512
pens and 0 pixels differ at frames 60-3600; the MAME-timed reference's RAM equals MAME's but for 1-3 stack bytes.

The port (`machine.TrackFieldPort`, `src/trackfld.s`): the foreground is a task loop ($6160: LDX <$1A; LDD ,X; ASLA;
BCS: the queue at $2900, an empty entry has bit 7); the IRQ handler ($6600) plays the game and queues tasks.  The idle
point $6160 with an empty queue is a native (`tf_idle`, gen.py NATIVES): the picture is drawn when due, the next
arcade frame awaited and the IRQ delivered (Q7 1) with $6160 as its return address; its RTI comes back there.  Six
arcade frames to five VBLs; MAX_SKIP 3.

The translation (`tools/gen.py`): the 6809's 64 KB are one block (`tf_mem`: RAM, NVRAM, video RAM and the ROM at
their addresses), so every slot's base is the same and an indexed access needs no slot.  The sites the coverage saw
touch the I/O ($1000-$12FF) or store to the video RAM go through `main_io_r` / `main_io_w`; a video RAM store lists its
cell for the renderer (267 sites, ~37 stores a frame).  Since every slot holds one page for good, no jump, call or
return checks a page (`fixed_slots`); the 68030 forms run (`fast_forms`), the return compares ordered by the
coverage's counts of each return; a call's live flags come from its callee's summary (`call_summaries`: what it reads
first, what it passes through) instead of every caller's needs, which halved the flag-keeping wrappers.

## State

* **Logic**: exact against the reference's port schedule.  `tools/logic_test.py`: RAM $1800-$1FFF, NVRAM and video
  RAM $2800-$3FFF, the latch (Q0, Q7), the sound commands (Q1's rising edges).  Seeds 1-12 20,000 frames each
  (attract, the name entry, play to the game over and again; every event from its start by MAME's cheats with
  always-qualify and infinite lives; two players; the other DIP switches).  The logic costs ~20-38k Musashi cycles an
  arcade frame (seed 1 19.7k, seed 6 37.5k over 20,000 frames, the video RAM marks included); the translator's flag
  work (below) took 10-17% off.
* **Picture**: exact in the shown colours.  `tools/render_test.py`: 0 differences in 715 sampled pictures of seed 6's
  play (frames 1000-6000) and 150 of seed 1's attract; `tools/sprite_test.py`: 154 made-up pictures exact (both side
  edges at every shift, holes, flips, overlaps, MAME's x - 256 wrap, the guard lines, 64 KB crossings, 60 pictures in
  a row with moving sprites, scrolls and tiles).  `BLIT_STATS=256`: every pass HOG, the longest 132 bus cycles.
* **Hatari** (F030Arcade build, STE, 4 MB, TOS 2.06): boot, attract, coin, the name entry, the 100 m dash, deaths;
  no crash, no late border event in 6,000 VBLs.
* **Colours**: the arcade shows 24 colours in the coverage; black and 15 fitted in Oklab (`tools/assets.py`): mean
  error 0.8 a channel, weighted by pixels; the worst-matched pens are rare (magenta, a dark grey).
* Not done: sound, the cocktail flip, the service mode, players 3 and 4 (IN1); the sprites' reordered-source /
  generated-code path (`engine/sprite_programs.py`, as Time Pilot's: AGENTS.md asks for it to be prototyped and
  measured; the row path is used so far, and docs/sprite-preparation.md has no Track & Field result yet).

## Speed (2026-10-29)

`tools/bench.sh 6000` (DEBUG build, the AUTOPLAY script: coin, start, the name, running): **95% of the arcade's speed
(median 60 arcade frames a second), pictures 43.8 a second on average, median 49, 10th percentile 30**; the dips are
the screen changes (a whole new tile map: ~1,800 cells converted and drawn into the playfield).

A picture (`tools/render_test.py`, Musashi, seed 6's play): ~49k CPU + ~33-40k Blitter bus cycles.
* **The playfield**: the 64 x 32 tilemap in STE planes, 768 pixels wide (the first 256 again at the end: a window at
  any scroll never wraps); a changed cell converted on first use per (code, colour, flips) into a tile cache (a long a
  row) and written with movep.l.
* **Rows**: a tile row is copied from the playfield into a buffer only when its scroll differs from what that buffer
  holds there, a cell of it changed, or the buffer's last sprites covered it: one HOG pass per plane and line (16
  words, FXSR and the skew for the scroll: 132 bus cycles, the addresses running on to the next plane).
* **Sprites**: baked on first use per (code, colour, flips) into a cache slot (the opaque rows, their masks, the plane
  words in pass order); a row is one HOG pass, OP 3 with the opaque pixels as end masks (docs/sprite-preparation.md);
  clipped at the group-aligned edges (screen x 32 and 288: the inner word only), whole into 16 guard lines above and
  below (cleared before the buffer's next picture).

## Full-game verification status

Automated players such as Dreamer can attempt a full playthrough once this port's
adapter and native Hatari replay transport are verified. An attempt or assisted
stage visit does not establish completion; a successful natural Hatari playthrough
and graphics, sound and control checks are required for green **Complete** status.
See the shared [status and verification policy](../../docs/port-status.md) and
[current port status](../../README.md). Existing test results above retain their
stated scope; this note does not claim a new successful run or Dreamer integration.
