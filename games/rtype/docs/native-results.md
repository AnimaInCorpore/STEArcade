# Native logic optimization, 2026-11-03

**Result: larger gains in early play and restarts, small gains in later steady
play.** The integrated changes reduce logic cycles by 16–23% in three early
play/restart windows. Eight later-game windows improve by 0.3–3.0%. The pinned
Hatari early-play replay improves logic throughput by 6.1% and picture rate by
14.2%. This is not a demonstrated 2x game or renderer speedup.

The verified cache correction, object handler, unused sprite-definition read removal,
and tile-RAM clears are now integrated into production `src/natives.s` and
`tools/gen.py`. `EMIT1_BODY` shares the one-entry emitter between its normal entry
and the object handler, with the appropriate saved-DS0 stack offset. The renderer,
core runtime, scheduler and previous window-refresh prototype are unchanged. The
pairwise palette-copy experiment remains excluded.

## What was profiled and changed

`tools/native_audit.py` builds private baseline/experimental programs and profiles
68000 instructions. Existing native routines already consume much of the hot
path: sprite emission, position updates, collision rejection, movement scripts
and tile lookups. A 60-frame seed-4 sample beginning at tick 600 attributes 24.2%
of logic cycles to the two existing fade routines, 12.1% to sprite emission,
7.5% to the fixed-object loop, and 5.5% to x-position updates.

The executed experiments are:

1. **Correct the palette target cache.** In `nat_init`, the red-byte load reuses
   the register holding the ROM source offset. Loading the low byte leaves that
   offset's high byte in the cached word. Green/blue already use a cleared
   register. Independent reads of every ROM target find **4,010 incorrect words
   among the 4,096 cached red words**. The slow fallback kept the actual palette
   values correct, but most completed targets failed the fast comparison.
   Zero-extending the red byte fixes all 12,288 cached RGB words. It adds 32,768
   CPU cycles once during initialization; hardware measurements include startup.
2. **Native handler for ROM `0040:E5CD`.** This routine moves an object in x,
   emits its sprite and performs the existing screen/cleanup tests. The prototype
   combines the position update and emitter body, preserving the V30 registers
   and emulated stack residues. Odd BP takes the original code. It also omits an
   unused definition-offset read in `EMIT_ENTRY` for object-list builds. The
   independent comparisons include object records, slot allocation and sprite DMA.
3. **Native tile-RAM initialization.** The three loops at `0040:E873`, `E890`
   and `E8AD` fill 3,968 or 4,096 tile cells with the same `$0FA0` code and zero
   attributes. Native longword stores replace individual translated word stores,
   marking each affected 64-byte video block once. Exact input guards retain the
   original loops for other counts, offsets, segments or attributes. This changes
   game tile RAM initialization, not the STE pixel renderer.

The production handlers and cache fix are in `src/natives.s`; `tools/gen.py`
registers the four new native entry points. The original isolated experiments in
`tools/native_clear.s`, `native_object.s` and `native_audit.py` remain reproducible
against the pinned pre-integration sources. A separate pairwise palette-copy experiment in
`native_fade.s` adds negligible savings after the cache correction and is **not**
included in the combined prototype.

## Controlled CPU measurements

Every window contains 600 consecutive logic frames. Baseline and prototype use
the same input sequence and the same baseline-produced compressed checkpoint.
Every frame is instruction-stepped; all routine dispatch, guards, markers and
fallbacks are included. No renderer cycles or picture-rate estimates are folded
into these logic figures.

| Seed 4 window | Baseline cycles/tick | Combined cycles/tick | Saving |
|---|---:|---:|---:|
| 600–1199, early play | 70,143 | 58,714 | **16.29%** |
| 2000–2599 | 80,111 | 65,477 | **18.27%** |
| 3000–3599, includes restart work | 41,134 | 31,679 | **22.99%** |

The component comparisons establish what contributes, rather than assigning the
entire saving to new native handlers:

| Same seed-4 window | Palette cache only | Object handler / unused read | Tile clears only |
|---|---:|---:|---:|
| 600–1199 | 12.99% | 3.31% | 0.00% |
| 2000–2599 | 11.57% | 2.35% | 4.35% |
| 3000–3599 | 5.58% | 0.19% | 17.21% |

These windows are not representative of every stage. The eight seed-10 windows
used to check later gameplay give:

