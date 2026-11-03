# Later-stage native experiments, 2026-11-03

**Small logic gains, essentially unchanged picture rates.** Against the production
code with the earlier native/cache fixes already enabled, the combined prototype
saves 0.49–2.54% of logic cycles in the six stage-3–8 windows. Pinned Hatari improves
logic throughput by 1.66% in the stage-7 replay and 2.58% in stage 8; picture rates
change by −0.57% and −0.23%. This does not provide a large further speedup.

Production natives, generator, generated translation and installed executable are
unchanged. All new replacements remain isolated experiments. The renderer and
scheduler are unchanged, and the earlier window-refresh prototype is disabled.

## Profiles and candidates

Profiles cover 600 consecutive logic frames at each of the eight existing seed-10
checkpoints. In later stages, 45–59% of cycles are already attributed to native
routines, with additional time in the runtime. The largest individual native
costs include the collision broad phase (up to 12.5%), sprite emission (8.0%), BG
tile lookup (7.7%), movement scripts (6.2%) and collision-summary preparation
(6.7%). The remaining translated work is spread across handlers, calls, returns,
map writes and the linked-object loop.

Five candidates were implemented and measured:

* **Movement-script leaf:** finish the common last-step increment and return in
  native code instead of going through translated F5EA–F5F0 and IP dispatch.
  Animation bytes retain their semantics. Segment transitions and the zero-count
  case retain the original translation, with the native return address discarded
  on fallback. Registers, return flags, emulated stack residues and host SP are
  checked. Maximum sampled logic saving: **1.17%**, stage 5.
* **Tile runs and BG patches:** guarded native replacements for EC6D's contiguous
  tile run and C44A's 7 × 6 patch. Write cells as longwords and mark each affected
  64-byte block rather than marking each word store. Nonstandard segments,
  counts, source wrapping, destination wrapping or alignment use the original
  loops. Maximum sampled logic saving: **1.76%**, stage 8.
* **Breakable FG cells:** combine 2736's coordinate/segment saves, native FG lookup,
  four tile tests, updates and restores. Preserve the original registers, counter,
  return flags and all stack residues. Maximum sampled logic saving: **0.81%**,
  stage 6.
* **Individual collision-box native/leaf:** reuse the existing native box test's
  operation for F578 calls. Its contribution is small and sometimes negative:
  **−0.04% to +0.14%** of sampled logic time. Not recommended for integration.
* **Linked-object dispatch:** fuse the 026A return/link traversal and the next
  indirect call, and fold the handler address load into one indexed MOVEA.
  Its savings range from −0.005% to +0.072%, with some regressions. It is not
  included in the combined prototype and is not recommended for integration.

The combined prototype contains the first four candidates. Its SIM stage program
grows from 6,060,500 to 6,062,192 bytes (**+1,692 bytes**). There is no new runtime
preparation table or startup pass. Dispatch, guards, fallbacks and first-use
terrain-cache work are included in the cycle measurements. These are CPU writes
to emulated tile RAM; no STE graphics or Blitter pass changes are involved.

## Controlled CPU results

Each row measures 600 frames with identical inputs from the same compressed
checkpoint, instruction by instruction. These are **logic cycles**, excluding
rendering. Every compared frame must match work RAM (including fades and stack),
video RAM, palettes, sprite/object buffers, normalized context, ports, sound
commands and dirty marks. Dirty marks are cleared before every tick.

| Window start | Production cycles/tick | Combined cycles/tick | Saving |
|---:|---:|---:|---:|
| 3000, stage 1 control | 97,195 | 96,994 | 0.21% |
| 11000, stage 2 control | 66,707 | 66,612 | 0.14% |
| 22000, stage 3 | 126,505 | 125,887 | 0.49% |
| 33000, stage 4 | 67,032 | 66,397 | 0.95% |
| 46500, stage 5 | 94,827 | 92,675 | 2.27% |
| 56000, stage 6 | 59,778 | 58,782 | 1.67% |
| 65000, stage 7 | 116,300 | 113,976 | 2.00% |
| 74000, stage 8 | 61,959 | 60,387 | 2.54% |

All **4,800 combined-comparison frames match**. Each component also has a separate
4,800-frame comparison, so gains are measured independently rather than assigned
to whichever replacement happened to be enabled last.

| Later-stage window | Script | Tile writes | FG helper | Box |
|---|---:|---:|---:|---:|
| Stage 3 | 0.00% | 0.05% | 0.29% | 0.14% |
| Stage 4 | 0.29% | 0.10% | 0.57% | −0.02% |
| Stage 5 | 1.17% | 0.65% | 0.49% | −0.04% |
| Stage 6 | 0.00% | 0.85% | 0.81% | 0.00% |
| Stage 7 | 0.89% | 0.79% | 0.34% | −0.01% |
| Stage 8 | 0.12% | 1.76% | 0.56% | 0.09% |

## Exactness

The checkpoints come from translated baseline logic; the comparisons above are
not independent reference evidence. Workers run in separate processes because
`machine68k` shares emulator state between instances.

