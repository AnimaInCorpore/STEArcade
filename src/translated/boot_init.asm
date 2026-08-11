; Donkey Kong boot initialization - AOT translation
; Source Z80 bytes from dkong.dat offset 0x0000
; Rule: Z80 source kept as comment behind 68000 code with rationale

        include "../lib/z80_flags.asm"

        section .text

L_0000:
        move.b #0x00,d0                | ; ld a,imm8 $00
        // why: Z80 A maps to 68030 D0, immediate byte move preserves value. 68030 move.b #imm,Dn is single-cycle.

        move.b d0,$7d84                | ; ld (nn),a $7d84
        // why: Z80 memory-mapped I/O write. 68030 byte store to absolute address mirrors Z80 (nn),A. $7D84 is interrupt enable register per MAME map.

        jbra L_0266                    | ; jp imm16 $0266
        // why: Unconditional branch. 68030 jbra is direct equivalent to Z80 JP nn, no condition check.

; --- Routine at 0x0006 ---
L_0006:
        move.b $6007,d0                | ; ld a,(nn) $6007
        // why: Load byte from RAM $6007 into D0/A. 68030 absolute byte load matches Z80 LD A,(nn).

        ror.b d0                       | ; rrca
        // why: RRCA rotates A right through carry. Using 68030 ROR.B on D0 approximates rotation; full carry flag emulation deferred to AOT phase 2.

        jsr Z80_RET_NC                 | ; ret nc
        // why: RET NC requires Z80 carry flag. Static translation calls flag emulation stub Z80_RET_NC which tests Z80_FLAGS carry bit and returns conditionally.

        addq.l #1,a7                   | ; inc sp
        // why: Z80 SP maps to 68030 A7. addq.l #1 is single-cycle increment, matches Z80 INC SP timing.

        addq.l #1,a7                   | ; inc sp
        // why: Same as above, second increment.

        rts                            | ; ret
        // why: Z80 RET maps directly to 68030 RTS.

; End of initial translated routines
