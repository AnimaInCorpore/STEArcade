# Mr. HELI no Daibouken

Experimental port work; see the [port table](../../README.md) for current status.

## Full-game verification status

Automated players such as Dreamer can attempt a full playthrough once this port's
adapter and native Hatari replay transport are verified. An attempt or assisted
stage visit does not establish completion; a successful natural Hatari playthrough
and graphics, sound and control checks are required for green **Complete** status.
See the shared [status and verification policy](../../docs/port-status.md) and
[current port status](../../README.md). Existing test results above retain their
stated scope; this note does not claim a new successful run or Dreamer integration.

## The main CPU's translation (agent A, 2026-11-02)

Mr. HELI's V30 program translated R-Type's way (engine/v30x.py; see games/rtype/README.md and docs/architecture.md
"The V30 translator"). Only the simulator build exists. There is no STE program yet: `src/mrheli.s` without `SIM`
just returns to the desktop.

* **The port's schedule** (`tools/machine.py` `MrHeli`): the board runs MAME's schedule up to `START` = frame 500,
  after the boot and the MCU's code in the dual-port RAM (the main CPU runs MCU-supplied code at B000:xxxx until
  frame ~490). The state is kept as `build/mrheli/state_boot.z` (`MrHeli.save` / `load`). After that, an arcade
  frame works like this:
  * the VBL interrupt (vector $20) is taken at the idle point 0040:01F2 (the queue [27C0] = [27C2], the task [3712]
    = 3323, the busy flag [27C4] = 0) and runs until the CPU is idle again;
  * the raster interrupt (vector $22) follows, and runs again for as long as its handler moves the raster line
    further down (the cave's second FG split, [293A]);
  * the **real i8751** (engine/i8051.py) then runs one frame's machine cycles (145408 / 12): INT0 from the mailbox
    write B0FFE, and the frame's port C0 writes fed to its latch one at a time. The MCU's dual-port RAM writes
    (command $10's protection code at B0000 and its wipe) appear in the lock-step as they do on the board.

  The Z80 and the PIC do not run. The sound commands (port $00 and port $C0) are kept in two rings
  (`sound_cmds`, `sound2_cmds`).
* **Coverage** (`ref/cover.py`): `SEED FRAMES` runs MAME's schedule from power-on (slow: ~4 frames/s). `--port SEED
  FRAMES` runs the port's schedule from `state_boot.z` (~20 frames/s with the MCU). That second run is the game the
  lock-step tests play: the VBL handler always runs to its end. Seeds 1-3 are attract, 4-7 play, 8+ play with the
  Invulnerability DIP (SW2:7 = $4000). Coverage so far:
  * board: seeds 1 (6000), 4 (10000), 8, 9 (15000), 10 (20000);
  * port: seeds 1, 4, 5 (20000), 6 (1000), 9, 10 (40000), 8 (40000, running).
* **gen.py**: R-Type's gen with Mr. HELI's map:
  * ROM $00000-$7FFFF, RAM $A0000, the dual-port RAM $B0000;
  * jump tables from ROM, stored handlers, store marks for the video RAM and palettes, leaf calls and inlining on,
    no natives;
  * the MCU's protection check (its ROM $0C3F-$0C5D) is translated as code at B000:0000;
  * three LAHF sites read only C (`FLAG_USES`);
  * palette reads get bits 5-15 set (`pal_sites`).

  Result: 21.9k instructions. Two unsupported instructions remain: 0DCA3 and 0DCA6, decoded from inside other
  instructions by a heuristic root, and never reached.
* **The translator** (`engine/v30x.py`, commit 47a701e) gained what Mr. HELI uses and R-Type did not:
  * TEST1 and bit numbers in CL;
  * shifts and rotates by CL;
  * rotate-by-one with O live;
  * LAHF / SAHF;
  * SUB4S / CMP4S (engine/rt/v30rt.s, `V30_SUB4S`);
  * AC of ADDC / SUBC into a high byte;
  * `Program.flag_uses`.

  Two fixes came with it: bit operations on memory whose operand setup changes the flags, and an inlined callee
  whose entry is not its lowest address. R-Type's generated code is byte-identical (checked by running its gen into
  a scratch directory with the old and the new engine). `engine/v30x_test.py` has 0 failures, including the 0F
  forms by `--bytes`.
* **Lock-step** (`tools/logic_test.py [frames] --seed N [--start F --snap] [--steplock F] [--cycles FILE]`): all the
  RAM, the dual-port RAM, the sprite RAM and buffer, the palettes, the video RAMs (and their marks), the registers,
  the scroll, the raster line and count, and both sound rings, compared every frame. The frames count from the
  port's start.

| seed | frames | result | 68000 cycles an arcade frame: mean / median / 90% / max |
|---|---|---|---|
| 1 (attract) | 0-20000 | identical | 124.5k / 134.3k / 204.7k / 1.81M |
| 4 (play) | 0-20000 | identical | 85.7k / 94.3k / 138.3k / 1.76M |

  The maximum (~1.8M) is a scene build, at most a frame or two.
* **Profile** (`tools/profile.py --seed 1 --start 2000 --frames 60 --snap`, the attract demo's play: 177k a frame):

  | where | share |
  |---|---|
  | translated code | 87% |
  | REP STMW (clears) | 4% |
  | the sprite DMA copy | 3.2% |
  | SUB4S (the score) | 2% |

  By 256 bytes of code:

  | code | share |
  |---|---|
  | 06400-064FF (an object's handler: four tile probes, `ror al,1` with O live at 156 cycles) | 15.2% |
  | 02400-024FF (the object loop, `call [bp+0]` at 0040:201C: 7.1%) | 14.5% |
  | 02500-025FF | 6.2% |
  | 03500-035FF | 4.8% |
  | 08900-089FF (0040:84E5, called by most handlers) | 3.2% |

  By instruction:

  | instruction | share | 68000 cycles each |
  |---|---|---|
  | mov | 26% | |
  | call | 13% | 63 |
  | ret | 10% | 53 |

  These are the candidates for natives: the object loop, 0040:84E5, the handler at 0040:6000-60F3, and the text
  writer 0040:27B5-27C6 (store marks at 126 cycles a store on title screens).

Open: the STE program and its bench, natives, and covering the later stages (invulnerable seeds to 40000 frames are
running). There is no RAM poke for a stage select yet.

## The i8751 MCU on the STE (agent B, 2026-11-02)

Native model, no interpreter: after the boot the MCU only answers the heartbeat (watchdog), command `$10` (the
protection check's code at `$B0000`, wiped 3 ticks later), command `$11` (the ROM test's answer) and plays samples.
`tools/mcu.py` (Python twin) and `src/mcu.s` (68000); interface, boot analysis and timing in
[docs/mcu-interface.md](docs/mcu-interface.md), "The MCU (agent B)". The boot (frames 0-483) is timing-bound (code
placed at a timer-dependent offset) and not modelled: the port starts after it.

Results (`tools/mcu_test.py`, the real program in the reference board from power-on, the model from frame 484):

| run | frames | V30 reads of the dual-port RAM | differ | frame boundaries different | samples (taken, address, DAC bytes) |
|---|---|---|---|---|---|
| seed 4, `--check 2000 --check 5000` | 484-9000 | 8647 | 0 | 0 | 6 of 6 equal, ends within 1 line |
| seed 8 (Invulnerability), same checks | 484-9000 | 8667 | 0 | 1 (the wipe's tick, not read) | 5 of 5 |
| seed 1, `--romtest 2500` | 484-3000 | 2539 | 0 | 0 | 5 of 5 |
| seed 4, `--starve 1200` (watchdog) | 484-2000 | 1513 | 0 | 0 | 1 of 1 |

`tools/mcu68k_test.py` (mcu.s on Musashi) on those four traces, with and without `MCU_HB_POLL`, and on 30000-frame
synthetic traces (`--synthetic`, `--noswap`): 0 differences. 68000 cycles: `mcu_frame` ~350 mean (1840 with the
wipe), `mcu_cmd` 550-1650, `mcu_hb` 66. Open: the samples' DMA player (tables ready: `mcu_samples`,
`mcu_sample_addr`, `mcu.dac_value`); random play never reached the game's own `$10` task (forced by `--check`).
