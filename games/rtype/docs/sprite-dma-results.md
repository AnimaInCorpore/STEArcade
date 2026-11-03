# Sprite DMA capture and picture deadlines — 2026-11-03

Fixed a production-only scheduling mismatch in `src/core.s`. The DMA-copy skip
assumed a picture could follow only when the logic backlog was empty or
`PIC_EVERY` was reached. With `PIC_VBLS=3`, `pic_due` can subsequently request a
picture using the just-completed logic frame's measured cost. That picture used
current scrolling with an older captured object list.

With picture deadlines enabled, every DMA now captures the object records at
the actual DMA point. Copying the live slots later, before drawing, would be
wrong: the game's emitters may already have overwritten them for the next DMA.
The old skip remains only with `PIC_VBLS=0`, where the scheduler has no later
deadline decision. Gameplay logic and the native object routines are unchanged.

## Regression and reference checks

`python games/rtype/tools/dma_test.py` assembles the actual DMA routine without
`SIM` and passes 54 cases: both schedulers, pending ticks, cadence boundaries,
retained list tails, fixed slots, register/stack preservation and writes to the
emitter slots after DMA. The pre-fix source fails the deadline-enabled case with
one pending tick and `since_pic=0`. The check is included in `port.py test rtype`.

Both production and stage-SIM programs rebuild. The rebuilt simulator passes
3,000 seed-4 logic ticks against the independent reference under the existing
`--snap --list` contract. That contract excludes approved fade/palette deviations
and expands object records against the reference sprite buffer. SIM already
captured every DMA, so this reference check alone cannot catch the original bug.

## Direct Hatari verification

Private instrumented baseline/fixed builds stamp the frame of each DMA request
and each object-list capture. After an actual picture is published, they compare
those epochs. Counts are retained in unused DEBUG counter slots; no audit code
is enabled in the delivered program.

| Replay | Baseline published / stale capture epoch | Fixed published / stale capture epoch |
|---|---:|---:|
| Stage 3, seed 1 ticks 12600–14400 | 1245 / **1047** | 1408 / **0** |
| Stage 7, seed 10 ticks 64500–67500 | 1621 / **1568** | 1960 / **0** |

An epoch mismatch means the latest requested DMA was not captured; it does not
assert that every object visibly changed on every such picture. Both fixed
replays finish without a crash and execute the expected 1801/3001 logic ticks.
The baseline core is from commit `140c09a`; other code, assets, snapshots and
inputs match between each pair. Audit overhead changes scheduling slightly,
so use the separate uninstrumented measurements below for performance.

## Uninstrumented corrected timing

Pinned local Windows Hatari 2.6.1-devel, 2026-10-30 build; STE 14 MB, TOS 2.06 DE,
cycle-exact/compatible CPU, sound off, fast-forward. Rates come from emulated
50 Hz VBL counters. Production scheduler defaults are unchanged. These samples
cover all eight stages, not every possible route or a new complete playthrough.

| Window | Seed / ticks | Before logic/s | Corrected logic/s | Before pictures/s | Corrected pictures/s |
|---|---|---:|---:|---:|---:|
| Early play | 4 / 600–3600 | 41.95 | 41.77 | 33.90 | 33.70 |
| Stage 1 | 8 / 3000–8000 | 39.95 | 34.04 | 21.70 | 20.61 |
| Stage 2 | 10 / 11000–13000 | 38.36 | 32.98 | 19.13 | 18.01 |
| Stage 3 | 1 / 12600–14400 | 28.55 | 22.22 | 19.20 | 17.31 |
| Stage 4 | 10 / 33000–36000 | 44.49 | 42.10 | 23.05 | 22.66 |
| Stage 5 | 10 / 46500–49500 | 33.86 | 30.09 | 21.23 | 19.76 |
| Stage 6 | 10 / 56000–59000 | 43.38 | 38.15 | 20.48 | 20.80 |
| Stage 7 | 10 / 64500–67500 | 36.57 | 26.57 | 19.62 | 17.17 |
| Stage 8 | 10 / 74000–77000 | 36.62 | 28.19 | 23.94 | 20.28 |

Capturing every DMA adds copying work. Drawing current poses also changes sprite
shapes, damage and cache workloads, so these differences are not a measurement
of copy cost alone. The old stale-list workload concealed a substantial cost in
heavy scenes. Do not retain the old speed figures as correct-picture throughput.

Every corrected timing replay completes with its expected logic count and no
crash. Stage 3 still had **22 late palette-on events** (fixed the same day: short `st_sync` passes, README); its report was
`(1,0,22,0,0)`. Other measured windows have `(1,0,0,0,0)`: one startup fallback,
zero late top/palette/bottom/off events. This fix does not resolve that separate
stage-3 border-timing issue.

Hatari SHA-256:
`247fbe210a340a0e93a7ba2ad4a6e3dfb38a34f905e7f374727b74215b56dd6d`.
TOS SHA-256:
`bcf89ce4e897c848f819b2227987ce754fa37994024d9f39a10ceb3bc91c999d`.

Raw audit/timing counters, hashes and logs are under
`build/rtype/local_stage_timing/dma_*`. Private orchestration scripts are
`build/rtype/local_dma_audit.py` and `local_dma_timing_suite.py`. Temporary replay
executables are removed; compressed reference snapshots and small reports remain.
Canonical replay inputs are unchanged.

The ordinary corrected program is `run/rtype/RTYPE.PRG`, without DEBUG or
PLAYBACK. Its manual test copy is `run/rtype_dma_fixed/RTYPE.PRG`.
