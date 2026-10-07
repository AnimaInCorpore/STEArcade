# Donkey Kong Atari Falcon030 Conversion

This project aims to convert the arcade game **Donkey Kong** to the Atari Falcon030.

## Overview

The original arcade game Donkey Kong is being ported/adapted for the Atari Falcon030 platform.
The implementation strategy is selective ahead-of-time recompilation: an initial translation
recovers the Z80 control-flow structure, while routines whose purpose is understood may be
rewritten as native 68030 code. The objective is to preserve observable game behavior, not to
produce a one-for-one instruction translation.

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

**Very important:** This project uses ahead-of-time recompilation and native routine replacement,
not a general-purpose runtime Z80 emulator.

- The first pass should produce a buildable structural translation with labels, control flow, and
  explicit markers for unresolved semantics.
- Unknown instructions must not silently become `NOP`s. They should produce a visible TODO,
  diagnostic stub, or other deliberate failure path.
- One-to-one instruction correspondence is not required. For a native replacement, retain the
  original Z80 address range, routine purpose, and a contract describing inputs, outputs, memory
  side effects, flags, timing, and hardware effects.
- Keep Z80 source or disassembly references close enough to the replacement to preserve
  traceability, and explain why the native routine is behaviorally equivalent.
- Treat Z80 flags as virtual state. Emulate or materialize only flags that are observable by a
  translated instruction, a caller, or a hardware/state boundary. Native replacement routines may
  use normal 68030 condition codes internally when their contract does not expose Z80 `F`.
- When behavior, timing, memory mapping, video, sound, or hardware effects are unclear, consult
  the reference manuals in `docs/` and the corresponding MAME driver/source before making an
  assumption. Record the relevant conclusion in the analysis notes or replacement contract.

This keeps the generated code auditable without forcing effort into Z80 instructions that will be
replaced at routine level.

## Resources

MAME emulator sources are available at:
`C:\Arbeit\F030Arcade\third_party\jsm68kdisassembler\third_party\mame`

## Status

The repository is currently at the analysis and runtime-foundation stage. The selected ROM set and
initial routine contracts exist, but the Falcon source does not yet pass a clean assembler build,
and the native routine files are drafts rather than validated replacements. See `PORTING.md` for
the gated implementation plan and current checklist.

Project plan, priorities and progress are tracked in `PORTING.md`.
See the gated checklist there before marking work complete.
