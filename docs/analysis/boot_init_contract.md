# Routine Replacement Contract: Boot Init 0x0000

## Identifier
- Z80 range: 0x0000-0x0004
- Native symbol: `L_0000_native`
- File: `src/translated/boot_init_native.asm`

## Purpose
Early boot initialization: clear interrupt enable and jump to main boot code.

## Inputs
- None
- Z80 registers: undefined on entry
- Memory: none read

## Outputs
- I/O write: `$7D84` ← 0x00  ; interrupt enable register
- Control flow: PC = $0266
- Registers modified: D0 (internal)

## Side Effects
- Memory-mapped I/O write to $7D84
- No RAM modification
- No flag dependency

## Validation
- Differential test: initial state with $7D84 = 0xFF → after routine $7D84 = 0x00, PC = $0266
- Reference: MAME dkong.cpp memory map confirms $7D84 = interrupt enable

## Rationale
Routine has no flag use, single I/O write, unconditional jump. Native replacement is safe and removes need for Z80 flag emulation.

## Open Issues
- None
