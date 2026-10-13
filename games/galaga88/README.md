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

## The picture (measured on the reference, plan)

The arcade picture is 288 x 224, turned (ROT270) to 224 x 288 portrait; the game always flips the screen.  All six
layers are on in play: layers 0-2 the star fields (each scrolls on its own: one of them changes in 50-80% of the
frames; ~110-520 non-empty cells of 4096 a layer, ~1-2 opaque pixels a cell), layer 3 the planets and the space
station (mostly still), fixed layer 4 the HUD (priority 6, on top), fixed layer 5 the backdrop (a full opaque
nebula image, priority 1).  Priorities: L4 6 > L3 5 > L0 4 > L1 3 > L2 2 > L5 1.  ~250 distinct pens a picture.
Sprites: 16 x 16 mostly, 32 x 32, 8 x 8.

Plan for the STE (224 pixels at x 48-271: the picture's edges on 16-pixel groups; open top and bottom borders, ~277
of the 288 lines as the Galaga port): the backdrop and layer 3 composed into the buffers when they change; the star
fields as lists of pixels per tile code, plotted per picture under the layer 3 mask and restored; sprites rotated at
build time, drawn with the Blitter (clipped at the side edges, whole into guard rows at the top and bottom); colours
per scene as Splatterhouse (15 + a HUD palette).
