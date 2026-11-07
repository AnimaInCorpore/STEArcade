# Mr. HELI no Daibouken (Irem, 1987) on the Atari STE

STE port of the MAME set `mrheli` (Irem M72, `irem/m72.cpp`). The main CPU's NEC V30 program is translated R-Type's
way (`engine/v30x.py`; [R-Type's README](../rtype/README.md)) and is exact against the reference board in lock-step to
40000 frames; the i8751 MCU runs as a native model (`src/mcu.s`); the Z80 sound CPU and the PIC do not run, so there is
no sound. The picture is the shared M72 renderer (`engine/rt/m72render.s`, R-Type's legacy renderer: the centred
320-pixel window, the top panel as its own screen, scene colours), the exact baseline. **Rule violation, to be
converted:** that renderer draws FG over BG with AND + OR Blitter passes (a BG copy, the FG opaque plane ANDed out,
the FG planes ORed in), which AGENTS.md forbids; R-Type's stage renderer, the planned replacement, has none. Status:
Experimental / deferred (logic exact, about 2 pictures a second; R-Type's stage renderer and natives next); not
registered in `port.py`, not released. Latest speed (2026-11-07, Hatari 14 MB, `-D DEBUG`): attract 28.8 arcade
frames a second (52% of the arcade's 55.02 Hz; 58% of the port's 50), 1.9 pictures a second; invulnerable play 22.5
(41%; 45%), 2.0 pictures a second.

## Build and run

```sh
venv/bin/python games/mrheli/tools/prepare.py        # checks mrheli.zip (docs/rom_manifest.json), unpacks it
venv/bin/python games/mrheli/ref/cover.py --port SEED FRAMES   # coverage on the port's schedule (Translation)
venv/bin/python games/mrheli/tools/build.py          # run/mrheli/MRHELI.PRG (--sim: the Musashi test build; -D NAME=V)
venv/bin/python games/mrheli/tools/logic_test.py FRAMES --seed N   # lock-step against the reference (Tests and tools)
venv/bin/python games/mrheli/tools/mcu_test.py --seed N   # the MCU model against the real i8751
venv/bin/python games/mrheli/tools/render_test.py    # R-Type's render_test.py --game mrheli (sprite_test.py likewise)
games/mrheli/tools/bench.sh [hatari items ...]       # its own Hatari (14 MB, stopped by its PID), COUNTERS.BIN
```

ROM: the MAME set `mrheli` (`assets/roms/mrheli.zip`, unpacked to `assets/roms/extracted/mrheli/`; build.py runs
prepare.py when it is missing). Older archives lack the i8751 program `mh_c-pr-.ic1` (4 KB, crc32 897dc4ee): put it
as `assets/roms/mh_c-pr-.ic1` (prepare.py's docstring). The port is not registered in `port.py` (no
`tools/hatari.sh`, no release): run it with `bench.sh`. A crash writes CRASH.TXT. Paths are relative to this folder;
`engine/`, `tools/`, `port.py` and `docs/` at the top are the repository's.

## Controls

Arrows, space / Control fire, Alternate button 2, 1 / 2 start, 5 / 6 coin, Esc quits; joystick 1 (player 1), joystick
0 (player 2), the Jaguar pads. A coin and a start reach the game (`bench.sh tap:06@32 tap:02@35`: the screenshot shows
the helicopter in the hangar under the top panel; not checked against the reference pixel by pixel).

## State

* Logic exact (2026-11-02 / 11-07): lock-step identical for seeds 1, 4, 5 (0-20000 frames) and the invulnerable seeds
  8, 9, 10 (0-40000), the MCU's protection check included (Lessons, 2026-11-05).
* MCU exact: `tools/mcu_test.py` 0 differing V30 reads of the dual-port RAM on four runs (attract with the ROM test,
  play, invulnerable play, the watchdog), every sample command and its DAC bytes equal; `tools/mcu68k_test.py` 0
  differences on those traces and on 30000-frame synthetic traces.
* The STE program (2026-11-07) runs the attract mode and 2000 frames of invulnerable play in Hatari without a crash.
* The renderer still uses AND + OR passes (forbidden; to be converted with R-Type's stage renderer).
* Open, in order: the stage renderer's port, scene by scene; natives for the logic (the profile below); sound (the Z80
  / YM2151 music, and the MCU's samples by DMA: tables ready, `mcu_samples`, `mcu_sample_addr`, `mcu.dac_value`); a
  stage select or RAM poke.
* Random play never reached the game's own `$10` task (`mcu_test.py --check` forces it).
* The picture is not checked against the reference pixel by pixel in Hatari.

## How it works

### The board and the reference

The reference board is `engine/m72board.py` with the real i8751 (`engine/i8051.py`); `tools/machine.py` `MrHeli` is
the port's schedule. The board runs MAME's schedule up to `START` = frame 500, after the boot and the MCU's code in the
dual-port RAM (the main CPU runs MCU-supplied code at B000:xxxx until frame ~490). The state is kept as
`build/mrheli/state_boot.z` (`MrHeli.save` / `load`). After that, an arcade frame works like this:

* the VBL interrupt (vector $20) is taken at the idle point 0040:01F2 (the queue [27C0] = [27C2], the task [3712]
  = 3323, the busy flag [27C4] = 0) and runs until the CPU is idle again;
* the raster interrupt (vector $22) follows, and runs again for as long as its handler moves the raster line
  further down (the cave's second FG split, [293A]);
* the **real i8751** then runs one frame's machine cycles (145408 / 12): INT0 from the mailbox write B0FFE, and the
  frame's port C0 writes fed to its latch one at a time. The MCU's dual-port RAM writes (command $10's protection code
  at B0000 and its wipe) appear in the lock-step as they do on the board.

The Z80 and the PIC do not run. The sound commands (port $00 and port $C0) are kept in two rings (`sound_cmds`,
`sound2_cmds`). The MCU's interface on both sides: [docs/mcu-interface.md](docs/mcu-interface.md).

### Translation

* **Coverage** (`ref/cover.py`): `SEED FRAMES` runs MAME's schedule from power-on (slow: ~4 frames/s). `--port SEED
  FRAMES` runs the port's schedule from `state_boot.z` (~20 frames/s with the MCU). That second run is the game the
  lock-step tests play: the VBL handler always runs to its end. Seeds 1-3 are attract, 4-7 play, 8+ play with the
  Invulnerability DIP (SW2:7 = $4000). Coverage so far: board seeds 1 (6000), 4 (10000), 8, 9 (15000), 10 (20000);
  port seeds 1, 4, 5 (20000), 6 (1000), 8, 9, 10 (40000).
* **gen.py**: R-Type's gen with Mr. HELI's map: ROM $00000-$7FFFF, RAM $A0000, the dual-port RAM $B0000; jump tables
  from ROM, stored handlers, store marks for the video RAM and palettes, leaf calls and inlining on, no natives; the
  MCU's protection check (its ROM $0C3F-$0C5D) is translated as code at B000:0000; three LAHF sites read only C
  (`FLAG_USES`); palette reads get bits 5-15 set (`pal_sites`). Result: 21.9k instructions. Two unsupported
  instructions remain: 0DCA3 and 0DCA6, decoded from inside other instructions by a heuristic root, and never reached.
* **The translator** (`engine/v30x.py`, commit 47a701e) gained what Mr. HELI uses and R-Type did not: TEST1 and bit
  numbers in CL; shifts and rotates by CL; rotate-by-one with O live; LAHF / SAHF; SUB4S / CMP4S
  (`engine/rt/v30rt.s`, `V30_SUB4S`); AC of ADDC / SUBC into a high byte; `Program.flag_uses` (Lessons, 2026-11-02).

### MCU

Native model, no interpreter: after the boot the MCU only answers the heartbeat (watchdog), command `$10` (the
protection check's code at `$B0000`, wiped 3 ticks later), command `$11` (the ROM test's answer) and plays samples.
`tools/mcu.py` (Python twin) and `src/mcu.s` (68000); interface, boot analysis and timing in
[docs/mcu-interface.md, "The MCU after the boot"](docs/mcu-interface.md#the-mcu-after-the-boot-the-native-model). The
boot (frames 0-483) is timing-bound (code placed at a timer-dependent offset) and not modelled: the port starts after
it. In the STE program: `mcu_init` runs after the snapshot; `mcu_frame` at the start of each `port_frame`, before the
VBL interrupt; `mcu_cmd` at each port C0 write, with 128 units; `MCU_HB_POLL` is set: the heartbeat B0FFE is polled,
not hooked.

### Schedule

`src/mrheli.s` without `SIM` is R-Type's m72render program of 138cd90, adapted. It starts from the snapshot
(`tools/snapshot.py`, `build/mrheli/snapshot.bin`): the reference at START = 500, or at a replay point
(`REPLAY=seed:frame`); the snapshot carries the dual-port RAM and the MCU model's 14-byte state. The schedule is
R-Type's: `PIC_EVERY` 8, `MAX_BEHIND` 12, one arcade frame per VBL. `PLAYBACK` / `INVULN` builds replay a lock-step
seed's inputs (`tools/play_inputs.py`).

### Picture

The shared renderer (`render.s`, the centred 320-pixel window). The top panel is its own screen (`BD_HUD`,
`BD_VSWITCH`, `M72_HUD_TOP` 32). `src/video.s` is R-Type's, with up to three raster bands; core.s keeps the raster
lines in `m72_rlines` and the scroll after the first raster handler in `m72_scroll_r1`. The picture costs ~0.8M cycles
in the shared renderer; it draws FG over BG with AND + OR passes (forbidden, to be converted). Since 2026-10-19 the
shared renderer uses cheaper contribution-bitmap rotations and reuses its access-count table in transfer fallback
paths ([measurements](../../docs/virtual-scroll-performance.md#implementation-results)).

### Colours

`engine/m72_palettes.py` / `engine/rt/m72render.s`: scene colours, packed OKLab L1 and count compression (not the
2026-11-05 default fitter: [colours.md](../../docs/colours.md#what-each-port-uses)). `tools/assets.py` builds
`m72_pal.bin` (7 scenes) from `render_test.py`'s recorded attract and play states (`build/mrheli/render_states.pkl`,
~20 minutes once).

### Sound

Not implemented: the Z80 / YM2151 music and the MCU's samples (to be played by DMA; the MCU model exports the sample
starts: `mcu_snd_start`, `mcu_snd_count`). R-Type's sound plan applies ([its README](../rtype/README.md)).

## Speed

| date | setup | arcade frames/s | % of 55.02 Hz (of 50) | pictures/s | time |
|---|---|---|---|---|---|
| 2026-11-07 | Hatari 14 MB, `-D DEBUG`, attract from START, 54 s | 28.8 | 52% (58%) | 1.9 | logic 34%, drawing 58% |
| 2026-11-07 | Hatari 14 MB, `REPLAY=8:3000:5000 FAST=true NOESC=1 EXTRA="-D INVULN -D PLAYBACK -D DEBUG"` (invulnerable play, 2000 arcade frames) | 22.5 | 41% (45%) | 2.0 | logic 57%, drawing 38% |

The logic on Musashi (`tools/logic_test.py`, 68000 cycles an arcade frame, 2026-11-02 / 11-07):

| seed | frames | result | mean / median / 90% / max |
|---|---|---|---|
| 1 (attract) | 0-20000 | identical | 124.5k / 134.3k / 204.7k / 1.81M |
| 4 (play) | 0-20000 | identical | 85.7k / 94.3k / 138.3k / 1.76M |
| 5 (play) | 0-20000 | identical | 89.8k / 100.3k / 148.4k / 1.76M |
| 8 (invulnerable) | 0-40000 | identical | 160.3k / 162.3k / 194.5k / 1.66M |
| 9 (invulnerable) | 0-40000 | identical | 153.0k / 144.4k / 202.6k / 1.66M |
| 10 (invulnerable) | 0-40000 | identical | 155.1k / 148.5k / 196.7k / 1.66M |

The maximum (~1.8M) is a scene build, at most a frame or two. Invulnerable play costs ~150-160k cycles an arcade
frame: more than the 160k an STE field has, so the logic alone cannot hold 50 Hz there. The MCU model on the board's
trace: `mcu_frame` ~354 cycles mean (1838 with the wipe), `mcu_cmd` 1646, `mcu_hb` 66 (Tests and tools).

Profile (`tools/profile.py --seed 1 --start 2000 --frames 60 --snap`, the attract demo's play: 177k a frame):

| where | share |
|---|---|
| translated code | 87% |
| REP STMW (clears) | 4% |
| the sprite DMA copy | 3.2% |
| SUB4S (the score) | 2% |

| code (256 bytes) | share |
|---|---|
| 06400-064FF (an object's handler: four tile probes, `ror al,1` with O live at 156 cycles) | 15.2% |
| 02400-024FF (the object loop, `call [bp+0]` at 0040:201C: 7.1%) | 14.5% |
| 02500-025FF | 6.2% |
| 03500-035FF | 4.8% |
| 08900-089FF (0040:84E5, called by most handlers) | 3.2% |

| instruction | share | 68000 cycles each |
|---|---|---|
| mov | 26% | |
| call | 13% | 63 |
| ret | 10% | 53 |

The candidates for natives: the object loop, 0040:84E5, the handler at 0040:6000-60F3, and the text writer
0040:27B5-27C6 (store marks at 126 cycles a store on title screens). The plan (the user, 2026-11-02: as R-Type, keep
the gameplay, drop costly effects): R-Type's stage renderer and natives.

Techniques other ports use that may apply:
[speed.md](../../docs/speed.md#techniques-that-look-applicable-elsewhere-2026-11-07).

## Tests and tools

* `tools/logic_test.py [frames] --seed N [--start F --snap] [--steplock F] [--cycles FILE]`: all the RAM, the
  dual-port RAM, the sprite RAM and buffer, the palettes, the video RAMs (and their marks), the registers, the scroll,
  the raster line and count, and both sound rings, compared every frame. The frames count from the port's start.
* `tools/mcu_test.py [frames] --seed N [--check F] [--romtest F] [--starve F] [--trace T]`: the real program in the
  reference board from power-on, the model from frame 484:

  | run | frames | V30 reads of the dual-port RAM | differ | frame boundaries different | samples (taken, address, DAC bytes) |
  |---|---|---|---|---|---|
  | seed 4, `--check 2000 --check 5000` | 484-9000 | 8647 | 0 | 0 | 6 of 6 equal, ends within 1 line |
  | seed 8 (Invulnerability), same checks | 484-9000 | 8667 | 0 | 1 (the wipe's tick, not read) | 5 of 5 |
  | seed 1, `--romtest 2500` | 484-3000 | 2539 | 0 | 0 | 5 of 5 |
  | seed 4, `--starve 1200` (watchdog) | 484-2000 | 1513 | 0 | 0 | 1 of 1 |

* `tools/mcu68k_test.py T [--poll] [--noswap]` / `--synthetic N`: `src/mcu.s` on Musashi, on those four traces with
  and without `MCU_HB_POLL`, and on 30000-frame synthetic traces: 0 differences. 68000 cycles (mcu.s unchanged since
  7690461; measured again 2026-11-07): on the board's trace `build/mrheli/mcu_trace_check.z` (frames 484-759)
  `mcu_frame` ~354 mean (1838 with the wipe), `mcu_cmd` 1646 (its 2 calls), `mcu_hb` 66; on a 3000-frame synthetic
  trace (more commands and samples) `mcu_frame` ~405 (1892), `mcu_cmd` ~535 (1646), `mcu_hb` ~68
  ([docs/mcu-interface.md](docs/mcu-interface.md)'s ~420 / ~70 are such a run).
* `tools/profile.py`: Musashi cycles by code, instruction and runtime helper.
* `tools/render_test.py`, `tools/sprite_test.py`: R-Type's tests with `--game mrheli`.
* `tools/bench.sh [hatari items ...]`: its own Hatari (14 MB, stopped by its PID; from R-Type's bench.sh of
  138cd90); `NOBUILD=1` runs the PRG as it is, a failed build stops it; `EXTRA`, `FAST`, `NOESC`, `REPLAY`,
  `MEMSIZE` as R-Type's.
* `ref/mame_cmp_mrheli.py`: the reference renderer against MAME's picture.

## Lessons

### 2026-11-05: the MCU's protection check in the lock-step

The invulnerable runs reach the game's own MCU check: object task 0040:1ECA sends $10, and 0040:1ED9 calls B000:0000 a
frame later. Seeds 8, 9 and 10 first get there at frames 8931, 12504 and 14519. Since 716644a, logic_test compares the
dual-port RAM as the V30 left it, then copies the reference i8751's writes into the image: the code at B0000, and its
wipe three ticks later. The simulator itself runs no MCU.

### 2026-11-02: what the translator lacked

Besides the new instructions (Translation), two fixes came with Mr. HELI: bit operations on memory whose operand setup
changes the flags, and an inlined callee whose entry is not its lowest address. R-Type's generated code is
byte-identical (checked by running its gen into a scratch directory with the old and the new engine).
`engine/v30x_test.py` has 0 failures, including the 0F forms by `--bytes`.

### 2026-11-02: MAME's protection comment is stale

MAME's "protection simulation" comment block in `m72.cpp` describes made-up routines from before the dump; MAME runs
the real program (`m72_8751`). The analysis of the MCU program found the two V30 sites the first measured runs (1500
attract, 6000 play frames) had not reached ([docs/mcu-interface.md](docs/mcu-interface.md)).

## Verification

Lock-step to 40000 frames (invulnerable seeds 8-10, the protection check included), the MCU against the real i8751,
Hatari runs of the attract mode and 2000 frames of invulnerable play; a coin and a start reach the game. No playtest,
MARP replay or picture check against the reference in Hatari yet.

Full-game verification follows the [status policy](../../docs/port-status.md); nothing here claims a complete playthrough.
