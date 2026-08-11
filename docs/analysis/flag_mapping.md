# Register & Flag Mapping Analysis

## Role in the Selective-Recompilation Strategy

This project does not require complete Z80 flag emulation for every native replacement. Z80 flags
are virtual state and only need to be preserved when they are observable by translated code, a
caller, or a state boundary.

Use native 68030 condition codes inside a replacement routine when its contract does not expose the
Z80 `F` register. At a boundary, either document `F` as undefined or materialize the required Z80
flags. For translated code, perform flag liveness analysis and materialize only the flag bits that
are consumed.

## Current Mapping from jsz80test/main.js

**8-bit registers**
```
Z80  -> 68030 pseudo
b    -> d1
c    -> d2
d    -> d3
e    -> d4
h    -> h   // symbolic, not a real 68030 register
l    -> l   // symbolic, not a real 68030 register
(hl) -> (a1)   // memory indirect via A1
a    -> d0
```

**16-bit registers**
```
bc -> a2
de -> a3
hl -> a1
sp -> a0
```

### Observations
- Data registers d1-d4 for B/C/D/E are valid 68030.
- A → D0 is valid.
- SP → A7 in our manual mapping, but jsz80test maps SP → A0. Inconsistent.
- `h` / `l` as register names are not valid Motorola assembly. In jsz80test they appear as symbolic placeholders. Real 68030 code would need to map H/L to bytes within a data register, e.g., D5 high/low byte, or use separate memory.
- `(hl)` mapped to `(a1)` implies A1 holds HL pointer. That's plausible.

## Z80 Flag Layout

The Z80 `F` register is:

```
bit 7 S   sign
bit 6 Z   zero
bit 5 Y   undocumented result copy
bit 4 H   half carry
bit 3 X   undocumented result copy
bit 2 P/V parity or overflow
bit 1 N   add/subtract
bit 0 C   carry
```

The bit layout must be corrected in the assembly comments before implementing general helpers.

## Status Flag Handling

Z80 flags F register:
- S  Sign
- Z  Zero
- H  Half carry
- P/V Parity / Overflow
- N  Add/Subtract
- C  Carry

68030 condition codes:
- N  Negative
- Z  Zero
- V  Overflow
- C  Carry

**Mismatches**
- No direct half-carry flag H in 68030. Z80 `DAA`, `ADC`, `SBC` depend on H.
- Parity flag P/V maps loosely to V but semantics differ.
- Z80 N flag is set by ADD/SUB; 68030 N is sign.
- Z80 S flag maps to N.

The jsz80test translator maps Z80 condition codes directly to 68030 branch conditions:
```
Z80 NZ,Z,NC,C,PO,PE,P,M  →  68030 ne,eq,cc,cs,po,pe,p,m
```
That direct mapping is only valid when the relevant Z80 flag bits have first been materialized in a
compatible form. Native replacement routines may use M68k conditions internally when their contract
does not expose Z80 `F`.

**Risk**
- Direct flag sync is a dead end for full accuracy because:
  1. 68030 does not have half-carry. DAA emulation requires H.
  2. Parity vs Overflow semantics differ.
  3. Z80 undocumented flags / flag quirks.
- For Donkey Kong, DAA is used for BCD score handling. If flags are wrong, score display will break.
- The `h`/`l` symbolic registers indicate the translator expects a custom assembler or a preprocessor. Generating raw VASM code with `h`/`l` will assemble fail.

## Recommendations
1. Clarify register mapping to real 68030 registers:
   - Map H/L to D5 high/low bytes, or keep HL as a pair in A1.
   - Decide SP mapping: use A7 per Motorola convention, not A0.
2. Flag handling strategy:
   - Treat `Z80_FLAGS` as shadow state, not as a mirror of the M68k CCR.
   - Track liveness per flag bit across all control-flow paths.
   - Materialize flags at conditional branches, flag-consuming arithmetic, `DAA`, `PUSH AF`, routine
     boundaries, and other observable points.
   - Do not call a full flag-update helper after every instruction by default.
   - Use native M68k flags inside replacements when Z80 `F` is not part of their contract.
3. Review `docs/z80.pdf` and `docs/M68000PRM.pdf` for:
   - Z80 flag definitions and DAA requirements.
   - 68030 condition code generation rules.
4. Prototype exact flag helpers only for translated paths that need them: `ADD`, `ADC`, `SUB`,
   `SBC`, `AND`, `OR`, `XOR`, `CP`, `DAA`, `SCF`, `CCF`, `CPL`, rotates, shifts, `BIT`, and
   block operations.
5. Validate register mapping against actual jsz80test output to see how `h`/`l` are expanded.

Current path is viable as a structural translation and routine-discovery tool. Exact status-flag
handling remains necessary only for translated or boundary-visible behavior; it is not required for
native replacements whose contracts do not expose Z80 `F`.
