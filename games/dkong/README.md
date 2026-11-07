# Donkey Kong (Nintendo, 1981) on the Atari STE

![Donkey Kong on the STE (Hatari)](docs/screenshot.png)

MAME set `dkong` (`nintendo/dkong.cpp`, `dkong_v.cpp`, `dkong_a.cpp`).  The main Z80 is statically translated to
68000 code (`engine/z80x.py` FAST) and checked in lock-step against a reference machine (`tools/machine.py`); the
8257 sprite DMA is a runtime routine.  The 8035 sound board is recorded in MAME and played as 8-bit DMA sound clips;
the discrete walk, jump and stomp circuits are YM2149 patches measured from the same recordings.  The picture is the
project's first renderer: the tile map compared with a shadow, generated Blitter code per sprite line; it equals the
reference renderer and MAME pixel for pixel.  Status: **Verification pending** (assisted loop replay verified;
full-game checks pending).  Speed: one arcade frame per 50 Hz VBL, 50 arcade frames a second (83% of the arcade's
60.6 Hz), 50 pictures a second in play, 0.8% of the frames late (Hatari, `-D TIMES=1 -D AUTOSTART=150`, 3000
frames, 4 MB, 2026-10-12).

## Build and run

```sh
python3 -m venv venv && venv/bin/pip install numpy pillow machine68k scipy   # once, in the repository root (scipy: the sound)
python port.py cover dkong          # coverage + palette pens the translator seeds from (~15 min on 8 cores)
python port.py build dkong          # -> run/dkong/DKONG.PRG (the ROMs embedded: nothing else needed)
python port.py test dkong           # lock-step 3000 frames, the build, the sprite edges
python port.py run dkong shot@30    # Hatari (F030Arcade build), screenshot at 30 s
python port.py mame dkong           # the reference picture against MAME (ref/mame_cmp_dkong.py)
python games/dkong/tools/build.py -D AUTOSTART=150    # a coin at frame 150, start a second later, then walk and jump
```

Supply `assets/roms/dkong.zip` (MAME's parent set; `docs/rom_manifest.json` has the 15 files' sizes, CRCs and
SHA-1s); `tools/prepare.py` joins the four CPU ROMs into `cpu.rom`.  The coverage and pens runs reproduce the
committed logs (`docs/coverage/*.log`) exactly (3766/4949 PCs, 155/115/154 pens).  `VASM`/`VLINK` select the
toolchain; the default on macOS is `~/Work/f030dsp3d/tools`.  The program needs about 2.3 MB of RAM (sprite data
0.9 MB, the dispatch table 256 KB).  The first build records the sound (below, ~1 min) when its output is missing.
Paths are relative to this folder; `engine/`, `tools/`, `port.py` and `docs/` at the top are the repository's; the
commands run from the repository root.

## Controls

