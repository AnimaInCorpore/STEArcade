# Donkey Kong Atari Falcon030 Conversion

This project aims to convert the arcade game **Donkey Kong** to the Atari Falcon030.

## Overview

The original arcade game Donkey Kong is being ported/adapted for the Atari Falcon030 platform.

## Files

- `README.md` - Project documentation
- `PORTING.md` - Porting plan, priorities and progress
- `docs/` - Reference documentation
  - `docs/M68000PRM.pdf` - Motorola 68000 Programmer's Reference Manual
  - `docs/z80.pdf` - Z80 reference manual
  - *Use these docs appropriately for development and research*
- `src/` - Atari Falcon030 assembly source code
- `tools/` - Node.js conversion utilities
  - `tools/convert.js` - Z80 → MC68000 converter skeleton based on jsz80test
- `assets/` - Project assets
  - `assets/roms/` - ROM archives
    - `assets/roms/dkong.zip` - Arcade ROM / data archive

## Development Rules

**Very important:** This project uses Ahead-Of-Time static translation, not runtime emulation.
- The original Z80 source / instruction must be kept as a comment immediately behind the corresponding Atari 68030 assembly.
- For each instruction or routine, add a note explaining *why* that particular 68030 instruction/routine was chosen for the translation.

This ensures traceability between the original arcade Z80 code and the Falcon030 implementation.

## Resources

MAME emulator sources are available at:
`C:\Arbeit\F030Arcade\third_party\jsm68kdisassembler\third_party\mame`

## Status

Initial project setup.

Project plan, priorities and progress are tracked in `PORTING.md`.
See the Progress checklist there to mark completed work.
