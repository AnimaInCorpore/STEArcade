# Avoiding redraws and buffer copies, 2026-11-03

Status: dated report (2026-11-03); a measured prototype, not integrated.

**Result: a small measured saving, no 2x renderer path found.** An isolated
window-refresh prototype saves 2.50% in the stage-3 window, 1.58% in stage 4,
and 0.81% in stage 6. It reduces large refresh spikes, while normal pictures
pay a little extra bookkeeping. Production `src/stage.s` is unchanged.

## Audit: which transfers could be avoided?

`tools/route1_audit.py` observes actual Blitter destinations, masks and bus
transactions. After each picture it walks the drawing passes backwards to find
restoration words whose written bits are completely overwritten by later
layer/sprite drawing. It also finds copies wholly outside the current physical
display window, including the HUD split and fine-scroll word masks.

The following are **transfer-only ceilings**, not implemented speedups. They
charge no CPU work for predicting coverage, maintaining pending updates or
splitting passes. The union avoids double-counting words that are both hidden
and overwritten. Off-window updates cannot simply be dropped: the area must be
made current before scrolling into view. This audit uses host-side hindsight;
it is not a proposed native algorithm.

| Stage | Recording / offsets | Mean renderer cycles, approximately | Restore/copy bus cycles overwritten later | Off-window restore/copy bus cycles | Union ceiling |
|---|---|---:|---:|---:|---:|
| 1 | `stage_states_8`, 3000–3999 | 224,767 | 7,772 | 5,967 | 13,637 / 6.1% |
| 2 | `stage_states_s2`, 700–1899 | 248,389 | 9,705 | 13,057 | 21,426 / 8.6% |
| 3 | `stage_states_3`, 1200–2999 | 268,675 | 13,319 | 12,200 | 24,209 / 9.0% |
| 4 | `stage_states_s4`, 0–999 | 148,962 | 2,126 | 7,544 | 9,612 / 6.5% |
| 5 | `stage_states_s5`, 0–999 | 240,152 | 18,642 | 7,764 | 25,714 / 10.7% |
| 6 | `stage_states_s6`, 0–999 | 133,648 | 3,237 | 7,902 | 10,836 / 8.1% |
| 7 | `stage_states_s7`, 0–1199 | 227,776 | 4,433 | 7,463 | 11,705 / 5.1% |
| 8 | `stage_states_s8`, 0–999 | 178,352 | 2,257 | 7,767 | 9,913 / 5.6% |

These windows check 4,600 pictures, 4,360 after warm-up, against the independent
model. Renderer CPU totals in this survey mix batched execution and periodic
instruction stepping; the controlled prototype comparisons below instruction-step
every measured picture. Transfer counts themselves are exact.

In stage 3, ordinary damage restoration accounts for about 32.4k bus cycles per
picture, with 11.3k overwritten later. Only 2.6k of that saving belongs to entire
passes that could disappear without splitting them. Whole-buffer refreshes cost
another 7.2k on average, 5.8k outside the current window. Ordinary log copies
outside the window account for only 2.3k.

Warship pixels hidden by later wall repair account for just 610 bus cycles per
picture, below 0.3% of total renderer cost. Individual sprite drawing contains
another 6.5k bus cycles overwritten by later sprites, but predicting that coverage
and preserving priority has not been implemented or charged. Neither is a large
demonstrated opportunity.

## Executed prototype: refresh the window, fill incoming strips

`tools/route1_window.s` changes the fallback taken when the composition log
overflows. The first full refresh of each display buffer remains unchanged;
this avoids imposing strip-copy work on scenes with no later full refreshes.
Subsequent fallbacks initialize only the 20 or 21 physical groups fetched for
the 320-pixel window, over 256 lines, rather than the entire virtual buffer.

For each partly refreshed display buffer, the prototype remembers the physical
x, y and width of its valid rectangle. On its next use, it copies newly exposed
top, bottom, left and right strips from the **current clean buffer**, then runs
ordinary log synchronization and old-damage restoration. Disjoint windows copy
the new window in full. This handles horizontal wraps, BG vertical wraps,
fine-scroll width changes and transitions between FG and BG buffer regions.
It does not assume that unseen BG guard lines are safe to display later.

Metadata takes 32 bytes. All native bookkeeping, incoming copies and extra
register setup are charged. Copies use the existing short HOG `st_copy` path,
with no AND/OR pairs or changes to sprite/layer priority. The experimental
source is generated under `build/rtype/route1_window_source/`.

## Controlled measurements

Musashi CPU + Blitter bus cycles, identical fixed screen-buffer addresses,
identical supplied states and layer-mode choices. Every measured picture is
instruction-stepped. First 30 pictures are checked and excluded from the table;
all later preparation and refresh work remains included.

