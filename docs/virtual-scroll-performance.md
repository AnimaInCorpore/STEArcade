# Virtual screen scrolling performance review — 2026-10-19

Initial audit: source review and existing recorded measurements. Implementation and fresh
measurements from the subsequent work are recorded below, under "Implementation results".
Figures below come from each game's README and its profiling tools. They use different
scripts, builds and dates, so they establish priorities, not an apples-to-apples ranking.
The original audit table below is historical context, not the result of the new builds.

## Finding

Keep hardware scrolling. The ports already move the Shifter's window over cached virtual
screens, rather than copying a background for every camera movement. Most remaining cost
is restoring and redrawing objects, text, relative motion between layers, cache misses,
and translated game logic. A single replacement scrolling routine will not deliver steady
25 pictures/s across these ports.

At 50 Hz, steady 25 pictures/s requires a new completed picture at least every two VBLs.
That is a 40 ms or nominal 320,000-cycle total budget at 8 MHz, including all logic due in
that interval, sound, interrupts, CPU drawing and Blitter bus ownership. A renderer-only
320k result is insufficient. For arcade rate F and measured logic cost L, the initial
budget equation is R <= (8,000,000 - F*L - other work per second)/25. Apply this to actual
emulated bus time, not uncorrected Musashi instruction cycles. The commonly recorded
~1.35 Hatari/Musashi ratio is a warning about the difference, not a universal multiplier.

Neither a whole-run average above 25 nor p99 below 40 ms proves an uninterrupted minimum.
Measure maximum displayed-picture interval as well as the distribution. State explicitly
whether loading/floor transitions are included in the requirement; their stalls are real.

## Ports and first experiments