| Start tick | Baseline cycles/tick | Combined cycles/tick | Saving |
|---:|---:|---:|---:|
| 3000 | 100,224 | 97,195 | 3.02% |
| 11000 | 67,051 | 66,707 | 0.51% |
| 22000 | 127,585 | 126,505 | 0.85% |
| 33000 | 67,935 | 67,032 | 1.33% |
| 46500 | 95,299 | 94,827 | 0.49% |
| 56000 | 60,371 | 59,778 | 0.98% |
| 65000 | 116,785 | 116,300 | 0.42% |
| 74000 | 62,150 | 61,959 | 0.31% |

The expensive later-stage collision and movement routines are already native;
these replacements do not remove their costs. Bulk clears are absent from those
particular 600-frame windows, so their large local gain does not improve those
steady-play averages.

## Exactness and local routine tests

The baseline-produced checkpoints accelerate controlled comparisons; they are
**not independent full-game reference evidence**. Baseline/prototype workers run
in separate processes because `machine68k` shares native emulator state between
instances. At every frame, the tests compare SHA-256 digests of work RAM (including
palette buffers, fade records and stack residues), sprite RAM, palettes, FG/BG
video RAM, object records and DMA state, registers/segment pointers, scroll/raster
ports, sound commands, and video dirty marks. Host pointers are normalized by
image base. Only arithmetic flags proved dead at the idle point are ignored;
the tool asserts `idle_flags == 0`.

All 6,600 combined-comparison frames match. Markers are cleared before each test
frame, preventing an earlier mark from hiding a missed video update.

Separate **fresh-boot independent reference lock-step tests** pass:

* Seed 4: 9,000 frames, normal play, deaths and restarts.
* Seed 1: 14,400 frames, through the stage-3 attract demo.

These use the established `--snap --list` contract: the stage build's existing
fade/palette deviations are excluded by the reference check, and object records
are expanded through ROM definitions against the reference sprite buffer. The
baseline/prototype digest comparisons above additionally compare the port's
palette buffers and fade records without those exclusions. This is not fresh-boot
reference coverage of all eight stages or the ending.

Focused tests independently verify all 12,288 palette-cache words, all three
bulk fills, exact byte contents and dirty-block ranges, final registers, and
short/nonzero-attribute fallback cases. A full 16 KB clear costs **1,122,302 →
60,188 CPU cycles**, about **18.6x faster for that routine**. A partial 15.5 KB
clear costs 1,087,230 → 58,320. Unsupported seven-cell cases remain exact and
pay extra guards (1,916 → 2,168 cycles). None of those local factors is an
overall-game speedup.

## Pinned Hatari measurement

Pinned `~/Work/F030Arcade/third_party/hatari/build/src/hatari`, STE 14 MB, TOS
2.06 DE, cycle-exact and compatible CPU, sound off. Identical private seed-4
snapshot and input runs, ticks 600–3600; `STAGE PLAYBACK DEBUG` with the current
scheduler, including `PIC_VBLS=3`. Canonical replay inputs, snapshots and installed
game binaries are not overwritten.

| Build | VBLs | Logic ticks/s | Pictures/s | Pictures | Dropped ticks |
|---|---:|---:|---:|---:|---:|
| Current | 3,795 | 39.54 | 29.71 | 2,255 | 50 |
| Combined native prototype | 3,577 | 41.95 | 33.94 | 2,428 | 41 |

Both execute 3,001 logic ticks. Both report one startup border fallback and zero
late top/palette/bottom/off events. Logic throughput increases 6.1%, picture rate
14.2%; dynamic picture scheduling changes the rendered workload. These are
early-play/restart replay rates, not a steady whole-game picture-rate claim.

## Production integration checks

The production generator was rerun, then both SIM configurations assembled: the
stage renderer with `FADE_SNAP`, and the original sprite-RAM path with full fades.
The generated translation differs from the previous baseline only in the four
new native jump/fallback entries. Historical regeneration with the pinned old
`gen.py` matches the saved pre-integration code, dispatch tables and generation
metadata byte for byte.

The 11 production CPU comparisons (6,600 frames) reproduce **every measured
per-window mean exactly**, including the 16.29%, 18.27%, 22.99% early-play savings
and the eight 0.3–3.0% later samples. Every compared state digest matches. The
production focused checks verify all 12,288 palette-cache words, the three bulk
fills and the three guarded fallbacks; their costs match the prototype exactly.

