# Sprite preparation after stefastbobs2

`AGENTS.md` asks every port to try this method for its sprites and to keep it only where measured CPU plus Blitter
bus cycles go down. This page describes what the method prepares, how a draw then runs, how to apply it to an arcade
port, and what each port found. The source is `/Users/saschaspringer/Work/stefastbobs2`: `sprite_compiler.js` (the
analysis and ordering) and `main5.s` (`draw_bobs3`, `draw_bob_0` .. `draw_bob_f`: the generated draw code).

## The idea

A Blitter pass with HOP 2 / OP 3 (destination = source) whose end masks are the sprite's opaque pixels draws a
cut-out: the masked bits are replaced, the rest of the screen stays. With an X count of one or two words END1 and END3
cover every word of the pass, so any opacity pattern up to 32 pixels fits in the end masks: no separate mask-plane
AND/OR passes and no clearing pass. Partial end masks still require destination reads by the Blitter; include those
in the bus-cycle measurement. Besides those transfers, each pass pays the cost of starting it. The
preparation therefore cuts the sprite into pieces that fit this, puts them in an order where consecutive passes share
as much Blitter state as possible, and generates straight-line code that only changes what differs.

## The preparation (per sprite image)

1. **Opaque runs.** Each row is cut into runs of opaque pixels (`pixelChunks`: x, y, length). Transparent holes are
   never drawn: they are gaps between runs, not masked words.
2. **Chains.** Runs of one row that together span at most 32 pixels are chained (`chunkChains`): one pass draws
   them, the gaps between them become zero bits of the chain's mask. A chain is drawn whole or its runs alone,
   never both.
3. **Blocks.** Chains are assigned to blocks by width, with a common 16-pixel-aligned origin (`blockX`) per block so
   one horizontal shift serves the whole block:
   - wider than 32 pixels (`A`): full middle words, end masks only at the ends;
   - 17-32 pixels: two-word passes (X count 2);
   - up to 16 pixels: one-word passes (X count 1).