| Port | Recorded evidence | Assessment and first experiment |
|---|---|---|
| 1942 | Hatari ~35–36 pictures/s and ~58 ticks/s. Render ~65–90k Musashi cycles in ordinary busy scenes; stage changes reported at 1–2.4M per tick. | Best starting point. Target stage-change palette/tile rebakes and sprite/character work rather than scrolling itself. Measure cache misses around palette-bank changes; prototype keeping or preparing frequently reused bank mappings within the memory budget. |
| Commando | Latest documented Hatari 26.9 pictures/s, 57 ticks/s. Recorded-play render mean 168k, p99 324k Musashi cycles in a separate test. | Average target approximately met, tail target unproven. Profile restores, sprite setup and text on missed deadlines; investigate avoiding repeated text composition when its screen-relative position changes. Retain twin-line restoration. A previous damage-bitmap union was slower: do not assume merging damage helps. |
| 1943 | Recorded Hatari results vary strongly by stage/build: ~11–12 pictures/s in ordinary runs, ~33–34 in stage 3; cloud-bank results include impossible counts and cannot be accepted. Render ~206k ordinary / ~354–366k cloud scenes. | Large front-layer cost: only the back layer persists cleanly; front tiles, sprites and text become damage each picture. Prototype a cached front-layer image with short strip/run composition for relative scroll and unchanged text strips. Measure front composition plus its later restore together. Validate benchmark counters before using cloud results. |
| Black Tiger | ~80k Musashi logic cycles/tick (~108k recorded in Hatari). Scrolling render ~437k CPU+Blitter after earlier optimization. A MAX_SKIPS=2 experiment gave 14 pictures/s and 33.5 ticks/s. | Both logic and drawing need work. First profile background-bank copying and guarded reads; investigate retaining directly addressable bank state with equivalent collision reads. Then text-strip pass setup, margin restoration and sprite setup. At the recorded 108k/tick, 60 ticks/s leave only ~61k cycles/picture at 25 fps before sound/interrupts: drawing alone cannot close this gap. |
| Gun.Smoke | Sound-enabled short-pass Hatari ~23 pictures/s, ~49 ticks/s. Consecutive renders 84–380k, round medians 89k and 251k; horizontal slides ~238k; redraws ~1M. | Near the average target, with substantial heavy-scene risk. Profile text-mask AND/OR strips, fallback sprite frequency and newly exposed strips by round. Prototype cheaper cached text-run composition and reduce fallback setup. Keep D802 hardware scrolling; the previous software shift was slower. |
| Kung-Fu Master | Hatari recorded play 27.1 pictures/s overall, gameplay windows 20–34, logic ~55–56/s in play. Render ~140–196k CPU+Blitter. | Explicitly fails a steady 25 requirement in some windows. First eliminate full-window copies at the 512-pixel wrap by choosing a valid twin window nearest the previous position; verify per-ring validity before reusing it. Then narrow priority-tile restoration to actual sprite overlap. Floor transitions require a separate cache/rebuild experiment. |
| Trojan | Hatari recorded play 10.4 pictures/s, logic 50/s (~90%); autoplay 18 pictures/s. Picture ~430–570k Musashi cycles. | Relative bg2 motion forces transparent bg1 cells to be composed again. Prototype two phases: copy bg2 runs, then overlay cached bg1 runs, preserving priority. Compare against current per-cell composition. Batch sprite saves before any drawing, and investigate writer-driven cell keys instead of a full 336-cell check. Logic also needs margin. |
| Double Dragon | Hatari recorded play 8.2 pictures/s overall, often ~4; logic mostly 20–24/s. Logic ~193–217k Musashi cycles/frame; render ~578k, text ~190k. | Major redesign, not a scrolling tweak. First prototype cached screen-relative text strips/HUD composition (with all priority and transparency preserved), followed by clean sprite saves/restores versus background-cell invalidation. Full-rate logic itself exceeds the 8 MHz budget at the recorded instruction cost; translator/native work is also necessary. Only ~35 KB remains below the release load-size limit, so caches need memory tradeoffs. |
| Gauntlet | Hatari ~14–20 pictures/s; logic scheduled at 50/s (2026-10-26: logic at 60/s, comparisons only where the game's writers marked, light play 32.6 pictures/s; see the game's README). Scenario render medians 160–430k CPU+Blitter. Busy scene: panel/restores 83k, object rows 69k, shadow rows 63k, comparisons 54k. | Preserve the playfield torus and incremental strips. Measure panel copies/restores and object/shadow rows first. Prototype keeping panel runs when scroll and content permit, narrower shadow work using prepared row masks, and writer-driven tile/palette dirty marks. Check title fades separately; many objects rebake there. |
| R-Type | Hatari ~5.5–6.5 pictures/s, play logic ~16/s. Render 0.7–1.7M Musashi cycles, logic 92–125k ordinary / 150–176k heavy. | Large shared M72 composition and logic problem. Profile class runs, moving-layer contribution, sprite priority fallback, save/restore and palette reconversion separately. Prototype reducing composition to moving-layer contributing runs and removing the video-state byte-order copy. Heavy logic cannot sustain the arcade's ~55/s at the recorded Musashi cost even before drawing. |
| Splatterhouse | Hatari recorded stage-2 play ~6.29 pictures/s, logic 13.8/s. Stage-2 render ~1.04–1.07M after overlay improvements; earlier ordinary TILE_FLAG medians ~261k. | Existing lead-layer virtual scrolling already avoids copying that layer. Target independently scrolling overlays, sprite/overlay setup and priority rows; prototype prepared overlay-row runs and shared setup. Retain layer flicker phases in the benchmark: every-other-frame sampling can hide an expensive layer. Scene choice/rebuild tails also need work. |
| Mr. HELI | Shared M72 renderer, standalone reference-state harness; no integrated game runtime or end-to-end fps result established here. | Include in every M72 optimization comparison, especially its cave raster splits and FG/BG parallax. Harness CPU+Blitter timings cannot establish integrated 25 fps. |

Black Tiger's historical MAX_SKIPS experiment is not a current-build headline rate.
For 1943, the README's cloud row reports 8,591–8,742 pictures in 8,000 VBLs. That cannot
mean newly displayed pictures; even completed renders need to be distinguished from
presentation. Inspect field offsets, meanings and reporting before treating this as fps.

## Recommended order

1. Establish deadline traces and fix ambiguous counters across the benchmark tools.
2. Secure 1942's tail latency, Commando's small margin and Kung-Fu Master's wrap/floor dips.
3. Bring Gun.Smoke's heavier rounds and slides under budget with sound enabled.
4. Prototype 1943 front-layer persistence and Gauntlet panel/object/shadow improvements.
5. Give Black Tiger and Trojan explicit logic and renderer budgets before larger changes.
6. Treat Double Dragon, R-Type and Splatterhouse as substantial performance projects.
   Reaching steady 25 at the intended game pace is not supported by the present evidence.