| Window | Cadence | Checked / measured per variant | Current mean | Prototype mean | Change |
|---|---|---:|---:|---:|---:|
| Stage 3, offsets 1200–2999 | Every 2 arcade frames | 900 / 870 | 266,396 | 259,742 | **−2.50%** |
| Same stage-3 window | Every arcade frame | 1,800 / 1,770 | 230,692 | 227,654 | **−1.32%** |
| Stage 4, offsets 0–999 | Every 2 frames | 500 / 470 | 146,512 | 144,192 | **−1.58%** |
| Stage 6, offsets 0–999 | Every 2 frames | 500 / 470 | 131,220 | 130,158 | **−0.81%** |

Stage 3's 90th percentile falls from 380,277 to 377,843 cycles, and its largest
measured picture from 7,675,026 to 6,965,516. Stage 4 and stage 6 have slightly
worse medians and 90th percentiles despite better means: the gain comes from
rarer, cheaper full-refresh pictures rather than uniformly faster drawing.

All compared pictures match `stage_model.py`: zero differing pixels. The
separate geometry check covers 84 cases across three buffers, all 16 fine
positions, horizontal and vertical moves in both directions, disjoint regions,
wraps and physical FG/BG transitions. Its 14,040 copy passes are HOG and at most
256 bus cycles. The consecutive stage-3 run also checks the new copy passes;
this does not certify unrelated existing sprite/layer passes.

### Pinned Hatari check

Pinned binary `~/Work/F030Arcade/third_party/hatari/build/src/hatari`, STE 14 MB,
TOS 2.06 DE, cycle-exact/compatible CPU, sound off, fast-forward; seed 1 replay
12600–14400. Both builds use the same privately generated snapshot and inputs,
with `STAGE PLAYBACK DEBUG` and the current scheduler defaults, including
`PIC_VBLS=3`. Shared snapshots, replay inputs and installed game binaries are
not overwritten.

| Build | VBLs | Logic ticks/s | Pictures/s | Pictures | Dropped ticks |
|---|---:|---:|---:|---:|---:|
| Current | 3,195 | 28.18 | 19.17 | 1,225 | 773 |
| Window refresh | 3,142 | 28.66 | 19.68 | 1,237 | 775 |

Both execute 1,801 logic ticks. Scheduling chooses different picture workloads,
so these rates support the direction of the change; the fixed-workload simulator
comparisons establish the renderer saving. Neither build runs gameplay at 50
logic ticks/s in this window.

Border reports `(fallback, late top, late palette-on, late bottom, late off)`:
current `(1, 0, 24, 1, 0)`, prototype `(1, 0, 15, 0, 0)`. The prototype does not
make this a timing-clean build: late palette events remain. It is retained as
an isolated experiment, not enabled in production.

## What this means for 2x

Exact stage-3 attribution gives 46,739 cycles to composition and 63,290 to
buffer synchronization, out of 266,396. Making **both phases completely free**
would yield only 1.70x renderer speed; layer/sprite drawing and the remaining
work still cost 156,367 cycles. This is a bound on eliminating those two phases,
not on every possible architectural change. Achieving 2x also needs substantial
savings in layer/sprite drawing or a different visual workload.

The audit does not rule out selective palette invalidation, a native
restore-excluding-future-coverage algorithm or other composition strategies.
It finds modest transfer-only ceilings, and the executed window-refresh
prototype supplies 0.8–2.5% savings, not a demonstrated 2x route.

## Reproduction and provenance

Baseline repository `9580433`; production `stage.s` SHA-256
`149decf0e98e487e3ceca2bc63abc0f9cf9d4ba22a348d47a41fb38aba7cba63`.
Window prototype SHA-256
`d8a66adc30d46ad67f7b1ed83044d79c14e23ca0218ace0d27c83edfcb3e12da`.

```sh
venv/bin/python games/rtype/tools/route1_audit.py build/rtype/stage_states_3.pkl \
  --profile-every 1 --out build/rtype/route1_s3_base_exact.json

venv/bin/python games/rtype/tools/route1_audit.py build/rtype/stage_states_3.pkl \
  --profile-every 1 --window-prototype --check-window \
  --out build/rtype/route1_s3_window_exact.json
```

Use `--every 1` for consecutive frames. Other stage windows use the table's
recording names and offsets with `--start` / `--frames`. Raw per-picture reports
and logs are private build artifacts under `build/rtype/route1_*`; the pinned
Hatari comparison is `build/rtype/route1_hatari.json` with its raw counters in
`run/rtype_route1_base` and `run/rtype_route1_window`. No claim of whole-game
coverage or full-game 2x speed is made.
