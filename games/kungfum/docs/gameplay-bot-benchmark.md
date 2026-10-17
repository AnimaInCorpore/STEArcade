# Kung-Fu Master gameplay-policy benchmark

Historical Kev experiment, retired after the PPO rollout. Its optional engine/scripts and downloaded weights
were removed to recover SSD space. These measurements describe the implementation at the time of the test.


Kev-0.6B now generates compatible offline replay inputs. Across three local seeds it produced more accumulated
scroll progress (107.7 versus 57.0 pixels on average), with five deaths versus four, at 17.6x the generation cost.
All runs stayed on floor 1. Keep search as the default; Kev is an optional additional input generator.
[Machine-readable results](gameplay-bot-results.json).

Measured on 2026-10-17 on this project's Apple M1 Mac with 8 GB unified memory, macOS 27.0.1.
The normal emulator/test environment is Python 3.14.8; the optional Kev worker uses Python 3.13.16,
PyTorch 2.8.0, Transformers 5.20.1 and PEFT 0.21.2. Inference uses MPS, fp16 and SDPA;
no Neural Engine or MLX backend is used for this Qwen3 checkpoint.

## Method

The existing search bot and Kev propose inputs to the same `engine/playbot.py` recorder. Each decision is
12 arcade frames. Both use the existing coin at frame 700, start at 760, infinite lives from frame 900,
death rewinds and stall rewinds. Kev replaces only the segment proposal: it samples from the model's probabilities
over the 21 unique direction/attack combinations already present in the baseline. Non-play transitions use the
baseline sampler. There is no extra invulnerability, infinite energy, stage skip, or game-specific fine-tuning.

Kev observes the current reference RAM and decoded sprite geometry: floor/exit direction, energy, the player
sprite and up to five nearby other sprite entries. Sprite types are not visually classified. The model cannot
see future states; only the shared rewind search can retry. Model inference pauses the reference machine.
The sampled controls are recorded by arcade tick, so replay speed does not depend on inference latency.

Each policy/seed runs in a fresh process; policy order alternates by seed. Timing includes all generation
attempts and rewinds. Model loading and warmup are recorded separately; the total generation time includes both.
Downloads were already cached for the paired runs. Each finished recording is then evaluated in a fresh reference
machine without inference or rewinds. Those accepted-frame metrics, rather than best discarded attempts, are
used for comparison. Evaluation time is excluded from generation time.

The benchmark covers seeds 1, 2 and 3 for 3,600 recorded frames each, including startup. This is an initial
bounded test, not a full-game evaluation or a statistical claim about all seeds. The original search policy's
recorded bytes were also compared against the unmodified recorder for 1,800 frames, seed 1: identical.

## Historical provenance

The model is `jaredpalmer/kev-0.6b`, adapter revision
`dece6dba8d43f0f7ded45e9f5b9df12474d90843`, on `Qwen/Qwen3-0.6B-Base` revision
`da87bfb608c14b7cf20ba1ce41287e8de496c0cd`. Kev runtime commit:
`1f04cfa28e6a708485b28a9585010b9e436b776e`. The worker applies the adapter and its trained pointer head;
it does not substitute a plain Qwen language model. The downloaded weight cache has since been removed.

Artifacts live in `build/kungfum/bots/benchmark/`: `results.json`, individual `.json` reports,
count/SYSTEM/P1 `.bin` recordings, model decision traces and logs. Reports record checkpoint hashes, source
hashes (read when each report is written), package versions, replay hashes and a hash of the final reference state. The raw generated recordings
are not committed. Existing `build/kungfum/play_inputs.bin` and the normal simulator build remain untouched.

Progress is the sum of positive within-floor scroll steps smaller than 64 pixels, only during accepted play
frames. It is a coverage/progress proxy, not net distance or score. A stall is 180 consecutive play frames without
such progress; maximum stall length is also reported. Gameplay PC coverage counts executed reference Z80
addresses in play. Sprite shape coverage is limited to the five nearest visible non-player sprite entries used
by the observation; it is not complete graphics coverage. Deaths can still occur with infinite lives.

Worker peak RSS and maximum post-call MPS driver allocations are reported separately. They share unified memory and must
not be added as independent allocations. The driver is sampled after calls, so it need not capture every transient
allocation; these are not a system-wide peak-memory measurement. Generation wall
time measures the local recording tool, not STE game-logic speed or picture rate.

## Replay verification

`tools/play_replay_test.py RECORDING` builds an isolated `SIM=1, PLAYBACK=1` executable with the requested
recording first on its asset include path. It compares every logic frame with the reference and checks the
renderer through the reference colour mapping (every 12th picture by default, every picture with `--every 1`).
The existing replay encoding and the normal test defaults are retained. No model is needed for verification.

All six benchmark recordings passed every one of their 3,600 logic frames and all 300 sampled pictures per recording: 21,600 logic frames and 1,800 pictures in total, with no differences.

A separate 1,800-frame Kev smoke recording passed all 1,800 logic frames and all 1,800 consecutive pictures.
The baseline smoke recording passed 1,800 logic frames and 150 sampled pictures. Lightweight contract tests
also cover deterministic baseline compatibility, every legal model action and invalid segment rejection.

## Results

| Policy | Seed | Accepted progress (pixels) | Deaths | 180-frame stalls | Gameplay PCs | Generation (s) |
|---|---:|---:|---:|---:|---:|---:|
| search | 1 | 88 | 1 | 4 | 2124 | 17.16 |
| kev | 1 | 130 | 0 | 2 | 2318 | 225.58 |
| search | 2 | 55 | 1 | 5 | 2121 | 19.06 |
| kev | 2 | 89 | 3 | 4 | 2127 | 422.33 |
| search | 3 | 28 | 2 | 4 | 2130 | 19.61 |
| kev | 3 | 104 | 2 | 5 | 2102 | 336.99 |

All six recordings stayed on floor 1. These are 3,600-frame recordings including startup; the accepted
play-frame count varies because a death temporarily leaves the play state.

| Aggregate | Search | Kev-0.6B |
|---|---:|---:|
| Mean accepted progress | 57.0 | 107.7 |
| Total deaths | 4 | 5 |
| Mean gameplay PCs per run | 2125.0 | 2182.3 |
| Mean generation seconds | 18.61 | 328.30 |

| Kev seed | Model calls (includes discarded attempts) | Median warm call (ms) | p95 warm call (ms) | Cached load (s) | Worker peak RSS (MiB) | Maximum post-call MPS driver allocation (MiB) |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 379 | 491.4 | 561.4 | 10.38 | 1063.9 | 1425.9 |
| 2 | 626 | 529.4 | 745.0 | 11.61 | 1049.9 | 1431.9 |
| 3 | 487 | 545.6 | 717.2 | 11.21 | 1073.8 | 1425.9 |

Kev produced more accumulated forward-scroll progress in all three seeds, but generation cost **17.6x** as
much wall time on average. Survival did not improve consistently: five accepted deaths versus four. Code coverage
was higher in seed 1, nearly equal in seed 2, and lower in seed 3. This does not establish better general gameplay,
net distance, stage completion, or broad new coverage. It also does not distinguish useful state reasoning from
an advantageous action prior; a matched-prior random or scripted control would be a further ablation.

Keep the existing search bot as the cheap default and use Kev as an optional source of different recorded paths.
The model completed these workloads within this 8 GB Mac's memory capacity, but the roughly half-second calls
are suited to paused offline recording. They are not evidence of a real-time control loop at arcade frame rate.
The original smoke test's first weight download/load took 96.6 seconds; paired-run loads above used cached files.
Wall times are local observations; desktop load and thermals were not controlled.
