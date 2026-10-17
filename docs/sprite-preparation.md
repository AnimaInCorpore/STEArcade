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

## Memory: prepared data from the hard disk (planned)

The prepared form (16 shifts, generated code, per-colour data) is several times larger than the ROM's sprite data,
and the 4 MB fill up (Splatterhouse uses ~3.6 MB before any of it). The plan is not to hold it all in RAM but to
load it from the hard disk while the game runs, with the program's own low-level driver (TOS is out of the picture
once the port owns the machine):

* **Drivers.** ACSI through the ST's DMA chip (the STE's own port, and SCSI adapters on it), and IDE (the Falcon's
  port and the IDE adapters for the ST / STE). One small routine per interface that reads sectors into a buffer,
  started and polled from the main loop, never waiting inside the border or VBL handlers. ACSI DMA moves data
  without the CPU; IDE's PIO costs CPU time per word, so its reads are kept small and spread over pictures.
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
| Donkey Kong, Galaga | The executed generated mask-reuse path is measured in `engine/sprite_blit_test.py`. `engine/sprite_reorder_audit.py` only estimates the cost of source seeks while retaining original-order assets; its predicted lack of a win is not a measured reordered-source prototype. They keep the generated path and generic 64 KB fallback; the full preparation experiment remains outstanding. |
| Commando, 1942, 1943, Gun.Smoke, Black Tiger, Bubble Bobble | Use reordered source data (see `docs/architecture.md`). |
| Splatterhouse | 2026-10-13: row-order drawing with mask reuse (a repeated row mask only restarts the Blitter; passes over the non-zero words only). Prototype of the method (`-D REN_GEN=1`, `REN_GSORT=1`; code in the README): code generated on first use per image x shift x flip into a 96 KB pool, one pass per row, Blitter state written only on change, the source address only where rows are not consecutive; exact, but slower: BENCH 612k -> 714k cycles a picture (Musashi), Hatari 13.96 -> 12.54 arcade frames/s. Sprite images and their colours change too often: ~6 new image x shift combinations a picture, a hit rate of 57% (75% with a 2 MB pool), ~22k to generate each against ~42k a picture saved. Opaque-run splitting was not built (rows are at most 32 pixels). Dropped; the prepared data from the hard disk (above) could change the balance, since generation would move to build time. |
| Galaga '88 | 2026-10-13: row-order drawing (a HOG pass a row: X count 3, the row's shifted mask as end masks). Prototype `-D REN_SB2=1` (`games/galaga88/src/render.s`, `ren_sb2_draw` / `ren_sb2_make`): per converted image (code, part, flips, colour) and shift a plan made on first use into a 96 KB pool: a piece per row with pixels (rows are at most 32 pixels: the row is the chain, its holes zero mask bits), the pieces sorted by their pre-shifted end masks, their 4 plane words in that order (the source address runs on), and generated code (an end mask written only when it changes, `addi.w #delta` to the destination's low word, Y count, start; shift 0 in 2-word passes); clipped sprites, the arcade-order pictures and 64 KB crossings take the row path. Exact (`render_test.py --edges`: 240 pictures of sprites across both edges, all fine positions, flips, sizes, the guards, 64 KB crossings; the BENCH game's 500 pictures). Measured on the BENCH game (arcade frames 600-1600, every 2nd, Musashi CPU + Blitter): 622M cycles both; CPU per picture 1170k both: the draws 62k -> ~29k (15k + ~14k generated code), the plans 33k a picture. Hatari BENCH: 9.74 -> 9.78 arcade frames/s (render VBLs 4322 -> 4279, ~1%), for 96 KB. Not kept on (`REN_SB2` stays an option): generating on first use eats the saving; with the plans made at build time (the shapes do not depend on the colour: code per (code, part, flips, shift), data per colour) the draws would save ~3% of a picture. |
| Kung-Fu Master | 2026-10-16 (`games/kungfum/src/render.s`): sprite cells (16 x 16, 3 bits) baked on first use per (code, colour, flip x) into a 600-slot cache: the opaque rows only, their plane words in blit order (the source address runs on), a HOG pass a row (X count 2 with NFSR, 1 at shift 0; the edge cells one word: left FXSR + source X increment 0, right the first word), END1 / END3 written only when the row mask changes. Measured on `render_test.py --seed 4` (6000 frames: attract, the floors, bosses; Musashi, CPU + Blitter): grouping equal row masks (`REN_ORDER=1`) against the natural row order (`REN_ORDER=0`): 142,050 against 141,536 CPU cycles a picture (draw_cell 39.3k against 39.9k, the bake 0.5k dearer), 31,263 Blitter bus cycles both; END1:END3 prepared for all 16 shifts per slot (`REN_SHIFTS=1`, made on first use per slot and shift, +1 KB a slot): 141,951. The fighters' rows rarely repeat a mask, so neither pays. Defaults corrected on 2026-10-17 to `REN_ORDER=0`, `REN_SHIFTS=0`; the measured slower options remain available for experiments. Generated code per shift remains untried; the row-loop profile (~25% of a picture, its mask part a third of that) does not substitute for that experiment. |
| Trojan | 2026-10-16 (`games/trojan/tools/assets.py` sprite_programs, `src/render.s` sprite_get / sprite_one): Black Tiger's preparation for 2048 sprites x flip x (16 x 16, always flipped in y): the rows sorted by their opaque mask at build time, the pixels baked in that order on first use per (code, flip, colour, palette epoch) into a 512-entry cache, one stream per image (shared between equal ones) and the masks for the 16 shifts, `tr_sprite_draw` writes END1 / END3 only when the mask changes, the source address runs on; clipped at the black side words (the inner word only). Measured against the same streams in the rows' own order (`TR_SPRITE_PLAIN=1`, rows drawn bottom-up, equal neighbours still sharing a group; `tools/profile.py 2000 2200 --seed 4`, level 1 in play, 27 sprites a picture, Musashi): `tr_sprite_draw` 35.7k -> 34.3k CPU cycles a picture (-4%), the Blitter the same 62.5k (the same passes), the program 10 KB smaller (more equal streams). Kept. |
| Double Dragon | 2026-10-16 (`games/ddragon/tools/assets.py` sprite_programs, `src/render.s` sprite_get / sprite_one): Trojan's preparation for 4096 sprites x flip x x flip y (16 x 16, 4 bits; the 16 x 32 / 32 x 16 / 32 x 32 objects as 2 or 4 parts): the rows sorted by their opaque mask at build time, baked in that order on first use per (code, flips, colour, palette epoch) into a 768-entry cache, one stream per image (shared between equal ones), masks for the 16 shifts, END1 / END3 written only when the mask changes; clipped at the black side words (the inner word only). Measured against the same streams in the rows' own order (`DD_SPRITE_PLAIN=1`; `tools/render_test.py 3400 --seed -1 --first 3000 --every 2 --profile`, mission 1 in play, 200 pictures, ~31 sprites a picture, Musashi CPU + Blitter): `dd_sprite_draw` 73.1k -> 71.3k cycles a picture (-2.4%), the program 32 KB smaller (more equal streams). Kept. |
| R-Type, Mr. HELI (shared M72 renderer) | The shared renderer has generated per-code/flip/shift line routines for whole pieces without priority pixels, with row-order source and mask reuse; clipped and priority pieces use the row loop. Its header records the 2026-10-13 sprite rebuild (CPU + Blitter per piece: R-Type play 10.6k -> 7.2k, Mr. HELI play 17.6k -> 9.7k, including other sprite-path changes). The row-group rejection there gives mask-change counts and estimated instruction overhead, not a reproducible executed reordered-source comparison. The full preparation comparison remains outstanding for both games. |
| Pac-Mania, Dragon Spirit, Track & Field, Hyper Sports, Gyruss | Board/reference work only; no STE sprite renderer or preparation measurement yet. Prototype and measure when adding the renderer. |