These are hypotheses to prototype and measure, not promised savings. Increasing picture
skips can improve logic speed while reducing picture rate; it does not solve this target.
Adding buffers helps only if a trace shows time wasted waiting for a free buffer or VBL.

## Measurement and acceptance

Use the pinned Hatari at 8 MHz, STE, 4 MB, cycle-exact settings and normal sound enabled.
Run the same count/SYSTEM/P1 replay before and after, including dense scenes, camera wraps,
both scroll axes, palettes, layer enable changes and scene transitions. Keep canonical
fixtures and coverage scripts. Boot can be reported separately, with an explicit boundary.

Record per VBL: logic rounds completed, picture starts/completions/publications, newly
shown buffer ID, displayed-picture age, pending logic and late border events. A flip
counter alone must not count the same picture twice. Keep a compact interval histogram,
maximum, p95/p99 and worst gameplay windows. A 2-VBL presentation ceiling is the strict
25-fps criterion. Check logic rate/backlog alongside it so slower gameplay cannot pass.
Report render duration too: a 3-VBL render can occasionally be hidden by a queued picture,
but presentation intervals are what determine visible steadiness.

Use each port's existing perf_test.py, profile.py or render_test.py --prof to attribute
CPU plus Blitter bus cycles. Compare scrolling with stationary-camera states only when
the remaining state is held equal; separate incoming strips, damage restoration, text,
sprites, priority/parallax, palette/cache work and scheduling waits. Normal gameplay
replays must then confirm any fixed-state improvement. Inspect at least one complete
camera wrap in every ring and repeat with relevant memory placements/64 KB crossings.

Preserve renderer contracts: old damage restored including guards, aligned side clipping
with prepared end masks/one-word passes, transparent holes and priority, all 16 shifts,
64 KB crossings, consecutive independent-reference pictures, HOG passes <=256 bus cycles,
and zero late border events in pinned Hatari. Keep logic and picture rates separate.
Reordered-source sprite preparation has already been tried in these renderer families;
consult docs/sprite-preparation.md, prototype any new variation, and retain only measured
CPU+Blitter improvements. Do not assume it always wins (Kung-Fu Master and Gauntlet kept
natural row order). Respect the normal release load-size budget when adding caches.

## Source map and exclusions

Evidence: games/{1942,commando,1943,blktiger,gunsmoke,kungfum,trojan,ddragon,gauntlet,
rtype,splatter}/README.md. Implementation: each game's src/render.s; 1942's bg/chr/spr
modules; engine/rt/m72render.s for R-Type and Mr. HELI. Contracts and existing optimization
history: docs/architecture.md, docs/porting-guide.md, docs/sprite-preparation.md.

Static oversized buffers used for margins are not camera-scrolling implementations:
Donkey Kong, Galaga and Bubble Bobble are outside this review (Galaga was deferred at the time).
Galaga '88 uses fixed-width display buffers and software plots/composition for scrolling
layers, rather than the virtual-screen hardware-scroll path under review. Other folders
containing only board/reference work do not establish an STE scrolling implementation.

## Implementation results

Implemented and measured on 2026-10-19. All twelve implementations in the audit were
revised, including the shared renderer used by R-Type and Mr. HELI. This is an incremental
improvement; steady 25 fps across all ports has **not** been achieved.

### Native timing

Pinned F030Arcade Hatari `3eea7b07cb65b9819a6c3f135579a64255a03b76`, Windows UCRT64
binary SHA-256 `d423e5d011e1b75c7ea2f63a90791f3bf08cbfc7436b48519923e7fd1644bb77`.
8 MHz STE, 4 MB, TOS 2.06, cycle-exact and compatible enabled, DEBUG + AUTOPLAY,
6000 program VBLs, boot included. Audio enabled at 44100 Hz with SDL's dummy output;
the game sound code runs normally. Repeated runs with Hatari audio disabled produced
the same counters. Only this work's emulator PIDs were managed.

| Port | Drawn pictures/s before → after | Logic ticks/s before → after | Late border events |
|---|---:|---:|---:|
| Black Tiger | 26.175 → 29.465 | 54.992 → 57.922 | 0 in both |
| Kung-Fu Master | 30.212 → 30.445 | 48.609 → 48.825 | 0 in both |
| Gun.Smoke | 23.013 → 23.508 | 49.108 → 49.850 | 0 in both |