A fresh independent reference run advances from boot to tick 74,600 and passes
**3,600 paired frames**: 600 in each stage-3–8 window listed above. Between
windows only the reference advances; the simulator is reloaded at each window's
start. This uses the established `--snap --list` contract: existing fade/palette
and stack-page exclusions apply, and the first two object-list warmup checks in
each window are skipped. Other comparisons remain active. The full-state A/B
comparisons and focused tests additionally check the port's fade buffers and
stack residues. This is bounded later-stage coverage, not continuous native
execution of all 74,600 frames or ending coverage.

Focused differential tests cover **416 cases**: 256 unsigned collision-box cases
(including overflow boundaries and reversed edges), 64 terrain/counter/scroll
cases, 64 movement-script cases, 16 tile runs and 16 BG patches. They compare
memory, dirty marks, registers, segment pointers and stack residues; collision,
script and terrain tests additionally compare all four CCR flags. Each case
asserts the host stack is balanced. A separate source-level flag analysis stops
at RET, follows calls and checks the native continuations independently of the
translator's caller-conservative liveness: five fallback/continuation entries
read no incoming flags, and all 50 direct leaf callers need no parity/auxiliary
flag result. A carry-reading conditional branch is the positive control. Scripts cover zero/255 counts, animation
bytes and segment ends; tile cases cover guarded fallbacks, low-byte destination
wrapping and source wrapping.

An ordinary 48-cell tile run costs 12,958 → 1,444 CPU cycles in the focused test;
the 7 × 6 patch costs 12,826 → 4,666. These are local routine costs, not game
speedup factors. The unchanged renderer receives identical picture inputs in
all baseline/prototype comparison frames.

## Pinned Hatari

Same pinned Hatari, STE 14 MB, TOS 2.06 DE, compatible/cycle-exact CPU and sound
off as the earlier experiment. Each build executes 601 logic ticks from the same
private production-derived checkpoint, with the seed-10 replay's original
count/SYSTEM/P1 input contract. The checkpoint is serialized in the normal
snapshot layout, with host pointers reduced to SP and V30 register/segment
values; it is not described as an independent arcade snapshot. INVULN is enabled
on both sides, as in the source checkpoint. Startup and the normal scheduler
(PIC_VBLS=3) are included.

| Replay | Logic ticks/s, production → combined | Pictures/s, production → combined |
|---|---:|---:|
| Stage 7, 65000–65600 | 40.940 → 41.620 | 21.730 → 21.607 |
| Stage 8, 74000–74600 | 36.031 → 36.962 | 24.041 → 23.985 |

Stage 7 uses 734 → 722 VBLs and produces 319 → 312 pictures. Stage 8 uses
834 → 813 VBLs and produces 401 → 390 pictures. Dropped ticks decrease
44 → 40 and 94 → 83 respectively. Both builds in both runs report one startup
border fallback and zero late top/palette/bottom/off events. Dynamic scheduling
changes the rendered workload: the fixed-tick CPU results establish the actual
logic saving, while picture rate remains effectively unchanged. These short
replays do not establish whole-game steady rates.

## Reproduction and artifacts

```sh
# Current production versus the combined prototype; eight 600-frame windows.
venv/bin/python games/rtype/tools/later_native_audit.py --frames 600
# Each component, against the same saved production oracle.
venv/bin/python games/rtype/tools/later_native_audit.py --benchmark --variant script --frames 600
# Other variants: box, tiles, terrain, dispatch.
venv/bin/python games/rtype/tools/later_native_audit.py --flags
venv/bin/python games/rtype/tools/later_native_audit.py --check --variant base
venv/bin/python games/rtype/tools/later_native_audit.py --check --variant combined
# Independent reference advances from boot; only the named windows are paired.
venv/bin/python games/rtype/tools/later_native_audit.py --reference --frames 74600 \
  --windows 22000-22599,33000-33599,46500-47099,56000-56599,65000-65599,74000-74599
venv/bin/python games/rtype/tools/native_hatari.py --later --seed 10 --start 65000 \
  --frames 600 --checkpoint build/rtype/native_audit/seed10_frame65000.pkl.gz
# Repeat hardware check with --start 74000 and its matching checkpoint.
```

Source: `tools/later_native_audit.py`, `later_native_tiles.s` and
`later_native_terrain.s`. `logic_test.py --windows` runs the independent reference
between inclusive ranges, reloads the simulator at each range start, resets the
object-list warmup and reports the actual paired-frame count. Its ordinary
60-frame mode and a two-window 200-frame run also pass.

Compact comparison summaries, compressed full profiles, focused results and checkpoint links live
under `build/rtype/later_native_audit/`; logs are
`build/rtype/later_native_*.log`. Hardware counters are in
`run/rtype_native_later_{65000,74000}_{base,combined}/`. Temporary emulator
programs are removed after verification.

Production native source SHA-256:
`b9cf78378d9014a3d9c50e42703520ee56450979b0b74a77535e811fc3a055b8`.
Production generator SHA-256:
`626314bb8aecd46a4989ce54a4c9d2cb4fa3f8c63764aaa9fb06b2103614a0cc`.
Production generated main code SHA-256:
`59416aa7ee6d95a98132735ecbeca046270b9ef165286d0cd80c7041098224ba`.
