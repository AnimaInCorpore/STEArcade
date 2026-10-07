# Donkey Kong Porting Plan - Atari Falcon030

## Goal

Port the selected Donkey Kong arcade CPU/video behavior to the Atari Falcon030 while preserving
observable gameplay, graphics, input behavior, interrupts, and bounded frame timing. The project
uses selective ahead-of-time recompilation: well-understood Z80 routines may be replaced by native
68030 code, but every replacement must preserve its documented observable contract.

Sound remains deferred until the CPU, video, input, and interrupt path is stable. Sound-register
writes must still be retained as logged or no-op effects from the beginning.

## Current status

The repository is at the analysis/foundation stage. The ROM set and initial routine notes exist,
but the native source is not yet a buildable or validated Falcon program.

The following rules govern progress:

- Do not mark an item complete because a source file or skeleton exists.
- A completed item needs a reproducible command, an artifact or trace, and a checkable result.
- Draft native routines and `NOP/RTS` stubs must not be reachable from the boot path.
- The boot path must assemble without warnings, have no undefined symbols, and produce a valid
  GEMDOS `.PRG` before routine replacement work is counted as integrated.

## Phases and gates

### 0. Toolchain and build gate

- [ ] Select and pin the target assembler dialect; use syntax accepted by the installed VASM/RMAC
  toolchain.
- [ ] Remove duplicate entry symbols and establish one source of truth for generated includes.
- [ ] Add a reproducible build directory and fail the build on assembler warnings, unresolved
  symbols, or unsupported instructions.
- [ ] Emit a real Atari GEMDOS `.PRG` header and verify the text/data/bss offsets and entry point.
- [ ] Add a minimal build smoke test that assembles `src/main.asm` from a clean checkout.

**Gate:** the minimal program assembles reproducibly and the output has a valid GEMDOS header.

### 1. ROM input and provenance

- [x] Select and document the TKG-04 CPU ROM set, load addresses, and concatenation order.
- [ ] Make archive extraction reproducible; verify every input file against recorded CRC32/SHA1
  values.
- [ ] Make the converter accept a validated raw CPU ROM image, or explicitly extract the archive;
  reject ZIP/container bytes as CPU input.
- [ ] Record the ROM manifest and tool versions used to generate every translated artifact.

**Gate:** one command produces the exact 16 KiB CPU image from the archive and a manifest verifies it.

### 2. Falcon-side Z80 runtime boundary

- [ ] Define a real virtual Z80 state: AF, BC, DE, HL, IX, IY, SP, PC, interrupt state, and shadow
  `F`; keep the native 68030 stack separate from the emulated Z80 stack.
- [ ] Define the Falcon-side memory layout for Z80 ROM, RAM, sprite RAM, video RAM, and state.
- [ ] Implement Z80 memory and I/O read/write interfaces for the documented `$6000-$7D87` map.
  Native routines must call these interfaces or use an explicitly mapped virtual address space;
  direct writes to `$7Dxx` are not Falcon hardware access.
- [ ] Define interrupt and vblank scheduling, including enable/disable behavior and the frame clock.
- [ ] Document Z80/Falcon endianness and 8/16-bit register representation.
- [ ] Add unit tests for memory mapping, I/O side effects, stack operations, and interrupt state.

**Gate:** a small boot state can be initialized, read/written, and interrupted deterministically
without depending on Falcon addresses that have not been mapped.

### 3. Structural AOT translation

- [ ] Replace the current linear byte scan with reachability-based CFG construction from declared
  entry points, restart vectors, interrupt vectors, and known call targets.
- [ ] Decode the complete Z80 instruction space needed by the selected ROM, including CB/ED/DD/FD
  prefixes and documented undocumented-opcode behavior where it is observable.
- [ ] Separate code, embedded tables, graphics/data references, and unreachable bytes.
- [ ] Generate one consistent symbol format from Z80 addresses and emit source/disassembly maps.
- [ ] Make all unknown opcodes and unresolved indirect control flow fail visibly with address,
  context, and a required resolution status. Never emit an unresolved label or a fake NOP path.
- [ ] Treat generated translation as a discovery/reference artifact until it passes semantic tests;
  it is not automatically executable native code.

**Gate:** the generated structural artifact assembles, has no unresolved labels, and reports all
remaining semantic or indirect-flow gaps explicitly.

### 4. Reference and differential validation

- [ ] Establish a reference runner using MAME traces or an equivalent verified Z80 execution model.
- [ ] Define snapshots containing registers, flags, PC/SP, relevant RAM, I/O writes, interrupt
  state, and a timing/cycle budget.
