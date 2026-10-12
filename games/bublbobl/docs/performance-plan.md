# Bubble Bobble: the next performance work

Investigation: 2026-10-11, against the current working tree, including its existing
whole-sprite and reordered-source changes. The recommendation is to keep the
current layered renderer and make its background work depend on actual changes,
then replace selected hot logic routines with equivalent native 68000 code.
Neither another sprite inner loop nor a simple redraw strategy reaches the target.

## Evidence and budget

The current simulator build was reproduced in a temporary source copy; its PRG
SHA-256 matched the existing build:
`43f02adf6f06103000a1622a0ace9042a5afbe76872610a605c5e38c2db3e7c9`.

`venv/bin/python games/bublbobl/tools/profile.py 1500 --chunk 256 --top 25
--window 600:900 900:1200 1200:1500` reproduced:

| VBL window | Pictures/s | Game rounds/VBL | Renderer cycles/VBL |
|---|---:|---:|---:|
| 600–899 | 4.7 | 0.63 | 85,389 |
| 900–1199 | 13.7 | 0.74 | 75,591 |
| 1200–1499 | 14.8 | 0.57 | 64,023 |

In 900–1199, the largest renderer samples were `sr_blocks_group` (12,473
cycles/VBL), `sr_draw1` (12,278), `sr_cell` (9,476), `sr_scan` (9,433),
`rf_palette` (6,264), and `tc_bake` (3,026). These are approximate PC-sample
attributions, including charged Blitter bus cycles, not exclusive routine timings.

The quoted 3% sub/MCU category excludes native MCU bus routines: `mcu_bus_read`
and `mcu_bus_write` consume another 9,630 cycles/VBL, about 6% of the entire CPU,
under runtime. MCU optimization therefore has more scope than the category suggests.

At the existing logic pace, 25 pictures/s requires roughly
`1 - 13.7 / 25 = 45%` less work per picture. This uses all current renderer time
and provides no extra logic speed or timing reserve. A planning estimate assigning
13k cycles/VBL to fixed sound/runtime work puts logic and its glue near 96k cycles
per game round in this window, leaving about 102k cycles per picture at 50 logic
rounds/s and 25 pictures/s. The present average is about 276k cycles/picture:
approximately 63% would need to go. The fixed/variable split must be measured
directly before treating that estimate as a hard limit.

Use the budget equation, rather than adding speedup percentages:

`50 * logic_cycles_per_round + 25 * renderer_cycles_per_picture +
50 * fixed_cycles_per_VBL <= 8,000,000`.

A useful engineering target is 70k/120k/10k respectively: 7M cycles/s, with
12.5% reserve. These are acceptance targets, not predicted gains. Fifty rounds/s
is the port's current full pace; the arcade runs about 59.19 rounds/s. Busy play
and transitions need separate budgets; later play already spends substantially
more on the sub CPU. A representative-window result cannot establish steady 25 fps.

## Experiments that constrain the solution

Temporary builds and patches are in `/tmp/bublbobl-solution-probe/`. Neither
experiment was installed into the working renderer. They have no Hatari validation.

The fixed-state comparison used `render_bench.py 900 40 1200 40 --step 2 --prof`
with an injected PRG/map for each variant. It rendered 40 sampled pictures across
the two windows. The initial cold picture is excluded from the first summary.

| Variant | 900–939 mean cycles | 1200–1239 mean cycles | Wrong game pixels |
|---|---:|---:|---:|
| Current renderer | 735,903 | 391,036 | 0 |
| Restore each page's old damage; draw every current sprite | 737,038 | 413,527 | 0 |
| Initialize a cell from its first nonblank tile | 716,829 | 382,101 | 0 |

The page-local experiment removed `sr_copy` and sprite closure, tracked old sprite
footprints and stale backgrounds separately for each page, and drew all current
sprites in priority order. Additional drawing and footprint work erased the copy
savings. Reject this implementation on these measurements.

