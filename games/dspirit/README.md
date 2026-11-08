# Dragon Spirit (Namco, 1987) on the Atari STE

Atari STE port of the MAME set `dspirit` (Namco System 1, `namco/namcos1.cpp`, ROT90), built from Galaga '88's
([its README](../galaga88/README.md)) and Splatterhouse's ([its README](../splatter/README.md)). The main and sub
MC6809E programs are translated to 68000 code (`engine/m6809x.py`, `tools/gen.py`, `src/core.s`) with three natives,
and are identical to the reference board `engine/namcos1.py` over 7700 frames on six seeds; the CUS64 MCU (HD63701)
runs as Splatterhouse's native model; the sound CPU is not run. The picture is upright and widened to the STE's 320
pixels (`src/render.s`, exact against the reference model); there is no sound. Status: Experimental / deferred (logic
exact, 320-pixel renderer, no sound); not registered in `port.py`, not released, and the program needs more than the
4 MB release budget: it is developed with 14 MB in Hatari (the user, 2026-11-07). Latest speed (2026-11-08, Hatari
14 MB, BENCH game: the intro, then stage 1): 8.32 arcade frames a second (14% of the arcade's 60.606 Hz), 2.93
pictures a second; logic 83.9k Musashi cycles a frame (seed 5).

## Build and run

```sh
venv/bin/python games/dspirit/tools/prepare.py          # checks dspirit.zip (docs/rom_manifest.json), unpacks it
venv/bin/python games/dspirit/ref/cover.py SEED FRAMES [--port]   # coverage -> build/dspirit/cover_[port_]SEED.pkl
venv/bin/python games/dspirit/tools/make_render.py      # writes src/render.s (Picture)
venv/bin/python games/dspirit/tools/build.py            # run/dspirit/DSPIRIT.PRG (--sim: the Musashi build; -D NAME=V)
venv/bin/python games/dspirit/tools/logic_test.py FRAMES --seed N   # lock-step against the reference
venv/bin/python games/dspirit/tools/render_test.py      # every picture against the reference model
games/dspirit/tools/bench.sh [TAG]                      # Hatari BENCH (Tests and tools)
```

ROM: the MAME set `dspirit` (`assets/roms/dspirit.zip`, unpacked to `assets/roms/extracted/dspirit/`). The port is not
registered in `port.py` (no `tools/hatari.sh`, no release): start `run/dspirit/DSPIRIT.PRG` in the pinned Hatari (STE,
14 MB) as `bench.sh` does. Uncovered code writes CRASH.TXT. Paths are relative to this folder; `engine/`, `tools/`,
`port.py` and `docs/` at the top are the repository's.

## Controls

Arrows, space / Z air shot, X / Alternate bomb, 1 start, 5 / 6 coin, Esc quits (writes COUNTERS.BIN); joystick 1, its
button both air shot and bomb.

## State

* Logic exact (2026-11-07): `logic_test.py 7700` identical for the attract mode (seed 1), the covered play seeds 5 and
  6 and the uncovered seeds 9, 10 and 11; with the natives `logic_test.py 3000` identical on seeds 5 and 22. Main
  13579, sub 2657 instructions translated, none unsupported (coverage: MAME schedule seeds 1, 4-8, 4000-6000 frames;
  port schedule seeds 1, 5, 6, 12-15, 8000 frames).
* MCU: `tools/mcu_test.py` 1500 frames: TRIRAM and the MCU's RAM equal, 12 frames with 98 / 100 instead of 99 voice DAC
  writes around a sample's start (the voice, not the game).
* Picture exact: `render_test.py --every 3` play 500 / 500, attract 167 / 167, `--edges` 252 / 252; with
  `FLAGS_ALL=1` (every writer flag set every picture) exact too. `tools/stemodel.py 2000`: 200 play pictures exact.
* Coverage of later stages is open: random play reaches only the first stage or two; later stages' code is translated
  where static flow and the jump tables reach it (`badpc` / CRASH.TXT where not). Snapshots, a scripted or Go-Explore
  player ([go-explore.md](../../docs/go-explore.md)) are the way.
* Memory: 3.79 MB (text + data + bss) before the renderer's buffers, about 3.8 MB with them: over the release's 3.7 MB
  load budget; the 4 MB release is open.
* Missing: sound.
* Speed: 14% of the arcade's rate; the logic alone takes ~0.81 VBL an arcade frame in Hatari.

## How it works

### The board and the reference

`tools/machine.py`: the reference board (`engine/namcos1.py`, MAME's scheduler) and the port's schedule
(`run_frame_port`), as Galaga '88's: the vertical blank, the MCU and the sound CPU on the board's scheduler, then the
main CPU's IRQ and frame, then the sub CPU's. The port starts at frame 300 (`tools/snapshot.py`: snapshot_vio.bin is
vio's starting content, core.s; snapshot_ctx.bin the CPUs', the key custom's and the MCU's).

* Main (DP $40: slot 2, the work RAM): `8048: JSR $8770` (the random numbers: an LFSR step of `<$D3/$D4`),
  `804B: STA $F200; LDA <$FF; BNE 8048`, then `INC <$FF; JSR $8140` (the frame). The IRQ handler ($81B4) clears
  `<$FF`. The arcade steps the LFSR on every pass (~3600 a frame); the port once a frame: idle at $804B while `<$FF`
  is set (core.s `main_idle`).
* Sub (DP $20: slot 1, the scratch RAM; its stack in slot 2): it never waits. The IRQ handler ($D6CD) clears byte 9
  of every sprite entry; the foreground loop `D6C5: STA $F200; JSR $D8B0; BRA D6C5` builds the sprite list from the
  objects in the work RAM ($41A0 + $28 n) on every pass, from scratch (~12 passes a frame in the arcade). The port
  runs one pass a frame: back from the IRQ at $D6C5 the pass starts, at its end the sub is idle (`sub_pass`, core.s
  `sub_idle`).
* The port's game runs ahead of the arcade's (frame 600 of the intro: the dragon already formed, MAME still in the
  flash): the arcade's main CPU overruns some frames; the port's schedule has no such frames.

### Translation

* **Coverage** (`ref/cover.py SEED FRAMES [--port]` -> `build/dspirit/cover_[port_]SEED.pkl`): seeds 1-3 the attract
  mode, seeds 4+ coin, start and random play (the 8-way stick, air shot 60%, bomb 15% of the holds: `random_bits`).
  `--port` runs the port's schedule (`tools/machine.py run_frame_port`) with the inputs of `tools/logic_test.py`
  (Lessons). `tools/gen.py` reads both kinds.
* **Direct page**: per CPU (`Program(dp=, a3_slot=)`; core.s `DPS` / `DPR` in the context). The main CPU's bank
  routines in page $334 ($A215, $A22A) use DP as a scratch register (`TFR B,DP`: DP = slot * $20 + $10) and map slot 6
  to the C116 registers (page $173) or TRIRAM (page $17F); the code after them reaches those through `<$xx` with DP
  $C0 / $D0 (a constant per site, `dp_sites`). The routines' shared instructions run with several DPs: allowed where
  the instruction neither addresses the direct page nor reads DP (`gen.py dp_free`).
* **Page $334 in two slots**: the main CPU runs that page's position-independent code from slots 5 and 6. The
  translation keeps one slot per page: slot 6's copy is page $30C (a mirror of the same ROM bytes; `PAGE_ALIAS` in
  ref/cover.py and tools/gen.py, `Program.page_alias` for the translation's inline bank writes, core.s `bank_set` and
  `alias_page`, its own 8 KB copy so the translation's page checks by address tell the two apart).
* **Jump tables** (`gen.py table_targets`): random play does not reach every entry of the state machines' tables
  (`JMP [A,U]`, `JMP $2000,U` after `LDU A,U`, `JMP D,X`). Per computed jump the coverage saw: the table's base from
  an immediate load on an executed path just before it, then its entries while they stay in the slot of the seen
  targets, outside the table and the executed instructions, and decode as legal code; they become roots (30 tables,
  ~250 entries). Entries into a slot whose page is set just before the jump (main $B80B: slot 3 = page $371) are not
  found that way: coverage only.
* **The protection check** (main $B65C-$B672): slot 0 gets page $173 (the C116's registers), the program patches the
  byte at $0004 from $0001 / $0003 and calls `JSR $0002`: `PSHU` with no registers, then `RTS` ($39) when the check
  passes. The port does not run code from RAM: core.s `main_prot` checks the three bytes and goes on after the JSR
  (else badpc $0002).
* **Stores into ROM**: main $AC00-$AC1A (`STA $6000` / `$6200` / `$6400` / `$6600`) write into slot 3's ROM page; the
  arcade ignores them. Such sites (`gen.py rom_writes`) go through core.s `io_w`, which drops stores into ROM pages.
* **Key custom**: CUS136 (type 1): registers 0-2 read the remainder and the quotient of regs 1-2 (16 bits) by reg 0
  (8 bits), register 3 the id $36 (core.s `key_divide`: one `divu`).
* **Dispatch**: the dispatcher's page tables are two-level (a directory of 32 blocks of 256 labels a page:
  `tools/gen.py dispatch_tables`; 556 -> 267 KB).

### Natives

`src/natives.s`, `tools/gen.py` NATIVES (`NO_NATIVES=1` builds without; R-Type's exact natives, 2026-11-07): the
object-slot loop $C37F (empty slots skipped), the tile-column fill $7A54 and the 4 x 4 tile block $C0DB (the stage's
tile streaming). Their test is `logic_test.py` (it runs the built program: `build.py --sim` first).

### Schedule

`src/dspirit.s` (from Galaga '88's): the translated CPUs from the snapshot at frame 300, the MCU (Splatterhouse's
native CUS64 model, the same ROM in all four Namco System 1 sets), the sound CPU's handshake answered, a picture every
`PIC_EVERY` (2) arcade frames; `MAX_BEHIND` 3 ticks behind before arcade frames are dropped (the game slows).

### Picture

Display (decided with the user, 2026-11-07): upright (the arcade picture 288 x 224 turned, as MAME shows it), widened
to the STE's 320 pixels: the scrolling layers and the sprites over the whole 320 pixels (the terrain maps hold valid
tiles beyond the arcade's 224: checked in areas 1-4), the text layers at their old place (x 48-271; their rows 0-15
shown 5 lines lower, 264-287 6 higher, so all of them fit the 277 lines of the open borders, `engine/rt/borders.s` as
Galaga '88: picture rows 5-281 shown), stage 1's water layer (2, under the terrain) locked to the terrain (its offsets
taken when the lock begins).

`tools/make_render.py` writes `src/render.s` from `src/render_new.s` (Dragon Spirit's parts), the colour, bank-map and
sprite-cache routines of Galaga '88's renderer (copied by label, patched in its `PATCHES`) and `src/render_data.s`.
Galaga '88's picture (ROT270 with its screen flip) has Dragon Spirit's geometry (ROT90, no flip): its turned
characters and sprites and its `ren_convert` are right as they are; the sprite positions are Dragon Spirit's.
`tools/stemodel.py picture_wide` is the picture in Python.

* Layers in play: 0 the terrain (all areas; stage 1: holes over layer 2, the water), 1 / 3 clouds, 4 / 5 the text.
* The buffers: two, each 2 x 288 lines (twin lines: any 277 in one block) of 424 bytes (the terrain's 512 columns and
  its first 336 again, twin columns: any 320 + the fine scroll's 16 in one line). The window: its first line follows
  layer 0's scroll (`ren_view`), screen x 0 is layer 0's image column K (`ren_xo`): the VBL sets the base, $ffff8265
  (the fine scroll) and $ffff820f (the line's rest). Vertical and horizontal scrolling are free.
* The terrain mode (`ren_mode`: layer 0 on and the first layer drawn, the C116 window whole, no sprite below
  layer 0): layer 0's image (all 64 tile columns of the 288 rows, the locked layers in its holes, its holes black)
  is the buffer's terrain: drawn whole only for a new tag (colours, bank, lock) or a scroll of a window or more;
  else last picture's damage is restored from the twin lines, and the rows that scrolled in or whose image rows
  changed (`ren_tdirty`) are drawn (both twins, both column copies). Clouds, text and sprites go on top into the
  window; their rows' group spans are the damage (`ren_dspan`, gathered over a row's passes: one `ren_dmg` a row).
  The text layers' passes are recorded per fine shift (`ren_pbufs`) and streamed while the text is unchanged.
* Otherwise (the title, the intro, the iris windows) every layer is drawn into the window (black first): the buffer's
  terrain is lost (drawn whole next time).
* Shared: a layer's turned image (512 x 512, mask, per row run lists rebuilt only when a tile changed its bytes),
  tiles drawn where their slot's stamp differs (refresh skipped when no writer flag - the translated stores into
  tile RAM, per layer: `gen.py tile_marks` - and the same window and tag), a tile shadow per layer (its tile words as
  last drawn, compared word by word), per row the opaque runs as HOG OP 3 copy passes (HOP 2 / OP 3, end masks),
  consecutive full rows as plane passes, rows a later layer covers skipped. The locked water is filled per character
  row; a locked layer flagged as written (the translated writers flag a layer on any store) is compared with its copy
  (`ren_lkshd`) before layer 0 is drawn again.

### Colours

Galaga '88's runtime chooser per scene (15 + black, representative pens;
[colours.md](../../docs/colours.md#what-each-port-uses); not part of the 2026-11-05 default-fitter rollout). The
intro's lightning is a palette flash (the user, 2026-11-07): layer 0's bank flips 0 <-> 3 every ~35 frames; layer 0
stays drawn with the bank it had when the colours were chosen (`ren_l0bank`), and while the game shows another the
representative pens of the held bank show their colours in the bank shown (`ren_flash_pen`; the quality check looks
pens up in the held bank, `ren_unflash_pen`, and does not choose again during a flash). Sprites sharing those indices
flash too (the hero's blue goes grey in the bright flash). render_test's model draws layer 0 in the held bank
(`Harness.held`): exact; play 230-560: colour choices 14 -> 6, 1036M -> 711M cycles; colour error over the play states
0.032 -> 0.053.

### Sound

Not implemented: the sound CPU is not run, the MCU's voices are not played.

## Speed

| date | setup | arcade frames/s | % of 60.606 Hz | pictures/s | Musashi |
|---|---|---|---|---|---|
| 2026-11-08 | Hatari 14 MB, `bench.sh` BENCH, frames 600-1600 (intro, stage 1), 9 natives | 8.32 | 14% | 2.93 | logic 0.807 VBL a frame, render 14.7 VBLs a picture |
| 2026-11-07 | Hatari 14 MB, `bench.sh` BENCH, frames 600-1600 (intro, stage 1) | 7.97 | 13% | 3.02 | render 14 VBLs a picture |
| 2026-11-07 | Musashi, `render_test.py` | | | | play median 1.3M a picture, attract 3.4M |
| 2026-11-08 | Musashi, 9 natives, seed 5 / seed 22, 3000 frames | | | | logic 83.9k / 110.5k a frame for the two CPUs |
| 2026-11-07 | Musashi, 3 natives, seed 5 / seed 22 | | | | logic 89.3k / 117.5k a frame for the two CPUs (attract ~63k, translation only) |

What made it fast (2026-11-07, R-Type's lessons; BENCH 0.55 -> 7.97 arcade frames/s, 0.24 -> 3.02 pictures/s):

* A locked layer flagged as written compared with its copy (`ren_lkshd`) before layer 0 is drawn again: in Hatari this
  was nearly all of the render time.
* The locked water filled per character row, not per pixel: a layer-0 redraw 50M -> 23M cycles.
* A tile shadow per layer: the per-slot stamps' scan 425k -> 160k a picture.
* A row's damage gathered over its passes (one `ren_dmg` a row).
* The terrain renderer above against the simple renderer: play median 4.1M -> 1.3M cycles a picture (Musashi).
  A Hatari run of the terrain renderer (14 MB, coin, start, intro, stage 1, 210 s, not the BENCH game): 5.2 arcade
  frames/s, 1.25 pictures/s.
* The natives: 106.8k -> 89.3k (seed 5) and 143.1k -> 117.5k (seed 22) cycles a frame; six more (2026-11-08: the
  enemy-slot collision scans $F4B0 / $F6C7, $836C, $8277, $9222, the tile streaming $C025, and a `dbra` slot skip in
  $C37F) -> 83.9k / 110.5k (-6%).  Natives stop paying here: each further candidate is 1-3%, the hand-written code
  pays the same byte accesses (16 bit fields at odd offsets), calls, returns and bank writes as the translation.
  Return points (`gen.py` writes `live_main.json` / `live_sub.json`: the flags each instruction reads) and
  `profile.py --callers N` (the code that goes on into a runtime routine) help writing and choosing them.
* The intro's palette flash: play 230-560 1036M -> 711M cycles (Colours).

Measured, not kept: R-Type's schedule (`-D PIC_EVERY=8 -D MAX_BEHIND=12`): 7.97 -> 11.2 arcade frames/s, but 3.02 ->
1.40 pictures/s.

Open (in order): the logic (~0.81 VBL an arcade frame in Hatari: at 60 frames a second the logic alone needs more than
the STE's 160k cycles a VBL; `tools/profile.py`: gameplay ~140k a frame before the natives, most of what is left is the
translation's own costs: returns that miss their compared return points and go through the dispatcher, ~10-15%, bank
writes ~5-7%, LDD/STD indexed ~80 cycles, dynamic slots, D built from A and B); the colour choices (~40-60M);
the text layers' passes (~300 a picture: recordings per fine shift rarely reused, the window pans every frame); tile
conversion of new terrain rows.

Techniques other ports use that may apply:
[speed.md](../../docs/speed.md#techniques-that-look-applicable-elsewhere-2026-11-07).

## Tests and tools

* `tools/logic_test.py FRAMES --seed N` (after `tools/build.py --sim`): frame by frame against the reference (work
  RAM, TRIRAM, the CUS30 RAM, tile RAM, palette, scratch and sprite RAM, CUS123 control, the key custom, `sub_pass`,
  both CPUs' registers and pages; `--steplock F` instruction by instruction, with the slot pages, the cached registers
  and the ROM image's changed bytes at a difference; `--trace F` the last translated labels).
* `tools/mcu_test.py`: the native MCU model against the board's HD63701.
* `tools/states.py`, `tools/render_test.py [--every N] [--edges]` (the window as the STE shows it: base, fine scroll,
  line width; `FLAGS_ALL=1` sets every writer flag every picture); `tools/stemodel.py` (the picture in Python).
* `tools/profile.py` (from Splatterhouse's): Musashi cycles by routine.
* `tools/bench.sh [TAG]`: the BENCH build (scripted coin, start and play, arcade frames 600-1600) in
  `run/dspirit_TAG` with Hatari started there (not by `tools/hatari.sh`, which stops every running Hatari);
  `MEMSIZE=14` by default, `PHASES=1` render.s' `REN_PHASES` (VBLs per phase of render_frame), `EXTRA="-D ..."`.
* `ref/mame_cmp_dspirit.py [frames...]`: the reference renderer against MAME's picture.

## Lessons

### 2026-11-07: coverage under the port's schedule

The port runs ahead of MAME's schedule (no frames the game overran), so coverage taken on MAME's schedule misses scenes
the port reaches (the attract mode's later scenes, page $371). `ref/cover.py --port` covers the port's schedule.

### 2026-11-07: a translator fix for all 6809 ports

`engine/m6809x.py`: a post-increment operand whose slot is computed at run time (`LDD ,Y++`) took the slot of the
incremented register when the 16-bit access emitted the operand twice (Y = $7FFE read $8000's slot). Galaga '88 and
Splatterhouse: 600 frames still identical after the fix.

## Verification

Lock-step (logic), `mcu_test.py` and `render_test.py` above; Hatari runs of the intro and stage 1 (the BENCH game; a
210 s run of coin, start, intro and stage 1). No playtest, MARP replay or recorded play yet.

Full-game verification follows the [status policy](../../docs/port-status.md); nothing here claims a complete playthrough.
