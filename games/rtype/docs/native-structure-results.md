# Retained native structural changes, 2026-11-04

**Measured improvements retained in `src/natives.s` and `src/core.s`.** The
selected changes reduce logic cycles by 1.06–2.97% across the eight existing
stage windows and by 1.77% over the complete 1,800-frame warship window. These
are additional changes against production commit `982f885`, with the earlier
higher-level experiments disabled. This is not a 2x speedup.

The installed stage program is rebuilt: `run/rtype/RTYPE.PRG`, 6,055,376 bytes
(+1,909 bytes). There is no additional runtime table/cache or BSS allocation.
The renderer, gameplay inputs, frame scheduler, sounds and sprite preparation
are unchanged.

## Retained changes and 68000-specific choices

* **Specialize one-entry sprite emission.** `EMIT1_BODY` emits its known
  eight-byte record directly and clears the one possible padding slot for a
  wide sprite. It avoids the generic variable-length tail loop, pointer spill
  to the host stack, and subsequent reconstruction of that pointer. The object
  address is formed once for x/y reads. The general emitter remains for builds
  without `SPRITE_LIST`; overflow, AW, pointer, slot data and V30 stack residues
  retain their old behavior. General indexed byte addressing is retained for
  the colour rather than adding a new BP-parity assumption.
* **Reuse collision-query endpoints.** On the common no-hit exit with a cached
  last active player object, construct AW from the x/y endpoints already in
  registers. Do not reload the enemy position/extents and rerun `nat_box` just
  to recover that return value. Owner-dependent last-box selection retains the
  old path because its register values have already been reused. Actual hits,
  collision order and full fallbacks are unchanged.
* **Keep derived tile-scroll fields close to the lookup code.** The existing
  writable cache words move into the text section after a returning routine;
  reads use PC-relative addressing. On the STE the program is writable ST RAM.
  Cache initialization/invalidation and the exact FG/BG calculations remain
  active. This shortens accesses without creating a second cache or assuming
  scroll values stay constant throughout a logic tick.
* **Use ADD/ADDX for the inline 24-bit position updates.** The bullet and
  decorative-object handlers store fractional and integer bytes in separated
  locations. Add the fractional byte, retain the X carry through byte loads
  and `EXT.W`, then `ADDX.W` the signed integer part. This avoids packing and
  unpacking the value with two long shifts. AW is overwritten before use in
  these handlers; the general position natives that must retain AW are left
  unchanged. Both x/y bullet updates and the decorative handler's shared
  macro call are covered.
* **Use the prepared word targets for changed fade rows too.** The existing
  `fade_tab` already holds correct native-endian colour words. On a changed
  ROM-target row, compare/copy pairs as longwords, count differing words
  exactly, and preserve the final channel difference in AW. Non-ROM targets
  keep the original byte path. Rows already at their target retain the old
  fast path. No extra table or preparation pass is needed.
* **Use flags already established by data operations.** `MOVEQ #0,D1` supplies
  exactly the N/Z/V/C state required at the tougher-enemy collision return;
  the following `CMP.B D0,D0` is removed. The movement script tests its count
  before the final `OR.B`, allowing that logical operation to supply the
  result flags without a restoring `TST.B`. These changes preserve X too.
  `MOVEA` and `MOVEM` are treated separately because they do not set these
  flags. Byte/word widths and intervening flag-writing operations matter.
* **Remove per-record DMA loop control.** One indexed dispatch enters a bounded
  sequence of longword copies. The fixed 64-byte slots are unrolled. The old
  general loop remains for larger counts, and the decision whether to capture
  a DMA is unchanged. Captured records still remain independent of later
  emitter writes; no DMA is skipped based on a predicted future picture.

