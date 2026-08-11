# Routine Boundary Analysis - 0x0266

## Entry point
Z80 address $0266 is the first instruction after boot init JP.
From CPU ROM dump:
```
0266 06 10       LD B,$10
0268 21 00 60    LD HL,$6000
026B AF          XOR A,A
026C 4F          LD C,A
026D 77          LD (HL),A
026E 23          INC HL
026F 0D          DEC C
0270 20 FB       JR NZ,$027D  ; loop
...
```

Observed pattern: repeated LD B, immediate; LD HL, address; XOR A,A; loop to clear RAM regions.

Later bytes show writes to I/O ports:
* $7D82 – flip screen
* $7D83 – ? 
* $7D86/$7D87 – palette bank selector
* $7D83 – ? 
* $60B0/$60B1 – RAM writes

## Hypothesized purpose
Main hardware initialization:
* Clear RAM work areas at $6000, $7000, etc.
* Initialize video/sprite RAM pointers
* Set palette banks and flip screen register
* Prepare interrupt enable state

## Call boundaries
No CALL/RET observed in first ~100 bytes; appears to be a linear init routine falling through to later code.
Next JP target likely at ~0x02xx.

## Native replacement considerations
* Routine contains many memory clear loops with `LD (HL),A` + `INC HL` + `DEC C` + `JR NZ`.
* These loops are ideal candidates for native 68030 `movem`/`memset` replacement.
* I/O writes are small and can be kept as direct 68030 stores.
* Flag dependency: loop uses C flag from DEC C, but native loop can use 68030 condition codes.

## Next steps
* Full disassembly of $0266-$03xx using a proper Z80 disassembler to confirm loop bounds and I/O writes.
* Document each RAM region cleared and I/O port written.
* Create replacement contract with input/output memory map.
* Implement native 68030 memset loops for each clear region.

## Open questions
* Exact size of RAM clear loops – need accurate HL increment count.
* Purpose of writes to $60B0/$60B1.
* Whether routine ends with RET or falls through to next init stage.
