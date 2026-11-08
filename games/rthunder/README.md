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

### 2026-11-08: coverage and translation

`ref/cover.py SEED 6000 --port` (now `RthunderRule`) for seeds 0-5 ran to the end (distinct pcs: cpu1 1964-3363, cpu2 4094-4570).
The spin sites and the `$16D2` semaphore they found are constants in `machine.py` (`SPIN`, `SEMO`); seeds 0, 1, 5 re-ran 4000
frames with them.  `tools/gen.py` translates the main program (4689 instructions) and the sub program (6411) with none
unsupported; the main program's `TST` / `INC` of the CUS30 mailbox needed `engine/m6809x.py` to read-modify-write I/O
sites (TST; INC/DEC when V is dead): `m6809x_test.py` passes but does not cover this path.  NOT done: the spin-hook stubs,
dispatch tables and `src/core.s`, so nothing of the translation has run; no lock-step, no renderer, no sound, no Hatari.

### 2026-11-08: the runtime and the lock-step test

`src/core.s` (contexts, the schedule of `RthunderRule` as 68000 code: both IRQs first, the CPU with `$1604 != $1605` first, a CPU
gives way at a semaphore store (`<cpu>_sem_yield`), a taken spin branch (`hooks_<cpu>.s`) and at its idle point; the dispatcher; the
I/O: the CUS30 mailbox, the bank selects, the scroll / tile bank / back colour registers in `hwregs`), `src/rthunder.s` (the sim
build only), `tools/build.py` and `tools/logic_test.py` (the translated programs on Musashi against `RthunderRule`, frame by frame:
both tile RAMs, the shared RAM with the sprite RAM, the CUS30 RAM, `hwregs`, the sprite latch, both CPUs' registers and bank pages;
the CC bytes the IRQs push are left out; `--steplock F` compares the registers at every translated instruction of frame F,
`--watch` adds shared RAM offsets).  **3000 frames identical for seeds 0 (attract mode) to 5 (random play), 58.8k-81.1k 68000
cycles a frame for the two CPUs (Musashi, translation only; a 50 Hz STE frame is 160k).**  Not verified: seeds 6-9 and 11-19,
runs past 3000 frames, the PCM writes (`$6000-$63FF`, ignored), a picture, Hatari.  Two bugs the test found: main's stores to the
mailbox were missing from the coverage's I/O sites (`ref/cover.py` recorded reads only), and the vertical blank's sprite buffer copy
(machine.py `vblank_begin`) is the harness' job.  Still missing for a program on the STE: the vertical blank's sprite copy, the
renderer (hardware scroll from the start), the palette fit, input, sound, `port.py` / `tools/release.py` registration.

### 2026-11-08: the renderer's first steps (NOT playable: no STE program, no Hatari run)

* `tools/palfit.py`: one fixed 16-colour STE palette for the whole game (the PROM palette is fixed: 154 of its 512 indirect
  colours occur in frames of seeds 0-5; 60-73 colours a picture), fitted with `engine/palette_quantize.py` to frames of those seeds
  (`build/rthunder/shots_1.png`: left the reference, right the fit).  A per-scene palette would look better; not done.
* `tools/stemodel.py`: the picture as the renderer composes it (painter's order: priority 0-7, per priority the scrolling layers
  3..0, then the sprites with that priority k, the lowest entry first): 0 pixels differ from the reference's per-pixel priority
  rule on sampled frames of seeds 1, 2 and 4 (every 10th frame of 600-1500).
* Layout facts from the traces: the three scrolling layers (CUS42 layers 0 and 1, CUS43 layer 0) get the same scroll (their
  values differ by exactly the layers' dx offsets: no parallax), only horizontal in the frames seen (y constant); layer 3 is a
  fixed front layer (priority 7: the HUD and texts), tile aligned on the screen.  So the design is a tile-aligned virtual screen
  `ren_bg` (512 x 256) holding the three layers composed, a window of it on the screen, the fixed layer and the sprites drawn
  over it.
* `src/render.s`, step 1: `tile_get` (a direct mapped cache of tiles in STE planar form: opaque mask + 4 planes a line, made from
  the 3 bit pens and the colour row's map on first use), `ren_setup` (layer order, back colour), `ren_cell`, `ren_bg_all`.
  `tools/render_test.py`: 0 pixels differ from the reference's layers on 4 pictures (seed 1).  Cost: a full recomposition is
  9.8M 68000 cycles with a warm tile cache (4.8k a cell; a cold cache 15-28M): the renderer must work incrementally (changed
  cells, the column scrolling in), which needs the tile writers' marks (`ref/cover.py` now records which tile RAM layer each
  store site writes: `tilew`; gen.py does not use it yet).
* Not started: the window onto the screen (Blitter copy with skew, later hardware scroll with twin columns, as `docs/speed.md`
  asks), the fixed layer, sprites (HOP 2 / OP 3 passes, prepared per code and colour row), the STE program (loader, VBL, borders,
  IKBD input, palette, the arcade-frame schedule with MAX_BEHIND), sound (the YM2151 and the 63701X PCM), `port.py` / release
  registration, Hatari measurements, `sprite_test`.

### 2026-11-08: what stands between the reference and an STE program (analysis, nothing run on the STE)

* **The MCU is the hidden big item.**  The HD63701 (internal `cus60-60a1.mcu` + the external `rt3_4.6b` at $4000-$BFFF) is the
  CPUs' mailbox: the main CPU reads the inputs, coins and the sound engine's states from CUS30 RAM ($4182-$4185, $4189-$418E,
  $41A5, $423D-$4281, $4380) and writes commands ($4183, $418C/D, $4286-$4294, $4380); in the reference `run_others` runs the real
  firmware, ~25k MCU cycles a frame.  Without it the STE program has no inputs and no coin handling.  Options: (a) translate
  the firmware to 68000 code (engine/m6801x.py is the 6801 translator of Bubble Bobble's MCU; the 63701's extra instructions
  and its sound engine's timers would have to be added; cost unmeasured, probably tens of thousands of 68000 cycles a frame),
  (b) a native model of the mailbox protocol checked against the firmware (what Splatterhouse's `mcu.s` does for its CUS64),
  with the sound commands recorded at build time.  Neither is started.
* **Sprites over the scrolling layers** are drawn after all three of them (the renderer's order, `stemodel.py --bgfirst`); the
  arcade lets sprites with a low priority go under the foreground layer: 52-427 pixels of a picture differ from the reference
  on sampled frames of seeds 1, 2 and 4 (worst 427).  The exact painter's order (`stemodel.py` without --bgfirst) has 0.
* **Sprite plan**: parts (code, sub-rectangle, flips, colour row) converted on first use to rows of an opaque mask and four
  plane longs (left justified), drawn as one HOP 2 / OP 3 Blitter pass a row (3 destination words, the end masks the opaque
  mask shifted, Y count 4 for the four planes, skew = the shift), no AND + OR pass.