The instruction semantics used here are specified in Motorola's
[M68000 Family Programmer's Reference Manual](https://www.nxp.com/docs/en/reference-manual/M68000PRM.pdf)
(ADDX, MOVE/MOVEQ, EXT and MOVEM). In particular, MOVE/EXT preserve X, so moving
data between the fractional ADD and integer ADDX does not lose that carry.
Cycle results below come from executed 68000 programs, not estimates from
instruction counts or timings of a later 68k CPU.

## Algorithms and variants measured separately

Each component below runs 120 frames at the same two seed-10 checkpoints.
Values are reductions in **total logic cycles**, not local routine speedups.
They are not an additive attribution of the longer combined run.

| Component | Stage 3 / 22000 | Stage 7 / 65000 |
|---|---:|---:|
| One-entry emitter | 0.463% | 0.640% |
| Collision return-value reuse | 0.000% | 0.256% |
| PC-relative tile fields | 0.360% | 0.552% |
| Inline ADDX position updates | 0.425% | 0.200% |
| Paired changed-fade path | −0.004% | 0.000% |
| Reused MOVE/logical flags | 0.046% | 0.052% |
| Unrolled DMA copy | 0.530% | 0.569% |

The fade change has little work in these two steady windows; the focused fade
cases improve 21.3%, and it is included in the eight-stage combined results.
Focused emitter cases improve 5.1%, FG/BG lookups 3.3%, bullet paths 5.6% and
decorative paths 8.9%. These mixed boundary cases are not gameplay-weighted
performance estimates.

Two proposals are **not retained**:

* Removing collision-summary deduplication makes its build simpler but repeats
  more query work: total logic becomes 1.86% / 4.01% slower in stages 3/7.
* Sharing an object address across FG/BG lookups and bypassing clamped row
  arithmetic is neutral/slower (+0.020% / +0.028%). The extra address setup
  cancels the shorter field accesses. It is excluded from the retained set.

## Fixed-workload logic results

Instruction-stepped Musashi CPU cycles per tick, including all native guards,
summary/cache preparation and fallbacks. Rendering and Blitter work are separate.
Baseline and candidate run in separate processes from the same compressed
checkpoints, with identical count/SYSTEM/P1 inputs.

| Window | Frames | Before | Retained | Reduction |
|---|---:|---:|---:|---:|
| Stage 1, seed 10 / 3000 | 600 | 97,195 | 94,313 | 2.97% |
| Stage 2, seed 10 / 11000 | 600 | 66,707 | 66,001 | 1.06% |
| Stage 3, seed 10 / 22000 | 600 | 126,505 | 124,279 | 1.76% |
| Stage 4, seed 10 / 33000 | 600 | 67,032 | 65,903 | 1.68% |
| Stage 5, seed 10 / 46500 | 600 | 94,827 | 93,062 | 1.86% |
| Stage 6, seed 10 / 56000 | 600 | 59,778 | 59,032 | 1.25% |
| Stage 7, seed 10 / 65000 | 600 | 116,300 | 113,787 | 2.16% |
| Stage 8, seed 10 / 74000 | 600 | 61,959 | 61,212 | 1.21% |
| Warship, seed 1 / 12600 | 1800 | 91,314 | 89,698 | 1.77% |

All **6,600 paired frames match** work RAM including fades and stack, video
RAM, palettes, sprite slots and captured object records, normalized idle
context, ports, sound commands and dirty marks. Native scratch/cache data and
dead idle flags are not game state. The seed-10 checkpoints are the existing
baseline-derived fixtures; the warship fixture comes from the independent
reference. These are bounded windows, not a new continuous full playthrough.

Focused differential execution passes **2,176 cases**: 1,152 existing collision
and script cases plus 1,024 emitter, tile-lookup, inline position and fade cases.
The latter cover slot overflow and wide padding, separated SS/DS0, fractional
carry/borrow and signed-speed extremes, clamped/wrapped coordinates, cache keys,
changed/unchanged colour words and non-ROM fade fallback. Memory, V30 registers,
segments and host-stack balance are checked. Four arithmetic flags are compared
where live; emitter/fade flags and decorative continuation flags are dead by
their existing contracts (the continuation starts with CMP or MOVE).

Fresh independent reference runs from boot pass **9,000 seed-4 frames** and
**1,800 paired warship frames** at seed 1 / 12600–14399. They use the established
`--snap --list` contract, including approved palette/fade/stack exclusions and
initial object-list warmup. They do not independently recheck every later stage.
The whole-state A/B and focused checks have their separate scope above.

The non-SIM DMA regression passes **72 cases** under both deadline and cadence
schedulers, including retained tails, fixed slots, register/stack preservation
and writes to the emitter slots after capture.

## Hatari

Local pinned Hatari path used by the existing benchmark tools, STE 14 MB,
TOS 2.06 DE, compatible/cycle-exact CPU, sound off, fast-forward. Both programs
use the same private checkpoint/input replay, production renderer, corrected
DMA capture and short Blitter passes. Rates are from emulated 50 Hz VBLs.

| Window | Logic ticks/s, before → retained | Pictures/s, before → retained |
|---|---:|---:|
| Warship, 1801 ticks | 22.136 → 22.279 (+0.64%) | 17.232 → 17.355 (+0.72%) |
| Stage 7 / 65000, 601 ticks | 22.560 → 22.904 (+1.52%) | 18.093 → 18.064 (−0.16%) |

All four runs have one startup border fallback and **zero late top, palette,
bottom or off events**, with no crash. Dynamic scheduling chooses a different
picture workload after logic changes. The fixed-tick simulator comparison
establishes the logic saving; these short replays do not demonstrate a steady
25 pictures/s or full-speed gameplay.

## Reproduction and retained evidence

`tools/native_structure_audit.py` pins the pre-change natives/core to commit
`982f885` and builds all variants privately. It does not patch production or
replay fixtures. Its `best` variant reproduces the retained instruction changes.

```sh
venv/bin/python games/rtype/tools/native_structure_audit.py --variant best --frames 600 \
  --starts 3000,11000,22000,33000,46500,56000,65000,74000
venv/bin/python games/rtype/tools/native_structure_audit.py --variant best --seed 1 --starts 12600 --frames 1800
venv/bin/python games/rtype/tools/native_structure_audit.py --focused --variant base
venv/bin/python games/rtype/tools/native_structure_audit.py --focused --variant best
venv/bin/python games/rtype/tools/native_structure_audit.py --extra --variant base
venv/bin/python games/rtype/tools/native_structure_audit.py --extra --variant best
venv/bin/python games/rtype/tools/native_structure_audit.py --reference --variant best --seed 4 --frames 9000
venv/bin/python games/rtype/tools/native_structure_audit.py --reference --variant best --seed 1 \
  --frames 14400 --windows 12600-14399
venv/bin/python games/rtype/tools/native_structure_audit.py --hatari --seed 10 --starts 65000 --frames 600
venv/bin/python games/rtype/tools/native_structure_audit.py --hatari --seed 1 --starts 12600 --frames 1800
```

`--series quick120` keeps component oracles separate from 600-frame runs.
After creating its matching baseline oracle with `--benchmark --variant base`,
use `--benchmark --variant emit|return_aw|append|tiles|pc_tiles|posadd|fade_pairs|move_flags|dma`.
Summaries, source hashes, compressed profiles and checkpoints remain in
`build/rtype/native_structure_audit/`; logs are `build/rtype/native_structure_*.log`.
Private generated programs are removed. The higher-level audit
(`tools/logic_level_audit.py`) and `tools/hot_native_audit.py` are separate tools.
