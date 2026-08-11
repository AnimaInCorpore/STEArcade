# Routine Replacement Contract Template

Use this template for each Z80 routine that is replaced by native 68030 code.

## Routine Identifier
- Z80 address range: `0xXXXX-0xYYYY`
- Name: `routine_name`
- Source reference: disassembly snippet or MAME analysis note

## Purpose
Brief description of observable behavior.

## Inputs
- Z80 registers: A, B, C, D, E, H, L, IX/IY, SP
- Memory regions read: addresses/ranges
- I/O ports read: addresses
- Flags consumed: C, Z, etc.

## Outputs
- Z80 registers modified: list
- Memory writes: addresses/ranges, values
- I/O ports written: addresses, values
- Flags produced: list of flags that callers may observe
- Return address / stack effects

## Side Effects
- Hardware effects: video RAM, sprite RAM, sound triggers, DMA
- Interrupt assumptions: NMI/INT timing
- Timing budget: cycles or frame budget

## Contract
The native replacement must produce identical observable state as the original Z80 routine for all inputs within the documented domain. Internal 68030 condition codes may be used; Z80 `F` is materialized only at boundary points listed above.

## Validation
- Differential test: initial state snapshot, inputs, expected outputs
- Reference trace from MAME at a known point

## Rationale
Why native replacement is safe: control-flow boundaries, no hidden flag dependencies, etc.

## Open Issues
- Unknown semantics, timing uncertainties, indirect jumps
