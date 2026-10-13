# Galaga '88

Atari STE port (4 MB) of the MAME set `galaga88` (Namco System 1, ROT270): the main and sub MC6809E programs
translated to 68000 code (`engine/m6809x.py`, `tools/gen.py`, `src/core.s`) on the reference board
`engine/namcos1.py` (its renderer pixel-exact against MAME), as Splatterhouse (`games/splatter`).  Work in progress:
the translated logic runs in lock-step with the reference; the STE program (renderer, MCU, sound, display) is not
written yet.

## Logic

* **Coverage** (`ref/cover.py SEED FRAMES` -> `build/galaga88/cover_SEED.pkl`): seeds 1-3 the attract mode (a coin
  late), seeds 4+ coin, start and random left / right / fire.  Besides what Splatterhouse's records it keeps the DP
  of every instruction site from frame 250 on (`dpsite`).
* **Schedule** (`tools/machine.py`): as Splatterhouse's (the vertical blank, the MCU and the sound CPU on the board's
  scheduler, then the main CPU's IRQ and frame, then the sub CPU's).  The port starts at frame 300 (both CPUs idle).
* **Direct page**: both programs run with DP = $40 (slot 2: the work RAM page $180, shared by the two CPUs) and keep
  their stacks in slot 2.  The translator takes the program's DP and the slots its cached registers hold
  (`Program(dp=$40, a3_slot=2, a4_slot=3 | 1)`: a3 = VB[2] is the direct page and the stack's base, S = a5 - a3).
  The main IRQ calls a routine ($C12A in page $3B0) that runs with DP 0 (`TFR A,DP` ... `PULS DP`): DP is a constant
  per instruction (`dp_sites` from the coverage); the TFR / PULS into DP change nothing in the translation.
  The same routine moves S into slot 0 (the C116 page, S ~ $1800) and back: `dynamic_stack` keeps the stack's slot in
  the context (core.s SSLOT / SBASE; an assignment to S takes the slot of S - 1, a bank write to that slot moves a5).
  `engine/m6809x_test.py --dp 0x40 --dynamic-stack` tests the instruction set that way.
* **Idle loops and random numbers**: main `INC <$20 / E16C: INC <$2C; LDA <$20; BNE E16C`, sub `INC <$21 / E05A:
  INC <$2D; LDA <$21; ORA <$E6; BNE E05A` ($E6 holds the sub CPU).  The loops count their passes in $2C / $2D and the
  game reads them as random numbers (main $7FB47E, sub $7F18BD), so the count is part of the state.  The arcade
  counts every pass (what is left of the frame); the port's schedule counts one a frame: idle at the loop's head
  without counting while the loop would go on, the pass that leaves the loop counted (`machine.py idle`, core.s
  `main_idle` / `sub_idle`, the `idle_add` macro of galaga88.s).
* **Key custom**: CUS153 (type 2, the 32 / 16 divider; every read clears the numerator's high word), core.s
  `key_divide`: two `divu` steps (the quotient may need more than 16 bits).

Results (2026-10-13): 1500 frames of play (seed 5: coin, start, random left / right / fire) identical, 98k 68000
cycles a frame for the two CPUs (54k in the attract mode); main 7247, sub 3653 instructions translated, none
unsupported (coverage: seeds 1, 4-7 6000 frames, seed 2 400).

Test: `tools/build.py --sim`, then `tools/logic_test.py FRAMES --seed N` (frame by frame against the reference: work
RAM, TRIRAM, the CUS30 RAM, tile RAM, palette, sprite RAM, CUS123 control, the key custom, both CPUs' registers and
pages; `--steplock F` instruction by instruction).

## The STE program (src/galaga88.s)

The snapshot of the reference at frame 300 (tools/snapshot.py), then in turn an arcade frame (the vertical blank's
work: the sprite list latch; the MCU: Splatterhouse's native model of the same CUS64 program, games/splatter/src/
mcu.s - tools/mcu_test.py: 1500 frames of play, 0 differences against the board; the sound CPU's handshake: the
command byte $240 of the CUS30 RAM taken at once; then the main and the sub CPU) and a picture every PIC_EVERY (2)
arcade frames.  Top and bottom borders open (engine/rt/borders.s, Galaga's timing): 277 lines, the picture's rows
0-276 (the last 11 rows, the lives and stage flags, are not shown yet).  Keys: arrows, space / Z fire, 1 start, 5 /
6 coin, Esc quits (COUNTERS.BIN); joystick 1.  Uncovered code: CRASH.TXT.  `tools/build.py` (and `-D BENCH=1`: the
scripted game of bench_inputs, counters at arcade frame 600 and the end at 1600).

## Renderer (src/render.s)

The arcade picture is 288 x 224, turned (ROT270) to 224 x 288 portrait; the game always flips the screen; the STE
shows it at x 48-271 (the picture's edges on 16-pixel groups).  tools/assets.py turns the graphics ROMs,
tools/stemodel.py is the renderer's geometry in Python (0 pixels against the reference's turned picture).
Measured on the reference: all six layers are on in play: layers 0-2 the star fields (each scrolls on its own; ~110-520
non-empty cells of 4096 a layer, ~1-2 opaque pixels a cell), layer 3 the planets and the space station, fixed layer 4
the HUD (priority 6), fixed layer 5 the backdrop (opaque, priority 1); ~250 distinct pens a picture.

* **Background** (layers 3-5): composed per 8 x 8 cell into a clean buffer when their tiles (the writers' flags;
  the fixed layers' rows, TILE_ROWS), layer 3's scroll or bank (its non-empty cells before and after), layer 4's bank,
  the stacking order of the enabled layers or the colours change.  Per cell the layers' characters (ren_cell_chars),
  a direct path for one layer of one character (its converted lines under its masks), else the merge of the layers'
  converted character lines (ren_cimgs: a 2-way cache of 8 planar longs per character and bank, `movep.l` into the
  planes).  Cover planes (1 bit a pixel) of layers 3 and 4 for the stars and sprites, a flag per cell.
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
* **Colours**: 15 + black per scene (as Splatterhouse: samples of the background, the stars and the sprites, weighted
  by the root of their counts, a median cut and 3 rounds of k-means in Oklab); a pen's index is the nearest centre of
  its colour when they were chosen; an index's STE colour is the current colour of a representative pen (fades and
  colour cycling cost nothing).  Chosen again: a new scene (a new backdrop: layer 5's bank or 64+ of its tiles;
  black until the palette rests 2 pictures), or every 16 pictures when the colours on the picture (126 background
  cells, the sprites) fit clearly worse than right after the choice (the mean Oklab distance above 1.25 x + 3: the
  space station fading in after a choice).
* Restores: the cells composed since (per 16-pixel group, or the whole picture by the Blitter after a full
  composition), the star words, the sprite rectangles (Blitter).

Test: `tools/states.py` (records 1500 play + 500 attract states once), `tools/render_test.py [--play A-B]
[--attract A-B] [--every N] [--png N] [--profile N] [--profile-range A-B] [--bench] [--edges]`: every pixel's index against the
reference's pen by the renderer's own mapping, the side bands clean, the colour error (Oklab), cycles by kind of
picture, the reasons of the colour choices.  2026-10-13: play 1500 / 1500 and attract 500 / 500 exact (an earlier
version); the final one every 3rd state: play 500 / 500, attract 167 / 167 exact; colour error 0.028 (play) /
0.032 (attract).

Hatari (BENCH: arcade frames 600-1600 of the scripted game): 6.4 -> 9.0 arcade frames/s, 3.2 -> 4.5 pictures/s
(a picture every 2 arcade frames); the logic ~0.8 VBL an arcade frame, the renderer the rest.  Costs (Musashi,
play 300-700, every 2nd state): a picture ~1.3M cycles (median; the warps' star streaks ~0.6-0.9M of it), a colour
choice ~12M (the full composition ~3.3M of it).

The stefastbobs2 method (`docs/sprite-preparation.md`, `AGENTS.md`): prototyped as `-D REN_SB2=1` (plans per image
and shift on first use: pieces ordered by their shifted masks, the reordered source, generated code); exact
(`--edges`, the BENCH states); the BENCH game: equal Musashi cycles (622M), Hatari 9.74 -> 9.78 arcade frames/s
(~1%, within the noise) for 96 KB: not on by default.  Details and numbers in the doc's table.

Open: speed (stars in the warps, layer 3's bank / scroll changes, colour choices, the logic's ~130k cycles a
frame); the last 11 rows; the HUD palette; sound; the stefastbobs2 sprite method still to be prototyped and measured
(AGENTS.md).
