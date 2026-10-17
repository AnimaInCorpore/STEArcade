# PPO RAM exploration in MAME and native Hatari replay

The controller trains in native MAME and produces the existing frame-indexed count/SYSTEM/P1 replay format.
The Hatari audit compares completed arcade frames with both native MAME and the independent port reference.
Normal rendering remains enabled; audit file I/O means the run is not a speed benchmark.

## Method

Measured on the project's 8 GB Apple M1 Mac, macOS 27.0.1, on 2026-10-17. The optional worker uses Python 3.13.16,
Torch 2.8.0, Stable-Baselines3 2.9.0 and Gymnasium 1.2.3 on CPU. MAME is 0.289; Hatari is the project's pinned
2.6.1-devel build. Checkpoint, executable, TOS, replay and source hashes are recorded with the artifacts.

PPO uses two consecutive normalised RAM observations: E000-E8FF plus C000-C0FF sprite shadow and scroll bytes.
Actor and critic each have two 64-unit hidden layers. Each decision spans 12 arcade frames. The 21 direction/button
combinations and two-on/two-off attack pulses match the existing bots' legal controls. Episodes last 3,600 frames,
including 900 boot/coin/start frames. Infinite lives, DIP switches and startup inputs retain the existing playback
contract. Energy is finite. There are no stage skips or search rewinds.

The primary reward is newly executed main-ROM instruction addresses, measured in MAME with one-shot debugger
breakpoints at every byte address 0000-7FFF. Boot/attract coverage before frame 900 is excluded. New addresses
receive 0.1 reward globally and 0.002 episodically; positive within-floor scroll steps under 64 pixels receive
0.02 per pixel, first entry to a floor receives 2, deaths cost 0.25 and decisions cost 0.01. Global coverage persists
across training resets; episodic coverage resets. Coverage is not in the policy's observation. There is no claim
of branch, data-access or complete game coverage.

The baseline samples uniformly from the same actions, also without rewinds. Exported policy runs sample the
trained action distribution with seeds 1, 2 and 3. They start from fresh MAME processes. These are bounded
same-game evaluations, not held-out games or proof of generalisation. Progress is accumulated positive scroll,
not net distance, score or stage completion. Native MAME coverage counts the whole post-boot interval, including
transitions; it is not directly comparable to the earlier Kev report's gameplay-only reference PC metric.

## Replay and diagnosis

The `.bin` file has no new headers or model dependency. Adjacent MAME `.states.jsonl` files contain boundary
RAM/sprite/scroll snapshots, PC, cumulative deaths and newly visited PCs every 12 frames starting at frame 900.
The Hatari tool assembles a private PLAYBACK/REPLAY_AUDIT executable. The instrumentation captures the same
arcade-frame indices at the completed-frame idle hook, rather than on a wall clock or display VBL. It writes
RAM D000-EFFF, sprite RAM C000-C0FF, scroll, hook PC and LFSR state in buffered diagnostic packets. The audit
requires exactly the expected checkpoint sequence and a completion marker; partial captures fail.

Native MAME and the port intentionally differ in CPU scheduling and refresh-register randomness. In addition,
MAME's checkpoints include the infinite-lives poke for the next frame; Hatari captures before that poke. The first
checkpoint is before the first learned action, so differences already present there are not caused by the policy.
The report retains those differences rather than calling them translation bugs. The separate comparison against
`KungFuPort` uses the port's actual schedule/RNG and the same precise dead-stack exclusions as the existing logic
test. Any mismatch in that comparison fails. Crashes and timeouts also fail. The first difference is the earliest
**sampled checkpoint**, not necessarily the first divergent instruction or frame.

The optional native smoke test repeats two MAME runs with identical controls and requires identical snapshots
and coverage. Contract tests check replay byte round-trips, all legal actions and observation boundaries. The
existing `play_replay_test.py` remains the check for every simulator logic frame and reference-rendered pictures.
Setup and commands are in the [game README](../README.md#ppo-ram-policy-trained-in-mame).

## Local results

The 665,750-parameter policy completed **4,096 PPO decisions** (49,152 controlled arcade frames, plus boot
frames on resets) in **397.0 seconds**. Its saved checkpoint, including optimiser state, is about 8.1 MB.
Training reached **2,643** distinct post-boot instruction addresses. Addresses **1671** (`ld a,$80`) and **1673**
(`jr z,$1677`) were absent from the existing coverage pickles; static discovery had already translated them.
This is additional dynamic coverage from the training campaign, not evidence of missing translated code or an
advantage over an equal-budget random campaign. These two addresses did not appear in the short exported tests.

| Recorder | Seed | Post-boot instruction addresses | Accumulated progress (pixels) | Life decrements | Floors |
|---|---:|---:|---:|---:|---|
| random | 1 | 2626 | 47 | 3 | 1 |
| random | 2 | 2596 | 49 | 3 | 1 |
| random | 3 | 2593 | 57 | 2 | 1 |
| ppo | 1 | 2637 | 45 | 4 | 1 |
| ppo | 2 | 2600 | 67 | 4 | 1 |
| ppo | 3 | 2621 | 26 | 4 | 1 |

PPO averaged **2,619.3** addresses versus **2,605.0** for uniform actions, a **0.55%** increase in these three
runs. The combined sets contain 2,641 versus 2,639 addresses: PPO additionally reached 14B8 and 14B9; the
uniform baseline had no exclusive addresses. Mean accumulated progress was **46 versus 51 pixels**, and total
life decrements were **12 versus 8**. Every run stayed on floor 1. This bounded training run shows a small
coverage gain, not strong gameplay, stage completion, a statistical result, or a replacement for the existing
scripted coverage and search recordings. Counts include post-boot transitions and life initialisation writes,
not only visible player deaths.

All three policy recordings completed **native Hatari** replay. Each passed **226** RAM/sprite/scroll/RNG
checkpoints against the port reference: **678 checkpoints, zero differences**. All three differ from native MAME
at the first sampled checkpoint, **frame 900**, before the first PPO action. The first raw differences include
E010-E017, timer/state bytes, stack bytes and the lives poke. They are retained in the reports and are not
classified as translation failures. There were no unexplained Hatari-vs-port-reference divergences in these runs.
The one-shot coverage bridge also passed the two-process MAME repeatability smoke check.

The existing replay harness passed **10,800 logic frames** across the three policy recordings, including RAM,
sprite RAM, scroll, sound commands and tile dirty marks. Seed 1 also passed **300 sampled pictures** against
the independent renderer. The new optional contracts and the existing bot contracts pass. The production build
with instrumentation disabled is **byte-identical** to the existing normal executable; canonical replay,
simulator PRG/map, normal PRG and existing coverage files were preserved.

[Machine-readable measurements and hashes](ppo-coverage-results.json). The actual checkpoint is
`build/kungfum/ppo/policy.zip`; recordings are `ppo_1.bin` through `ppo_3.bin`, with adjacent MAME snapshots.
Each `ppo_N_hatari/` contains `AUDIT.BIN`, the private program/map and `divergences.json`. Weights, raw memory
captures and recordings stay in ignored build output; no ROM assets are added to this report. Recorded generation
and training wall times were observed with other validation work running; desktop load and thermals were not
controlled. Audit timings include diagnostic I/O and must not be used as normal game-speed measurements.