Fresh-boot production reference checks pass 9,000 seed-4 stage-build frames and
14,400 seed-1 stage-build frames. An additional 9,000 seed-4 frames pass with full
arcade fades and the original sprite-RAM emitter path (no `--snap` or `--list`
exclusions). Production-recorded gameplay ticks 2000–2095 and stage-3 demo ticks
11400–11495 each pass 96 consecutive pixel comparisons against `stage_model.py`:
**192 pictures, zero differing pixels**. These checks include the renderer's
existing approved simplifications; they do not extend fresh-boot coverage to all
eight stages and the ending.

The ordinary production `STAGE` executable is rebuilt at `run/rtype/RTYPE.PRG`
without debug or playback settings. Pinned Hatari production measurements reproduce
all baseline/prototype counters in the table above exactly: 3,795 → 3,577 VBLs,
3,001 logic ticks each, 2,255 → 2,428 pictures, and `[1,0,0,0,0]` border counters.

Integration outputs are `build/rtype/native_production_*.log`,
`build/rtype/native_audit/production_seed{4,10}_comparison.json`,
`focused_production.json` and `production_hatari_comparison.json`. Raw hardware
counters are under `run/rtype_native_production_{base,production}/`.

## Reproduction

```sh
# Baseline-generated checkpoints and initial hot-code samples.
venv/bin/python games/rtype/tools/native_audit.py
venv/bin/python games/rtype/tools/native_audit.py --seed 4 --starts 600,2000,3000

# Separate historical-baseline/production processes; all 600 ticks per window measured.
venv/bin/python games/rtype/tools/native_audit.py --compare production --frames 600
venv/bin/python games/rtype/tools/native_audit.py --compare production \
  --seed 4 --starts 600,2000,3000 --frames 600

venv/bin/python games/rtype/tools/native_audit.py --check
venv/bin/python games/rtype/tools/native_hatari.py
venv/bin/python games/rtype/tools/native_audit.py --reference production --seed 4 --frames 9000
venv/bin/python games/rtype/tools/native_audit.py --reference production --seed 1 --frames 14400

# Original sprite-RAM path and full fades, with no fade/list comparison exclusions.
venv/bin/python games/rtype/tools/build.py --sim
venv/bin/python games/rtype/tools/logic_test.py 9000 --seed 4

# Capture a short production stage sequence, then compare every picture.
venv/bin/python games/rtype/tools/native_audit.py --reference production --seed 4 \
  --frames 2096 --start 2000 --record build/rtype/native_audit/production_play_states.pkl
venv/bin/python games/rtype/tools/stage_test.py \
  build/rtype/native_audit/production_play_states.pkl --every 1 --quiet
# Stage-3 sequence: use seed 1, --frames 11496 --start 11400, a separate record file.
```

Build the production stage SIM before these checks with
`venv/bin/python games/rtype/tools/build.py --sim -D STAGE=1 -D FADE_SNAP=1`.
The `production` audit variant uses these generated files and the current native
source directly, without applying experimental patches. Other audit variants use
`gen.py` and `natives.s` from commit `958043317915566359fb72ff721d162a82513193`;
the historical translation cache is compressed. `--compare combined` retains the
original combined experiment for comparison.

Private checkpoints, oracle hashes, per-label profiles and comparisons live under
`build/rtype/native_audit/`; reference logs are `build/rtype/native_reference_seed*.log`,
and hardware results are `build/rtype/native_audit/hatari_comparison.json` with
raw counters under `run/rtype_native_base` / `run/rtype_native_combined`.
Temporary emulator programs are removed; compressed checkpoints and small reports
remain. `--benchmark` selects component experiments after creating the matching
baseline oracle with `--compare`.

Pre-integration baseline repository `9580433`, `src/natives.s` SHA-256
`2a051531400667d47fa51711ef18f3a5ead75c706617b20ec58772f5128f7aca`.
Combined generated `natives.s` / `code_main.s` hashes:
`2874ca96e9141f0381b782442361d289c64bcf69471e8c0de0143c4351a63c22` /
`59416aa7ee6d95a98132735ecbeca046270b9ef165286d0cd80c7041098224ba`.