Raw `(VBLs, pictures, ticks)` counters: Black Tiger `(6000,3141,6599)` →
`(6002,3537,6953)`; Kung-Fu Master `(6001,3626,5834)` → `(6001,3654,5860)`;
Gun.Smoke `(6001,2762,5894)` → `(6000,2821,5982)`. Black Tiger compares
`BT_EAGER_TWINS=1` with the default lazy instance preparation, using the same final
shared dispatcher. The other two compare the original renderer/dispatcher with the
final implementation, using the same generated assets and translated logic.

These are averages of completed renders, not a maximum presentation-gap guarantee.
Black Tiger's minimum recorded 100-VBL window, including transitions, improved from
2 to 8 pictures/s. The target still fails in slow windows. Neither 50/60 Hz game pace
nor 25 pictures/s may be inferred from the other counter alone.

### CPU plus Blitter measurements

The measurements below use identical inputs before and after. Counts are Musashi CPU
cycles plus modeled Blitter bus cycles. They are not native fps. Each baseline uses
the old renderer and shared dispatcher with the same generated game logic/assets,
except Black Tiger's native timing isolation noted above. Some changes are small
enough that code placement and 64 KB fallback selection matter.

| Port | Scenario / unit | Before → final | Interpretation |
|---|---|---:|---|
| Black Tiger | `PERF_EVERY=3 perf_test.py 1600 1430`, mean per picture | 459,227 → 422,556 | 8.0% less; logic 69,148 cycles/tick in both |
| Commando | `perf_test.py 1600 900`, mean per picture | 175,092 → 174,645 | 0.26% less; logic 47,971 in both |
| 1942 | `perf_test.py 1600 0 1200`, mean total tick including drawing | 139,432 → 139,250 | 0.13% less; this row includes logic |
| 1943 | `perf_test.py 1700 1300`, mean per picture | 215,736 → 213,988 | 0.81% less; logic ~49.16k/tick in both |
| Gun.Smoke | `render_test.py 100 seq --first 1300 --seed 6`, median picture | 143,100 → 141,062 | 1.42% less in consecutive scrolling |
| Gun.Smoke | `render_test.py 20 scroll --first 1100 --seed 6`, median picture | 2,245,409 → 2,256,314 | 0.49% more on the artificial jump/fallback sweep; safety dispatch is more conservative |
| Kung-Fu Master | `render_test.py 2200 --start 1400 --seed 4`, mean picture | 171,358 → 170,574 | 0.46% less; logic 42,620 in both |
| Trojan | `render_test.py 2100 --first 1800 --seed 4`, last 100-frame window including logic | 359,228 → 359,170 | Essentially unchanged; the shared margin-fill setup is cheaper |
| Double Dragon | `render_test.py 1800 --first 1400 --seed 1`, mean picture | 364,323 → 364,122 | 0.06% less; not a solution to its logic bottleneck |
| Gauntlet | `render_test.py --frames 850 --first 780 --every 1`, mean picture | 189,349 → 189,125 | 0.12% less; the panel/shadow divider is also removed |
| R-Type | play states 900–1000, 101 consecutive pictures, median | 432,088 → 431,728 | 0.08% less |
| Mr. HELI | same shared-renderer test range, median | 699,494 → 695,812 | 0.53% less; renderer harness only |
| Splatterhouse | play states 900–1000, median | 538,142 → 538,250 | Essentially unchanged (+0.02%); simpler dispatch in copy/fill paths does not remove its composition cost |
| Splatterhouse | same range, `REN_VSW=0`, median | 527,242 → 527,212 | Essentially unchanged; exercises the explicit one-line bar-copy path |

The small rows should not be advertised as meaningful fps gains. In particular,
layer composition and translated logic remain the major work for the slower ports.

### Retained changes

* Black Tiger validates another physical instance when it enters the checked window,
  instead of eagerly preparing up to eight offscreen twins. Its per-cell keys still
  handle mode/page/colour changes. This transfers the useful duplicate-work lesson
  from `F030Arcade-private/games/blktiger/src/gfx.s`; it does not copy Falcon RGB565
  routines into the STE planar renderer.
