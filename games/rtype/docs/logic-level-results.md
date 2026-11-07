# Higher-level logic audit, 2026-11-04

Status: dated report (2026-11-04); measured experiments, not integrated. Current figures: [the
README](../README.md#speed).

**No 2x logic speedup demonstrated.** Three executed algorithmic experiments
together save **2.13%** of logic cycles over the stage-3 warship replay and
**3.47%** in the stage-7 sample: about **1.022x / 1.036x**, against the requested
2x. This is evidence about these implementations and workloads, not a proof
that a different native gameplay engine could never reach 2x.

Production code, scheduler, renderer, installed program and canonical replay
fixtures are unchanged. The experiments are isolated in
`tools/logic_level_audit.py`; the existing untracked `hot_native_audit.py` was
not edited or used as the production baseline.

## Higher-level profiles

The profiler measures complete linked-object handler invocations, including
their dispatch and callees, rather than treating each translated instruction
as an independent optimization opportunity. These semantic profiles cover 120
consecutive frames at seed-10 checkpoints 22000 and 65000. They are narrower
than the 600-frame comparisons below.

| Sample / handler (V30 IP) | Inclusive share of all logic | Translated code within the path | Native/runtime callees |
|---|---:|---:|---:|
| Stage 3, E2AA | 17.77% | 5.56% | 12.20% |
| Stage 3, C7C3 | 16.72% | 9.37% | 7.35% |
| Stage 7, 5E8E | 37.35% | 10.08% | 27.26% |

Deleting all translated instructions in stage 7's busiest handler while
retaining its existing native primitives would therefore save at most 10.08%
of sampled logic. That unrealistic zero-cost replacement would yield only
1.112x. Deleting the entire handler, including gameplay work, would save 37.35%
and yield 1.596x. The two busiest stage-3 handlers together occupy 34.48%; even
making them completely free yields 1.526x. These are conditional bounds for
those selected paths, not bounds on a whole-engine rewrite.

Stage 7 makes 1,896 movement-script calls in its 120-frame profile, all to ROM
segment 1000h with two motion commands per call. Existing empty-shot handling
already batches idle slots (`nat_objloop`). Further object dispatch fusion
and simple collision bounding-box schemes were measured in earlier audits;
they do not supply the missing half of logic time.

## Executed algorithms

1. **More exact shared collision summary.** Keep the original unsigned player
   box edges instead of ordering them into conservative spans. Form an enemy's
   x/y and offset extents once, then use the arcade's exact branch conditions
   against each distinct box. This removes the widened-query path and avoids
   some unnecessary full scans. The summary can still contain owner-dependent
   boxes that are ineligible for a particular query, so a potential hit always
   returns to the original ordered collision code. Hit effects, object order,
   summary rebuilding after a hit and no-hit register/stack reconstruction
   remain active.
2. **Compile pairs of movement commands.** At build time, derive an immutable
   eight-byte transition for every start offset of ROM segment 1000h: the final
   byte's address, cumulative x/y changes, last animation change, resulting AL
   and a validity flag. The native query performs one transition for two motion
   commands, including intervening animation bytes. Segment-end commands,
   source wrapping, other step counts and other segments execute the original
   interpreter. The final original continuation preserves return flags and
   register values. The table costs **524,288 bytes** of additional program
   data. There is no runtime compilation or mutable cache. Build-time table
   generation and executable loading are outside the per-tick measurements;
   all native lookup, guards and fallbacks are included.
3. **Hoist query construction out of collision scans.** Compute the enemy's
   coordinates and extents once for the whole 24- or three-target scan, then
   test targets in arcade order with those values. Run the final original box
   test to reproduce AW/flags and retain the correct remaining count and stack
   residue. The focused 24-target cases save 28.5% locally; the three-target
   cases become 49.5% more expensive because setup dominates. These deliberately
   adversarial cases are not gameplay-weighted speed estimates. The combined
   prototype below includes both scans; it is not recommended for integration
   as-is.

Initial component comparisons, same 120-frame windows and matching production
oracles, measure reductions in total logic cycles:

| Component | Stage 3 / 22000 | Stage 7 / 65000 |
|---|---:|---:|
| Exact collision summary | 1.64% | 0.80% |
| Compiled motion pairs | 0.00% | 2.46% |
| Hoisted collision scans | 1.48% | 0.004% |

These are separate component measurements, not an attribution of the longer
combined run's saving. They show why large local reductions need not produce
a large game-wide improvement.

## Controlled combined results

CPU cycles per logic tick, instruction-stepped in Musashi, including native
guards, dispatch, summary preparation and first-use terrain-cache work. No
renderer or Blitter work is charged as logic. Each pair starts from the same
compressed checkpoint with the same count/SYSTEM/P1 input sequence. Separate
processes avoid `machine68k`'s shared emulator state.

| Window | Frames | Production cycles/tick | Combined cycles/tick | Reduction |
|---|---:|---:|---:|---:|
| Stage 3 warship, seed 1 / 12600 | 1800 | 91,314 | 89,371 | **2.13%** |
| Stage 1, seed 10 / 3000 | 600 | 97,195 | 96,752 | 0.46% |
| Stage 2, seed 10 / 11000 | 600 | 66,707 | 66,102 | 0.91% |
| Stage 3, seed 10 / 22000 | 600 | 126,505 | 122,426 | **3.22%** |
| Stage 4, seed 10 / 33000 | 600 | 67,032 | 66,441 | 0.88% |
| Stage 5, seed 10 / 46500 | 600 | 94,827 | 93,075 | 1.85% |
| Stage 6, seed 10 / 56000 | 600 | 59,778 | 59,453 | 0.54% |
| Stage 7, seed 10 / 65000 | 600 | 116,300 | 112,266 | **3.47%** |
| Stage 8, seed 10 / 74000 | 600 | 61,959 | 61,027 | 1.51% |

All **6,600 production/prototype frames match** work RAM (including stack and
fade records), video RAM, palettes, sprite slots and captured object lists,
normalized context, scroll/control ports, sound ring and dirty marks. Existing
idle-point dead-flag normalization is retained. Native scratch registers and
private summary/cache data are not game state. The seed-10 checkpoints are the
existing baseline-derived fixtures. The warship checkpoint was freshly built
by advancing the independent reference from boot; its subsequent A/B run is not
an independent paired reference run of all 1,800 frames.

Focused execution compares **1,152 cases** against production: 512 ordered
24/three-target scans, 256 ordinary and 256 tougher-enemy collision queries,
and 128 movement-script cases. Cases cover empty/first/last active targets,
zero/reversed edges, unsigned overflow boundaries, hits and misses, ROM ends,
animation and segment-end commands, count and segment fallbacks. They compare
RAM including stack residues, V30 registers and segment pointers, all four
arithmetic CCR flags, and host-stack balance.

A further independent reference run from boot passed **1,800 paired frames**
in seed-10 windows 3000–3599, 11000–11599 and 22000–22599 under the existing
`--snap --list` contract. That contract excludes the approved palette/fade and
stack-page differences and allows the initial object-list warmup. The broader
requested sweep was stopped during reference-only advancement after frame
30000, with no mismatch reported: the measured candidates had already missed
the 2x objective and were not being integrated. It did **not** complete the
later-stage independent reference windows. The 6,600-frame full-state A/B
comparison and focused checks above have their own, separate scope.

No new Hatari throughput, border-timing, sound or complete-playthrough claim
is made. The renderer receives identical inputs in the paired frames, so this
logic-only experiment does not require a new sprite layout or rendering pass.

## Reproduction

Use the repository venv, prepared stage assets and the existing compressed
`build/rtype/native_audit/seed10_frame*.pkl.gz` fixtures.
The tool pins `natives.s` and `core.s` to `982f885`, preserving this earlier
experiment after the later structural changes were integrated.

```sh
venv/bin/python games/rtype/tools/logic_level_audit.py --profile --frames 120
venv/bin/python games/rtype/tools/logic_level_audit.py --variant all --frames 600 \
  --starts 3000,11000,22000,33000,46500,56000,65000,74000
# Separate components: create a matching --variant base --benchmark oracle,
# then --benchmark --variant exact, script, or scan, with identical frame ranges.
venv/bin/python games/rtype/tools/logic_level_audit.py --capture --seed 1 --starts 12600
venv/bin/python games/rtype/tools/logic_level_audit.py --variant all --seed 1 \
  --starts 12600 --frames 1800
venv/bin/python games/rtype/tools/logic_level_audit.py --focused --variant base
venv/bin/python games/rtype/tools/logic_level_audit.py --focused --variant all
venv/bin/python games/rtype/tools/logic_level_audit.py --reference --variant all \
  --seed 10 --frames 22600 --windows 3000-3599,11000-11599,22000-22599
# Optional broader independent sweep (not completed in this audit):
# --frames 74600 --windows \
# 3000-3599,11000-11599,22000-22599,33000-33599,46500-47099,56000-56599,65000-65599,74000-74599
```

Compact results and compressed profiles/checkpoints are under
`build/rtype/logic_level_audit/`; logs are `build/rtype/logic_level_*.log`.
Private generated programs/source directories are temporary. The tool does not
regenerate the installed program or edit canonical input recordings.
