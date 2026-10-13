# Sprite preparation after stefastbobs2

`AGENTS.md` asks every port to try this method for its sprites and to keep it only where measured CPU plus Blitter
bus cycles go down. This page describes what the method prepares, how a draw then runs, how to apply it to an arcade
port, and what each port found. The source is `/Users/saschaspringer/Work/stefastbobs2`: `sprite_compiler.js` (the
analysis and ordering) and `main5.s` (`draw_bobs3`, `draw_bob_0` .. `draw_bob_f`: the generated draw code).

## The idea

A Blitter pass with HOP 2 / OP 3 (destination = source) whose end masks are the sprite's opaque pixels draws a
cut-out: the masked bits are replaced, the rest of the screen stays. With an X count of one or two words END1 and END3
cover every word of the pass, so any opacity pattern up to 32 pixels fits in the end masks: no mask plane, no
read-modify-write of the destination, no clearing pass. What remains per pass is the cost of starting it. The
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

## What the ports found

| Port | Result |
|---|---|
| Donkey Kong, Galaga | `engine/sprite_reorder_audit.py` tried mask-group order on their shared original-order assets: no variant saved cycles after the extra address moves; they keep the generated mask-reuse path and the generic 64 KB fallback. |
| Commando, 1942, 1943, Gun.Smoke, Black Tiger, Bubble Bobble | Use reordered source data (see `docs/architecture.md`). |
| Splatterhouse | 2026-10-13: row-order drawing with mask reuse (a repeated row mask only restarts the Blitter; passes over the non-zero words only). A count over 400 play pictures (94,213 rows, 58,178 mask changes, 49,777 equal-mask groups) suggested little from grouping by row masks alone; the full method (runs, chains, generated code per shift, a first-use cache) is being prototyped and measured in Hatari, where sprites take 44% of a picture's time. |
