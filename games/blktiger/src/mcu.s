; Executes the reset and INT1 code from bd.6k. All firmware-used instructions
; are decoded; any other opcode stops visibly. No timer/serial opcodes are used.
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
mcu_send:
    lea mcu_ram,a0
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
mcu_run:
    lea mcu_ram,a0
    lea mcu_rom,a1
    moveq #0,d3
    move.w mcu_pc,d3
    move #4095,d4
.loop:
    moveq #0,d0
    move.b (a1,d3.w),d0
    addq.w #1,d3
    cmp.b #$02,d0
    beq .ljmp
    cmp.b #$75,d0
    beq .movdi
    cmp.b #$78,d0
    beq .movr0
    cmp.b #$74,d0
    beq .movai
    cmp.b #$f6,d0
    beq .movir0
    cmp.b #$d8,d0
    beq .djnz
    cmp.b #$c2,d0
    beq .clrbit
    cmp.b #$d2,d0
    beq .setbit
    cmp.b #$80,d0
    beq .sjmp
    cmp.b #$e5,d0
    beq .movad
    cmp.b #$54,d0
    beq .anla
    cmp.b #$90,d0
    beq .movdptr
    cmp.b #$93,d0
    beq .movc
    cmp.b #$f5,d0
    beq .movda
    cmp.b #$32,d0
    beq .reti
    jmp z80_unsupported
.ljmp:
    moveq #0,d1
    move.b (a1,d3.w),d1
    addq.w #1,d3
    lsl.w #8,d1
    move.b (a1,d3.w),d1
    move.w d1,d3
    bra .next
.movdi:
    moveq #0,d1
    move.b (a1,d3.w),d1
    addq.w #1,d3
    move.b (a1,d3.w),d2
    addq.w #1,d3
    move.b d2,(a0,d1.w)
    cmp.b #$80,d1
    bne .next
    move.b d2,g_mcu_response
    bra .next
.movr0:
    move.b (a1,d3.w),(a0)
    addq.w #1,d3
    bra .next
.movai:
    move.b (a1,d3.w),$e0(a0)
    addq.w #1,d3
    bra .next
.movir0:
    moveq #0,d1
    move.b (a0),d1
    move.b $e0(a0),(a0,d1.w)
    bra .next
.djnz:
    move.b (a1,d3.w),d1
    addq.w #1,d3
    subq.b #1,(a0)
    beq .next
    ext.w d1
    add.w d1,d3
    bra .next
.clrbit:
    moveq #0,d2
    bra.s .bit
.setbit:
    moveq #1,d2
.bit:
    moveq #0,d1
    move.b (a1,d3.w),d1
    addq.w #1,d3
    move.w d1,d5
    and.w #7,d5
    and.w #$f8,d1
    tst.b d2
    beq.s .clear
    bset d5,(a0,d1.w)
    bra .next
.clear:
    bclr d5,(a0,d1.w)
    bra .next
.sjmp:
    move.b (a1,d3.w),d1
    addq.w #1,d3
    ext.w d1
    add.w d1,d3
    cmp.w #-2,d1
    beq .idle
    bra .next
.movad:
    moveq #0,d1
    move.b (a1,d3.w),d1
    addq.w #1,d3
    cmp.b #$80,d1
    bne.s .ordinary
    move.b mcu_command,$e0(a0)
    bra .next
.ordinary:
    move.b (a0,d1.w),$e0(a0)
    bra .next
.anla:
    move.b (a1,d3.w),d1
    addq.w #1,d3
    and.b d1,$e0(a0)
    bra .next
.movdptr:
    move.b (a1,d3.w),$83(a0)
    addq.w #1,d3
    move.b (a1,d3.w),$82(a0)
    addq.w #1,d3
    bra .next
.movc:
    moveq #0,d1
    move.b $83(a0),d1
    lsl.w #8,d1
    move.b $82(a0),d1
    moveq #0,d2
    move.b $e0(a0),d2
    add.w d2,d1
    move.b (a1,d1.w),$e0(a0)
    bra .next
.movda:
    moveq #0,d1
    move.b (a1,d3.w),d1
    addq.w #1,d3
    move.b $e0(a0),(a0,d1.w)
    cmp.b #$80,d1
    bne .next
    move.b $e0(a0),g_mcu_response
    bra .next
.reti:
    moveq #0,d1
    move.b $81(a0),d1
    moveq #0,d3
    move.b (a0,d1.w),d3
    lsl.w #8,d3
    subq.b #1,d1
    move.b (a0,d1.w),d3
    subq.b #1,d1
    move.b d1,$81(a0)
.next:
    dbf d4,.loop
    jmp z80_unsupported
.idle:
    move.w d3,mcu_pc
    rts
    section bss,bss
mcu_ram: ds.b 256
mcu_pc: ds.w 1
    section text,code
