# Renderer experiments, 2026-11-01

Investigation of overlapping/sparse damage restoration and prepared secondary-layer
drawing. Base renderer: `138cd90`, `src/stage.s`. Gameplay and scheduling code
were not changed. These are renderer measurements,
not picture rates or evidence that the game runs at 50 logic ticks/s.

## Method

`tools/renderer_audit.py` runs the existing Musashi stage harness and compares
every executed picture against the independent `stage_model.py` model. It counts
the copy rectangles recorded for the next reuse of that display buffer, their
unique destination groups, and the groups actually touched by nonzero drawing
masks. A group is 16 pixels / four plane words.

The first 30 pictures warm the buffers and caches and are excluded from the
statistics, but still checked. The harness renders one picture per two recorded
arcade ticks; it does not model the program's game-speed-first `PIC_EVERY=8`
scheduling. The observations cover windows in all eight stages, not
every frame of every stage. The baseline sweep checks 4,600 pictures and measures
4,360 after warm-up.

The prototype comparisons use identical screen-buffer addresses (`--fixed-buffers`)
so changed code/data sizes cannot change the frequency of 64 KB sprite crossings.
Those addresses are private simulator memory; they are not a proposed STE memory
layout. Every prototype picture is compared to the same independent model.

## 1. Restore overlapping damage once, omit transparent areas

The table gives optimistic **transfer-only ceilings**, not measured speedups.
Duplicated groups are repeated copies of the same address. Untouched groups are
inside the union of copy rectangles but outside every nonzero sprite/layer drawing
mask. Clearing rectangles are excluded. Copying one group costs 32 ideal Blitter
cycles; none of the figures charges construction of a union, extra runs, mask
lookups or additional pass starts. Lists are observed when created; their work is
paid when that buffer is next used.

| Stage | Recording / offsets | Mean renderer cycles | Duplicate-copy cycles | Untouched-copy cycles | Combined ceiling |
|---|---|---:|---:|---:|---:|
| 1 | `stage_states_8`, 3000–3999 | 224,670 | 13,366 | 4,588 | 8.0% |
| 2 | `stage_states_s2`, 700–1899 | 249,571 | 4,794 | 8,960 | 5.5% |
| 3 | `stage_states_3`, 1200–2999 | 268,370 | 7,602 | 3,311 | 4.1% |
| 4 | `stage_states_s4`, 0–999 | 149,108 | 3,141 | 3,198 | 4.3% |
| 5 | `stage_states_s5`, 0–999 | 240,253 | 16,215 | 4,637 | 8.7% |
| 6 | `stage_states_s6`, 0–999 | 134,095 | 3,693 | 1,985 | 4.2% |
| 7 | `stage_states_s7`, 0–1199 | 227,786 | 7,431 | 6,041 | 5.9% |
| 8 | `stage_states_s8`, 0–999 | 178,506 | 2,446 | 2,689 | 2.9% |

Executed prototype: compact the damage list in place, comparing each rectangle
with the last emitted rectangle. Merge equal-width/equal-x vertical spans or
equal-height/equal-y horizontal spans only when they overlap/touch and have the
same clear/copy flag. Do not extend the height beyond its byte field, or widen a
horizontal pass beyond 32 words. Charge the entire merge to the renderer.

| Scene | Baseline mean | Merge mean | Change |
|---|---:|---:|---:|
| Stage 1, middle | 224,906 | 224,080 | −0.37% |
| Stage 3, warship | 268,789 | 273,377 | **+1.71% slower** |
| Stage 5 | 240,274 | 234,983 | **−2.20%** |

A second stage-5 prototype also rejects a new rectangle wholly contained in the
last output rectangle. It reaches 236,786 cycles (−1.45%), worse than the simpler
merge: the extra comparisons consume the saving. A preliminary stage-2 run of
the simple merge was also slower (+1.2%, ordinary buffer layout).

Extending stage 5 to all 3,000 recorded ticks changes the conclusion: with the
merge restricted to scene 8, 1,500 pictures are exact (1,470 measured), and the
mean is 207,438 → 206,123 cycles (**−0.63%**). The median is slightly worse,
165,238 → 167,642, and the 90th percentile is essentially unchanged,
400,472 → 400,924. The first third's 2.2% does not describe the whole recording.