The cell experiment bypassed the initial pixel clear and the first tile's read/
mask/merge, using the cached tile's zero transparent pixels to initialize the cell;
subsequent tiles still compose normally. It preserved front opacity and blank
cells. Means improved 2.6% and 2.3%; medians were unchanged. Rebuild maxima fell
from approximately 3.93/3.97M to 3.75/3.79M cycles. Under the actual VBL schedule,
pictures/s changed from 4.7/13.7/14.8 to 3.3/14.3/14.7 in the three windows.
Small savings change which scene state is captured and when. Do not infer steady
frame-rate improvement from the fixed-state saving, and do not promote this alone.

## Recommended implementation order

### 1. Stop invalidating useful baked graphics

`sr_pal_cells` already filters static cells with `bb_penmask` and `pen_chg`.
However, sprite keys in `sr_ckey`/`sr_gens` use a whole-bank generation, and the
tile cache invalidation in `rf_palette` invalidates changed banks. A remapping
of one unused pen can therefore force unrelated sprite/tile rebakes.

Keep raw tile identity, flips, used-pen masks, and the relevant pen-to-slot mapping
with each baked entry. When a bank changes, invalidate only entries whose used
pens intersect `pen_chg`. An RGB change that retains a slot must not rebake pixels.
Preserve exact cache-key comparisons, collision handling, and generation wrap;
a hash alone cannot establish that an entry is valid.

Maintain cell dependency bitmaps by bank and pen, updated when maps or tile
entries change. Palette changes then union the affected bitmaps instead of
walking all 3,584 map slots. Sixteen banks times fifteen opaque pens times 112
bytes is about 26 KiB before bookkeeping. Account for the cost of maintaining
the index, especially during a full map rebuild.

### 2. Cache cell recipes and share repeated composites

`sr_cell` clears a cell, decodes up to four tile keys, fetches baked tiles and
composes them through repeated `movep` reads and writes. The short benchmark
attributes about 38% to `sr_cell` plus `sr_key`; another 16% goes to map building.

Resolve a cell's ordered tile descriptors when its map or tile entries change.
Classify empty, single-tile and general compositions then, rather than rediscovering
them on every redraw. Compose general rows in registers and write the final four
plane bytes and front-opacity byte once. Initialize from the first tile when valid.

Add a bounded cache of repeated ordered cell recipes. Its key must include all
tile identities, flips, relevant palette mappings, and the back/front split.
Cache both final pixels and front opacity. Copy hits into `sr_img`/`sr_msk`; keep
the existing exact composition for misses. Measure recipe reuse before sizing the
cache. Do not pre-bake all 16,384 tiles for all sixteen banks: even one unflipped
32-byte image per combination would need 8 MiB.

Handle scene changes as coherent generations. Build the next maps, necessary
bakes and composites in a separate bounded workspace while continuing logic and
displaying the last complete page. Publish a completed picture with its palette.
If logic has advanced, reconcile subsequent changes before publication. This
controls transition stalls; it does not by itself reduce total work or guarantee
that intermediate scene pictures can all be displayed.

### 3. Reduce object polling without making game writes expensive

Keep the existing fast moved-sprite path and tile-page checks. Add compact object
change marks at audited object-RAM writer bursts, and dependency lists from tile
pages to their sprite records. Avoid a full expensive mark on every byte store.
Consume marks with the same interrupt-safe discipline as `rf_vdiff`; writes arriving
after consumption must remain pending for the next snapshot.

Refresh only affected descriptors and tile keys. Retain ordered drawing and a
cheap traversal of the live list. A column's chained X or phase change can affect
later entries even when their own bytes are unchanged, so propagate structural
changes or fall back to a complete scan. Compare the added translated-writer cost
with the removed renderer work across both fast and general rendering paths.

Keep the current per-page stale sets and final-picture copying unless a measured,
correct replacement beats them. Optimize run discovery/setup and sparse damage
only after recording block counts, copied bytes and pass lengths separately.

### 4. Replace hot logic work at routine boundaries

