# Hyper Sports (Konami, 1984) for Atari STE

![Hyper Sports on the STE (Hatari)](docs/screenshot.png)

MAME set `hyperspt` (Konami GX330).  The main CPU, a KONAMI-1 (an MC6809 with encrypted opcodes, 48 KB of ROM), is
statically translated to 68000 code (`engine/m6809x.py`) and checked against a reference board in lock-step; the
picture is MAME's, 256 x 224, centred in the 320-pixel screen with the top and bottom borders open.  The port is
Track & Field's (`games/trackfld`: the same board family, the same runtime and renderer design) with this board's
memory map.  Work in progress: no sound yet (the sound board's Z80, SN76489A, VLM5030 speech and DAC), one fitted
16-colour palette.  Started 2026-10-29.

```sh
python games/hyperspt/tools/prepare.py      # verify assets/roms/hyperspt.zip, unpack to assets/roms/extracted/hyperspt/
python port.py cover hyperspt               # coverage: ref/cover.py seeds 1-12 (~1 min in parallel)
python games/hyperspt/tools/build.py        # -> run/hyperspt/HYPERSPT.PRG (--sim: run/hyperspt_sim; --assets: colours again)
python games/hyperspt/tools/logic_test.py 20000 --seed 5  # the translation in lock-step with the reference
python games/hyperspt/tools/render_test.py 3000 --seed 5 --start 500   # the STE picture against the reference
python games/hyperspt/tools/sprite_test.py                # edges, all 16 shifts, holes, guards, 64 KB crossings
python games/hyperspt/tools/native_test.py 2000           # src/natives.s against the 6809, edge cases included
games/hyperspt/tools/bench.sh 6000          # Hatari speed (its own Hatari, killed by PID): logic and pictures a second
python games/hyperspt/ref/mame_cmp_hyperspt.py [frame ...]  # the reference against MAME 0.289
```

Supply `assets/roms/hyperspt.zip` (MAME's parent set; `docs/rom_manifest.json` has the files' sizes, CRCs and
SHA-1s).  Nothing ROM-derived is in git: the graphics, colours and ROM image are made into `build/hyperspt/` and
assembled into the program.

Controls: **5/6** coin 1 / 2, **1/2** start; the left button (run, fire left) **Left / Z**, the right button **Right /
C**, the action (jump, the angle, lift: hold) **Up / Space / Control / X**; **Esc** quits.  Joystick port 1 player 1,
port 0 player 2: left and right the two buttons, up and fire act.  Jaguar pad / PowerPad: pad A player 1, pad B player
2, the D-pad's left / right and **A / C** the buttons, **B** and up act, **Option** coin, **Pause** start.  DIP
switches: MAME's defaults (the game over after the last event, demo sounds on, the records kept, difficulty "Normal 8").

## The board and the port's schedule

`tools/machine.py` follows MAME's `konami/hyperspt.cpp`: the KONAMI-1 at 1.536 MHz, 60 Hz, the IRQ at the VBLANK while
the LS259 latch's Q7 is 1; sprite RAM $1000-$10BF (48 entries: attributes, y, code, x; attributes bit 5 the code's
bit 8: 512 sprites of 16 x 16, 4 bpp) and the row scrolls $10C0-$10FF, the watchdog $1400, the latch $1480-$1487, the
sound latch $1500, DSW2 $1600, SYSTEM / P1_P2 / P3_P4 / DSW1 $1680-$1683, video and colour RAM $2000-$2FFF (64 x 32
tiles of 8 x 8, 4 bpp, 1024 codes: the colour byte's bits 7 and 6 are the code's bits 8 and 9), RAM $3000-$37FF,
NVRAM $3800-$3FFF, ROM $4000-$FFFF.  `ref/mame_cmp_hyperspt.py` (2026-10-29): 0 of 512 pens and 0 pixels differ at
frames 60-3600; the MAME-timed reference's RAM equals MAME's but for 1-3 stack bytes.

The port (`machine.HyperSportsPort`, `src/hyperspt.s`): the foreground is a task loop ($41B1: LDX <$1E; LDD ,X; ASLA;
BCS: an empty queue entry has bit 7); the IRQ handler ($44F5) plays the game and queues tasks.  The idle point $41B1
with an empty queue is a native (`hs_idle`, gen.py NATIVES): the picture is drawn when due, the next arcade frame
awaited and the IRQ delivered (Q7 1) with $41B1 as its return address; its RTI comes back there.  Six arcade frames
to five VBLs; MAX_SKIP 3.

