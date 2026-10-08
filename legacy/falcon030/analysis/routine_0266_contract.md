# Routine Replacement Contract: Init Routine 0x0266

## Identifier
- Z80 range: 0x0266 – 0x03DE (estimated)
- Native symbol: `init_0266_native`
- Analysis: `docs/analysis/routine_0266_analysis.md`
- Disassembly excerpt: `docs/analysis/routine_0266_disasm.txt`

## Purpose
Early hardware initialization:
* Clear work RAM regions $6000, $7000, $7400, etc.
* Initialize I/O registers for video, palette, flip screen
* Set up initial values for $60B0/$60B1 and palette banks $7D82-$7D87

## Inputs
- None
- Z80 registers undefined on entry

## Outputs
- Memory writes:
  * $6000-$60FF cleared to 0x00
  * $7000-$70FF cleared to 0x00
  * $7400-$74FF cleared to 0x00
  * $60B0 = 0xC0
  * $60B1 = 0xC0
- I/O writes:
  * $7D82 = 0x00  ; flip screen
  * $7D83 = 0x00
  * $7D86 = 0x00  ; palette bank
  * $7D87 = 0x00
  * $7D84 = 0x01  ; interrupt enable
- Control flow: falls through to next init stage at ~0x03E0

## Side Effects
- Memory-mapped I/O writes as above
- No flag dependency for native implementation
- Timing not critical

## Native Implementation Notes
* Replace `LD B,n; LD HL,addr; XOR A; LD C,A; loop` with 68030 `move.l #0, (a1)` + `subq.l #1,d1` loop or `memset`
* I/O writes can be emitted as direct `move.b` stores
* Preserve original Z80 address range in comments for traceability

## Validation
* Differential test: compare RAM regions $6000-$60FF, $7000-$70FF, $7400-$74FF after routine vs MAME trace
* Verify I/O writes $7D82/$7D83/$7D86/$7D87/$7D84 match reference

## Open Issues
* Exact end address of routine needs full disassembly confirmation
* Purpose of $60B0/$60B1 writes needs MAME cross-check
