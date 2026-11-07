# Pac-Mania (Namco, 1987) on the Atari STE

Reference work only, no STE program. The MAME set is `pacmania` (Namco System 1, `namco/namcos1.cpp`: three MC6809E
and the HD63701 MCU, as Splatterhouse, Galaga '88 and Dragon Spirit). The shared reference board `engine/namcos1.py`
renders its picture and is compared with MAME's; nothing is translated (`src/` is empty), there is no picture or sound
path on the STE and no speed figure. Status in the root README's table: Experimental / deferred, early implementation
/ reference work (2026-11-07).

## Build and run

```sh
venv/bin/python games/pacmania/tools/prepare.py                 # checks pacmania.zip (docs/rom_manifest.json), unpacks it
venv/bin/python games/pacmania/ref/mame_cmp_pacmania.py [frames...]   # engine/namcos1.py's picture against MAME's
```

ROM: the MAME set `pacmania` (`assets/roms/pacmania.zip`, unpacked to `assets/roms/extracted/pacmania/` by
`engine/roms.py`). Paths are relative to this folder; `engine/`, `tools/`, `port.py` and `docs/` at the top are the
repository's.

## State

* Present (2026-11-07): the ROM manifest (`docs/rom_manifest.json`), `tools/prepare.py`, and
  `ref/mame_cmp_pacmania.py` (`engine/namcos1_mame.py`: the shared Namco System 1 reference renderer against MAME's
  picture).
* Missing: the translation of the main and sub CPUs, the STE program, the renderer, colours, sound; no test results.
* The other Namco System 1 ports show the way: [Splatterhouse](../splatter/README.md),
  [Galaga '88](../galaga88/README.md), [Dragon Spirit](../dspirit/README.md).

## Verification

None yet: no STE program exists.

Full-game verification follows the [status policy](../../docs/port-status.md); nothing here claims a complete playthrough.
