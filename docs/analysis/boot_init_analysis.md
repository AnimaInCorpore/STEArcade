# Boot Init Routine Analysis - 0x0000-0x0265

## Z80 bytes
```
0000 3E 00          LD A,$00
0002 32 84 7D       LD ($7D84),A    ; interrupt enable clear
0005 C3 66 02       JP $0266
```

## Observable contract
- Input: none
- Output: writes $00 to memory-mapped I/O $7D84 (interrupt enable)
- Side effect: unconditional jump to $0266
- No flag dependency, no RAM read/write beyond I/O

## Native 68030 replacement proposal
```
L_0000:
        move.b #0,d0
        move.b d0,$7D84          ; interrupt enable
        jbra L_0266
```

Contract preserved: single byte write to $7D84, control flow to $0266.
Timing not critical for boot path.

## Next steps
Validate $7D84 mapping against MAME memory map: interrupt enable register.
Confirm no subsequent code depends on flags set by LD A,$00.
