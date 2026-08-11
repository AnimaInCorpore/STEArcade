# Donkey Kong Porting Plan - Atari Falcon030

## Goal
Convert the arcade Donkey Kong to run on Atari Falcon030 hardware, preserving observable gameplay,
graphics, input behavior, and timing. The implementation may replace well-understood Z80 routines
with native 68030 code; it does not need to translate every Z80 instruction one-for-one.

## Priorities
- **High:** Gameplay logic and graphics display
- **Low:** Sound - deferred until core gameplay/graphics are stable

## Progress
- [ ] 1. Analysis & Tooling
  - [x] Initial memory map, I/O, interrupt, and MAME source review
  - [x] Initial Node.js and Falcon assembler scaffolding
  - [x] Select and document the exact CPU ROM set and concatenation layout
  - [x] Make the ROM extraction and build pipeline reproducible
  - [x] Define routine replacement contracts and validation format
- [ ] 2. Structural AOT Pass
  - [x] Reachability-based disassembly with labels and code/data separation
  - [x] Buildable control-flow skeleton for the CPU code
  - [x] Explicit diagnostics for unknown opcodes and unresolved indirect control flow
  - [ ] Flag liveness annotations and boundary materialization hooks
- [ ] 3. Native Routine Replacement
  - [x] Identify routines with clear purpose and stable call boundaries
  - [x] Implement replacements with documented inputs, outputs, side effects, flags, and timing
  - [x] Differential-test replacements against MAME/reference traces
  - [x] Native skeleton for init routine 0x0266
  - [x] Source comment rule: routine purpose comments in translated source
- [ ] 4. Hardware Interfacing (Videl & I/O)
- [ ] 5. Incremental Integration & Testing
  - [ ] Milestone A: Buildable boot path and independently validated title-screen renderer
  - [ ] Milestone B: Attract mode execution with vblank/interrupt timing against MAME
  - [ ] Milestone C: Playable physics and input latency tuning
- [ ] 6. Sound - Deferred low priority, with register-write stubs retained from the start

## Source Material
- ROM: `assets/roms/dkong.zip`
- Reference docs: `docs/M68000PRM.pdf`, `docs/z80.pdf`
- MAME sources: `C:\Arbeit\F030Arcade\third_party\jsm68kdisassembler\third_party\mame`
- When the implementation is ambiguous, consult the Z80 and M68000 manuals together with the
  corresponding MAME driver/source. Use them to resolve instruction semantics, flags, memory and
  I/O behavior, video timing/orientation, interrupts, and sound-register effects rather than
  guessing. Record important conclusions in `docs/analysis/` or the relevant replacement contract.

## Architecture
- Original: Z80 CPU + custom video/audio hardware
- Target: Motorola 68030 @16MHz + Falcon Videl video + Blitter + DSP 56001
- Strategy: selective ahead-of-time recompilation
  - Use the initial translation to recover control flow, routine boundaries, data references, and
    hardware accesses.
  - Replace complete routines with native 68030 implementations when their purpose and observable
    contract are understood.
  - Retain precise Z80 semantics only where translated code or a routine boundary can observe them.
  - Keep a virtual Z80 state model for compatibility; do not assume the 68030 CCR is the Z80 `F`
    register.
- Notes:
  - Use 68020/030-specific instructions only after the behavioral contract is correct.
  - MAME declares Donkey Kong as `ROT270`. The raw visible raster is 256×224, but the final logical
    display is portrait-oriented after rotation; validate the 224×256 presentation before choosing
    a Falcon framebuffer layout.
  - DSP 56001 remains available for later offload of graphics/audio work; sound is deferred for now.
  - Final output is an Atari `.PRG` with a real GEMDOS header, assembled and linked as part of the
    build pipeline.

## Phases

### 1. Analysis & Tooling
- [x] Review Z80 memory map, I/O ports, interrupts, and MAME video behavior
- [x] Select one exact Donkey Kong CPU ROM set and document its load/concatenation map
- [x] Make the ROM extraction and build pipeline reproducible
- [x] Define replacement contract format and differential-test input/output snapshots
- [ ] Confirm the MAME `ROT270` orientation against a captured reference frame
- [ ] Finalize target assembler and make a minimal GEMDOS `.PRG` build pass

### 2. Structural AOT Pass (Node.js)
- **Decision: Use AOT structural translation plus native routine replacement, not strict one-to-one translation.**
- Build `tools/convert.js` to produce a buildable control-flow skeleton with source addresses,
  labels, and diagnostics.
- Separate code from data and resolve direct branches, calls, returns, restarts, and indirect-flow
  sites before optimizing.
- Keep original Z80 ranges and disassembly references at routine level; attach rationale and
  unresolved-issue markers to generated code.
- Do not silently emit `NOP` for unknown instructions or leave unresolved labels in the output.
- Reuse mapping tables from `C:\Arbeit\jsz80test` only as input to the structural translator, not
  as the runtime register/flag model.

### 3. Native Routine Replacement
- Identify routines whose purpose is clear from disassembly, MAME behavior, and call sites.
- Document each replacement contract: inputs, outputs, clobbers, Z80-visible RAM writes, I/O,
  flags, interrupt assumptions, and timing budget.
- Use native M68k condition codes internally when Z80 `F` is not part of the contract.
- Preserve or materialize only the Z80 flags consumed by translated code or exposed at a boundary.
- Differential-test replacement routines from identical initial state and inputs before removing the
  original translated path.

### 4. Hardware Interfacing (Videl & I/O)
- Implement Videl routines for Falcon-specific resolutions, VGA/RGB compatibility
- Map Donkey Kong video RAM and graphics ROM formats to a Falcon renderer using the Blitter where
  useful; do not assume the arcade layout is already a linear framebuffer
- Map arcade I/O ports to Falcon IKBD/Joystick
- Implement the confirmed portrait orientation and cocktail/flip-screen behavior
- Preserve sound-register writes as logged/no-op handlers while sound is deferred

### 5. Incremental Integration & Testing
- **Milestone A:** Buildable structural path and independently validated title-screen renderer
- **Milestone B:** Attract mode execution, verifying game state and vblank/interrupt timing against MAME
- **Milestone C:** Playable physics, input latency, and frame-budget tuning
- Maintain traces/screenshots for each milestone and iterate on performance hotspots using the 68030
  instruction cache only after behavior is stable

## Deliverables
- `src/` assembly source with routine-level Z80 references, replacement contracts, and rationale
- Node.js structural AOT toolchain `tools/convert.js`
- Build script for Falcon030 producing a valid `.PRG`
- Differential-test fixtures or traces for translated/replaced routines
- README updates with status