* Known full-word copies/fills bypass general classification through `blit_go_copy`.
  No-source masked fills use `blit_go_fill`. Wide strip piece sizes use a table;
  the ordinary split loop avoids a subroutine round trip. These paths serve the
  incoming strips, margin clears, damage restores and bar-image copies where their
  contracts hold. Splatterhouse's 20/21-word bar copies use an explicit one-line
  piece, whose bus cost is bounded without a general dispatcher call.
* The generic dispatcher now budgets masked destination reads and extra FXSR fetches.
  The old code could issue 384-cycle HOG passes. Correctness/timing takes priority
  over the tiny regression on some artificial full-redraw sweeps.
* Kung-Fu Master's masked copies, Double Dragon's solid text fills, and Gauntlet's
  shifted copies look up their piece sizes. Kung-Fu Master's black bands use HOP 0,
  avoiding source fetches. M72's transfer fallback reuses its access-count table.
* M72 contribution maps rotate A and A xor B, then exchange the wrapped bits. Two
  rotations replace four long variable shifts, choosing the shorter rotation
  direction. Priority, layer contributions and transparent holes remain exact.

Primitive comparisons, including setup/return and bus transfers where applicable:
282 full-word copy cases **1,027,250 → 997,386** CPU+bus cycles; 744 no-source fill
cases **2,647,304 → 2,320,288**; 2048 bitmap rotations **647,592 → 567,592** CPU cycles.
These synthetic totals explain the local savings, not whole-game speed.

### Verification and rejected work

`engine/borders_blit_test.py` executes 2256 generic, 282 copy and 744 fill cases:
split and unsplit pixels match, hardware endpoints and CPU registers match, all
passes are HOG and no pass exceeds 256 bus cycles. `engine/m72_bitmap_test.py`
checks all 512 pixel offsets on random and extreme bitmaps, including preserved
registers. Both tests are registered in `port.py test engine`.

Picture checks passed: Black Tiger's scroll/flip/layout sweeps, 4096 edge sprite
draws and 400 random-walk frames; Commando's consecutive pictures and edge states;
1942's 100 consecutive pictures with clean margins and 56,952 sprite draws/restores
(33,857 clipped edge cases, including 15,000 at a 64 KB boundary); 1943's 1800 consecutive
logic/picture comparisons, 376 sprite-edge and 768 front-tile edge cases;
Gun.Smoke's consecutive scroll and jump sweeps plus 3600 edge cases;
Kung-Fu Master's 800 consecutive comparisons and 1122 edge/guard pictures;
Double Dragon's reference comparisons and 32 multi-object edge pictures;
Trojan's reference comparisons and 32 edge pictures; Gauntlet's reference
comparisons and 305 sprite/shadow/priority pictures; R-Type, Mr. HELI and
Splatterhouse's consecutive reference-state sequences. Dedicated edge checks cover
all 16 shifts, holes and 64 KB crossings. This is scenario coverage, not a full-game
or newly recorded canonical-replay claim. The private Double Dragon recorded play
was absent, so its optional explicit seed-1 edge scenario was used; the default
recorded-play contract remains unchanged.

The 1942 sprite restore check requires a normal `--sim` build without `--debug`.
DEBUG deliberately paints counters into ring 0 during the copy routine; both the
original and revised DEBUG builds fail the untouched-pixel check for that reason.
The normal build passes without changing the pixel oracle.

Black Tiger's consecutive scrolling run recorded 23,724 short HOG passes, longest
256, with no shared-bus passes. The shared M72 checks also recorded only HOG passes
of at most 256 cycles. Native late-event counters above verify actual timer timing
on the pinned emulator; the simulator does not model MFP interrupt timing.

A Kung-Fu Master front-cell stamp experiment reduced the tested busy-scene render
cost by ~2%, but Hatari's AUTOPLAY average regressed (30.21 → 29.99 pictures/s),
without improving the minimum window. It was removed, including its 4 KB stamp
array. The final build uses no such cache.

Fresh-build fixes needed for validation: bounded Windows sound-recording workers,
Gun.Smoke's sound-module import order, independent generation of Gauntlet's fixed
renderer map, explicit Double Dragon native continuation roots, and preserving
established 1942/1943 ROM-window guards when coverage is regenerated from fewer
scenarios. Canonical replay fixtures were not replaced. Generated programs,
compressed reference states, logs and temporary baseline sources remain in ignored
`build/` and `run/`; no private emulator build or ROM-derived output is committed.