**5** coin, **1/2** start, **arrows** move, **Space/Ctrl/Alt** jump, **Esc** quits.  Players take turns: both
joysticks and both pads move Mario (fire jumps).  Jaguar pad / PowerPad (STE enhanced ports,
[architecture](../../docs/architecture.md#input-all-ports)): either pad, the D-pad moves, **A / B / C** jump,
**Option** coin, **Pause** start, keypad **1/2** start, **5** coin, **\*** + **#** quit.

## State

* **Logic**: exact.  `tools/logic_test.py 3000` (2026-11-07) runs all 3000 frames in lock-step against the Z80
  reference, as `port.py test dkong` does.  `tools/insn_bench.py` (2026-11-07): 2420 single-instruction cases, 1
  fails (`ldir`: BC' and DE' differ; Donkey Kong has no `exx`).
* **Picture**: exact.  The screen equals the reference renderer pixel for pixel, frozen at frames 650, 800, 1000 and
  1200 (0 of 57344 pixels differ; frame 800 re-checked after the MAME fixes of 2026-10-08), and the reference equals
  MAME's screenshot ([porting guide](../../docs/porting-guide.md#against-mames-picture-every-port)).
  `tools/sprite_test.py`: 2048 edge cases exact, side bands untouched; `engine/sprite_blit_test.py`: 8192
  shape/skew/direction checks and 48 renderer comparisons.
* **Hatari** (F030Arcade build, STE, 4 MB): 50 pictures a second in play; 5000 VBLs without a crash file; the Dreamer
  playtests reached the difficulty loop with assistance (Verification).
* **Sound**: recorded from MAME, loudness and pitch within 1 dB a frame of the arcade; the YM's discrete sounds are
  brighter than the arcade's circuits (Sound).
* Not done: a natural full playthrough with graphics, sound and control checks; the 16-sprites-per-scanline limit and
  the sprite wrap-around of the arcade hardware; the arcade's full rate (one NMI per 50 Hz VBL: 83%).

## How it works

### The board and the reference

`tools/machine.py` is the reference machine (the Z80, the video, the 8257 DMA); `tools/dkong_pens.py` holds the 256
palette pens dumped from MAME 0.289; `ref/mame_cmp_dkong.py` compares the reference picture with MAME's.  The MAME
check of 2026-10-08 fixed the sprite row and the palette: a sprite's left display column is u0 = y - 23 (it was
y - 22: MAME's line buffer fetches a sprite one line ahead).  Files: `src/` (`dkong.s` runtime, `render.s` tiles,
`sprites.s` Blitter sprites, `sound.s`), `tools/` (`machine.py`, `dkong_pens.py`, `prepare.py`, `gen.py`,
`assets.py`, `build.py`, `logic_test.py`, `nmitrace.py`, `insn_bench.py`, `perf_test.py`, `sprite_test.py`,
`frametimes.py`, `sound_capture.py`, `sound_convert.py`, `sound_ym.py`), `ref/` (coverage `cover.py` /
`cover_stages.py` / `cover_pens.py`, `mame_cmp_dkong.py`, one-off probes in `ref/probes/`), `docs/` (the screenshot,
the coverage logs in `docs/coverage/`, the loop regression report).

### Translation

`tools/gen.py` translates from the coverage (`ref/cover.py` seeds 11-14, `ref/cover_stages.py` 21-24) with
`z80x.FAST`; no runtime change was needed for it: Donkey Kong has no `exx` / `ex af,af'`, and `logic_test.py` reads
IY from a2.  BC is kept swapped; the dispatch table has 65536 entries (256 KB).  `ref/cover_pens.py` (seeds 31-33)
finds the palette pens.  The other ports' translator figures:
[architecture](../../docs/architecture.md#tests-and-measurements-of-the-translator).

### Schedule

VBL-locked ([architecture](../../docs/architecture.md#the-schedules-in-use)): the VBL switches the screens, starts
the border timers (`engine/rt/borders.s`), copies the inputs, runs the Z80 NMI ($0066, return token $4001) when the
NMI mask `$7D84` is set, then draws; the main thread (the idle loop, head $02BD) runs below the VBL level.  A frame
that takes longer than a VBL is interrupted by the next one, which only restarts the border timers (`vbl_skip`).
One NMI per 50 Hz VBL: 5/6 of the arcade's rate.

### Picture

**Tiles** (`src/render.s`): the 1 KB tile map is compared with a shadow every frame (the 224 visible longs, eight per
turn); changed tiles go into the background screen at once and into a queue for each draw screen.  A palette bank
change (level starts, the title wipe, the title logo's colour cycle: 48 changes in 96 frames) draws only the visible
tiles that look different in the new bank: `dk_tile_pens` (the pens a tile code uses) against `dk_bank_change` (per
old and new bank and colour code, the pens whose palette index moves), both from `assets.py`.  In the logo cycle
that is about 160 of 896 tiles; the first frame draws all of them.  Level starts and the title wipe redraw every tile
and take about ten frames each.

**Sprites** (`src/sprites.s`, `engine/sprite_codegen.py`): the project's first sprite renderer (described in the
architecture document until 2026-11-07); the later ports refined it
([sprite preparation](../../docs/sprite-preparation.md)).  Like the bob routines of `stefastbobs2/main.s`: one blit per
sprite line writes the four planes of the line (Y count 4, source = destination), and the end masks are the mask:
END1/END3 hold the outline of the line (holes included) shifted to the two screen words, so the opaque pixels
replace what is below and the rest stays.  No clearing pass, no colour mixing.  The masks of every (shape, flip y,
skew) are a table (`dk_spr_masks`, 256 KB); the line words come from colour data baked per colour quad
(`dk_spr_data`, 608 KB: 19 distinct mappings of the pen values to the planes) that the Blitter's source address
walks through; `NFSR` lets the second destination word reuse the one source word of a plane (a sprite of skew 0 is
one word wide); flip x draws the lines upwards.  The Blitter registers of the line loop are written through
preloaded pointers (END1, END3, control, Y count, and the low word of the destination address, advanced with
`add d4,(a3)` as in the demo).  The empty lines at both ends of a shape are left out (`dk_spr_span`).  END2 is unused.

The fast path selects generated code for the shape/skew (`engine/sprite_codegen.py`): masks that stay the same are
not written again, empty interior lines are skipped, and a line whose END3 is zero uses X count 1 even at a nonzero
skew.  Such a line clears NFSR and sets destination Y increment 2; a two-word line sets NFSR and Y increment -6.
Both finish eight bytes past their starting destination and consume eight source bytes.  Lines whose END1 alone is
zero still use two words: their source would need a different shift/pipeline arrangement.  Colour data remains shared
by every skew; the generated instruction sequences and compressed mask streams are deduplicated separately.  Sprites
whose lines cross a 64 KB boundary of the screen keep the original unrolled full-address path.  `-D NOSPRITECODE=1`
selects the generic renderer for comparison.

**Edges**: the game area's edges lie on chunk boundaries (GAME_X = 3 chunks, 14 chunks wide), so sprites are clipped
there by the shared rule ([porting guide](../../docs/porting-guide.md#renderer-correctness)): a sprite across an edge
(display column u0 -15..-1 or 209..223) draws only its inner word, one word a line (`sprite_edge` in
`src/sprites.s`; right: the first word, the skewed source under the line's END1 mask; left: the second word, FXSR
and source Y increment 0 under the line's END3 mask, which the line macros write to END1).  Its rectangle and cells
are the inner chunk's, so the side bands stay black and are never restored; a sprite wholly outside is culled.  The
common path tests both with one unsigned compare; the edge path is the same macro (`sprite_draw 1`) with the generic
masks and full addresses, the 64 KB fallback included.  Top and bottom use guard rows.

**Damage**: most of the 128 list entries are empty: a frame first lists the entries that are not empty (`tst.l`
over the list), and each draw screen keeps the list it was last drawn with and remembers per slot what it got there
(list entry, colour bank, rectangle, cells).  A frame restores the background under the sprites of the screen's old
list that changed or are gone, then draws the active list: a sprite that is unchanged is drawn only if its rectangle
touches an 8x8 cell that was redrawn (tile), restored or drawn (a sprite earlier in the list) in this frame.  The
cells are a bitmap (`tile_marks`, 8 bytes per display row, cleared each frame); a sprite's cells are a window of four
bits in up to three rows, kept in its slot record, so a test is three `and.l` and a mark three `or.l`.

`z80_dma` (`engine/rt/rtlib.s`) is the 8257 sprite DMA, hooked on the `ld ($7D85),a` stores.

**Colours**: a small PROM set merged by distance and the square root of the minimum count
([colours](../../docs/colours.md#what-each-port-uses)).

### Sound

The arcade's 8035 sound board (tunes on `$7C00`, effects on `$7D03-$7D05`, death on `$7D80`) plays one mono DAC
stream, so it is pre-rendered and played by STE DMA sound (`src/sound.s`, a few hundred cycles a frame, estimated,
not measured).  `tools/sound_capture.py` records the board in MAME (the main CPU parked on a `jr $`, a Lua script
writes the ports; needs a full MAME build: default `C:\Arbeit\F030Arcade\third_party\wolfmame-0162\mame.exe`, else
the `mame` on the path, `$MAME` overrides); `tools/sound_convert.py` turns the recordings into
`build/dkong/dk_sound.s` / `dk_sound.bin`: 8 bit signed, 6258 Hz (the board low-passes at ~1.9 kHz), 317 KB.
`build.py` runs both only when their output is missing (~1 min).

What the driver copies from the 8035 (measured in MAME): a one-shot tune starts when `$7C00` changes to it and plays
to its end (the game holds it 3 frames); a background tune (03 04 08 09 0B) loops while `$7C00` holds it and starts
again from its beginning after a one-shot; a rising edge on a pin starts its effect; the newest sound wins.  The
background loops are one measured period each (2.29 s barrels ... 4.92 s out of time), seams in silence.

Walk, jump and stomp (`$7D00-$7D02`) are discrete circuits on the arcade board, independent of the 8035: YM channels
A, B, C, one (tone period, volume) a 50 Hz frame, restarted by a rising edge.  `tools/sound_ym.py` measures the
patches from the MAME recordings (pitch by autocorrelation, stomp: the mean of its own random 5.5-13 ms cycles per
frame; level by RMS, matched through Hatari's measured YM volume table and a gain measured in Hatari, -11.9 dB) ->
`build/dkong/dk_ym.s`, plus A/B files in `build/dkong/sound/ym/`.  Loudness and pitch follow the arcade frame by
frame (< 1 dB a frame); the tone is brighter: the arcade circuits are integrated (stomp has 95% of its energy below
200 Hz, nothing above 800 Hz), a YM square puts 7-19% above 800 Hz, and the pitch only changes 50 times a second (the
stomp's real cycles change every 4-6 ms).

## Speed

| Date | Setup | Logic | Pictures | Musashi cycles a frame |
|---|---|---|---|---|
| 2026-10-12 | Hatari, `-D TIMES=1 --debug`, AUTOSTART=150, 3000 frames, 4 MB | 50 arcade frames a second, 83% | 50 a second, 0.8% of the frames late (the full redraws); drawing 59.0 Timer D ticks a frame | logic 15.4k, picture 34.8k (`draw_sprites` 24.4k), total 50.2k (`tools/perf_test.py 3000 200`) |
| 2026-10-09 | Hatari, TIMES, 4096 frames of `port.py cover dkong`'s coverage | 83% | a frame takes 35% of the 50 Hz frame on average (Z80 NMI 9%, drawing 26%), 2.6% run into the next VBL | |

What made it fast, newest first:
* **Translator** (2026-10-08): `z80x.FAST`; `engine/xprof.py dkong` (1500 NMI frames of `logic_test.py`): translated
  code 5.2k -> 4.8k cycles a frame (1.08x, the direct returns and the flags).
* **Selective palette bank redraw** (2026-10-09, with the translator speed-up): average 44% -> 35% of a frame.  The
  title logo's colour cycle (96 frames, 1.6 s on the arcade) lost 618 VBLs when every bank change redrew all tiles,
  now 148 (2 at a change, 1 the frame after, for the other draw screen; the game's own code takes 32% of a frame
  there).  The rest of the late frames are the start, the title wipe (0 -> 2: nearly every tile) and single level
  starts.
* **Generated sprite code** (2026-10-08, `engine/sprite_codegen.py`): 3.2% less CPU plus Blitter bus work over the
  `sprite_blit_test.py` workload (isolated line bodies 9.0%; Galaga's 4.3% and 9.9%); simulated, not a Hatari
  figure.  The executable grew by about 407 KB (Galaga's 558 KB) and still fits a 4 MB STE.
* **Sprite list and damage** (2026-10-07: the non-empty list, slot records, cell bitmap; the tile shadow): the
  average frame 75% -> 44% of a 50 Hz frame (Z80 NMI 14%, drawing 30%; play frames 50-80%, the busiest 96-119%, 6 of
  2400), skipped VBLs 9% -> 0.5% (2400 frames of attract mode and demo play, a 50 Hz frame = 160256 cycles).  Visiting
  all 128 list entries twice a frame had cost 24K cycles.

Measured, not kept: none of this port's own.  Not tried here: the full reordered-source preparation (Galaga measured
it with `engine/sprite_programs.py` and found it not faster:
[sprite preparation](../../docs/sprite-preparation.md#what-the-ports-found)).

Techniques other ports use that may apply:
[speed.md](../../docs/speed.md#techniques-that-look-applicable-elsewhere-2026-11-07).

## Tests and tools

* `tools/logic_test.py 3000`: the whole program in lock-step against the Z80 reference, the NMI injected at the idle
  loop head.  `tools/nmitrace.py N`: the NMIs from frame N on, instruction by instruction, names the first diverging
  instruction.  `tools/insn_bench.py`: single instructions against the Z80 reference; the full instruction check is
  `engine/xbench.py`.
* `tools/sprite_test.py`: 2048 cases (4 shapes with holes, both flips, 16 shifts, at both edges and outside, plain
  and across a 64 KB boundary, the restore a frame later), on the generated-code and the NOSPRITECODE build.
  `venv/bin/python engine/sprite_blit_test.py` (also in `port.py test engine`) builds both sprite paths and executes
  the assembled 68000 code on Musashi with a Blitter model: all 8192 shape/skew/line-direction combinations against
  independent masked pixels, then 48 successive complete sprite renders against the generic path (overlap, background restoration,
  colour changes, 64 KB crossings); Galaga's part too.
* `tools/perf_test.py FRAMES N` (Musashi, the sim build with AUTOSTART=150, the VBL raised at every third idle-loop
  visit so two builds play the same frames): CPU + Blitter cycles a frame for the logic, the picture and
  `draw_sprites`.  There is no bench script for this port.
* `tools/build.py` options: `--debug`: frame, Timer A, Timer B, VBL and skipped-VBL counters as bits in the top-left
  corner (plane 0, lines 0-4; read them back from a Hatari AVI; an AVI starts at power on, the program about 300
  VBLs later).  `--dumpat N`: at frame N write Z80 memory `$6000-$7FFF` to `DUMP.BIN` and freeze the game; the screen
  can then be compared with `tools/machine.py`'s `render_raw()` of the same memory.  `--dumpbank N`: the same at the
  Nth palette bank change (20 and 21 are in the title logo's colour cycle).  With TIMES, give `--frames` more than the
  run reaches: the frame count goes on while the game stands still.  `-D TIMES=1 --debug --frames N`: MFP Timer D
  (81 us ticks) is started at every VBL and its count recorded when the NMI and when the drawing end, with the
  skipped-VBL count and the palette bank; `TIMES.BIN` is written when the program quits after N frames
  (`python games/dkong/tools/frametimes.py TIMES.BIN` prints the histogram); run with `--run-vbls` of about
  N*5/4+600.  `--nosprites`: no sprite drawing.  `-D NAME=VALUE`: any define.  `-D AUTOSTART=150` with Hatari's
  `--avirecord true --sound 44100 --run-vbls 3000` records coin, intro, How high, the barrels loop and the deaths
  (the AVI says 60 fps for the 50 Hz frames).
* Profile: in the Hatari debugger `profile on` at one VBL breakpoint and `profile save` at a later one; Hatari 2.6
  prints the per-address lines to its stdout.
* Comparing builds: the game is not deterministic across builds.  Its idle loop counts its spins (`inc ($6019)`),
  so the attract sequence and the demo play depend on how much CPU time a frame leaves; frame counts of two builds
  show different game phases.  What compares exactly is a frozen frame of one build against the reference renderer.

## Lessons

### 2026-10-12: clipping at the side edges costs nothing

Before, sprites hung into the visible side bands (4 band pixels in the last frame of the run, none now); the old code
fails `tools/sprite_test.py` (pixels in the left band).  `tools/perf_test.py 3000 200` (2800 frames, ~4 edge sprites
drawn a frame): logic 15423.9 cycles a frame both; picture (render_frame) 34807.6 -> 34818.9 (+0.03%), draw_sprites
24344.7 -> 24356.0; total 50231.5 -> 50242.8 (+0.02%).  Hatari (not the same frames, see Tests and tools): 50 fps
both, 0.8% frames late both, drawing 59.8 -> 59.0 Timer D ticks a frame.  The common path's two signed compares
became one unsigned compare.

### 2026-10-09: recorded sound is not sample-exact

Two MAME runs of the same port-write script differ: a rebuild of the clips differs in ~0.3% of the bytes, by a few
steps.

### 2026-10-08: the sprite revision kept the source order

The reference's (stefastbobs2's) arbitrary row reordering relies on matching reordered source data; copying that
order without also preparing matching source data would break the sequential source walk.  The revision retained the
source layout and used register reuse and variable-width blits.  The later `engine/sprite_reorder_audit.py` is an
instruction-cost estimate for source seeks, not an executed prototype of reordered source data.  The rebuilt binary
completed 5000 VBLs in the pinned Hatari with no crash file.

### 2026-10-08: tools must follow the translator's register layout

`tools/insn_bench.py` failed 61 cases once BC was kept swapped, until it learned the swapped BC and the 65536-entry
dispatch table.

## Verification

Dreamer Hatari playtest (2026-10-20): the adjacent Dreamer project's `scripts/stearcade_play.py` explores the port in
a patched Windows Hatari (SHA256 `f113a3853fd993cac459cb672748f1c20c59ee4ac370501f49d5a6597cbf1796`) that instruments
the NMI opportunities and owns the input bytes.  The natural run completed 22,200 ticks (1,800 decisions, 434 learner
updates) without a detected crash, input mismatch or 600 identical RAM observations; it lost lives and restarted but
did not clear barrels.  A separate 22,200-tick assisted run refilled lives and requested stage types 2, 3, 4 and 1 by
writing `$6227` (assisted visits, not natural clears); both fresh-process replays matched all 185 sampled RAM
checkpoints (370 in all).  The assisted continuation then used the ROM's own board-clear paths for all four types
(refilled lives, assisted exit and rivet conditions; no writes to stage, difficulty, pointer or phase state), entered
difficulty 4 after the four-type level 3 sequence and reached the repeating sequence's level 5 -> 6 pointer wrap at
tick 36,727.  A fresh process replayed all 38,200 inputs with 318 exact RAM checkpoints and identical progression; no
missing translation or port crash was found ([the loop regression report](docs/dkong-loop-regression-2026-10-20.md)).
Limits: keyboard/pad handling, sound, full renderer equivalence and natural full-game progression were not verified
there (sampled guest framebuffers showed gameplay); the Dreamer project's `docs/stearcade-playtesting.md` describes
the commands, instrumentation and limits.  This establishes assisted progression, not a natural clear.

PPO exploration: `venv/bin/python port.py ppo dkong test --steps 256 --frames 2100` ([the PPO guide](../../docs/ppo.md)).
Full-game verification follows the [status policy](../../docs/port-status.md); nothing here claims a complete playthrough.
