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

* **Background** (layers 3-5): composed per 8 x 8 cell into a clean buffer when their tiles (the writers' flags),
  layer 3's scroll (its cells before and after), a bank (that layer's cells), the priorities or the colours change.
  A cell line is the merge of its layers' converted character lines (ren_cimgs: 8 planar longs per character and
  bank, made on first use, `movep.l` into the planes).  Cover planes (1 bit a pixel) of layers 3 and 4 for the stars
  and sprites.
* **Stars** (layers 0-2): plotted per picture from lists of their non-empty cells (rebuilt when their tiles change),
  only the rows with pixels, under the layers above them; their words restored from the clean buffer later.
* **Sprites**: converted per (code, part, flips, colour) into a cache (planar rows with their masks), one HOG Blitter
  pass a line (4 planes, X count 3, the row's shifted mask as end masks; groups outside the picture get end mask 0;
  whole into 32 guard lines at the top and bottom).  Sprites of a priority below layer 3 or 4 (the '88 emblem under
  the HUD layer) lose the pixels those layers cover; a hidden sprite pixel still takes the pixel from the entries the
  arcade draws after it (the emblem's dissolve), so with such a sprite on the picture the entries are painted in the
  arcade's order with a taken plane.
* **Colours**: 15 + black per scene (as Splatterhouse: samples of the background, the stars and the sprites, weighted
  by the root of their counts, a median cut and 4 rounds of k-means in Oklab); a pen's index is the nearest centre of
  its colour when they were chosen; an index's STE colour is the current colour of a representative pen (fades and
  colour cycling cost nothing).  A new scene (a new backdrop, priorities) shows black until the palette rests.
* Restores: the cells composed since (copied from the clean buffer), the star words, the sprite rectangles (Blitter).

Test: `tools/states.py` (records 1500 play + 500 attract states once), `tools/render_test.py [--play A-B]
[--attract A-B] [--every N] [--png N] [--profile N]`: every pixel's index against the reference's pen by the
renderer's own mapping, the side bands clean, the colour error, cycles.  2026-10-13: play 1500 / 1500 and attract
500 / 500 pictures exact; colour error 0.023 (play) / 0.029 (attract).

Hatari (BENCH, arcade frames 600-1600, a version before the compose speed-ups): 6.4 arcade frames/s, 3.2 pictures/s;
the renderer takes ~89% of the time (colour choices and layer 3's changes recompose hundreds of cells), the logic
~0.8 VBL an arcade frame.

Open: speed (recomposes: colour choices ~15M cycles, layer 3 bank / scroll changes; a picture ~0.3-0.5M); the last
11 rows; the HUD palette; sound; the stefastbobs2 sprite method still to be prototyped and measured (AGENTS.md).
