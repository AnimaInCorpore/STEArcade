# Donkey Kong Porting Plan - Atari Falcon030

## Goal
Convert the arcade Donkey Kong to run on Atari Falcon030 hardware, preserving gameplay and timing.

## Priorities
- **High:** Gameplay logic and graphics display
- **Low:** Sound - deferred until core gameplay/graphics are stable

## Progress
- [ ] 1. Analysis - Disassemble Z80 code, map memory/I/O/interrupts
- [ ] 2. Emulation Core - Z80 emulation on 68000, video via Videl/blitter
- [ ] 3. Porting Rules - Z80 source comments + rationale in `src/`
- [ ] 4. Integration - Asset loading, input mapping, timing
- [ ] 5. Testing - Gameplay/graphics validation vs MAME
- [ ] 6. Sound - Deferred low priority

## Source Material
- ROM: `assets/roms/dkong.zip`
- Reference docs: `docs/M68000PRM.pdf`, `docs/z80.pdf`
- MAME sources: `C:\Arbeit\F030Arcade\third_party\jsm68kdisassembler\third_party\mame`

## Architecture
- Original: Z80 CPU + custom video/audio hardware
- Target: Motorola 68030 + Falcon Videl video + DMA audio

## Phases

### 1. Analysis
- Disassemble Z80 code from ROM
- Map memory map, I/O ports, interrupts
- Document game loops, rendering, input

### 2. Emulation Core
- Implement Z80 instruction emulation on 68000 with cycle accuracy
- Emulate original video hardware via Falcon Videl / blitter
- Sound mapping to Falcon DSP / DMA is low priority and deferred
- Reuse usable parts from `C:\Arbeit\jsz80test` via Node.js tools in `tools/convert.js`

### 3. Porting Rules
- All `src/` code must keep original Z80 source as comment behind 68000 code
- Add notes why each 68000 instruction/routine was chosen for Z80 emulation
- Use `docs/` references appropriately

### 4. Integration
- Build asset loading from `assets/roms/`
- Input mapping: arcade controls -> Falcon joystick
- Timing/synchronization to 50/60 Hz

### 5. Testing
- Compare behavior vs MAME reference
- Verify levels, physics, graphics, input latency
- Sound testing deferred; focus on gameplay and graphics first
- Iterate on performance hotspots

## Deliverables
- `src/` assembly source with documented Z80 mapping
- Build script for Falcon030
- README updates with status