This makes coalescing a small, workload-dependent opportunity, rather than a
general union/grid optimization to enable. A native sparse-span implementation has not been measured;
the untouched-group audit above must not be described as an executed span win.

The selective merge also passed 131 focused restoration cases: all 16 shifts,
side and guard positions, physical-row wraps, 64 KB crossings, mixed clear/copy
flags, and byte-sized height / short-pass width limits. The destination after
restoration equals the independently prepared clean image in every case; every
pass in those focused cases is HOG and at most 256 bus cycles. This does not
claim that unrelated existing passes in the production renderer satisfy that limit.

Hatari confirmation: pinned STE build, 14 MB, seed 10 ticks 46500–49500,
`STAGE INVULN PLAYBACK DEBUG`, current game-speed-first defaults
`PIC_EVERY=8 MAX_BEHIND=12`. The selective merge is enabled only in scene 8.
Both programs use the same generated replay snapshot and inputs.

| Stage-5 replay | VBLs | Logic ticks/s | Pictures/s | Pictures | Dropped ticks |
|---|---:|---:|---:|---:|---:|
| Existing renderer | 3,244 | 46.25 | 14.49 | 940 | 65 |
| Scene-8 merge | 3,237 | 46.35 | 14.29 | 925 | 65 |

The tiny logic-rate change is accompanied by fewer pictures and a lower picture
rate. Because scheduling chooses pictures dynamically, it also changes the
rendered workload; the fixed-picture simulator comparisons above establish the
actual renderer saving. Neither result justifies retaining this merge. Both
Hatari runs report one startup border fallback and zero late border/palette events.

## 2. Prepare/compile secondary-layer pieces

Both experiments preserve the existing HOP 2 / OP 3 drawing and the pass order.
They execute both halves of stage 3's hybrid: BG pieces over the FG buffer, then
FG pieces over the BG buffer. Each runs the same 900 pictures (870 measured).

| Stage-3 renderer | Mean cycles | Change from baseline |
|---|---:|---:|
| Existing piece lists | 268,789 | — |
| Unrolled piece routines | 268,512 | −0.10%, effectively neutral |
| Prepared masks, last shift per map row | 271,580 | **+1.04% slower** |

The unrolled version selects a generated sequence by the number of pieces in
each class, consuming the same lists and masks without a `DBF` per piece. Its
selection/call overhead cancels the loop saving. It is not a complete compiler
specialized to each row's content.

The shifted-mask cache prepares END1/END2/END3 when a row is first drawn at a new
skew. Its key includes FG/BG mode; rebuilding the original row list invalidates
the entry. Storage is 128 KB plus keys. Partial-piece reuse is only 44.4% with
one cached shift; an ideal cache of all 16 shifts raises that to 54.9%. Changes
to the window, row data and skew cause enough preparation that the executed
single-shift cache loses overall. Blitter cycles are identical to the baseline.

Instruction-level sampling (44 pictures) attributes approximately 48.3k cycles
to the two layer draw loops and 10.0k to their row-list builders per picture,
averaged over this window. Eliminating row-list building altogether would still
address only about 3.7% of the mean render cost. A content-specific compiler or
map-coordinate cache has not been executed; these results do not prove that all
such approaches are exhausted.

**Result:** no production renderer changes retained. The simple damage merge
is workload-dependent; compiling the loops is neutral and caching shifted masks
is slower. Neither tested proposal supplies the large gain needed for steady
25 pictures/s with full gameplay speed.

## Reproduction

For the baseline damage and layer-cache audit:

```sh
venv/bin/python games/rtype/tools/renderer_audit.py \
  build/rtype/stage_states_3.pkl --start 1200 --frames 1800 \
  --profile-every 20 --out build/rtype/renderer_audit_s3_final.json
```

For a controlled comparison, add `--fixed-buffers`. `--source path/to/stage.s`
selects an isolated experiment source directory without modifying the production
renderer; other asset paths remain the ordinary build paths. Raw JSON reports,
isolated prototype sources and the merge/shift patch are private build artifacts
under `build/rtype/renderer_*`. Slower experimental paths are not kept in the
production renderer.
