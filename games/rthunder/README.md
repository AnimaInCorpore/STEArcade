# Rolling Thunder (Namco System 86, 1986): reference board only

![Incomplete](../../docs/status/incomplete.svg)

**State (2026-11-07): there is no STE program.**  What exists and what is verified:

| Stage | Result |
|---|---|
| ROMs | `tools/prepare.py` verifies `rthunder.zip` (MAME `rthunder`, rev 3) against `docs/rom_manifest.json` and unpacks the 28 files |
| Reference board | `tools/machine.py` (`Rthunder`): two MC6809E, the HD63701 MCU with its real program, the CUS30 mailbox, the YM2151's status model, MAME's scheduler (1/48000 s quanta), the CUS42/43 tilemaps, the CUS39 sprites, the palette PROMs |
| Against MAME | `ref/mame_cmp_rthunder.py` (WolfMAME 0.248, `MAME=.../wolfmame-0248/mame.exe`): at ten frames from 300 to 6000 (attract mode) **0 differing pixels and 0 differing pens**; with `--logic` the board's tile RAM, CUS30 RAM, shared RAM and sprite RAM equal MAME's at the same frames except the stack area `$57E0-$57FF` (stale pushes of interrupts: the two CPUs' interrupt timing differs by a few cycles from MAME 0.248's) |
| Coverage | `ref/cover.py` records what the translator needs (`--port`: on the port schedule); no coverage set was completed: the port schedule stops (below) |
| Translation | `tools/gen.py` is an untested draft; no runtime (`src/`), assets, renderer or sound exist |

Not done: translation, STE runtime, renderer, colour fit, sound, registration in `port.py` and `tools/release.py`.
Nothing here has run in Hatari.

## Findings that cost time

* **Tile ROMs**: `init_namco86` shuffles the nibbles of the plane-1,2 ROM into two planes and inverts the third (mono)
  plane before `gfx_8x8x3_planar` applies; decoding the ROMs as thirds gives noise.  `Rthunder.gfx()`.
* **Palette**: the 0.286 source computes `double` resistor weights; the 0.248 binary behaves as if they were rounded
  to integers (14, 31, 67, 143): 398 of 4096 pens are one level off.  `Rthunder.palette(int_weights=True)` equals the
  binary; the default is the source (AGENTS.md: the source wins).
* **Registers**: the tile banks, scroll registers (priority in bits 9-11 of the X scroll) and the back colour are
  write-only; the compare tool takes them from `engine/mame_frames.lua`'s taps (frames before the first tap installed
  have no state: compare from frame 300).
* **Sprite RAM** is buffered by the chip at a write to offset `$7F2` (copied at the vertical blank, `copy_sprites`).

## Port schedule: the open problem

The two 6809 run concurrently on the board and the programs depend on it.  They synchronise through counters in the
shared RAM (`$5606/$5607` of cpu1 = `$1606/$1607` of cpu2 and others: `$D2`, ...): cpu1 clears `$06`, works ~40 cycles,
sets it to 1 and spins until `$07 = 1`; cpu2 spins until `$06 = 0`, clears `$07`, spins until `$06 = 1`, works and sets
`$07`; more than 200 code sites use some variant.  Their IRQ handlers dispatch through per-state tables (`$02/$03`) and
sub-step counters (`$04/$05`) that both CPUs advance in lock step.