The translation (`tools/gen.py`): the 6809's 64 KB are one block (`hs_mem`), so every slot's base is the same.  The
sites the coverage saw touch the I/O or store to the video RAM go through `main_io_r` / `main_io_w` (they route every
address as the board does: the boot's test of $1000-$13FF reads 0 from the unmapped $1100-$13FF); a video RAM store
lists its cell for the renderer.  ROM page $E000-$FFFF holds data only: no dispatch table.  As Track & Field's:
`fixed_slots` (no page checks), `fast_forms`, the return compares ordered by the coverage's return counts, and
`call_summaries` (a call's live flags from its callee's summary): together 16-21% off the logic.

## State

* **Logic**: exact against the reference's port schedule.  `tools/logic_test.py`: the sprite RAM and scrolls
  $1000-$10FF, the video RAM, RAM and NVRAM $2000-$3FFF, the latch (Q0, Q7), the sound commands (Q1's rising edges).
  Seeds 1-12 20,000 frames each (attract, the name entry, play to the game over and again; every event from its start
  by MAME's cheats with always the first try and no false starts; two players; the other DIP switches).  The logic
  costs ~30-56k Musashi cycles an arcade frame (seeds 1-12 over 20,000 frames each: 29.6k-56.0k; seed 5's skeet
  shooting 52.8k, seed 9's weightlifting 56.0k), more than Track & Field's (~2,200 6809 instructions a frame).
* **Natives** (`src/natives.s`, gen.py NATIVES): the IRQ handler's copies of the sprite RAM ($4FBD: $3600 -> $1000,
  144 bytes) and the scrolls ($4FD2: 64 bytes) as long moves, and the division at $A62B (0:D rotated, the divisor
  normalized, shift and subtract, the quotient in X, the remainder rotated back) in registers, step for step as the
  6809 does it (the count byte that wraps for a divisor of $1000 or more, the bytes <$5B-$5F, the flags at the RTS).
  The logic without them / with them (20,000 frames): seed 1 47.7k / 39.3k, seed 5 59.8k / 52.8k, seed 9 82.7k /
  56.0k.  The play gives the division small divisors only, so `tools/native_test.py` checks the natives against the
  6809 (the reference CPU) in 2,000 random states and the edge cases (X = 0, $1000 and more): it found the routine's
  CLRs clearing C before the first ROLB, which the play never shows.
* **Picture**: exact in the shown colours.  `tools/render_test.py`: 0 differences in 715 sampled pictures of seed 1
  and 786 of seed 5 (skeet shooting); `tools/sprite_test.py`: 154 made-up pictures exact (both side edges at every
  shift, holes, flips, overlaps, MAME's x - 256 wrap, the guard lines, 64 KB crossings, 60 pictures in a row with
  moving sprites, scrolls and tiles).  `BLIT_STATS=256`: every pass HOG, the longest 132 bus cycles.
* **Hatari** (F030Arcade build, STE, 4 MB, TOS 2.06): boot, attract, coin, the name entry, swimming, the game over;
  no crash, no late border event in 6,000 VBLs.
* **Colours**: black and 15 fitted in Oklab (`tools/assets.py`): mean error 1.0 a channel, weighted by pixels; the
  worst-matched pens are rare (a pink, a brown).
* Not done: sound, the cocktail flip, the service mode, players 3 and 4 (P3_P4); the sprites' reordered-source /
  generated-code path (`engine/sprite_programs.py`: AGENTS.md asks for it to be prototyped and measured; the row path
  is used so far).

## Speed (2026-10-29)

`tools/bench.sh 6000` (DEBUG build, the AUTOPLAY script: coin, start, the name, running): **93% of the arcade's speed
(median 60 arcade frames a second), pictures 34.6 a second on average, median 34.5, 10th percentile 15** (before the
natives: 91%, 31.6, 30, 12; before the translator's flag work: 89%, 28.4, 26.5, 11.5).  A picture
(`tools/render_test.py`, Musashi): ~65-76k CPU + ~39-49k Blitter bus cycles; the renderer is Track & Field's (see its
README: the playfield, the rows drawn only where their scroll or cells changed or sprites were, the sprites' row path).

## Full-game verification status

Automated players such as Dreamer can attempt a full playthrough once this port's
adapter and native Hatari replay transport are verified. An attempt or assisted
stage visit does not establish completion; a successful natural Hatari playthrough
and graphics, sound and control checks are required for green **Complete** status.
See the shared [status and verification policy](../../docs/port-status.md) and
[current port status](../../README.md). Existing test results above retain their
stated scope; this note does not claim a new successful run or Dreamer integration.