An instruction-level run, `engine/xprof.py bublbobl --skip 650 --frames 80
--top 16 --pcs`, measured MCU bus reads/writes near 12.9k cycles/game round and
translated MCU work near 5.3k. The bus helpers are already native; another generic
I/O fast path is not the next step. Profile their callers and replace suitable
firmware loops with equivalent native transfers, preserving observable registers,
internal RAM, shared RAM, latch state, credit/protection state and interrupt edges.
Keep firmware paths that do not satisfy the native routine's preconditions.

For the main CPU, investigate the hot task/object traversal around `$26A4–$2772`
and frequent small call/return pairs. Native replacements or translator inlining
must preserve flags, alternate registers, stack conventions and bank identity.
Do not remove game work or skip MCU checks to meet a renderer target.

The odd-source/even-destination 360-byte object copy at `$04B6` costs about 5k
cycles/round in this sample, including 4,320 in byte moves. It deserves measurement
but has a limited absolute ceiling; a generic copy-loop tweak cannot supply the
required overall saving. A fused, equivalent copy and object-change detection
routine is a better experiment than adding separate bookkeeping per byte.

Sound is another 12.5–14k cycles/VBL in the existing notes. Consider active-track
lists and cheaper selection/mixing after the larger changes, retaining stream
timing, priorities and effects. Disabling sound is not an accepted gain.

## Acceptance and measurement

First add counters for fast-path dirty cells, static rebuilds, palette-invalidated
entries, cache hits/misses, sprite closure growth, copy versus restoration bytes,
and logic/runtime cycles per completed round. The existing `sim_rf_*` dirty and
palette counters describe the general renderer and report zero while `srender.s`
is active; those zeros do not mean the fast path had no background work. Report
completed/displayed pages too: `sim_renders` currently counts starts.

Compare identical reference-frame sequences and skipped-picture sequences, including
palette changes and transitions. Then measure the actual VBL schedule, reporting
logic rounds/VBL separately from pictures/s and transition latency. Include CPU
and Blitter bus costs and enough margin for border timing.

Before retaining a renderer change, require the independent whole-sprite edge
tests, all sixteen shifts, transparent holes, cache collisions and 64 KiB crossings,
plus consecutive reference pictures and page reuse with guard damage. Draw whole
sprites into margins/guards and restore old damage before the next picture;
preserve visible side bands, priority, and the general fallback. HOG passes remain
at most 256 bus cycles with the shared synchronized border handlers.

For native logic/MCU changes, require per-round RAM/state comparisons over extended
scripted and varied inputs, not only the standalone MCU translation test (which
does not exercise the runtime's native bus helpers). Finally verify gameplay and
timer diagnostics in the pinned Hatari build. Only that validation can establish
a hardware result; every measurement in this investigation is a simulator estimate.

## Implementation status (2026-10-12)

Implemented in this order; details, measurements and the validation in the README ("Performance plan, implemented").

* Counters first: `profile.py` reports renders started / completed / shown, the fast path's cells, composite hits,
  palette-marked cells, pens invalidated, sprite lookups / bakes, closure growth (visible vs drawn), blocks copied /
  restored, palette changes, and logic / runtime cycles per game round.  `sr_blocks_group` had been charged to the
  runtime; it is renderer time.
* Step 1: palette epochs and stamps (tile cache, sprite cache, cell composites), pen-precise, no walk at a change;
  candidate cells by a per-cell bank mask.
* Step 2: the exact composite cache and first-tile initialisation.  Per-cell recipes and scene-change generations
  not done (see the README for why); the colour-cycling screens are the case a mapping-keyed cache would serve.
* Step 3: writer marks for object RAM rejected on measurement (the `$04B6` copy rewrites every sprite entry each
  round); the scan, the block run discovery, the sprite draw loop, the guards and the video RAM diff made cheaper.
* Step 4: the MCU's bus calls direct, its helpers trimmed (no firmware loops to replace); sound's track step and
  channel picks; the main and sub CPUs analysed (no single hot routine; the sub CPU's flag liveness noted).

Result: play 13.7 -> 15.8 pictures a second (Musashi), 11.7 -> 14.7 (Hatari), the game's pace unchanged or slightly
faster.  The 25 pictures a second at full pace remain out of reach: a play picture costs ~285k renderer cycles against
the ~125k the budget leaves.