4. **Order.** Within a block the chains are sorted by their mask, so passes with the same end masks follow each
   other and the registers are written only when the mask changes. The order is free: rows of a sprite are
   independent once each pass has its own destination. (The opaque masks overwrite; with equal-priority sprites the
   order between sprites must stay, the order of a sprite's own pieces does not matter.)
5. **Reordered source.** The pixel data is stored in exactly that pass order, all four planes of a piece together.
   The Blitter's source address then advances by itself from one pass to the next: no source address is written
   during a sprite.
6. **Masks for every shift.** For each of the 16 horizontal shifts the end masks are shifted in advance, and the
   pass type is fixed (skew = the shift, NFSR / FXSR where the shifted piece needs them). Nothing is shifted at draw
   time.
7. **Generated code per shift.** One routine per shift (`draw_bob_0` .. `draw_bob_f`) with every value as an
   immediate or a preloaded register:

   ```
   move   #mask1,(a2)            ; END1, only when it changes              [12]
   move   #mask3,(a3)            ; END3, only when it changes              [12]
   move.l d2,$ffff8a36.w         ; X count, Y count: when the block changes
   move   #pass_type,(a6)        ; skew / NFSR / FXSR: when it changes      [8]
   add    #delta,(a4)            ; destination low word: to the next piece [12-16]
   move   d6,(a5)                ; Y count (the 4 planes)                  [8]
   move.b d7,(a6)                ; BUSY + HOG: start                       [8]
   ```

   A piece whose masks and type equal the previous one costs the last three instructions: about 28-32 CPU cycles
   plus its bus cycles. Frequent destination deltas (one line down, one line up) sit in registers (`d4`, `d5`).
   The routine is entered once per sprite after setting the destination's high word and the source address.

The fixed Blitter setup for all sprites (`draw_bobs3`): HOP 2, OP 3, source X / Y increment 2, destination X
increment 8 (the next 16-pixel group of interleaved planes), destination Y increment back to the next plane, Y count
4 (the planes), HOG on.

## Applying it to an arcade port

* **When to prepare.** Arcade sprites come from ROM: prepare at build time into `build/<game>/` (never committed:
  the repository is public) or on first use into a cache, per sprite code x flip x shift (or the 16 shifts lazily).
  Count the memory: a 16x16 sprite's code for 16 shifts is a few KB, a 32x32 one more; a cache with eviction keeps it
  bounded.
* **Colours.** The method writes all four planes of each piece: sprites whose colour changes at run time need the
  data per palette or a conversion per colour (Splatterhouse converts per colour into its cache).
* **Clipping.** Side edges on 16-pixel group boundaries: draw only the inner word of a piece that crosses the edge
  (`AGENTS.md`), or fall back to the row path for clipped sprites; top and bottom into guard rows. Generated code can
  take a piece range per row band if bars or palette splits cut a sprite.
* **Exactness.** Priority between sprites and against the background, transparent holes, all 16 shifts, flips and
  64 KB address crossings are checked against the port's reference renderer, as for any sprite path.
* **Short passes.** Every pass stays a short HOG pass (`engine/rt/borders.s`: at most ~256 bus cycles): pieces of one
  or two words over four planes are far below that.
* **Measure.** CPU plus Blitter bus cycles in the simulator on states that match real play, and the real rates in
  Hatari (a deterministic benchmark: inputs scripted by game frame, see Splatterhouse's `BENCH`). Keep logic speed
  and picture rate apart. Keep the method only if it wins; write down what was measured either way, below.

## Generated code per shape and pass-type pattern (`engine/sprite_programs.py`; Time Pilot, 2026-10-25)

The reference implementation for sprites whose rows are 16 pixels wide (one source word a plane), the form the
stages above take when carried through. It replaced Time Pilot's row loop (~150 CPU cycles a row) with ~42 cycles a
row. The user's points (2026-10-25), which every port should follow:

* **Rows reordered** so equal end masks follow each other: END1 / END3 are not reloaded inside a group. The order is
  per shape (`order_table`); the port bakes the plane words in that order, so the source address runs on.
* **The 16-pixel case as stefastbobs2 does it** (not as stedaimakaimura's `sprite_compiler.js`): per row and shift a
  row whose pixels stay in one destination word is a one-word pass (the left word, or the right word with the
  destination one group further); only a row that straddles the border is a two-word pass with NFSR. **The rows are
  stored aligned** (stefastbobs2's `draw_bob_1` runs rows with skew 9 at bob shift 1: their source moved within the
  word): every row's plane words are baked shifted left by its empty columns (`align_of`), and the row's skew is
  (shift + empty columns) & 15, its destination word the next one when that sum reaches 16. So no pass needs FXSR: a
  one-word pass reads the source once a plane (3 bus accesses a plane against 4 with FXSR's pre-read; a two-word NFSR
  pass 5). Only a straddling row cut at the left edge (clip 1) keeps FXSR. Until 2026-10-25 (afternoon) the right-word
  rows were FXSR passes over unaligned data. Source X increment 0 and Y increment 2 serve every type; the control word
  (skew, NFSR / FXSR; its write starts the pass) comes from the stream at each group, so the code still depends only
  on the pattern of pass types.
* **Masks from an address, not as immediates** (stedaimakaimura's generated code: `move (a0)+,(a1)`): the code per
  shape and *pattern of pass types* is shared by every shift with the same pattern; a stream per shape and shift holds
  the end masks and each group's control word. That is a compression of code: Time Pilot's 358 shapes x 16 shifts x 3 clip cases need 4,085
  routines and 217 KB of masks.
* **Shared by content** (`create_sprite_code.js` hashes): identical routines and identical stream blocks are stored
  once.

`programs(shapes, nshapes)` makes the routines, the stream and a table of records (per shape 48 variants: clip 0-2 x
16 shifts; each the code, the stream, the damage: the drawn lines and words). The module's docstring has the register
contract. What the port's draw routine must do (Time Pilot's `src/render.s` `draw_one`):

* keep the Blitter pointers and constants in registers from sprite to sprite (the code clobbers d0 and a0 only);
* decide every fallback **before** listing damage: sprites without generated code (shapes the coverage did not see),
  64 KB crossings (the code steps the destination's low word), anything the port clips otherwise (bands) go to the
  row path, which keeps working on the same baked slot (it is in the generated order);
* list as damage only the drawn lines and words (the record's damage), and restore with passes sized to the width
  (one group: 8 lines a pass, two: 4; at most 32 words, `BLIT_STATS=256`);
* keep slot headers (the shape's record, the plane words' address) so the per-sprite setup has no lookups;
* bake the aligned plane words for the generated code; Time Pilot, Gyruss and Kung-Fu Master keep a second, unaligned
  copy in the slot for their row paths (which take a sprite-wide skew), +64-128 KB of slots.

**The simulator**: with NFSR the last source read of a line is skipped and the read before it is the line's last:
Hatari adds the source Y increment after it. `engine/sim.py` follows Hatari since 2026-10-25 (it added X before;
equal increments, as every earlier port used, give the same result).

**What it gained, measured** (Time Pilot, seed 1's play, Musashi CPU + Blitter a picture, exact throughout): the row
loop 163.9k; the generated code with every value from the stream 155.1k; code per type pattern, masks-only streams
151.7k; the per-sprite setup in registers, clipped variants, damage of the drawn lines and words 103.6k (with the
tile-list and score-band changes). The code alone is a few percent of the picture; the per-sprite setup and the
restores around it matter as much. Profile the port first.

**Where it pays, measured 2026-10-25** (each port's own profiler on Musashi, play; the counts of rows whose pixels stay
in one word after the shift measured, savings marked *est.* estimated):

| Port | Sprite kernel today | Sprites in the picture | What would pay |
|---|---|---|---|
| Gyruss, Kung-Fu Master | done (rows above) | | |
| Commando, 1942 | 1942's `spritegen` code, 45-46 CPU cycles a row (as fast as this path); Commando 85% of rows unshifted already | 52% (Commando), 33% (1942) of a picture | not the kernel (one-word rows save ~0.8k bus a picture); the per-sprite setup (Commando's `draw_sprites` 29k, ~820 a sprite) and the damage restores (27.6k), as Time Pilot's `draw_one` and drawn-lines damage |
| 1943, Gun.Smoke | the same generated form, ~45-47 cycles a row | ~12% (1943), ~25% (Gun.Smoke) | the per-part setup (~660-870 cycles a part) *est.* 6-9k a picture for Gun.Smoke; 1943 has 31 KB free and its costs are `front_tile` and the characters |
| Black Tiger | a stream interpreter, ~107 cycles a row | ~35% of the picture's CPU | *est.* 15-20k CPU; only 82 KB free: needs memory first (or prepared data from the hard disk) |
| Trojan | a stream interpreter, ~60 cycles a row | ~30% (mostly bookkeeping: saves, `sprite_cells`) | the bookkeeping; the kernel *est.* 10-15k of ~580k |
| Double Dragon | a row loop, ~92 cycles a row with groups | ~26% | *est.* 26k of 576k, but the logic (191k a frame) limits it and 64 KB are free |
| Bubble Bobble | a row loop with runtime shifts, 151 a row with setup | ~24% | *est.* 17k (~10% of the median picture); shapes are composed at run time (code on bake), 40 KB free |

**Aligned rows instead of FXSR, measured 2026-10-25** (exact in every port's `sprite_test.py` and `render_test.py`;
Musashi CPU + Blitter a picture; Time Pilot and Gyruss against the commit before built with its screen buffers padded
to the same address modulo 64 KB, since the buffers' place decides which sprites cross 64 KB and take the row path):
Time Pilot (`render_test.py 1600 --start 1000`) 72.9k + 30.6k -> 73.3k + 30.1k (-0.05%); Gyruss (`render_test.py 3000
--start 1000`) 76.9k + 13.2k -> 77.1k + 12.6k (-0.45%); Kung-Fu Master (`render_test.py --seed 4`, stream mode: its
code wrote every control word before) 110.9k + 33.0k -> 110.9k + 32.1k (-0.6%). The Blitter saves 0.5-0.85k a
picture; in Time Pilot and Gyruss the control word from the stream at every group (12 cycles against an 8-cycle byte
start) takes most of it back. Writing it only where it changes saves that CPU but splits the code by the rows'
alignments (Gyruss: +320 KB of code, over the load budget). Program sizes: Time Pilot 2.18 -> 2.47 MB, Gyruss 3.03
-> 3.46 MB, Kung-Fu Master 3.09 -> 3.16 MB (load budget 3.7 MB).

Lesson from Gyruss and Kung-Fu Master: the kernel is part of the gain; the per-sprite setup and what the damage list
drives (span copies, front tiles drawn again, restores) are as large. Kung-Fu Master's blank cells widened every
damage rectangle: skipping them cut its front-tile and span copies by two thirds.

## Memory: prepared data from the hard disk (planned; the driver exists: `engine/rt/hdd.s`)

The prepared form (16 shifts, generated code, per-colour data) is several times larger than the ROM's sprite data,
and the 4 MB fill up (Splatterhouse uses ~3.6 MB before any of it). The plan is not to hold it all in RAM but to
load it from the hard disk while the game runs, with the program's own low-level driver (TOS is out of the picture
once the port owns the machine):

* **Drivers** (done, 2026-10-13: `engine/rt/hdd.s`, see `docs/architecture.md`, "Hard disk streaming"; the cache and
  the prefetch below are still to come).  ACSI through the ST's DMA chip (the STE's own port, and SCSI adapters on
  it), and IDE (the Falcon's port and the IDE adapters for the ST / STE). One small routine per interface that
  reads sectors into a buffer, started and polled from the main loop, never waiting inside the border or VBL
  handlers. ACSI DMA moves data without the CPU; IDE's PIO costs CPU time per word, so its reads are kept small and
  spread over pictures.
* **Data on disk.** The prepared sprites as a file in sector-aligned blocks, per sprite code (or per group of codes
  that are used together), with an index the program loads once: where each block is, how large it is. Built at build
  time into `build/<game>/` and copied next to the program (ROM-derived: never committed).
* **The cache in RAM.** A fixed pool with eviction (least recently drawn), like Splatterhouse's conversion cache.
  A sprite whose prepared data is not in RAM yet is drawn by the slower path that needs no preparation (the row or
  converted-image path) until its block arrives; so a slow disk costs speed for a few pictures, never correctness.
* **Prefetch.** Loads are requested ahead of use: when a stage or scene starts (the game's own stage number or tile
  bank switch), the blocks of the sprites seen there before (a per-stage list made from the coverage runs) are queued.
* **Measure** the disk's cost like everything else: the reads' CPU time in the deterministic Hatari benchmark (Hatari
  emulates ACSI and IDE hard disks), and pictures drawn by the fallback path while blocks were missing.

## What the ports found

These results describe the experiments actually implemented, including partial ones. Use them to identify work
still required by `AGENTS.md`; a cost estimate or an untried stage is not a completed preparation experiment.

| Port | Result |
|---|---|
| Donkey Kong, Galaga | The executed generated mask-reuse path is measured in `engine/sprite_blit_test.py`. `engine/sprite_reorder_audit.py` only estimates the cost of source seeks while retaining original-order assets; its predicted lack of a win is not a measured reordered-source prototype. They keep the generated path and generic 64 KB fallback; the full preparation experiment remains outstanding. **Galaga, 2026-10-25**: the full preparation measured with `engine/sprite_programs.py` (prototype, not kept): per (code, flip y) the rows grouped by mask and baked in that order per colour quad, each row aligned in its word (512 KB), flip x as the mirrored row map over the same data, a one- or two-word pass per row and shift, no clipped variants (edge_blits stays): 492 shapes, 3,678 routines (~700 KB of code), 171 KB of streams; the per-part setup from tables (the shape's record, its line 0 offset, the aligned data per (code, flip y)), the Blitter registers kept in data registers around the call. Exact (`sprite_test.py` 2664 edge cases; `perf_test.py compare` 1201 pictures identical) but not faster: `perf_test.py` (attract VBL 2400-3600, Musashi) draw_sprites 94.1k -> 95.6k CPU + Blitter a picture; in the first 300 pictures the generated code 14.3k CPU + 20.5k Blitter -> 15.7k + 18.3k, the per-part setup +3.0k. A first try with FXSR passes for the second-word rows over unaligned data saved only 1.1k of Blitter (98.2k in all; Hatari with a 14 MB STE, the program needing 4.8 MB: 31.1 -> 31.0 pictures a second). Why: Galaga's 16-line shapes have 12.2 opaque rows in 10.5 mask groups (few repeats, so few END writes saved, and the destination jumps between groups cost), and its old generated code already writes END1 / END3 only on change and uses one-word passes for first-word rows. The remaining cost is the per-part setup (draw_part ~42k CPU) and the restores. |
| Commando, 1942, 1943, Gun.Smoke, Black Tiger, Bubble Bobble | Use reordered source data (see `docs/architecture.md`). |
| Splatterhouse | 2026-10-13: row-order drawing with mask reuse (a repeated row mask only restarts the Blitter; passes over the non-zero words only). Prototype of the method (`-D REN_GEN=1`, `REN_GSORT=1`; code in the README): code generated on first use per image x shift x flip into a 96 KB pool, one pass per row, Blitter state written only on change, the source address only where rows are not consecutive; exact, but slower: BENCH 612k -> 714k cycles a picture (Musashi), Hatari 13.96 -> 12.54 arcade frames/s. Sprite images and their colours change too often: ~6 new image x shift combinations a picture, a hit rate of 57% (75% with a 2 MB pool), ~22k to generate each against ~42k a picture saved. Opaque-run splitting was not built (rows are at most 32 pixels). Dropped; the prepared data from the hard disk (above) could change the balance, since generation would move to build time. |
| Galaga '88 | 2026-10-13: row-order drawing (a HOG pass a row: X count 3, the row's shifted mask as end masks). Prototype `-D REN_SB2=1` (`games/galaga88/src/render.s`, `ren_sb2_draw` / `ren_sb2_make`): per converted image (code, part, flips, colour) and shift a plan made on first use into a 96 KB pool: a piece per row with pixels (rows are at most 32 pixels: the row is the chain, its holes zero mask bits), the pieces sorted by their pre-shifted end masks, their 4 plane words in that order (the source address runs on), and generated code (an end mask written only when it changes, `addi.w #delta` to the destination's low word, Y count, start; shift 0 in 2-word passes); clipped sprites, the arcade-order pictures and 64 KB crossings take the row path. Exact (`render_test.py --edges`: 240 pictures of sprites across both edges, all fine positions, flips, sizes, the guards, 64 KB crossings; the BENCH game's 500 pictures). Measured on the BENCH game (arcade frames 600-1600, every 2nd, Musashi CPU + Blitter): 622M cycles both; CPU per picture 1170k both: the draws 62k -> ~29k (15k + ~14k generated code), the plans 33k a picture. Hatari BENCH: 9.74 -> 9.78 arcade frames/s (render VBLs 4322 -> 4279, ~1%), for 96 KB. Not kept on (`REN_SB2` stays an option): generating on first use eats the saving; with the plans made at build time (the shapes do not depend on the colour: code per (code, part, flips, shift), data per colour) the draws would save ~3% of a picture. |
| Kung-Fu Master | 2026-10-16 (`games/kungfum/src/render.s`): sprite cells (16 x 16, 3 bits) baked on first use per (code, colour, flip x) into a 600-slot cache: the opaque rows only, their plane words in blit order (the source address runs on), a HOG pass a row (X count 2 with NFSR, 1 at shift 0; the edge cells one word: left FXSR + source X increment 0, right the first word), END1 / END3 written only when the row mask changes. Measured on `render_test.py --seed 4` (6000 frames: attract, the floors, bosses; Musashi, CPU + Blitter): grouping equal row masks (`REN_ORDER=1`) against the natural row order (`REN_ORDER=0`): 142,050 against 141,536 CPU cycles a picture (draw_cell 39.3k against 39.9k, the bake 0.5k dearer), 31,263 Blitter bus cycles both; END1:END3 prepared for all 16 shifts per slot (`REN_SHIFTS=1`, made on first use per slot and shift, +1 KB a slot): 141,951. The fighters' rows rarely repeat a mask, so neither pays. Defaults corrected on 2026-10-17 to `REN_ORDER=0`, `REN_SHIFTS=0`; the measured slower options remain available for experiments. Generated code per shift remains untried; the row-loop profile (~25% of a picture, its mask part a third of that) does not substitute for that experiment. **2026-10-25**: `engine/sprite_programs.py` in stream mode (one routine per cell shape, per shift a stream of every value that changes: 978 KB for the 598 cells of 99% of the draws; the whole-code variant would have needed ~3.4 MB) with whole destination addresses (the 129 KB rings cross 64 KB boundaries), flip y as a row map, blank cells skipped before their damage: seed 4 131.3k CPU + 25.1k Blitter -> 89.0k + 20.0k a picture (exact); Hatari recorded play 27.4 -> 33.2 pictures a second (93% speed both). |
| Trojan | 2026-10-16 (`games/trojan/tools/assets.py` sprite_programs, `src/render.s` sprite_get / sprite_one): Black Tiger's preparation for 2048 sprites x flip x (16 x 16, always flipped in y): the rows sorted by their opaque mask at build time, the pixels baked in that order on first use per (code, flip, colour, palette epoch) into a 512-entry cache, one stream per image (shared between equal ones) and the masks for the 16 shifts, `tr_sprite_draw` writes END1 / END3 only when the mask changes, the source address runs on; clipped at the black side words (the inner word only). Measured against the same streams in the rows' own order (`TR_SPRITE_PLAIN=1`, rows drawn bottom-up, equal neighbours still sharing a group; `tools/profile.py 2000 2200 --seed 4`, level 1 in play, 27 sprites a picture, Musashi): `tr_sprite_draw` 35.7k -> 34.3k CPU cycles a picture (-4%), the Blitter the same 62.5k (the same passes), the program 10 KB smaller (more equal streams). Kept. |
| Double Dragon | 2026-10-16 (`games/ddragon/tools/assets.py` sprite_programs, `src/render.s` sprite_get / sprite_one): Trojan's preparation for 4096 sprites x flip x x flip y (16 x 16, 4 bits; the 16 x 32 / 32 x 16 / 32 x 32 objects as 2 or 4 parts): the rows sorted by their opaque mask at build time, baked in that order on first use per (code, flips, colour, palette epoch) into a 768-entry cache, one stream per image (shared between equal ones), masks for the 16 shifts, END1 / END3 written only when the mask changes; clipped at the black side words (the inner word only). Measured against the same streams in the rows' own order (`DD_SPRITE_PLAIN=1`; `tools/render_test.py 3400 --seed -1 --first 3000 --every 2 --profile`, mission 1 in play, 200 pictures, ~31 sprites a picture, Musashi CPU + Blitter): `dd_sprite_draw` 73.1k -> 71.3k cycles a picture (-2.4%), the program 32 KB smaller (more equal streams). Kept. |
| Gauntlet | 2026-10-17 (`games/gauntlet/src/render.s`): motion objects baked on first use per (code, size, flip, palette, colour mapping) into a 400 KB pool as 32-pixel strips, a HOG pass a row (Y count 4, the opaque mask in END1-END3, written only when it changes, the source address running on); shadow rows (pen 1) a pass from the shadow playfield. Prototype `-D MO_ORDER=1`: the rows sorted by their mask at bake time, the plane words in that order, a ring offset per row. Measured on `tools/render_test.py` level 5 with 3 players (350 pictures, Musashi CPU + Blitter): the row drawing 31.0k -> 31.8k a picture, the sort 6.6k at the bake, the picture 263.0k -> 270.3k. Gauntlet's rows are the objects' outlines (pen 1 in 15 of 23 rows on average) and rarely repeat a mask: natural order stays the default, the option remains. Prepared masks for the 16 shifts and generated code per shift were not tried. |
| R-Type, Mr. HELI (shared M72 renderer) | The shared renderer has generated per-code/flip/shift line routines for whole pieces without priority pixels, with row-order source and mask reuse; clipped and priority pieces use the row loop. Its header records the 2026-10-13 sprite rebuild (CPU + Blitter per piece: R-Type play 10.6k -> 7.2k, Mr. HELI play 17.6k -> 9.7k, including other sprite-path changes). The row-group rejection there gives mask-change counts and estimated instruction overhead, not a reproducible executed reordered-source comparison. The full preparation comparison remains outstanding for both games. |
| Gyruss | 2026-10-17 (`games/gyruss/src/render.s`): the 8 x 16 sprites turned to 16 x 8 (ROT90), baked on first use per (bank, code, flips, colour) into a 1024-slot cache: the opaque rows only, their plane words in blit order (the source address runs on), a HOG pass a row (X count 2 with NFSR, 1 at shift 0; the edge cells one word), END1 / END3 written only when the row mask changes, the pass type's registers only when it differs from the last sprite's. Grouping equal row masks (`-D REN_ORDER=1`) against the natural order, `tools/render_test.py 3000 --start 1000` (seed 1: attract and play, 2000 pictures, exact both; Musashi): 120,757 against 120,660 CPU cycles a picture, 27,150 Blitter bus cycles both. Most draws are stars and shots of one to six pixels in one or two rows, so masks rarely repeat: natural order stays the default, the option remains. Prepared masks for the 16 shifts and generated code per shift were not tried. **2026-10-25**: `engine/sprite_programs.py` (Time Pilot's generated path) for the coverage's 1,381 shapes, the entries an unrolled loop with the Blitter registers held, damage of the drawn lines and words, tile cell lists: seed 1's play 116.1k CPU + 28.4k Blitter -> 75.4k + 12.7k a picture (exact; the Blitter halved by one-word passes: most draws are stars and shots); Hatari 54% -> 55%, 11.6 -> 12.1 pictures a second (the logic limits Gyruss). |
| Time Pilot | 2026-10-25 (`games/timeplt/tools/assets.py` sprite_programs, `src/render.s` draw_one): the full preparation for the 16 x 16 sprites turned (ROT90). Per shape (code x flips; the 358 the coverage saw) the opaque rows grouped by mask (`tp_order`), baked on first use per colour into a slot in that order (the source address runs on); per shift a pass type per row as stefastbobs2 does it: a 16-pixel row whose pixels stay in one destination word after the shift is a one-word pass (the left word plain, the right word with FXSR; source X increment 0, Y increment 2 serve all types), two words with NFSR otherwise; at the side edges one word only. Code per shape and pattern of types (Y increment, X count and skew byte written only where the type changes, the destination's low word stepped by immediates; the skew in registers), end masks from a stream at an address (stedaimakaimura's form); code and streams shared by content (hash): 4,085 routines, 217 KB of masks. Measured on `tools/render_test.py 1600 --start 1000` (seed 1's play, 600 pictures, Musashi, CPU + Blitter, exact throughout): the row loop (natural order) 125.0k + 38.9k; rows grouped by mask in that loop −0.5k net (the bake +0.6k); generated code with every value from the stream 117.8k + 37.3k; code per type pattern with masks-only streams 114.4k + 37.3k; then with the per-sprite setup rewritten, the clipped variants and damage of the drawn lines and words only 73.2k + 30.4k (with the tile and score-band changes, README). Kept. The simulator's Blitter model added the X increment after a read before an NFSR-skipped one; Hatari (blitter.c) adds the Y increment there: `engine/sim.py` now follows Hatari (equal results whenever both increments are equal, as in every earlier port). |
| Black Tiger, Gun.Smoke: text | 2026-10-24: the text layers (masked over the scrolling picture) drawn like bobs instead of an AND pass and an OR pass a plane: a run's (row's) lines cut into pieces of one or two words with opaque pixels when the text changes, the planes stored in pass order, a copy pass a piece with the shifted mask words as end masks and the skew in the pass (`text_run_pieces`, `fg_pieces_build`). Black Tiger (MARP inputs, Musashi): the text 83.7k -> 57.3k cycles a scrolling picture, every picture 195.4k -> 185.7k; Hatari 24.6 -> 25.5 pictures a second. Gun.Smoke (`render_test.py 200 seq`): median 135.8k -> 110.5k a picture. Kept. Trojan and Double Dragon already draw their text this way (a pass per char row). 1942, 1943 and Commando draw word-aligned text with the CPU (one read-modify-write of the background a line, 1942 restoring from the clean screen in the same loop). Commando measured 2026-10-24 (prototype: a text row's pieces made when one of its cells changes, two-word pieces where neighbouring chunks have pixels, aligned passes without skew; `PLAY=1 perf_test.py 3000 1000 profile`): `draw_foreground` 25.0k -> 26.4k cycles a picture (19.3k CPU + ~7k Blitter), the mean picture 155.1k -> 160.7k, pictures over 300k 7 -> 21 (rows made again when the text changes). Dropped: without a shift the CPU's `movep` / `movem` line (76 / 108 cycles for 8 / 16 pixels) costs no more than a pass. 1942 and 1943 (also unshifted) are expected to behave the same; not prototyped. |
| Pac-Mania, Dragon Spirit, Track & Field, Hyper Sports | Board/reference work only; no STE sprite renderer or preparation measurement yet. Prototype and measure when adding the renderer. |
