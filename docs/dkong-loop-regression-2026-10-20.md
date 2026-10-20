# Donkey Kong assisted board and difficulty-loop regression, 2026-10-20

**Passed:** all four board types cleared with assistance; the ROM advanced into
the following difficulty levels and wrapped its repeating sequence into level 6.
A fresh Hatari process replayed all **38,200 inputs** with **318 exact 3 KB RAM
checkpoints**, identical progression and no crash or input mismatch.

The retained 22,200-tick assisted run selected stage types by writing `$6227`.
This continuation instead uses the ROM's completion logic and board sequence:
it refills lives, places Mario at the exit for barrels/conveyors/elevators, and
removes the rivets for the rivet board. It does not write stage, difficulty,
board-table pointer, or game-phase state during the extension.

## Progression observed

| Event | Tick |
|---|---:|
| Original retained inputs complete, all 185 checkpoints match | 22,200 |
| Difficulty 1 → 2 after rivets | 23,490 |
| Difficulty 2 → 3 after rivets | 25,861 |
| Difficulty 3 barrels active | 26,309 |
| Difficulty 3 conveyors active | 26,934 |
| Difficulty 3 elevators active | 27,561 |
| Difficulty 3 rivets active | 28,194 |
| Difficulty 3 → 4 after all four board types | 28,859 |
| Difficulty 4 barrels active | 29,307 |
| Difficulty 4 → 5 | 32,482 |
| Difficulty 5 → 6, repeating sequence wraps | 36,727 |
| Difficulty 6 barrels active | 37,175 |
| Last successful tick | 38,200 |

The game starts with the shorter US board sequences. Difficulty 3 is the first
containing all four types. At difficulty 5 → 6, the ROM itself wraps `$622A/B`
from `$3A78` to `$3A73` and increments `$6229`; this establishes the repeating
board-sequence loop, rather than merely selecting a stage or writing a level.
Guest framebuffer captures show the corresponding boards and `L=06`.

No port crash, missing translation, or input mismatch occurred in the successful
discovery. No game/runtime/translation change was needed for this progression.

## Assistance and method

The extension supplied neutral held SYSTEM/P1 inputs. Every input and assist
write is recorded. Allowed extension writes are:

- `$6228 = 6`: refill lives.
- `$6203 = $80`, `$6205 = $20`: move Mario to the completion region on board
  types 1–3. The ROM checks Y against `$31` or `$51` in `$1E57-$1E7D`.
- `$6290 = 0`, `$6292-$6299 = 0`: clear the rivet count and flags on type 4.
  The ROM checks the remaining count at `$1E80`.

After 120 active ticks per board, the assist satisfies those conditions. The ROM
then enters its normal board-clear animation (`$600A = $16`), advances the board
pointer via `$178E` or `$193D`, and increments difficulty at `$1954` after rivets.
The completion helpers never directly invoke those routines or change their
dispatch phase. These are assisted clears, not a natural playthrough.

The private harness preserves the retained instrumented source and pins the
original executable, Hatari and TOS hashes. It checks held input bytes every tick
and samples the full 3 KB `$6000-$6BFF` RAM window every 120 ticks. It records
stage type `$6227`, difficulty `$6229`, and pointer `$622A/B` transitions.

Donkey Kong's idle-loop counters are timing-sensitive: an initial harness probe
added framebuffer captures during the original replay and differed at the first
RAM checkpoint despite a byte-identical private PRG. That attempt stopped at
tick 120 with no guest crash. Moving added captures to tick 22,200 onward restored
all 185 original matches. The successful discovery and final replay use the same
per-board capture schedule (`capture_start = 22200`), so diagnostic activity is
part of their replay conditions. Input timelines remain gameplay inputs and
explicit assist writes; manifests and the runner define diagnostic scheduling.

This is native Hatari assisted-progression verification. Sound is disabled,
host keyboard/pad input is bypassed, and independent logic/render equivalence,
real STE performance and natural full-game playability are not established.
The port remains yellow, **Verification pending**, under the README's legend.

## Retained evidence and reproduction

The original discovery and successful extension use the same private program:

`891c50a0c0ef5f4f4d63f426b581d4c37d3c3cbb10f8f7e87579c0e1bee92b4f`

Pinned Hatari SHA256:
`f113a3853fd993cac459cb672748f1c20c59ee4ac370501f49d5a6597cbf1796`

Generated translation SHA256:
`3ac3d0d5d4bb196fe348a20c7f958888326f8069663de8f8cd3ba1ed2b13790f`

The original 22,200 ticks were followed by 16,000 new assisted ticks. A fresh
process replayed the complete stream through tick 38,200, matching every saved
checkpoint through 38,160. The decompressed input and RAM-checkpoint files are
byte-identical, as are all 22 per-board framebuffer and palette captures.
An audit of extension commands confirms only the allowed assist locations above
were written, with neutral held inputs throughout. Neither stage `$6227`,
difficulty `$6229`, pointer `$622A/B` nor phase `$600A` was directly written.

[Machine-readable results](dkong-loop-regression-2026-10-20.json) retain the
manifests, transition stream, assists and input/checkpoint hashes.
[Level 6 framebuffer](../games/dkong/docs/loop-level6-2026-10-20.png) shows the
next loop in gameplay.

Local evidence in `C:/Arbeit/dreamerv3/runs/`:

- `stearcade-dkong-assisted`: preserved original discovery.
- `stearcade-dkong-loop-discovery-2`: successful assisted continuation.
- `stearcade-dkong-loop-verified`: successful complete fresh-process replay.
- `stearcade-dkong-loop-discovery`: initial diagnostic-schedule mismatch at
  tick 120, retained separately; not a port crash.

Reproduce from `C:/Arbeit/dreamerv3`, using a new output folder:

```powershell
& C:/msys64/opt/dreamerv3-python/python.exe scripts/stearcade_dkong_loop.py runs/stearcade-dkong-loop-discovery-2 runs/stearcade-dkong-loop-reverify --extend 0
```

The runner checks the pinned original program, Hatari and TOS identities before
replay. Canonical port sources and recordings were not replaced. Compressed
inputs/checkpoints and private builds remain in ignored local `runs/` folders.

Portable copies of the replay runners and their local prerequisites are now
retained under [tools/playtests](../tools/playtests/README.md).
