; The i8751 of 1943: the dumped firmware (mcu.rom) run at reset and at each VBL INT1, the same instructions as
; tools/mcu.py (any other opcode stops at z80_unsupported).  a0 = the internal RAM and SFRs (256 bytes), a1 = the
; ROM, d3 = pc, d4 = the instruction budget.  The SFRs that matter: P0 ($80, the command latch AND the port's
; output latch on a read), P3 ($b0: a falling edge of bit 6 copies P0 to the reply latch g_mcu_response), PSW
; ($d0: the register bank, CY, AC, OV; the parity bit is made exact where PSW is read), ACC ($e0), DPTR ($82/$83).
; Registers: everything but d0-d7/a0-a6 of the caller is kept (mcu_vblank saves them all).

mcu_init:
    lea mcu_ram,a0
    move #63,d0
.clear:
    clr.l (a0)+
    dbf d0,.clear
    move.b #7,mcu_ram+$81
    move.b #$ff,mcu_ram+$80
    move.b #$ff,mcu_ram+$90
    move.b #$ff,mcu_ram+$a0
    move.b #$ff,mcu_ram+$b0
    clr.w mcu_pc
    bra mcu_run

; INT1 (the VBL): push the pc, run from $0013 to the idle loop.
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
    move.w #$13,mcu_pc
    bra.s mcu_run
.off:
    jmp z80_unsupported            ; (INT1 not enabled: the firmware is not where it should be)

mcu_run:
    lea mcu_ram,a0
    lea mcu_rom,a1
    lea mcu_ops(pc),a2
    moveq #0,d3
    move.w mcu_pc,d3
    move #4095,d4
mcu_next:
    subq.w #1,d4
    bmi.s .budget
    moveq #0,d7
    move.b (a1,d3.l),d7            ; (d7 = the opcode for the handlers)
    addq.w #1,d3
    move.w d7,d0
    add.w d0,d0
    move.w (a2,d0.w),d0
    jmp (a2,d0.w)
.budget:
    jmp z80_unsupported            ; (did not reach the idle loop)

; operand fetch: d1 = the next byte (upper bits 0)
fetch macro
    moveq #0,\1
    move.b (a1,d3.l),\1
    addq.w #1,d3
    endm
; d1 = the address of register Rn (n = the low 3 bits of the opcode in d7), in the bank of PSW bits 3-4
regaddr macro
    move.b $d0(a0),\1
    and.w #$18,\1
    add.w d7,\1
    endm
opcode macro
    and.w #\1,d7
    endm

