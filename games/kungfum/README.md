# Kung-Fu Master (Irem, 1984) for Atari STE

2026-10-19: ring copies use the full-word dispatcher, masked strip piece sizes use a lookup, and black-band
fills avoid source reads. See [measurements and the rejected overlap experiment](../../docs/virtual-scroll-performance.md#implementation-results).

![Kung-Fu Master on the STE (Hatari)](docs/screenshot.png)

MAME set `kungfum` (Irem M62).  The main Z80 program (32 KB, flat) is statically translated to 68000 code; the
picture (all 256 x 256 arcade pixels, centred in the 320-pixel screen, top and bottom borders open) is drawn by
`src/render.s` with a hardware-scrolled playfield and Blitter sprites.  The sound board's M6803 driver is translated
too and plays its two AY-3-8910s on the YM2149 (three of the six channels), the ADPCM voices through the DMA sound.
For a 4 MB STE (it asks TOS for 1.6 MB).

```sh
python games/kungfum/tools/prepare.py      # verify assets/roms/kungfum.zip, unpack to assets/roms/extracted/kungfum/
for s in $(seq 1 13); do python games/kungfum/ref/cover.py $s 20000; done   # coverage (~3 min in parallel)
python games/kungfum/tools/build.py        # -> run/kungfum/KUNGFUM.PRG (--sim: run/kungfum_sim for the tests)
python games/kungfum/tools/logic_test.py 20000 --seed 4     # the translation in lock-step with the reference
python games/kungfum/tools/render_test.py 20000 --seed 4    # the STE picture against the reference, every frame
python games/kungfum/tools/sprite_test.py                   # sprites at the edges, all shifts, holes, 64 KB crossings
python games/kungfum/tools/sound_test.py 20000 --random     # the STE's sound against its model (--seed N: the game's)
python games/kungfum/ref/mame_sound_kungfum.py 6000 --play  # the sound board's model against MAME 0.289
python games/kungfum/tools/play_search.py 9000              # the recorded play (build/kungfum/play_inputs.bin)
games/kungfum/tools/bench.sh 6000          # Hatari speed (PLAY=1: the recorded play): logic and pictures a second
games/kungfum/tools/shots.sh tap:5@26 tap:1@29 shot@40      # its own Hatari: keys, screenshots
python games/kungfum/ref/mame_cmp_kungfum.py [frame ...]    # the reference against MAME 0.289
```

Supply `assets/roms/kungfum.zip` (MAME's 28 files under MAME's names; `docs/rom_manifest.json` has their sizes, CRCs
and SHA-1s).  Nothing ROM-derived is in git: the graphics, palettes and the ROM image are made into `build/kungfum/`
(`tools/assets.py`) and assembled into the program.

Controls: **5/6** coin 1 / 2, **1/2** start, **arrow keys** move (up jumps, down crouches), **Space / Ctrl / Z**
punch, **Alt / X** kick, **Esc** quits.  Joystick port 1 player 1, port 0 player 2 (fire punches).  Jaguar pad /
PowerPad: pad A player 1, pad B player 2, the D-pad moves, **A** punch, **B** kick, **Option** coin, **Pause**
start, keypad **1/2** start, **5/6** coin, **\*** + **#** quit.  For scripted Hatari events: coin `5`, start `1`,
`Left` / `Right`, `z` punch, `x` kick.  DIP switches: MAME's defaults.

## State

* **Logic**: exact.  `tools/logic_test.py` runs the translation (Musashi) in lock-step with the reference's port
  schedule (`machine.KungFuPort`): RAM, tile RAM, sprite RAM, scroll and the sound commands equal every frame, every
  changed tile RAM row marked: 20,000 frames each of the 13 coverage seeds (attract, coin, start, play, deaths,
  game over and the high-score entry, all five floors and their bosses, floor 2's pots, the ending, the
  invulnerability and level selection DIP switches) and the 9,000 frames of the recorded play.
* **Picture**: exact in the shown colours.  `tools/render_test.py` runs the program with its renderer and compares
  every frame's STE picture (panel image + the published ring at its window) with the reference renderer through the
  scene's pen map: 0 differences in 20,000 frames of each of the 13 seeds and in the 9,000 of the recorded play; the
  bands black but where a sprite overhangs an edge inside a word (below).  No HOG pass longer than 256 bus cycles,
  none without HOG (`BLIT_STATS=256`).  `tools/sprite_test.py`: 1,122 made-up pictures, cells across both edges at every pixel offset for
  24 window offsets, 1-, 2- and 4-cell sprites with transparent rows and holes, flips, overlaps, the three rings'
  64 KB crossings, moving sprites and window (damage restores, strips): exact; the band check fails 737 of them if no
  overhang is allowed (all at windows inside a word: at group-aligned windows the clipping is exact).
* **Hatari** (F030Arcade build, STE, 4 MB, TOS 2.06): attract, coin, start, play by keyboard and by the recorded play;
  no crash, no late border event (DEBUG counters, 6000 VBLs).
* **Sound**: the model of the sound board equals MAME instruction for instruction (`ref/mame_sound_kungfum.py`: all
  2,066,844 writes of the M6803 to its ports, the IRQ acknowledges and the ADPCM nibbles, in order, over 6,000 frames of
  attract and play); the STE's player equals the model in the STE's schedule (`tools/sound_test.py`, below).
* Not done: the flip screen (cocktail), the service mode (its code at $7666 is not translated: DSW2 bit 7 is off).

## Speed

`tools/bench.sh` (DEBUG build, 6000 VBLs from power-on, Hatari): the logic (arcade frames a second; the arcade 56.34)
and the pictures a second, separately; per 100 VBLs in RATE.BIN.

| run | logic | pictures |
|---|---|---|
| recorded play (`PLAY=1`), the whole run | 51.9 /s (92%) | 27.1 /s |
| recorded play, in play (VBLs 2000-6000) | 55-56 /s (~99%) | 20-34 /s |
| AUTOPLAY script (attract, coin, random play) | 48.0 /s (85%) | 27.6 /s |
| recorded play without the sound (`EXTRA="-D NOSOUND=1"`) | 52.4 /s (93%) | 29.5 /s |

Musashi (`render_test.py`, a picture's render_frame; `logic_test.py`, a frame's logic, now with the sound's ~10k): the
logic 37-47k cycles a frame in play (21-27k in the level selection screens) without the sound; a picture 125-160k CPU cycles and 15-36k Blitter bus cycles
(13 seeds' averages).  Where a picture's time goes (`render_test.py --prof`, seed 4): the sprite rows 25%, the front
tiles over the sprites 13%, bringing the ring to the window 11%, the sprite list 10%, cell copies 9%, the tile RAM
compare 7%.  The dips in the timeline are the scene changes (a new floor: the caches flushed, everything baked and
drawn again) and the window's jumps at the 512-pixel wrap (the ring's whole window copied).  The program needs
1,504,648 bytes without the sound (text 68 KB, data 454 KB: the dispatch table, the ROM and the graphics; BSS 982 KB:
the four playfield buffers, the caches); the sound adds 127 KB (the voices 46 KB, the driver's translation, its 64 KB
memory image): 1,631,532 bytes.

## The schedule (src/kungfum.s)

The game's foreground waits for the IRQ in spin loops on RAM the IRQ handler changes ($E882: frames to wait, $E020
the intro's sequence, $E000 the state, $E904 / $E906 the inputs), and in play it runs a loop of HUD work (time,
score, extra lives) over and over while the IRQ handler plays the game.  Those pcs are idle hooks
(`machine.KungFuPort.HOOKS`, the translation's `z80_hook`): at a hook whose condition says the game waits, the runtime
draws the picture when due, waits for the next arcade frame and delivers the IRQ (RST 38) with a token as its return
address; the return continues at the hook (its instruction runs before the condition is looked at again), and a
handler that restarts the foreground (`jp $0217` at 012A / 0396: a coin in the attract mode) simply comes to the next
hook.  The play loop's head always yields: it runs once a frame instead of as often as the arcade's spare time
allows (its work is gated by the IRQ's counters, so the state is the same).  The VBL counts 56.25 arcade frames a
second (a second one every 8th VBL), at most 3 waiting; a picture at least every third frame.  `ld a,r` (the game's
random numbers) reads a shift register the reference has too.  The I/O ports: `in a,(n)` reads `io_ports`, `out (0)`
puts the sound command into a ring, `out (1)` the flip latch.  The tile RAM's 23 writers (from the coverage) mark the
64-byte row they hit; the renderer compares only marked rows with its copy.  The jump tables: coverage targets and
the 5th floor boss's table (`gen.py TABLES`); the other `jp (hl)` tables run whole or hold entries outside the ROM.

## The picture (src/render.s)

* **Two sources**, switched by `engine/rt/borders.s`' Timer B events (BD_HUD + BD_VSWITCH, as R-Type's status bar):
  the score panel (lines 0-47) from an image of its own with its own 16 colours, the playfield (lines 48-255) from a
  hardware-scrolled ring with the scene's 16 colours.  TA_DATA 98, PIC_TOP 10, PIC_LINES 256.
* **Virtual screens**: three rings and a clean screen of 304 lines x 424 bytes; buffer x b shows tilemap x (b mod 512)
  (twin columns up to 848), so the window Wx = (scroll + 96) mod 512 is contiguous: the video address by words,
  `$ffff8265` by pixels.  The tile RAM's changed cells are drawn (movep.l, baked per code, colour and scene in a
  cache) into the clean screen and marked in each ring's bitmap; a ring is brought to its picture from the clean
  screen with short HOG Blitter passes (`blit_go`): the columns the window's move brought into the picture span,
  the band columns blackened, its last sprites' rectangles, the marked cells (movep.l when inside the span).
* **Sprites**: cells baked on first use in natural row order (`REN_ORDER=0`; grouping equal masks measured
  slower overall and remains optional as `-D REN_ORDER=1`; see `docs/sprite-preparation.md`), a HOG pass a row (4 planes, under
  2 x 4 words), END1 / END3 from the row mask only when it changes, full destination addresses (no 64 KB limit).
  The picture's edges are at Wx + 32 and Wx + 288: a cell across the word boundary at or outside an edge draws only
  its inner word (left: FXSR, source X increment 0; right: the first word), a cell wholly outside is culled.  With Wx
  a multiple of 16 that is the edge itself (AGENTS.md); with the edge inside a word up to 15 pixels of a sprite show
  in the band (as Black Tiger's band words; nothing is erased after drawing), and the ring's next picture blackens
  them with its damage restore.  Top and bottom: whole cells into the guard lines (the panel covers the top).
* **Priority**: the tiles of colours 26-31 (MAME's category 1) copied back from the clean screen over the sprites'
  cells after drawing.
* **Colours** (`tools/assets.py`): a scene per floor (while a game or the demo runs) and one for the attract
  screens, each 16 colours: black (the bands) and 15 fitted by a weighted k-means in Oklab to that scene's pixels in
  the coverage runs, snapped to 4 bits a gun; every pen maps to the nearest.  The mean error per channel is 3.8-6.0
  of 255 (the playfield shows 30-51 colours a scene, 88 in all).  The panel: 15 fitted to its 36 pens (5.4).  A change
  of scene flushes the caches and draws everything again.

## Sound (src/sound.s, tools/sound.py, tools/sndgen.py)

The board (MAME irem/audio/irem.cpp, m62): an M6803 (3.579545 MHz / 4) writes two AY-3-8910s through its ports (port 1
the bus, port 2 the strobe, address / data and chip select), feeds two MSM5205 ADPCM voices from its NMI (the MSM5205's
VCK, 4 kHz) and gets the commands by IRQ, reading them from the first AY's port A.  The driver (a-3h): the NMI counts
($BD each, $C0 each 16th: the sequencers' 250 Hz tick) and feeds the voices; the main loop, once an NMI (each AY write
waits for one), handles a command (0 stop, 1-7 a voice, $10-$24 a sequence into one of four slots; $20-$23 the tunes
reset everything first), steps the slots whose timer ran out (scripts of AY register writes, loops, calls,
envelopes), and the volume decays.  The 45L's port A (the netlist drums of other M62 games) is never written: Kung-Fu
Master has no drums.

* **The model** (`tools/sound.py Board`, engine/m6801.py's core in expanded mode): MAME's 6803 cycle table, its E
  clock rounded up (894,887 Hz), the NMIs fitted to MAME's debugger traces (the first at E cycle 1156.86, every
  223.72), interrupts seen only where MAME's core looks (a timeslice's start, CLI after one more instruction, RTI),
  the DDRs reading $FF, the command latch visible from the start of the main CPU's timeslice that wrote it, the IRQ
  acknowledged only once the latch has bit 7.  Against MAME (`ref/mame_sound_kungfum.py 6000 --play`, the commands
  at the reference main board's exact times): all 2,066,844 port, acknowledge and ADPCM writes equal, in order; the AY
  register writes equal in every one of the 5,998 frames.
* **The STE's schedule** (`TickBoard`): no NMIs; the busy waits (an AY write's wait for $BD, a voice start's five
  NMIs) and the loop's port B write (the MSM5205 resets) are left out, and the main loop runs once per command (`$BC`
  set) and once per tick (`$C0` = 1; 4.4375 ticks an arcade frame).  The driver writes the same values; within a tick
  the arcade spreads them over the tick's NMIs and does the volume steps an iteration later, so the AY registers at
  the end of an arcade frame equal the exact board's in 55% of the frames (3,000 frames of play), the others differ by
  that sub-tick order (the tones' and volumes' steps, a few ms).
* **Translated, not recorded**: the commands share state (the slots write any AY register, the mixer masks and the
  volume envelopes are per channel), so recording each command alone would miss what an effect does to a tune; the
  driver is small (580 instructions, `tools/sndgen.py`: engine/m6801x.py's emitter, the ROM at $E000, words at odd and
  indexed addresses as byte pairs: the driver keeps words at odd RAM addresses, which Musashi accepts and the 68000
  does not).  Its iterations cost ~6k cycles an arcade frame (Musashi), a tune's start up to 55k.
* **YM2149** (`snd_ym`, `sound.py YM`): each arcade frame the three loudest audible AY channels (volume or envelope
  mode, tone or noise on) go to the YM, a channel keeping its YM channel while it stays chosen; periods x 2000000 /
  894886, noise and envelope from the chip of the first chosen channel that uses them, only changed registers written
  (none in a frame without AY writes).  ~2k cycles.
* **Voices** (`snd_voice`, `snd_mix`, `sound.py VoiceMix`): the seven voice samples (the shouts and screams) are the
  MSM5205's output decoded offline with MAME's algorithm (the exact board playing each command alone), resampled to the
  DMA sound's 6258 Hz, 46 KB.  Voice 1 (commands 1-2) and voice 2 (3-7) restart with their commands and end with 0 and
  the tunes (checked on the exact board); `snd_mix` adds the two into a 2 KB ring the DMA plays in a loop, four bytes
  at a time (biased bytes: no carry between them), 700 bytes ahead of the DMA's counter, from the main flow once an
  arcade frame (no interrupt).  ~1.6k cycles an arcade frame.
* **Checks**: `tools/sound_test.py` runs snd_frame and snd_mix on Musashi beside STEBoard and VoiceMix: the AY register
  files, the YM's registers and channel choice, the DMA ring, every frame: equal in 20,000 frames of random commands
  (all of the driver's commands) and 20,000 each of the game's commands (seeds 1 and 9).  Hatari (recorded play, 6000
  VBLs, DEBUG): no late border event; the music's pitch classes over the first tune match MAME's audio (`-wavwrite`)
  best unshifted.  Cost: logic 52.4 -> 51.9 arcade frames and 29.5 -> 27.1 pictures a second.

## The board (MAME irem/m62.cpp, m62_v.cpp)

* **Main CPU**: Z80 at 18.432 MHz / 6 = 3.072 MHz.  Map: $0000-$7FFF ROM, $A000 / $B000 write the scroll register's
  low / high byte, $C000-$C0FF sprite RAM (write only), $D000-$D7FF tile codes, $D800-$DFFF tile attributes,
  $E000-$EFFF RAM (stack at $F000 down).  I/O: reads 0 SYSTEM, 1 P1, 2 P2, 3 DSW1, 4 DSW2; writes 0 sound command,
  1 flip screen + coin counters.  IM 1; IRQ once a frame at the VBLANK (irq0_line_hold: held until acknowledged).
  The IRQ handler ($0038) copies the sprite list from RAM ($EB25.., 24 entries from $C020) and writes the scroll
  register right at the VBLANK, so the picture never changes mid-frame.
* **Sound board** (M6803 + 2 AY-3-8910 + 2 MSM5205, see "Sound"): it only receives the command byte (bit 7 0 raises the
  M6803's IRQ); nothing comes back to the main CPU: `sound_log` keeps (frame, command), `sound_times` the exact
  times for `ref/mame_sound_kungfum.py`.  In the attract sequence the game sends commands only at boot and around frame
  2986 (no demo sounds).
* **Screen**: 6.144 MHz pixel clock, 384 x 284 total, 256 x 256 visible (x 128-383, lines 0-255), 56.34 Hz: 192 CPU
  cycles a line, 54528 a frame.
* **Tiles**: a 64 x 32 tilemap (512 x 256 pixels) of 8x8 3bpp tiles (1024, `g-4c/4d/4e`): code = $D000 byte + attr
  bits 6-7 << 8, colour = attr bits 0-4 (32 sets of 8 pens), attr bit 5 flips x.  Opaque.  Rows 0-5 (the score panel,
  48 lines) are never scrolled, rows 6-31 by the one 16-bit scroll register (x only).  Over the sprites: rows 0-5 and
  every tile whose colour >> 1 is above 12 (colours 26-31).
* **Sprites**: 32 entries of 8 bytes (colour, y 9 bits, code 11 bits + flip x/y, x 9 bits), 16x16 3bpp (1024 cells,
  `b-*`), drawn first to last (the last on top), pen 0 transparent.  The height PROM `b-5f` (by code >> 5) makes a
  sprite 1, 2 or 4 cells tall (16x16, 16x32, 16x64).
* **Colours**: two 256-pen palettes from 4-bit-a-gun PROMs (tiles `g-1j/1f/1h`, sprites `b-1m/1n/1l`; 2.2k / 1k /
  470 / 220 ohm, 470 ohm pulldown, MAME's compute_res_net), then m62_amplify_contrast scales both by 255000 / the
  brightest luminance.  MAME's `pen_color` (what the Lua sees) is the colour before that scaling, the screen after.
* **DIP switches**: MAME's defaults (DSW1 $FF: easy, slow energy loss, 3 lives, 1 coin 1 credit; DSW2 $FD: upright,
  coin mode 1, no cheats).

## The reference (tools/machine.py)

`KungFuMaster` runs the Z80 with `engine/z80mame.py` (MAME's core, resumable mid-instruction).  The schedule is
MAME's: the screen starts at the VBLANK, frame k ends at k x the frame period.  A CPU cycle (325520833333 as) is a
little longer than two pixels (2 x 162760416666 as), so up to frame k's end the CPU gets 54528 k - 1 cycles (and may
finish its last M-cycle beyond); the IRQ is taken at the next instruction.  Rounding this up to 54528 k takes the IRQ
one instruction late at some frames, and the game's random numbers (`ld a,r` into $E010-$E013) drift: MAME's
debugger trace (`trace` with `totalcycles`) showed the one-cycle difference.  `Video` draws a frame from the tile
RAM, the sprite RAM and the scroll register (numpy, `engine/mamegfx.py`).

## The reference against MAME (ref/mame_cmp_kungfum.py)

One MAME run (`engine/mame_frames.lua`) dumps $D000-$EFFF at each frame and taps the write-only registers (sprite
RAM, scroll, I/O ports 0 and 1); a second short run takes the sprite palette's pens.

* pens: 0 of 512 differ (both palettes, before the contrast);
* render: the reference renderer from MAME's memory, 0 differing pixels at 60, 120, 300, 600 ... 3600 (attract, the
  intro, the demo play with scrolling, the high-score table) and every 600 frames from 4200 to 13800, and 13801-13802;
* logic: the reference from power-on: 0 of 8192 RAM bytes, 0 sprite RAM bytes differ, the scroll register and the
  sound commands of the frame equal, at all the same frames (up to 13802, MAME's 250 s limit), and its own picture
  differs from MAME's in 0 pixels.

Not covered: the flip screen (cocktail; the renderer raises), play with coins and inputs (the comparison runs the
attract sequence only).


## Default row order (2026-10-17)

`REN_ORDER=0` is now the default, matching the lower whole-picture CPU plus Blitter cost recorded in
`docs/sprite-preparation.md`; `-D REN_ORDER=1` retains the grouped-mask experiment. Verification: 1,122 synthetic
edge pictures exact (54 pictures crossing 64 KB), and 200 consecutive reference pictures with
`tools/render_test.py 800 --seed 4 --start 600 --stop`. Pinned Hatari `tools/bench.sh 2000` completed 2,001 VBLs
with zero late border or palette events (two startup fallback armings). This run checks timing for the selected
default; the earlier 6,000-frame measurement remains the basis for choosing it.

## Gameplay recordings

PPO is the standard supplemental exploration workflow; see [the shared guide](../../docs/ppo.md).
The earlier Kev experiment has been retired and its weights/runtime removed. Its small historical
[benchmark report](docs/gameplay-bot-benchmark.md) is retained as evidence.

The existing search recorder and RLE replay contract remain supported. Validate a recording without changing
canonical artifacts with `tools/play_replay_test.py RECORDING`; add `--every 1` for consecutive reference pictures.

### PPO RAM policy trained in MAME

The optional PPO controller trains on the original `kungfum` board in **MAME**, not the Python reference.
Use a separate Python 3.13 environment (the normal test environment stays independent):

```sh
python3.13 -m venv build/ppo-venv
build/ppo-venv/bin/pip install -r games/kungfum/tools/ppo-requirements.txt
build/ppo-venv/bin/python games/kungfum/tools/ppo_test.py --mame
build/ppo-venv/bin/python games/kungfum/tools/play_ppo.py train --steps 4096
build/ppo-venv/bin/python games/kungfum/tools/play_ppo.py record --model build/kungfum/ppo/policy.zip --seed 1
venv/bin/python games/kungfum/tools/ppo_hatari.py build/kungfum/ppo/ppo_1.bin
venv/bin/python games/kungfum/tools/play_replay_test.py build/kungfum/ppo/ppo_1.bin
```

`MAME`, `HATARI` and `TOS` override executable/ROM paths; the default Hatari/TOS paths are the pinned local
F030Arcade tools used by the other benchmarks. MAME 0.289 was used for the measured run. Existing generated
Kung-Fu Master code/assets and the assembler toolchain are required for Hatari and simulator replay checks.
`--out DIR` isolates a training/recording campaign. Each decision executes 12 MAME frames; `--frames 3600`
includes the 900-frame coin/start bootstrap. Training `--steps` counts decisions, rounded up to a 256-step PPO
rollout. `record --random` runs a uniform baseline over the same 21 actions, without rewinds.

The observation consists of E000-E8FF work/object RAM, C000-C0FF sprite shadow and the scroll bytes,
normalised to 0..1, with two consecutive observations. The policy has separate 64/64-unit actor and critic
networks, runs on CPU and has no text or screenshot model. Coverage is **exact first execution of main-ROM
instruction addresses** after frame 900, measured with one-shot MAME debugger breakpoints at every address
0000-7FFF. It can discover code missing from the existing disassembly. The reward combines global and episodic
PC novelty, within-floor scroll progress and new floors, with small death/time penalties. Coverage itself is not
part of the model observation. Coin/start, DIP switches and infinite lives follow the existing recorder's contract;
there are no stage skips, infinite energy or death rewinds. The model must be trained; no pretrained universal
arcade-game policy is supplied.

Outputs under ignored `build/kungfum/ppo/` include `policy.zip`, `training.json`, RLE `.bin` recordings,
MAME `.states.jsonl` checkpoints and per-run coverage/metrics `.json`. The recordings retain the existing
count/SYSTEM/P1 triples and zero terminator; inference and training are not needed to replay them.

`ppo_hatari.py` assembles an isolated, instrumented **native Hatari** program with normal rendering. It records
RAM/sprites/scroll and the port RNG at completed arcade-frame idle hooks, every 12 frames from 900, independent
of STE VBL timing or picture skipping. It compares those checkpoints against native MAME and separately against
`KungFuPort`, excluding only the dead merged-PUSH/POP stack bytes already excluded by `logic_test.py`.
`divergences.json` reports the earliest **captured checkpoint** that differs and the first differing addresses.
A matching audit is not an assertion about intermediate frames; `play_replay_test.py` checks every logic frame
in the existing simulator and sampled or consecutive reference pictures. Native MAME uses different CPU timing
and a hardware refresh-register RNG; MAME checkpoints also include the next-frame lives poke, whereas Hatari's
precede it. A native MAME mismatch alone therefore does not establish a translation bug. Hatari vs `KungFuPort`
mismatches, crashes, missing checkpoints, timeouts and mismatched replay metadata fail the audit.

The audit's `REPLAY_AUDIT` instrumentation is absent from normal builds. It writes diagnostic data through
GEMDOS, so its wall time is not a normal game-speed benchmark. Canonical `play_inputs.bin`, simulator PRG/map,
normal game PRG and existing coverage pickles are not replaced. See the [PPO coverage report](docs/ppo-coverage.md)
for the local training and replay results.

## Standard PPO exploration

Use `venv/bin/python port.py ppo kungfum test --steps 256 --frames 2100` to check the shared training/recording/replay workflow. See [the common PPO guide](../../docs/ppo.md). PPO supplements the existing scripted coverage; canonical replay fixtures are preserved.

## Full-game verification status

Automated players such as Dreamer can attempt a full playthrough once this port's
adapter and native Hatari replay transport are verified. An attempt or assisted
stage visit does not establish completion; a successful natural Hatari playthrough
and graphics, sound and control checks are required for green **Complete** status.
See the shared [status and verification policy](../../docs/port-status.md) and
[current port status](../../README.md). Existing test results above retain their
stated scope; this note does not claim a new successful run or Dreamer integration.
