# Blitter renderer performance investigation

Compared the current working tree with `C:\Arbeit\stefastbobs2\main.s` on 2026-10-08. Existing runtime and generator edits were left unchanged.

## Conclusion

The generated sprite drawing routines already implement the central fast-bob technique. The first improvement should be reducing sprite restoration and dirty tracking from three chunks to two. Next, cache unchanged sprite descriptors and reduce unnecessary dependency propagation. Register constants, as used by `main.s`, offer a smaller, straightforward improvement inside the drawing routines.

## What already matches the reference

`ste/tools/sprites.py` generates a routine for each of 16 shifts, stores source words in drawing order, groups runs by width and horizontal start, and only updates masks/counts/skew when they change. Repeated runs use a relative destination adjustment, Y-count write, and byte start command. `ste/rt/sprites.s` uses 64 KiB aligned buffers and an RTS chain; the Blitter advances the source pointer itself. Multiple opaque spans in a row are handled as separate runs, preserving holes.

These are already the important ideas from the reference's `draw_bobs` and `.draw_bob_0` routines. Replacing the current drawing method wholesale would duplicate work already done.

## Ranked improvements

### 1. Restore and track two chunks instead of three

Location: `ste/rt/sprites.s`, `mark_rect`, `test_rect`, and the restoration setup around line 328.

All sprites are 16 pixels wide. At any shift 0..15 their pixels occupy at most two 16-pixel chunks. The current restoration copies three chunks, and dependency tracking also marks/tests the third chunk.

Concrete change:

- Restore X count 8 instead of 12 (four plane words per chunk).
- Change both restoration Y increments from 234 to 242: `256 - 16 + 2`.
- Remove the third-column accesses in `mark_rect` and `test_rect`, and update their comments.

Background copies have full endmasks, HOP 2, OP 3. Their transfer cost decreases from `12 * 16 * 8 = 1536` to `8 * 16 * 8 = 1024` cycles per restored sprite rectangle, excluding setup/arbitration. This saves 512 cycles per restored rectangle, or 64 microseconds at 8 MHz. Twenty restorations would save 10,240 transfer cycles (1.28 ms). This is a conditional example, not a measured typical frame.

The smaller footprint can also prevent unrelated sprites in the third chunk from entering the redraw closure. That additional saving depends on the scene.

Validation performed: enumerated the 324 nonempty shapes selected by the current generator, their 5,952 opaque runs, and all 16 shifts. Every run's first destination chunk plus its X count is at most two. A second enumeration of all 368 nonempty code/flip combinations also fits this bound.

Later, per-shape/per-shift bounding rectangles could reduce coverage to one chunk or fewer rows where possible. Old and new bounds must both be retained per draw buffer.

### 2. Cache decoded descriptors for unchanged sprite slots

Location: `ste/rt/sprites.s`, `.slot` (line 157 onward).

The global quick exit helps completely unchanged frames. When any slot changes, however, pass A decodes every visible slot before comparing its raw entry with the previous entry. That decoding includes position/flip calculations, shape and colour tables, a multiply, source lookup, and shift-routine lookup.

Compare the raw entry first. Reuse the cached rectangle, routine pointer, and source pointer when it is unchanged and the palette bank is unchanged. Redraw eligibility remains separate: an unchanged descriptor may still need drawing because a tile or overlapping sprite changed.

The current shared `spr_new_*` arrays are not sufficient as per-buffer caches: they describe the last processed frame, which may belong to the other screen. Maintain descriptor caches for both draw screens, alongside `spr_prev`, or cache against a shared last-decoded entry while still tracking each buffer's previous drawn state separately. Invalidate source colour lookup on bank changes.

Keep the existing sprite order and the overlap closure. Skipping unchanged sprites unconditionally would erase them when background restoration or tile drawing touches their pixels.

### 3. Reduce repeated background copies and coarse dependency expansion

Location: `.closure` and `.restore` in `ste/rt/sprites.s`.

The current 16-line cell grid rounds sprite coverage vertically to one or two cell rows. This creates false overlaps. In addition, each redrawn slot restores its old rectangle independently, so overlapping old rectangles may copy the same background words repeatedly.

After the two-chunk fix, measure duplicate restored words and redraws induced only by cell rounding. Consider exact rectangle intersections or finer vertical cells, plus union/merging of old restoration spans. Merely enlarging every copy to whole dirty cells can lose the expected gain. Compare the CPU cost of building the union with the transfer cycles it eliminates.

Preserve the order: update background tiles, restore all required old regions, then draw affected sprites in their original order. Do not interleave restoration with drawing individual sprites.

### 4. Preload count/increment constants as in main.s

Location: `ste/tools/sprites.py`, `emit_count` (lines 123..126); drawing-chain register setup in `ste/rt/sprites.s` (around line 404).

The reference preloads destination Y increments and packed X/Y counts in registers. The current generator emits immediate values whenever X count changes. Current 16-pixel runs only require X count 1 or 2, so the available d0..d3 registers can hold:

| Register | Proposed value |
|---|---|
| d0 | 2 (destination Y increment for X count 1) |
| d1 | -6 (destination Y increment for X count 2) |
| d2 | `(1 << 16) + 4` |
| d3 | `(2 << 16) + 4` |

Keep d4/d5 for line offsets, d6's low word equal to 4, and d7 for the byte start command. Substitute register writes for both immediate writes in `emit_count`.