; write the byte d2 to the direct address d1 (P3's falling edge of bit 6 latches P0 as the reply)
mcu_write:
    cmp.b #$b0,d1
    beq.s .p3
    move.b d2,(a0,d1.w)
    rts
.p3:
    btst #6,$b0(a0)
    beq.s .store
    btst #6,d2
    bne.s .store
    move.b $80(a0),g_mcu_response
    addq.w #1,mcu_transactions
.store:
    move.b d2,$b0(a0)
    rts
; d2 = the byte at the direct address d1 as the program reads it (P0 = the command AND its latch; PSW with parity)
mcu_read:
    cmp.b #$80,d1
    beq.s .p0
    cmp.b #$d0,d1
    beq.s .psw
    move.b (a0,d1.w),d2
    rts
.p0:
    move.b mcu_command,d2
    and.b $80(a0),d2
    rts
.psw:
    bsr.s mcu_parity
    move.b $d0(a0),d2
    rts
; PSW bit 0 = the parity of ACC (the 8051 keeps it so after every instruction)
mcu_parity:                        ; (uses d2 and a3 only)
    moveq #0,d2
    move.b $e0(a0),d2
    lea mcu_partab(pc),a3
    move.b (a3,d2.w),d2
    bclr #0,$d0(a0)
    or.b d2,$d0(a0)
    rts

op_nop:                            ; 00
    bra mcu_next
op_ljmp:                           ; 02 hi lo
    fetch d1
    lsl.w #8,d1
    move.b (a1,d3.l),d1
    move.l d1,d3
    bra mcu_next
op_mov_dir_imm:                    ; 75 dir,#
    fetch d1
    move.b (a1,d3.l),d2
    addq.w #1,d3
    bsr mcu_write
    bra mcu_next
op_mov_r_imm:                      ; 78-7f Rn,#
    opcode 7
    regaddr d1
    move.b (a1,d3.l),(a0,d1.w)
    addq.w #1,d3
    bra mcu_next
op_mov_a_imm:                      ; 74 A,#
    move.b (a1,d3.l),$e0(a0)
    addq.w #1,d3
    bra mcu_next
op_mov_ind_a:                      ; f6/f7 @Ri,A
    opcode 1
    regaddr d1
    moveq #0,d2
    move.b (a0,d1.w),d2
    move.b $e0(a0),(a0,d2.w)
    bra mcu_next
op_mov_dir_a:                      ; f5 dir,A
    fetch d1
    move.b $e0(a0),d2
    bsr mcu_write
    bra mcu_next
op_clr_a:                          ; e4
    clr.b $e0(a0)
    bra mcu_next
op_mov_a_r:                        ; e8-ef A,Rn
    opcode 7
    regaddr d1
    move.b (a0,d1.w),$e0(a0)
    bra mcu_next
op_mov_r_a:                        ; f8-ff Rn,A
    opcode 7
    regaddr d1
    move.b $e0(a0),(a0,d1.w)
    bra mcu_next
op_mov_a_dir:                      ; e5 A,dir
    fetch d1
    bsr mcu_read
    move.b d2,$e0(a0)
    bra mcu_next
op_mov_r_dir:                      ; a8-af Rn,dir
    fetch d1
    bsr mcu_read
    opcode 7
    regaddr d1
    move.b d2,(a0,d1.w)
    bra mcu_next
op_mov_dir_r:                      ; 88-8f dir,Rn
    opcode 7
    regaddr d2
    move.b (a0,d2.w),d2
    fetch d1
    bsr mcu_write
    bra mcu_next
op_clr_bit:                        ; c2 bit
    fetch d1
    moveq #7,d5
    and.w d1,d5
    bsr.s bitaddr
    cmp.b #$d0,d1
    bne.s .plain
    bsr mcu_parity
.plain:
    move.b (a0,d1.w),d2
    bclr d5,d2
    bsr mcu_write
    bra mcu_next
op_setb_bit:                       ; d2 bit
    fetch d1
    moveq #7,d5
    and.w d1,d5
    bsr.s bitaddr
    cmp.b #$d0,d1
    bne.s .plain
    bsr mcu_parity
.plain:
    move.b (a0,d1.w),d2
    bset d5,d2
    bsr mcu_write
    bra mcu_next
; d1 = the bit address -> the byte's direct address
bitaddr:
    cmp.w #128,d1
    bhs.s .sfr
    lsr.w #3,d1
    add.w #$20,d1
    rts
.sfr:
    and.w #$f8,d1
    rts
op_anl_dir_imm:                    ; 53 dir,#
    fetch d1
    cmp.b #$d0,d1
    bne.s .plain
    bsr mcu_parity
.plain:
    move.b (a0,d1.w),d2
    and.b (a1,d3.l),d2
    addq.w #1,d3
    bsr mcu_write
    bra mcu_next
op_clr_c:                          ; c3
    bclr #7,$d0(a0)
    bra mcu_next
op_inc_dir:                        ; 05 dir
    fetch d1
    cmp.b #$d0,d1
    bne.s .plain
    bsr mcu_parity
.plain:
    move.b (a0,d1.w),d2
    addq.b #1,d2
    bsr mcu_write
    bra mcu_next
op_movc:                           ; 93 A,@A+DPTR
    moveq #0,d1
    move.b $83(a0),d1
    lsl.w #8,d1
    move.b $82(a0),d1
    moveq #0,d2
    move.b $e0(a0),d2
    add.l d2,d1
    move.b (a1,d1.l),$e0(a0)
    bra mcu_next
op_subb_r2:                        ; 9a A,R2: CY, AC, OV as tools/mcu.py
    moveq #2,d7
    regaddr d1
    moveq #0,d2
    move.b (a0,d1.w),d2            ; b
    moveq #0,d1
    move.b $e0(a0),d1              ; a
    moveq #0,d5
    btst #7,$d0(a0)
    beq.s .nc
    moveq #1,d5                    ; carry
.nc:
    move.b $d0(a0),d7
    and.b #$3b,d7                  ; (~$c4)
    move.w d1,d0
    sub.w d2,d0
    sub.w d5,d0                    ; result (negative: borrow)
    bpl.s .cy
    bset #7,d7
.cy:
    move.w d1,a3
    and.w #15,d1
    move.w d2,-(sp)
    and.w #15,d2
    add.w d5,d2
    cmp.w d2,d1
    bhs.s .ac
    bset #6,d7
.ac:
    move.w (sp)+,d2
    move.w a3,d1
    eor.b d1,d2                    ; a ^ b
    eor.b d0,d1                    ; a ^ result
    and.b d1,d2
    bpl.s .ov
    bset #2,d7
.ov:
    move.b d7,$d0(a0)
    move.b d0,$e0(a0)
    bra mcu_next
op_jnz:                            ; 70 rel
    move.b (a1,d3.l),d1
    addq.w #1,d3
    tst.b $e0(a0)
    beq mcu_next
    ext.w d1
    add.w d1,d3
    bra mcu_next
op_djnz_r:                         ; d8-df Rn,rel
    opcode 7
    regaddr d1
    move.b (a1,d3.l),d2
    addq.w #1,d3
    subq.b #1,(a0,d1.w)
    beq mcu_next
    ext.w d2
    add.w d2,d3
    bra mcu_next
op_sjmp:                           ; 80 rel (to itself: the idle loop, the end of a run)
    move.b (a1,d3.l),d1
    addq.w #1,d3
    ext.w d1
    add.w d1,d3
    cmp.w #-2,d1
    beq.s .idle
    bra mcu_next
.idle:
    move.w d3,mcu_pc
    bsr mcu_parity
    rts
op_reti:                           ; 32
    moveq #0,d1
    move.b $81(a0),d1
    moveq #0,d3
    move.b (a0,d1.w),d3
    lsl.w #8,d3
    subq.b #1,d1
    move.b (a0,d1.w),d3
    subq.b #1,d1
    move.b d1,$81(a0)
    bra mcu_next
op_bad:
    subq.w #1,d3
    move.l d3,d7
    jmp z80_unsupported

mcu_ops:                           ; (the handler of each opcode, op_bad: not used by the firmware)
    dc.w op_nop-mcu_ops,op_bad-mcu_ops,op_ljmp-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_inc_dir-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops   ; 00
    dc.w op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops   ; 08
    dc.w op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops   ; 10
    dc.w op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops   ; 18
    dc.w op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops   ; 20
    dc.w op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops   ; 28
    dc.w op_bad-mcu_ops,op_bad-mcu_ops,op_reti-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops   ; 30
    dc.w op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops   ; 38
    dc.w op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops   ; 40
    dc.w op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops   ; 48
    dc.w op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_anl_dir_imm-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops   ; 50
    dc.w op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops   ; 58
    dc.w op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops   ; 60
    dc.w op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops   ; 68
    dc.w op_jnz-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_mov_a_imm-mcu_ops,op_mov_dir_imm-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops   ; 70
    dc.w op_mov_r_imm-mcu_ops,op_mov_r_imm-mcu_ops,op_mov_r_imm-mcu_ops,op_mov_r_imm-mcu_ops,op_mov_r_imm-mcu_ops,op_mov_r_imm-mcu_ops,op_mov_r_imm-mcu_ops,op_mov_r_imm-mcu_ops   ; 78
    dc.w op_sjmp-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops   ; 80
    dc.w op_mov_dir_r-mcu_ops,op_mov_dir_r-mcu_ops,op_mov_dir_r-mcu_ops,op_mov_dir_r-mcu_ops,op_mov_dir_r-mcu_ops,op_mov_dir_r-mcu_ops,op_mov_dir_r-mcu_ops,op_mov_dir_r-mcu_ops   ; 88
    dc.w op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_movc-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops   ; 90
    dc.w op_bad-mcu_ops,op_bad-mcu_ops,op_subb_r2-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops   ; 98
    dc.w op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops   ; a0
    dc.w op_mov_r_dir-mcu_ops,op_mov_r_dir-mcu_ops,op_mov_r_dir-mcu_ops,op_mov_r_dir-mcu_ops,op_mov_r_dir-mcu_ops,op_mov_r_dir-mcu_ops,op_mov_r_dir-mcu_ops,op_mov_r_dir-mcu_ops   ; a8
    dc.w op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops   ; b0
    dc.w op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops   ; b8
    dc.w op_bad-mcu_ops,op_bad-mcu_ops,op_clr_bit-mcu_ops,op_clr_c-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops   ; c0
    dc.w op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops   ; c8
    dc.w op_bad-mcu_ops,op_bad-mcu_ops,op_setb_bit-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops   ; d0
    dc.w op_djnz_r-mcu_ops,op_djnz_r-mcu_ops,op_djnz_r-mcu_ops,op_djnz_r-mcu_ops,op_djnz_r-mcu_ops,op_djnz_r-mcu_ops,op_djnz_r-mcu_ops,op_djnz_r-mcu_ops   ; d8
    dc.w op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_clr_a-mcu_ops,op_mov_a_dir-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops   ; e0
    dc.w op_mov_a_r-mcu_ops,op_mov_a_r-mcu_ops,op_mov_a_r-mcu_ops,op_mov_a_r-mcu_ops,op_mov_a_r-mcu_ops,op_mov_a_r-mcu_ops,op_mov_a_r-mcu_ops,op_mov_a_r-mcu_ops   ; e8
    dc.w op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_bad-mcu_ops,op_mov_dir_a-mcu_ops,op_mov_ind_a-mcu_ops,op_mov_ind_a-mcu_ops   ; f0
    dc.w op_mov_r_a-mcu_ops,op_mov_r_a-mcu_ops,op_mov_r_a-mcu_ops,op_mov_r_a-mcu_ops,op_mov_r_a-mcu_ops,op_mov_r_a-mcu_ops,op_mov_r_a-mcu_ops,op_mov_r_a-mcu_ops   ; f8
mcu_partab:
    rept 256
PB set REPTN
PB set (PB&1)+((PB>>1)&1)+((PB>>2)&1)+((PB>>3)&1)+((PB>>4)&1)+((PB>>5)&1)+((PB>>6)&1)+((PB>>7)&1)
    dc.b PB&1
    endr
    even
    section bss,bss
mcu_ram: ds.b 256
mcu_pc: ds.w 1
mcu_transactions: ds.w 1
    section text,code
