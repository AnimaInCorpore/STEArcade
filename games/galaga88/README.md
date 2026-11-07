# Galaga '88 (Namco, 1987) on the Atari STE

Atari STE port (4 MB) of the MAME set `galaga88` (Namco System 1, `namco/namcos1.cpp`, ROT270), built the way
Splatterhouse is ([its README](../splatter/README.md)). The main and sub MC6809E programs are translated to 68000 code
(`engine/m6809x.py`, `tools/gen.py`, `src/core.s`) and run in lock-step with the reference board `engine/namcos1.py`
(its renderer pixel-exact against MAME); the CUS64 MCU (HD63701) runs as Splatterhouse's native model of the same
program; the sound CPU is not run (its handshake is answered). The picture is the arcade's turned to 224 x 288
portrait (`src/render.s`); the last 11 rows (lives, stage flags) are not shown, the HUD has no palette of its own,
there is no sound. Status: Experimental / deferred (early implementation / reference work); not registered in
`port.py`, not released. Latest speed: Hatari BENCH (scripted game, arcade frames 600-1600, 4 MB) 12.14 arcade frames
a second (20% of the arcade's 60.606 Hz), 6.08 pictures a second, measured on 2026-10-17 with the bank maps as the
`REN_BANKDIFF` prototype (the default since 2026-11-02, not measured in Hatari again); logic 100.7k Musashi cycles a
frame (2026-11-02).

## Build and run

```sh
venv/bin/python games/galaga88/tools/prepare.py         # checks galaga88.zip (docs/rom_manifest.json), unpacks it
venv/bin/python games/galaga88/ref/cover.py SEED FRAMES # coverage -> build/galaga88/cover_SEED.pkl
venv/bin/python games/galaga88/tools/build.py           # run/galaga88/GALAGA88.PRG (--sim: the Musashi build; -D NAME=V)
venv/bin/python games/galaga88/tools/build.py -D BENCH=1   # the scripted BENCH game (Speed)
venv/bin/python games/galaga88/tools/logic_test.py FRAMES --seed N   # lock-step against the reference
venv/bin/python games/galaga88/tools/render_test.py     # every picture against the reference (Tests and tools)
```

ROM: the MAME set `galaga88` (`assets/roms/galaga88.zip`, unpacked to `assets/roms/extracted/galaga88/`). The port is
not registered in `port.py` (no `tools/hatari.sh`, no release): start `run/galaga88/GALAGA88.PRG` in the pinned Hatari
(STE, 4 MB) as `games/splatter/tools/bench.sh` does. Uncovered code writes CRASH.TXT. Paths are relative to this
folder; `engine/`, `tools/`, `port.py` and `docs/` at the top are the repository's.

## Controls

Arrows, space / Z fire, 1 start, 5 / 6 coin, Esc quits (writes COUNTERS.BIN); joystick 1.

## State

* Logic exact: seed 5 (coin, start, random left / right / fire) 1600 frames identical after the 2026-11-02 translator
  switches (1500 frames on 2026-10-13); main 7247, sub 3653 instructions translated, none unsupported (coverage:
  seeds 1, 4-7 6000 frames, seed 2 400).
* MCU: `tools/mcu_test.py` 1500 frames of play, 0 differences against the board's HD63701.
* Picture exact (2026-11-02): `render_test.py --every 3` play 500 / 500 and attract 167 / 167, `--edges` 252,
  the BENCH states 650 / 650 (`--every 2`); colour error 0.028 (play) / 0.032 (attract, Oklab).
* Missing: sound (the sound CPU and the MCU's voices are not run); the last 11 picture rows (lives, stage flags); a
  HUD palette.
* Speed: 20% of the arcade's rate in the BENCH game; the stars cost 37.5% of a picture, the logic ~0.8 VBL a frame.

## How it works

### The board and the reference

`tools/machine.py` is the reference board (`engine/namcos1.py`, MAME's scheduler) and the port's schedule
(`run_frame_port`): as Splatterhouse's, the vertical blank, the MCU and the sound CPU on the board's scheduler, then
the main CPU's IRQ and frame, then the sub CPU's. The port starts at frame 300 (both CPUs idle; `tools/snapshot.py`).
Measured on the reference: all six layers are on in play: layers 0-2 the star fields (each scrolls on its own; ~110-520
non-empty cells of 4096 a layer, ~1-2 opaque pixels a cell), layer 3 the planets and the space station, fixed layer 4
the HUD (priority 6), fixed layer 5 the backdrop (opaque, priority 1); ~250 distinct pens a picture.

### Translation

* **Coverage** (`ref/cover.py SEED FRAMES` -> `build/galaga88/cover_SEED.pkl`): seeds 1-3 the attract mode (a coin
  late), seeds 4+ coin, start and random left / right / fire. Besides what Splatterhouse's records it keeps the DP
  of every instruction site from frame 250 on (`dpsite`).
* **Direct page**: both programs run with DP = $40 (slot 2: the work RAM page $180, shared by the two CPUs) and keep
  their stacks in slot 2. The translator takes the program's DP and the slots its cached registers hold
  (`Program(dp=$40, a3_slot=2, a4_slot=3 | 1)`: a3 = VB[2] is the direct page and the stack's base, S = a5 - a3).
  The main IRQ calls a routine ($C12A in page $3B0) that runs with DP 0 (`TFR A,DP` ... `PULS DP`): DP is a constant
  per instruction (`dp_sites` from the coverage); the TFR / PULS into DP change nothing in the translation.
  The same routine moves S into slot 0 (the C116 page, S ~ $1800) and back: `dynamic_stack` keeps the stack's slot in
  the context (core.s SSLOT / SBASE; an assignment to S takes the slot of S - 1, a bank write to that slot moves a5).
  `engine/m6809x_test.py --dp 0x40 --dynamic-stack` tests the instruction set that way.
* **Idle loops and random numbers**: main `INC <$20 / E16C: INC <$2C; LDA <$20; BNE E16C`, sub `INC <$21 / E05A:
  INC <$2D; LDA <$21; ORA <$E6; BNE E05A` ($E6 holds the sub CPU). The loops count their passes in $2C / $2D and the
  game reads them as random numbers (main $7FB47E, sub $7F18BD), so the count is part of the state. The arcade
  counts every pass (what is left of the frame); the port's schedule counts one a frame: idle at the loop's head
  without counting while the loop would go on, the pass that leaves the loop counted (`machine.py idle`, core.s
  `main_idle` / `sub_idle`, the `idle_add` macro of galaga88.s).
* **Key custom**: CUS153 (type 2, the 32 / 16 divider; every read clears the numerator's high word), core.s
  `key_divide`: two `divu` steps (the quotient may need more than 16 bits).
* `tools/gen.py` sets `fast_forms` and `call_summaries` (m6809x, as Hyper Sports and Double Dragon; 2026-11-02).

### Schedule

`src/galaga88.s`: the snapshot of the reference at frame 300, then in turn an arcade frame (the vertical blank's work:
the sprite list latch; the MCU: Splatterhouse's native model of the same CUS64 program, `games/splatter/src/mcu.s`;
the sound CPU's handshake: the command byte $240 of the CUS30 RAM taken at once; then the main and the sub CPU) and a
picture every `PIC_EVERY` (2) arcade frames, or when the logic caught up.

### Picture

The arcade picture is 288 x 224, turned (ROT270) to 224 x 288 portrait; the game always flips the screen; the STE
shows it at x 48-271 (the picture's edges on 16-pixel groups). Top and bottom borders open (`engine/rt/borders.s`,
Galaga's timing): 277 lines, the picture's rows 0-276. `tools/assets.py` turns the graphics ROMs, `tools/stemodel.py`
is the renderer's geometry in Python (0 pixels against the reference's turned picture).

* **Background** (layers 3-5): composed per 8 x 8 cell into a clean buffer when their tiles (the writers' flags;
  the fixed layers' rows, `TILE_ROWS`), layer 3's scroll or bank (its non-empty cells before and after), layer 4's
  bank, the stacking order of the enabled layers or the colours change. Per cell the layers' characters
  (`ren_cell_chars`), a direct path for one layer of one character (its converted lines under its masks), else the
  merge of the layers' converted character lines (`ren_cimgs`: a 2-way cache of 8 planar longs per character and bank,
  `movep.l` into the planes). Cover planes (1 bit a pixel) of layers 3 and 4 for the stars and sprites, a flag per
  cell.
* **Bank maps** (`ren_bank_diff`, the default since 2026-11-02): layer 3's bank cycles 0-7 every 8 arcade frames (the
  BENCH game from frame 966), and the banks differ in a few of the pens its characters use (51 of ~220 non-empty
  cells use one). A layer 3 or 4 bank change compares the two banks' index maps (`ren_bmap`, this choice of colours)
  four pens at a time and marks only the cells whose character uses a differing group (`ren_cvals.bin`, assets.py:
  64 KB, the pens' groups per character; groups of 4 are as good as single pens here: 2856 vs 2844 cells over the
  BENCH changes); the other cells keep their converted lines.
* **Stars** (layers 0-2): each layer's visible window of tile RAM scanned per picture (37 x 28 words; their tiles
  change in the warps), the rows with pixels of its non-empty cells plotted under the layers above (a single pixel:
  4 bset / bclr; several: their spread indices merged with `movep.l`), colours from the bank's index map (the star
  banks cycle); their words restored from the clean buffer later.
* **Sprites**: converted per (code, part, flips, colour) into a cache (a row's pens unpacked in column order, 8 at a
  time through the colour's spread table), one HOG Blitter pass a line (4 planes, X count 3, the row's shifted mask
  as end masks; groups outside the picture get end mask 0; whole into 32 guard lines at the top and bottom).
  Sprites of a priority below layer 3 or 4 (the '88 emblem under the HUD layer) lose the pixels those layers cover;
  a hidden sprite pixel still takes the pixel from the entries the arcade draws after it (the emblem's dissolve), so
  with such a sprite on the picture the entries are painted in the arcade's order with a taken plane.
* **Restores**: the cells composed since (per 16-pixel group, or the whole picture by the Blitter after a full
  composition), the star words, the sprite rectangles (Blitter).

### Colours

15 + black per scene, chosen at run time as Splatterhouse's ([its Colours section](../splatter/README.md#colours):
pens to the nearest centre, representative pens, so fades and colour cycling cost nothing), with the stars sampled too
and 3 rounds of k-means; not part of the 2026-11-05 default-fitter rollout
([colours.md](../../docs/colours.md#what-each-port-uses)). Chosen again: a new scene (a new backdrop: layer 5's bank
or 64+ of its tiles; black until the palette rests 2 pictures), or every 16 pictures when the colours on the picture
(126 background cells, the sprites) fit clearly worse than right after the choice (the mean Oklab distance above 1.25
x + 3: the space station fading in after a choice).

### Sound

Not implemented: the sound CPU is not run, its command byte is taken at once.

## Speed

| date | setup | arcade frames/s | % of 60.606 Hz | pictures/s | Musashi |
|---|---|---|---|---|---|
| 2026-10-17 (bank maps as the prototype, now the default) | Hatari BENCH, frames 600-1600, 4 MB | 12.14 | 20% | 6.08 | |
| 2026-11-02 | Musashi, BENCH states 600-1600 | | | | 890k a picture (CPU + Blitter), the stars 334k (37.5%) |
| 2026-11-02 | Musashi, seed 5 | | | | logic 100.7k a frame for the two CPUs (54k in the attract mode on 2026-10-13) |

The logic takes ~0.8 VBL an arcade frame in Hatari (~810-840 VBLs of the BENCH run).

What made it faster, newest first:

* 2026-11-02: `fast_forms` and `call_summaries` in `tools/gen.py`: seed 5, 1600 frames identical, 104.2k -> 100.7k
  cycles a frame (-3.4%; `call_summaries` alone changes nothing here).
* 2026-11-02: the bank maps by default, with the NFSR fix (769c6fb), `render_test.py --bench --play 300-1600 --attract
  "" --every 2`: 693M -> 613M cycles (-11.5%), median 595k -> 569k a picture, 90% 2381k -> 1527k, big pictures 102 ->
  59. BENCH profile 600-1600: 1053k -> 890k a picture ([the 2026-11-02
  audit](../../docs/speed.md#history-the-audit-of-2026-11-02)). As the `REN_BANKDIFF` prototype: Musashi on the BENCH
  states 911M -> 827M cycles, the cycling pictures 1000-1200 649k -> 468k a picture (`ren_cell` 103k -> 23k); Hatari
  10.62 -> 12.14 arcade frames/s. Left: the scan of layer 3's 2048 words per change (`ren_bank_diff` ~14k a picture).
* 2026-10-13: Hatari BENCH 6.4 -> 10.6 arcade frames/s, 3.2 -> 5.3 pictures/s with the renderer above. A picture then
  cost 1.1M cycles on average on the BENCH states (Musashi, CPU): stars ~30% (the warps' streaks: ~1400 pixels a
  picture), the background's compositions (colour choices, layer 3's bank cycling through all 8 banks every ~7
  frames) ~25%, restores ~9%, sprites ~15%; a calm picture ~0.4M.

Where the time goes: measurement switches (2026-10-13, Hatari BENCH, arcade frames 600-1600, a picture every 2 frames):

| build | arcade frames/s | pictures/s | render VBLs | colour choices |
|---|---|---|---|---|
| baseline (as shipped 2026-10-13, before bank maps) | 10.62 | 5.32 | 3882 | 10 |
| `-D REN_NOSTARS=1` (no star layers) | 16.10 | 8.06 | 2262 | 8 |
| `-D REN_NOCYCLE=1` (layer 3 / 4 bank changes ignored, no re-choice for a worse fit) | 15.08 | 7.55 | 2499 | 3 |
| both | 25.06 | 12.57 | 1176 | 3 |
| bank maps (then `-D REN_BANKDIFF=1`; the default since 2026-11-02: the current build) | 12.14 | 6.08 | 3292 | 10 |

The logic stays ~810-840 VBLs in the baseline and the first three variants. Both off, a picture is ~291k cycles in
Musashi (BENCH states), sprites the largest part (draw 48k, conversion 40k, geometry 28k).

Measured, not kept:

* The stefastbobs2 method ([sprite-preparation.md](../../docs/sprite-preparation.md), `AGENTS.md`), prototyped as
  `-D REN_SB2=1` (plans per image and shift on first use: pieces ordered by their shifted masks, the reordered source,
  generated code): exact (`--edges`, the BENCH states); the BENCH game: equal Musashi cycles (622M), Hatari 9.74 ->
  9.78 arcade frames/s (~1%, within the noise) for 96 KB: not on by default. Preparing its plans at build time remains
  a separate experiment.
* Star runs by the Blitter (`-D REN_STARBLIT=1`; see [speed.md, Blitter costs](../../docs/speed.md#blitter-costs)).

Open: the stars in the warps, layer 3's bank / scroll changes, the colour choices, the logic.

Techniques other ports use that may apply:
[speed.md](../../docs/speed.md#techniques-that-look-applicable-elsewhere-2026-11-07).

## Tests and tools

* `tools/logic_test.py FRAMES --seed N` (after `tools/build.py --sim`): frame by frame against the reference (work RAM,
  TRIRAM, the CUS30 RAM, tile RAM, palette, sprite RAM, CUS123 control, the key custom, both CPUs' registers and
  pages; `--steplock F` instruction by instruction).
* `tools/mcu_test.py [frames] [--seed N] [--voice] [--commands]`: the native MCU model against the board's HD63701.
* `tools/states.py` records 1500 play + 500 attract states once (`--bench`: the BENCH game's states);
  `tools/render_test.py [--play A-B] [--attract A-B] [--every N] [--png N] [--profile N] [--profile-range A-B]
  [--bench] [--edges]`: every pixel's index against the reference's pen by the renderer's own mapping, the side bands
  clean, the colour error (Oklab), cycles by kind of picture, the reasons of the colour choices.
* `tools/stemodel.py`: the renderer's geometry in Python against the recorded states.
* `ref/mame_cmp_galaga88.py [frames...]`: the reference renderer against MAME's picture.
* Hatari BENCH: build with `tools/build.py -D BENCH=1` (`bench_inputs` in galaga88.s: coin at arcade frame 60, start at
  140, then right / left every 60 frames and fire every 20; the counters kept at frame 600, the program quits at 1600)
  and start `run/galaga88/GALAGA88.PRG` in the pinned Hatari (STE, 4 MB, `--cpu-exact`, fast-forward), as
  `games/splatter/tools/bench.sh` does; the port has no bench.sh of its own. COUNTERS.BIN holds eight longs at the end
  and the same eight at frame 600 (VBLs, arcade frames, pictures, frames dropped, pictures skipped, colour choices,
  VBLs in the logic, VBLs in render_frame): arcade frames/s = 50 x frames / VBLs of the difference.

## Verification

Lock-step (logic), `mcu_test.py` and `render_test.py` above; no playtest, MARP replay or recorded play yet.

Full-game verification follows the [status policy](../../docs/port-status.md); nothing here claims a complete playthrough.