Nominal 68000 instruction costs drop by 4 cycles for the word increment write and 8 cycles for the long count write: 12 cycles per count change, before amortizing the once-per-chain register loads. The enumeration found 13,792 count changes across 95,232 generated run/shift operations, averaging about 511 cycles saved across all 16 shift routines of a shape, or about 32 cycles per shape/shift. This is an unweighted code average, not a gameplay measurement. The preload cost can outweigh this saving in short chains, so benchmark or load constants lazily for chains that benefit.

Other small generator opportunities: use `subq #8,(a4)` for delta -8 and omit zero adjustments where the a4 pointer mode permits it. There were 1,457 delta -8 operations and 1,093 zero-delta operations in that enumeration. Keep the pointer transition when a4 still points to X count.

### 5. Avoid unconditional cell clearing on clean frames

Location: `ste/rt/render.s:43` and `ste/rt/sprites.s:19`.

`clear_cells` runs before the unchanged-frame sprite quick exit. Its 128-longword loop costs roughly 2.8k nominal CPU cycles every frame. Defer clearing until dirty tiles will be marked or the full sprite path will run, clearing exactly once before either operation. Do not move it after dirty tile marking, which would discard the marks.

### 6. Batch long groups of identical adjacent runs selectively

For a vertical sequence with identical masks, skew and width, consider plane-major source data and four Blitter calls, each with Y count equal to the number of rows, instead of one call per run with Y count 4. This can reduce starts and CPU register writes for sufficiently long sequences. It needs a different source layout and plane/row increments; do not simply increase Y count in the existing interleaved-plane routine.

An enumeration of all code/flip variants found identical-run groups as long as 16, but many groups are only one or two runs. Only consecutive rows can be batched directly, and profitability must include four-plane setup. Use a cost model to select between methods per group/shift rather than applying batching globally.

## Timing limitations and verification

`ste/tools/sim.py` reads destination words to implement masks but adds cycles only for source reads and destination writes. It omits the four-cycle destination read required by partial endmasks, and does not model Blitter bus arbitration or CPU prefetch overlap. Its timing totals therefore underestimate hardware costs.

Across all 368 nonempty code/flip variants and all shifts, 589,824 of 592,368 destination word writes use partial masks. This is an unweighted exhaustive count, but shows that the omitted read cost is material for this drawing method. A masked four-plane run with X count 1 transfers in 48 cycles, rather than the simulator's 32, before arbitration.

This was checked against the local Hatari `src/blitter.c` and [Hatari's upstream implementation](https://raw.githubusercontent.com/hatari/hatari/master/src/blitter.c): destination reads are required for partial masks, memory bus accesses cost four cycles, and STE arbitration costs four cycles on each bus ownership change. The startup gap can overlap CPU work, so blindly adding all latency to the existing simulator would also be inaccurate.

`ste/tools/prof.py` additionally refers to `spr_old_count`, which the current map no longer contains. Repair that counter lookup before using its sprite-count reports. `prof2.py` gives coarse sampled categories; it does not separate descriptor decoding, closure, restoration, and chain construction within `render_sprites`.

The attempted 900-frame sampling run and a shorter 180-frame run did not return results during the investigation and were stopped. No measured gameplay speedup or completed dynamic profile is claimed here; the savings above are transfer/instruction estimates and exhaustive geometry counts.

For implementation, first compare the two-chunk version against the unchanged renderer on identical deterministic inputs, then check independent reference pixels. Exercise palette changes, appearing/disappearing sprites, overlapping sprites, tile updates beneath sprites, shifts 0..15, edge positions, and both draw buffers. Existing `rcheck.py` uses RGB tolerance 40 and has previously saved difference images, so a tolerant pass should not be presented as an exact pixel proof. Use cycle-exact Hatari or STE hardware for final frame-budget measurements, including Timer A/B interaction.

## Implemented follow-up

The STE runtime is the only implemented renderer among the Z80 ports in this workspace. The Falcon drafts contain no Blitter renderer. The STE follow-up implements two-chunk restoration/tracking, shared descriptor caching keyed by raw entry and palette bank, deferred cell clearing, and register count/increment constants. Builds regenerate sprite code when the generator changes and verify generated shapes before assembling. The simulator now counts masked/destination-dependent reads, and the profiler reads visible counts from the current per-buffer rectangle arrays.

Validation also uncovered and fixed two existing rendering bugs: `mark_tile` clobbered the screen destination before `draw_tile`, and a restoration ending at row 256 advanced the Blitter's high address word into another buffer. Dirty tile drawing now reloads the screen pointer after marking; restoration writes complete source/destination addresses per rectangle.

`ste/tools/check_render_perf.py` directly exercises the assembled renderer without game/VBL scheduling. All 268 deterministic frames match fresh redraws exactly, and match the previous binary after its two known bugs are repaired in the test oracle. Cases cover all shifts, both buffers, overlapping/appearing/disappearing sprites, palette changes, changed tiles, and edge rows/columns. Clean-frame checks confirm that dirty cells are not cleared unnecessarily. All 368 nonempty shape/flip variants also pass the generator's random-background pixel model at all 16 shifts.

The direct test measured 21,385,366 simulated cycles for the repaired baseline and 20,993,290 for the new renderer, about 1.8% less across this synthetic workload, including forced tile refreshes. The baseline oracle does not charge additional instructions for its address repairs, and the simulator still excludes arbitration and CPU overlap; these numbers are not hardware frame-rate measurements. Both normal and simulator STE builds assemble and link successfully. More complex restoration merging and vertical batching remain candidate optimizations rather than implemented changes.