- [ ] Build a harness that executes the reference and native routine from identical snapshots and
  compares observable results.
- [ ] Keep ROM-byte and source-text checks as smoke tests only; do not call them differential tests.
- [ ] Store deterministic fixtures and traces under `docs/analysis/` or a dedicated test directory.

**Gate:** at least one routine has an automated state comparison against the reference, including
  the flags and stack effects that its callers can observe.

### 5. Native routine replacement

- [ ] Identify a routine only after confirming its complete boundary, callers, return convention,
  memory/I/O effects, interrupt assumptions, flags, and timing budget.
- [ ] Complete the contract and disassembly before creating a native implementation. `Purpose: TBD`,
  estimated ranges, and `NOP/RTS` files are drafts, not replacements.
- [ ] Implement the 0x0266 initialization routine against the virtual memory/I/O boundary and
  confirm the exact cleared ranges and continuation address.
- [ ] Complete the 0x0450 disassembly before implementing its conditional branches, calls, rotates,
  and loop bounds. Its current carry approximation and unknown-byte TODOs are not behaviorally safe.
- [ ] Implement only the Z80 flags that are live at each translated or native boundary. Keep H,
  P/V, N, undocumented X/Y, and DAA behavior explicit where observable.
- [ ] Replace direct Z80 `CALL`/`RET` assumptions with an explicit convention; do not map Z80 `SP`
  to the native stack without a proven compatibility layer.
- [ ] Differential-test each replacement before removing or bypassing the reference path.

**Gate:** every integrated replacement has a complete contract, a passing differential fixture,
and no unresolved TODO in its observable path.

### 6. Video, input, and Falcon hardware

- [ ] Implement the Falcon framebuffer and renderer interface separately from the Z80 virtual video
  RAM model.
- [ ] Decode the arcade graphics ROM layout and map sprite/background data correctly.
- [ ] Validate the MAME `ROT270` behavior against a captured reference frame before choosing the
  Falcon framebuffer orientation; support cocktail/flip-screen behavior.
- [ ] Map arcade controls to Falcon IKBD/joystick input and measure input latency.
- [ ] Implement vblank-driven presentation and verify the frame budget on a 16 MHz 68030.

### 7. Incremental integration milestones

- [ ] **Milestone A:** clean-build GEMDOS program, deterministic virtual Z80 boot, and independently
  validated title-screen renderer with a reference screenshot.
- [ ] **Milestone B:** attract mode with verified interrupt/vblank timing and state traces against
  MAME.
- [ ] **Milestone C:** playable physics, input latency, collision behavior, and frame-budget tuning.
- [ ] **Milestone D:** sound-register logging/no-op behavior is stable; only then evaluate DSP or
  native sound implementation.

## Architecture decisions

- Original system: Z80 main CPU plus custom video, input, DMA, and audio hardware.
- Target: Motorola 68030 at 16 MHz, Falcon Videl, Blitter, and optional DSP 56001.
- Strategy: selective AOT recompilation with a virtual Z80 state and explicit Falcon-side hardware
  interfaces.
- The 68030 CCR is not the Z80 `F` register. Use native condition codes internally only when the
  replacement contract does not expose Z80 flags.
- Preserve original Z80 address ranges and disassembly references in contracts and source comments.
- Use 68020/030-specific instructions only after behavioral correctness and the frame budget are
  measured.
- The raw arcade raster is 256x224; Donkey Kong is declared `ROT270` in MAME, so validate the
  final 224x256 presentation before selecting a framebuffer layout.

## Source material

- ROM archive: `assets/roms/dkong.zip`
- ROM map and hashes: `docs/analysis/rom_info.md`
- Memory/I/O map: `docs/analysis/memory_map.md`
- Z80 manual: `docs/z80.pdf`
- Motorola manual: `docs/M68000PRM.pdf`
- MAME source: `C:\Arbeit\F030Arcade\third_party\jsm68kdisassembler\third_party\mame`

When behavior is ambiguous, consult the Z80 and M68000 manuals together with the corresponding
MAME driver/source. Record conclusions in `docs/analysis/` or the relevant replacement contract.

## Deliverables

- `src/` assembly with valid Falcon toolchain syntax and routine-level Z80 references.
- A reproducible ROM extraction, manifest, and structural AOT toolchain.
- Falcon-side virtual Z80 state, memory/I/O, interrupt, and vblank interfaces.
- A build script that produces and verifies a valid GEMDOS `.PRG`.
- Differential fixtures/traces for translated and replaced routines.
- Reference screenshots and milestone results.
- README status kept aligned with this plan.
