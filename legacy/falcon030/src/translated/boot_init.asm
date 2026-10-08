; Donkey Kong boot initialization - AOT translation
; Source Z80 bytes from dkong.dat offset 0x0000
; Rule: Z80 source kept as comment behind 68000 code with rationale

        include "../lib/z80_flags.asm"

        section text

L_0000:
        move.b #$00,d0                 ; Z80: ld a,imm8 $00
        ; why: structural reference only; Z80 flags/state are not mapped here.

        move.b d0,$7d84                ; Z80: ld (nn),a $7d84
        ; why: reference memory-map access; production code must use the virtual I/O boundary.

        bra   L_0266                   ; Z80: jp imm16 $0266
        ; why: unconditional structural branch.

; --- Routine at 0x0006 ---
L_0006:
        move.b $6007,d0                ; Z80: ld a,(nn) $6007
        ; why: reference memory access; no Falcon address mapping is implied.

        ror.b #1,d0                    ; Z80: rrca
        ; why: structural rotate only; Z80 flag materialization remains unresolved.

        jsr Z80_RET_NC                 ; Z80: ret nc
        ; why: draft flag boundary; helper is not a complete Z80 return implementation.

        addq.l #1,a7                   ; Z80: inc sp
        ; why: draft only; native A7 is not the emulated Z80 stack.

        addq.l #1,a7                   ; Z80: inc sp
        ; why: draft only; native A7 is not the emulated Z80 stack.

        rts                            ; Z80: ret
        ; why: draft only; Z80 return semantics require the virtual stack.

; End of initial translated routines
