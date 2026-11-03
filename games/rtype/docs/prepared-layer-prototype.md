# Prepared secondary-layer prototype, 2026-11-02

**Result: exact, but no consistent speedup. Production `src/stage.s` is unchanged.**
The prototype loses 0.68% when drawing every second arcade frame and gains 0.67%
when drawing every arcade frame. This does not justify enabling it or claiming an
improvement in game speed or picture rate.

## Executed implementation

`tools/prepared_layer.py` creates an isolated `build/rtype/renderer_prepared_source/stage.s`.
It replaces the two secondary-layer piece interpreters with `tools/prepared_layer.s`:

* On first use or row-list invalidation, native 68000 code packs all four planes
  into pass order and emits a content-specific drawing routine. Source is set
  once per row and advances through the packed words without per-piece writes.
* The generated code embeds destination deltas, reads width settings only when
  the pass width changes, and consumes a prepared end-mask stream. Equal adjacent
  masks share register state. It retains the existing piece order; there is no
  additional global sort of equal masks.
* Shift streams are prepared lazily by native 68000 code, for all 16 shifts.
  A worst-case row requiring more than 672 mask bytes per shift uses eight
  directly mapped shift entries instead, keeping storage bounded.
* The cache has 32 directly mapped row slots shared by FG and BG, 16 KB each:
  **512 KB additional BSS**. A rebuilt row invalidates its entry, including changes
  to coloured pixels. Layer identity and the window's first chunk are in the key.
* HOP 2 / OP 3 copies preserve transparent holes. Full destination addresses are
  used. Existing seven-word full pieces split into six plus one source words so
  shifted passes remain below 256 bus cycles. That adds some transfers relative
  to the current renderer; those transfers are included in the results.

This is a row-based prototype over the existing window-relative piece lists.
It does **not** implement the proposed fixed-map-chunk cache, content sharing
between unrelated rows, build-time preparation, or a different hybrid crossover.
It goes beyond the earlier loop unrolling: source packing, generated destination
steps and lazy prepared masks all execute and are charged.

## Controlled comparison

Source base: repository `9580433`, production `stage.s` SHA-256
`149decf0e98e487e3ceca2bc63abc0f9cf9d4ba22a348d47a41fb38aba7cba63`.
Generated prototype SHA-256:
`788a4b2f865e93a7fc89dd1e5b48b4f1bf7170dda114ec728757881f95232743`.

Both variants use `stage_states_3.pkl`, offsets 1200–2999, covering the BG-pieces
and FG-pieces halves of the stage-3 hybrid. They start with cold caches and use
the same fixed simulator screen addresses ($D00000 and following buffers), so
changed executable size cannot change sprite destination crossings. Layer-mode
selection and the sequence of supplied states are the same.

Every measured picture is instruction-stepped in Musashi; the table sums CPU
cycles and Blitter bus cycles. The first 30 pictures are checked and excluded
from the warmed statistics. **All subsequent packing, compilation, invalidation,
cache lookup and mask generation remain included.** Initial renderer setup is
recorded separately. No host-side preparation is substituted for native work.

| Picture cadence | Checked / measured per variant | Current mean | Prepared mean | Change | Current / prepared p90 |
|---|---:|---:|---:|---:|---:|
| Every 2 arcade frames | 900 / 870 | 266,396 | 268,203 | **+0.68% slower** | 380,277 / 384,280 |
| Every arcade frame | 1,800 / 1,770 | 230,692 | 229,140 | **−0.67%** | 316,742 / 314,015 |

Medians: every-two-frame cadence 244,464 → 242,200; consecutive cadence
235,022 → 228,769. Including all cold-start pictures, the respective mean
costs are 286,017 → 287,836 and 240,597 → 239,093 cycles. The improved medians
do not establish a consistent total-cost reduction.

| Preparation/reuse | Every 2 frames | Every frame |
|---|---:|---:|
| Prepared row draws | 5,534 | 11,042 |
| Code/source builds | 182 | 182 |
| Shift-stream builds | 2,271 | 2,355 |
| Shift-stream cache hits | 3,263 | 8,687 |
| Mean compilation + packing + mask-preparation cycles per measured picture | 6,579 | 3,345 |

Preparation attribution comes from instruction-level labels (`st_pr_compile`,
`st_pr_emit`, `st_pr_make_masks`); cache lookup and generated drawing are charged
elsewhere in the same total. The same 182 code/source builds amortize over twice
as many row draws in the consecutive run. This explains why picture cadence
changes the conclusion.

The BG-pieces half loses 0.82% at the every-two-frame cadence; the FG-pieces half
loses 0.51%. With consecutive pictures, the BG-pieces half loses 0.41% and the
FG-pieces half gains 1.87%. These are window-specific renderer costs, not
whole-stage or whole-game performance figures.

## Correctness and pass limits

Both 900-picture and 1,800-picture runs match the independent `stage_model.py`
picture at every executed state, for both variants: **zero differing pixels**.
Buffer reuse/restoration, the hybrid switch, HUD and sprite order remain active.
The test asserts that the baseline actually uses the production renderer.

The separate focused check passes **113 cases**, covering all 16 shifts,
transparent holes, full runs including the seven-word split, physical row wraps,
side/guard addresses, source and destination 64 KB crossings, recolouring and
rebuilding the same key, shift-cache replacement, and the maximum 176-piece row
(including the eight-entry capacity fallback). Its oracle applies source pixels
and opacity directly to independently initialized destination words.

Every generated drawing pass is checked for HOP 2 / OP 3, HOG, four planes,
source bounds and at most 256 bus cycles. The longest observed prepared pass is
**240 bus cycles**. The two recording runs execute 105,952 and 211,748 prepared
passes. This does not certify unrelated existing renderer passes.

These are simulator comparisons. No pinned-Hatari border-timing or picture-rate
claim is made, and the prototype is not enabled in the game. Fixed map chunks
could improve reuse, but their boundary handling and preparation costs remain
unmeasured; the small result here is not proof that that further approach wins.

## Reproduction

From the repository root, with the existing assets and stage-3 recording:

```sh
venv/bin/python games/rtype/tools/prepared_layer.py --check

venv/bin/python games/rtype/tools/prepared_layer.py --measure --profile-every 1 \
  --out build/rtype/renderer_prepared_exact_every2.json

venv/bin/python games/rtype/tools/prepared_layer.py --measure --every 1 --profile-every 1 \
  --out build/rtype/renderer_prepared_consecutive.json
```

Reports include per-picture CPU/Blitter costs, native preparation counters,
mode-specific statistics, cold-inclusive statistics, preparation profiles and
the generated source hash. Raw reports, logs and generated sources stay under
`build/rtype/renderer_prepared*`; only this report and the executable experiment
sources are retained outside build artifacts.