`RthunderPort` (`tools/machine.py`) runs them one after the other, cooperatively (a CPU runs until it is idle, writes
a semaphore byte or a spin wait goes round again; spin sites and semaphore bytes are learned: `ref/cover.py --port`
prints them).  This follows the game for **1972 frames (cpu1 first) or 2168 (cpu2 first) of attract mode, then
deadlocks**: the programs also assume the board's *timing* (cpu1's sub-step completion advances cpu2's counter on the
assumption that cpu2 dispatched its own step thousands of cycles earlier; cpu2 samples cpu1's flag `$18` ~100 cycles
into its IRQ, long before cpu1 changes it), and whichever CPU runs first breaks one of the two kinds.  Tried 2026-11-07: a cycle-counted interleave (`RthunderCycles`: the CPUs alternate in slices of N 6809 cycles, IRQs
at the idle points, no semaphore or spin yields): N = 32 follows 366 frames then runs over budget (cpu1 in `$A668`);
N = 256 and 1024 fail in the first frame (cpu2 spins at `$858F`, cpu1 already idle).  Worse than the cooperative
schedule, and it would need cycle counting in the translator; not a way forward as it stands.  Tried 2026-11-07 (second attempt): the MAME-schedule trace of a frame shows the cross-CPU traffic is tiny (frames
401-403: only `$1606/$1607` with `$1600`, `$1632`; frames 2363-2370: the `$16D2` pair, the data at `$1000-$101F` that cpu1 writes
before it releases `$D2`, plus `$1632`), i.e. semaphore protocols, which the yield-at-semaphore-write schedule follows.  The
deadlock of `RthunderPort` (port frame 2168) is cpu1 at `$9036` waiting for `$07` while cpu2 has gone idle in the handler
at `$8569` (`CLR <$07` ... RTS without the `INC <$07` of the normal path): the port's game state had left MAME's before (at the
same MAME frame 2369 MAME still runs the `$D2` handshake).  Port and MAME agree on `$1600-$16FF` apart from timing-loop
temporaries (`$160E/F`, `$1612/13`, `$1624`, `$1626/27`) for 232 frames; the divergence is elsewhere and not found.
`RthunderOverrun` (a blocked CPU stays in its handler into the next frame, as MAME's overruns) does not help: from frame
~2170 on cpu1 is blocked every frame (3832 of 6000 frames), i.e. the game is hung, not slowed.  **Working schedule (2026-11-08): `RthunderRule`.**  A search with rollback (one deep copy of the board a frame, trying
ORDER (1, 0), then (0, 1)) needed exactly one flip in 12000 attract frames, at port frame 2168 (`$1604 = 1`, `$1605 = 0`:
cpu1 has counted a sub-step cpu2 has not taken).  The rule `cpu1 first iff $1604 != $1605, else cpu2 first` then runs
8000 frames on the reference board for seeds 0 (attract), 1 and 2 (`ref/cover.py` random play).  The play seeds first failed
at frames 871 / 1055 (cpu2 in the loop at `$8928`): its spin wait writes the watchdog (`$8000`) every pass, which the
spin learner counted as progress; writes at `$8000` and above no longer count.  What this shows and does not: the board
neither deadlocks nor hangs in those runs (no check yet that the play seeds reach and stay in the game, nor that the RAM
is right: the port's state is not MAME's, the idle-loop counters are the games' random numbers).  One flip and a rule from
one data point is thin evidence for other scenes; seeds 3-9 and 11-19 are not run.  The translation, runtime, renderer, sound
and Hatari are still not done.  Earlier note, kept: not tried: taking the IRQs
mid-foreground as the board does; a lock-step comparison of the *whole* RAM of port and MAME to find the first real
divergence (needs a per-frame normalisation of idle-loop counters).  Idle points found: cpu1 `$81BC` (the main loop's
BRA, queues `$56B3/$56B4`, `$566E/$566F` equal), cpu2 `$80A6` (`$1667/$1668` equal).

## Tools

    python games/rthunder/tools/prepare.py                     # verify and unpack the ROMs
    MAME=.../wolfmame-0248/mame.exe python games/rthunder/ref/mame_cmp_rthunder.py [--logic] [frame ...]
    python games/rthunder/ref/cover.py SEED FRAMES [--port]    # coverage (the port schedule stops at about 2000 frames)

Memory map, interrupts and the video chips are in the docstring of `tools/machine.py` (MAME 0.286 source:
`src/mame/namco/namcos86.cpp`, `namcos86_v.cpp`, `namco_cus4xtmap.cpp`, `namcos1_sprite.cpp`).
