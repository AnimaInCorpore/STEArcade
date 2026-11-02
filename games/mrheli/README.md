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
