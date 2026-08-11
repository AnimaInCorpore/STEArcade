# Donkey Kong Porting Plan - Atari Falcon030

## Goal
Convert the arcade Donkey Kong to run on Atari Falcon030 hardware, preserving gameplay and timing.

## Priorities
- **High:** Gameplay logic and graphics display
- **Low:** Sound - deferred until core gameplay/graphics are stable

## Progress
- [ ] 1. Analysis & Tooling
- [ ] 2. Static Translation Core (Node.js AOT)
- [ ] 3. Hardware Interfacing (Videl & I/O)
- [ ] 4. Incremental Integration & Testing
  - [ ] Milestone A: Boot sequence and static graphics rendering (Title Screen)
  - [ ] Milestone B: Attract mode execution (game loop + timing vs MAME)
  - [ ] Milestone C: Playable physics and input latency tuning
- [ ] 5. Sound - Deferred low priority

## Source Material
- ROM: `assets/roms/dkong.zip`
- Reference docs: `docs/M68000PRM.pdf`, `docs/z80.pdf`
- MAME sources: `C:\Arbeit\F030Arcade\third_party\jsm68kdisassembler\third_party\mame`

## Architecture
- Original: Z80 CPU + custom video/audio hardware
- Target: Motorola 68030 @16MHz + Falcon Videl video + Blitter + DSP 56001
- Notes:
  - Use 68020/030-specific instructions (bitfield, 32-bit mul/div) instead of generic 68000
  - Screen orientation: Donkey Kong arcade is horizontal. MAME source: MASTER_CLOCK 61.44MHz, PIXEL_CLOCK 6.144MHz, HTOTAL 384/HBSTART 256/HBEND 0, VTOTAL 264/VBSTART 240/VBEND 16 → visible 256×224, total 384×264. True bitmap height 224 px ≤256 px, so no TATE rotation needed; keep assets in native orientation
  - DSP 56001 left available for later offload of graphics/audio work; sound deferred for now
  - Final output is Atari `.PRG` with GEMDOS header, assembled with VASM/RMAC

## Phases

### 1. Analysis & Tooling
- Disassemble Z80 code from ROM using `jsm68kdisassembler`
- Map memory map, I/O ports, interrupts
- Confirm screen orientation from MAME: visible 256×224, total 384×264, pixel clock 6.144MHz. No TATE rotation required, bitmap height 224 px ≤256 px
- Finalize target assembler (VASM recommended) and set up `.PRG` build pipeline with GEMDOS header

### 2. Static Translation Core (Node.js)
- **Decision: Ahead-Of-Time static recompilation, not runtime emulation.**
- Build `tools/convert.js` to perform AOT translation of Z80 ASM to 68030 ASM
- Keep original Z80 source as comment immediately behind 68000 code per project rule, with rationale note
- Implement cycle-padding or timer-based synchronization to run game logic at correct 60Hz arcade speed on 16MHz 68030
- Reuse mapping tables from `C:\Arbeit\jsz80test`

### 3. Hardware Interfacing (Videl & I/O)
- Implement Videl routines for Falcon-specific resolutions, VGA/RGB compatibility
- Map Donkey Kong custom video RAM layout to Falcon linear frame buffer using Blitter
- Map arcade I/O ports to Falcon IKBD/Joystick
- No rotation needed; render assets in native horizontal orientation

### 4. Incremental Integration & Testing
- **Milestone A:** Boot sequence and static graphics rendering (Title Screen)
- **Milestone B:** Attract mode execution, verifying game loop and timing vs MAME
- **Milestone C:** Playable physics and input latency tuning
- Iterate on performance hotspots using 68030 instruction cache

## Deliverables
- `src/` assembly source with documented Z80 mapping and rationale comments
- Node.js AOT toolchain `tools/convert.js`
- Build script for Falcon030 producing `.PRG`
- README updates with status
