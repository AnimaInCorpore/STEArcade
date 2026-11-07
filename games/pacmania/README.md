# Pac-Mania

Experimental port work; see the [port table](../../README.md) for current status.

State (2026-11-07): only the ROM manifest (`docs/rom_manifest.json`), `tools/prepare.py` (verifies and unpacks
`pacmania.zip`) and `ref/mame_cmp_pacmania.py` (the shared Namco System 1 reference renderer, `engine/namcos1.py`,
against MAME's picture) exist. `src/` is empty: nothing is translated, there is no STE program and no test results.

## Full-game verification status

Automated players such as Dreamer can attempt a full playthrough once this port's
adapter and native Hatari replay transport are verified. An attempt or assisted
stage visit does not establish completion; a successful natural Hatari playthrough
and graphics, sound and control checks are required for green **Complete** status.
See the shared [status and verification policy](../../docs/port-status.md) and
[current port status](../../README.md). Existing test results above retain their
stated scope; this note does not claim a new successful run or Dreamer integration.
