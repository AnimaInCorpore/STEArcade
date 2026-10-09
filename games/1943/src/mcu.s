; The i8751 of 1943: the dumped firmware (mcu.rom) translated to 68000 code by tools/mcux.py (mcu_code.s), run at reset
; and at each VBL INT1.  a0 = the internal RAM and SFRs (256 bytes), a1 = the ROM.  The SFRs that matter: P0 ($80, the
; command latch AND the port's output latch on a read), P3 ($b0: a falling edge of bit 6 copies P0 to the reply latch
; g_mcu_response), PSW ($d0: the register bank, CY, AC, OV; the parity bit is made exact where PSW is read and at the
; end of a run), ACC ($e0), DPTR ($82/$83).  The callers keep their registers (the hook saves them all).

mcu_init:
    lea mcu_ram,a0
    move #63,d0
.clear:
    clr.l (a0)+
    dbf d0,.clear
    lea mcu_ram,a0
    move.b #7,$81(a0)
    move.b #$ff,$80(a0)
    move.b #$ff,$90(a0)
    move.b #$ff,$a0(a0)
    move.b #$ff,$b0(a0)
    lea mcu_rom,a1
    move.b $e0(a0),d0              ; (ACC: d0 in the translated code)
    bra M0000                      ; (to the idle loop; its rts returns from here)

; INT1 (the VBL): push the pc (the idle loop), run from $0013 to the idle loop again.
mcu_vblank:
    lea mcu_ram,a0
    move.b $a8(a0),d0
    and.b #$84,d0
    cmp.b #$84,d0
    bne.s .off
    moveq #0,d0
    move.b $81(a0),d0
    addq.b #1,d0
    move.w mcu_pc,d1
    move.b d1,(a0,d0.w)
    addq.b #1,d0
    lsr.w #8,d1
    move.b d1,(a0,d0.w)
    move.b d0,$81(a0)
    lea mcu_rom,a1
    move.b $e0(a0),d0
    bra M0013
.off:
    jmp z80_unsupported            ; (INT1 not enabled: the firmware is not where it should be)

; reti: d1 = the popped return address
mcu_reti:
    moveq #0,d3
    move.b $81(a0),d3
    moveq #0,d1
    move.b (a0,d3.w),d1
    lsl.w #8,d1
    subq.b #1,d3
    move.b (a0,d3.w),d1
    subq.b #1,d3
    move.b d3,$81(a0)
    rts

; d2 = the new P3: its bit 6 falling latches P0 as the reply
mcu_p3:
    btst #6,$b0(a0)
    beq.s .store
    btst #6,d2
    bne.s .store
    move.b $80(a0),g_mcu_response
    addq.w #1,mcu_transactions
.store:
    move.b d2,$b0(a0)
    rts

; PSW bit 0 = the parity of ACC (the 8051 keeps it so after every instruction).  Uses d2 and a3.
mcu_parity:
    moveq #0,d2
    move.b $e0(a0),d2
    lea mcu_partab(pc),a3
    move.b (a3,d2.w),d2
    bclr #0,$d0(a0)
    or.b d2,$d0(a0)
    rts

mcu_partab:
    rept 256
PB set REPTN
PB set (PB&1)+((PB>>1)&1)+((PB>>2)&1)+((PB>>3)&1)+((PB>>4)&1)+((PB>>5)&1)+((PB>>6)&1)+((PB>>7)&1)
    dc.b PB&1
    endr
    even
    include "mcu_code.s"
    section bss,bss
mcu_ram: ds.b 256
mcu_pc: ds.w 1
mcu_transactions: ds.w 1
    section text,code
