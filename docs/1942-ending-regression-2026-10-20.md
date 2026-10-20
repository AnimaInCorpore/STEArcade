# 1942 assisted ending and following game, 2026-10-20

**Passed:** ending reached, both further missing translations fixed, explicit
start/continue returned to stage byte 0 and progressed to 6. A fresh process
replayed all **51,176 inputs** with **426 exact RAM checkpoints**, identical
stage transitions and execution markers, and no guest crash or input mismatch.

The continuation of the retained assisted run found two more indirect task
entries missing after the `$70F2` fix:

| Task | Installer | Fatal dispatch index | Last successful tick |
|---|---|---|---:|
| `$6EEB` | `ld bc,$6EEB` at `$6CC8`, `rst $38` at `$6CCD` | `$0003ADB8` | 43,175 |
| `$6EDA` | `ld bc,$6EDA` at `$6CC2`, `rst $38` at `$6CC7` | `$000369B8` | 43,175 |

Both are high-score entry tasks. They are now explicit roots and join points in
`games/1942/tools/gen.py`, alongside `$70F2`. Adding them emits 24 additional Z80
instructions relative to the `$70F2`-only translation (15,469 total). Existing
unsupported instructions and missing direct targets are unchanged. The generator
regression removes all three task bodies from observed coverage and verifies
their callable labels and actual byte-swapped dispatch entries.

Small crash reports are retained beside this document. Full local discovery
folders, private programs, maps, compressed input/checkpoint streams and logs
remain under the adjacent Dreamer project's ignored `runs/` directory.

## Ending semantics

The ROM's ending does not automatically wrap into another campaign. `$70B4`
clears player lives and then jumps to `$6996`, the game-over/high-score path.
Execution markers reached both addresses at tick 43,146. The captured guest
framebuffer shows “WE GIVE UP!”, “SPECIAL BONUS 10,000,000 PTS”, and “GAME OVER”.
The continuation therefore allows game-over to finish, then supplies explicit
coin/start pulses with fire held for the following game/continue. A framebuffer
sample at the next stage-setup entry still shows the outgoing “CONTINUE GAME”
screen. This is an explicit start/continue after the ending, not evidence of an
automatic difficulty loop. Lives/invincibility are assisted;
finish requests resume during gameplay. Lives are not refilled while the ending
stage byte is 32, so the ROM can clear them normally.

## Method

`C:/Arbeit/dreamerv3/scripts/stearcade_1942_ending.py` builds from the retained
instrumented source with the current generated translation. It verifies source
program/Hatari/TOS hashes, relocates validated TEXT-relative cheat writes, records
every attempted input and cheat write, checks held input bytes every successful
tick, and stores full 4 KB RAM checkpoints every 120 ticks. New builds replay all
retained inputs and compare all available checkpoints before extending.

Diagnostic execution-marker breakpoints and framebuffer captures do not alter
game input. Sound is disabled and host keyboard/pad handling is bypassed. This
is assisted port replay verification, not independent arcade or renderer
equivalence, natural completion, or real STE timing evidence.

## Final evidence

| Event | Tick |
|---|---:|
| Stage byte 31 → 32 | 41,008 |
| Ending complete / game-over entry | 43,146 |
| Both high-score task failures passed | 43,176 |
| Post-ending stage setup, byte 0 | 43,798 |
| Following game: byte 0 → 1 | 44,822 |
| Following game: byte 5 → 6 | 50,485 |
| Last successful tick, discovery and fresh replay | 51,176 |

The transition stream also records temporary byte changes 32 → 0 → 32 at
43,760/43,762 before the explicit start. These are not counted as gameplay
progress; the stage-setup execution marker and later advancement establish that.

The successful continuation compared all 359 checkpoints retained through the
high-score failure, then recorded another 8,000 ticks. The final fresh replay
compared all 426 checkpoints. Decompressed timeline and checkpoint streams from
the successful continuation and final replay are byte-identical. All attempted
inputs and every explicit assist write are retained, including former failure
inputs. No crash report was produced by either successful run.

Fixed private program SHA256:
`8b41d667769679be93edd708c6063f9986028afc2617245489e4407a794ef1df`

Generated translation SHA256:
`d90d3e9cf5e92d06a6d75ddc15672a9232f253a94359e95e0224f801c9ee51e7`

Pinned Hatari SHA256:
`f113a3853fd993cac459cb672748f1c20c59ee4ac370501f49d5a6597cbf1796`

[Machine-readable results](1942-ending-regression-2026-10-20.json) include the
manifests, transitions, markers and stream hashes.
[Ending framebuffer](../games/1942/docs/ending-2026-10-20.png) is decoded directly
from guest framebuffer/palette memory, not a headless host screenshot.

Local evidence directories in `C:/Arbeit/dreamerv3/runs/`:

- `stearcade-1942-ending-discovery-2`: reproduced `$6EEB` failure.
- `stearcade-1942-ending-fixed`: reproduced companion `$6EDA` failure.
- `stearcade-1942-ending-fixed-2`: successful final build and continuation.
- `stearcade-1942-ending-verified`: successful full fresh-process replay.

The first `stearcade-1942-ending-discovery` attempt was interrupted at tick
15,144 without a guest crash report, after 126 matching checkpoints. Its cause
was not established; the rerun passed that point and all final evidence comes
from the later complete runs.

## Reproduce

Regenerate and test from `C:/Arbeit/STEArcade`:

```powershell
& C:/msys64/opt/dreamerv3-python/python.exe games/1942/tools/gen.py
& C:/msys64/opt/dreamerv3-python/python.exe -W ignore::ResourceWarning games/1942/tools/gen_test.py
```

From `C:/Arbeit/dreamerv3`, use a new output folder:

```powershell
& C:/msys64/opt/dreamerv3-python/python.exe scripts/stearcade_1942_ending.py runs/stearcade-1942-ending-fixed-2 runs/stearcade-1942-ending-reverify --extend 0
```

To extend that retained run further, set a positive `--extend` budget. Generated
binaries, compressed timelines and RAM checkpoints remain local in ignored
`runs/`; the original campaign and failing evidence folders are preserved.

Portable copies of the replay runners and their local prerequisites are now
retained under [tools/playtests](../tools/playtests/README.md).
