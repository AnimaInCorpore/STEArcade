; Double Dragon's sprite MCU (HD63701Y0) as a native routine: its NMI handler's job on the shared RAM, as
; tools/mcu.py (the model, checked against the interpreter by tools/mcu_test.py) does it step for step.
;
; mcu_job: called by main_io_w at a write to $380F; every register kept.  The shared RAM is g_mem+$2000 (the MCU's
; $8000-$81FF), the MCU's own RAM mcu_ram ($40-$13F, a1 = mcu_ram-$40 so that $nn(a1) is its byte $nn), its ROM
; mcu_rom64 (a 64 KB image, $FF below $C000: a2 + an MCU address).  Then $0E3E = 1, as the main CPU's IRQ handler
; would set it (the port takes no IRQ).

	section text,code
mcu_job:
	movem.l d0-d7/a0-a2,-(sp)
	lea g_mem+$2000,a0
	lea mcu_ram-$40,a1
	lea mcu_rom64,a2
	tst.b mcu_done_first
	bne.s .later
	st mcu_done_first		; the first job: the ROM's sum into $8000
	move.b #MCU_SUM,(a0)
	move.b #1,$66(a1)
	bra .out
.later:
	bsr mcu_sort
	moveq #1,d2			; $4F: the record's offset (a byte)
	moveq #1,d3			; X - $8000
.rec:	cmp.b (a0),d2			; (cmpa $8000; bcc: done when the offset >= the end)
	bhs.s .end
	move.b 0(a0,d3.w),$40(a1)
	move.b 1(a0,d3.w),$41(a1)
	move.b 2(a0,d3.w),$42(a1)
	move.b 3(a0,d3.w),$43(a1)
	move.b 4(a0,d3.w),$44(a1)
	move.b 5(a0,d3.w),$45(a1)
	move.b 6(a0,d3.w),$46(a1)
	move.b 7(a0,d3.w),$47(a1)
	move.b d2,$4F(a1)
	moveq #$7F,d0
	and.b 1(a0,d3.w),d0
	cmp.b #$7F,d0
	beq.s .skip
	movem.l d2-d3,-(sp)
	bsr mcu_expand
	movem.l (sp)+,d2-d3
.skip:	addq.w #8,d3
	and.w #$1FF,d3
	addq.b #8,d2
	bra.s .rec
.end:	move.b d2,$4F(a1)
	clr.b (a0)
.out:	or.b #3,$65(a1)			; (port 6: the main CPU's IRQ raised, its own NMI released)
	movem.l (sp)+,d0-d7/a0-a2
	move.b #1,g_mem+$0E3E
	rts

; $C0A8: bubble sort of the 8-byte records at $8001 until a pass swaps none; a record goes after the next one when its
; word at +4 is lower.  d2 = the offset $4E, d4 = the swaps $4F.
mcu_sort:
	tst.b (a0)
	beq.s .r
.pass:	moveq #0,d4
	moveq #1,d2
.in:	move.b d2,d0
	addq.b #8,d0
	cmp.b (a0),d0
	bhs.s .endp
	moveq #0,d3
	move.b d2,d3
	moveq #0,d5
	move.b 4(a0,d3.w),d5
	lsl.w #8,d5
	move.b 5(a0,d3.w),d5
	moveq #0,d6
	move.b 12(a0,d3.w),d6
	lsl.w #8,d6
	move.b 13(a0,d3.w),d6
	cmp.w d6,d5
	bhs.s .no
	lea 0(a0,d3.w),a1		; (a1 borrowed: the record)
	moveq #8-1,d6
.sw:	move.b (a1),d5
	move.b 8(a1),(a1)+
	move.b d5,7(a1)
	dbf d6,.sw
	lea mcu_ram-$40,a1
	move.b 14(a0,d3.w),$40(a1)	; (its temporary: the last word swapped)
	move.b 15(a0,d3.w),$41(a1)
	addq.b #1,d4
.no:	addq.b #8,d2
	bra.s .in
.endp:	move.b d2,$4E(a1)
	move.b d4,$4F(a1)
	tst.b d4
	bne.s .pass
.r:	rts

; rom8: d7.b = the ROM byte at d2.w (the MCU address), d2 += 1 (16 bits)
ROM8	macro
	move.b (a2,d2.l),\1
	addq.w #1,d2
	endm

; $C10B: one record ($40-$47) into sprite entries.  d2 = X (16 bits, the upper word 0).
mcu_expand:
	cmp.b #$4B,$1FD(a0)
	bhs .r
	moveq #0,d2
	move.w $44(a1),d0		; $56 = ($44) + ($46) - ($81FB)
	add.w $46(a1),d0
	move.b $1FB(a0),d1
	lsl.w #8,d1
	move.b $1FC(a0),d1
	sub.w d1,d0
	move.w d0,$56(a1)
	move.w $42(a1),d0		; $58 = ($42) - ($81F9)
	move.b $1F9(a0),d1
	lsl.w #8,d1
	move.b $1FA(a0),d1
	sub.w d1,d0
	move.w d0,$58(a1)
	move.b $41(a1),d0
	lsr.b #4,d0
	and.b #8,d0
	move.b d0,$54(a1)		; the flip flag
	move.b $40(a1),d0
	move.b d0,$5E(a1)
	and.b #$7F,d0
	move.b d0,$5F(a1)
	moveq #0,d1			; X = ($C2EF + 2 * $5F), then (X + 2 * ($41 & $7F))
	move.b d0,d1
	add.w d1,d1
	add.w #$C2EF,d1
	move.b (a2,d1.l),d2
	lsl.w #8,d2
	move.b 1(a2,d1.l),d2
	moveq #$7F,d1
	and.b $41(a1),d1
	add.w d1,d1
	add.w d2,d1
	moveq #0,d2
	move.b (a2,d1.l),d2
	lsl.w #8,d2
	addq.w #1,d1
	move.b (a2,d1.l),d2
	move.w d2,$48(a1)
	moveq #0,d0			; $4A = $8081 + ($81FD) * 5
	move.b $1FD(a0),d0
	mulu #5,d0
	add.w #$8081,d0
	move.w d0,$4A(a1)
	ROM8 d0				; the list's head byte
	clr.b $50(a1)
	clr.b $52(a1)
	clr.b $5A(a1)
	move.b d0,$4E(a1)
	moveq #$1F,d1
	and.b d0,d1
	move.b d1,$53(a1)
	tst.b d0
	bpl.s .n50
	ROM8 $50(a1)
.n50:	btst #6,d0
	beq.s .n51
	ROM8 $51(a1)
	st $52(a1)
.n51:	btst #5,d0
	beq.s .part
	st $5A(a1)
	ROM8 d1
	lsl.w #8,d1
	ROM8 d1
	move.w d1,$4C(a1)
.part:					; $C189: one part
	tst.b $4E(a1)
	bpl.s .rd
	move.b $50(a1),d4
	bra.s .got
.rd:	ROM8 d4
.got:	move.w d2,$48(a1)		; d4 = the part byte
	moveq #0,d1			; $C27F + ((3 * $5F) & $FF) + ((a & $30) >> 4)
	move.b $5F(a1),d1
	move.b d1,d5
	add.b d1,d1
	add.b d5,d1
	moveq #$30,d5
	and.b d4,d5
	lsr.b #4,d5
	add.w d5,d1
	add.w #$C27F,d1
	moveq #$0F,d0
	and.b d4,d0
	or.b (a2,d1.l),d0		; $62
	moveq #$F0-256,d5
	and.b d0,d5
	cmp.b #$20,d5
	bhs.s .s62
	tst.b $5E(a1)
	bpl.s .s62
	eor.b #$10,d0
.s62:	move.b d0,$62(a1)
	moveq #0,d1			; $61 = (($C2EB + (a >> 6)) ^ $54) | $80
	move.b d4,d1
	lsr.b #6,d1
	add.w #$C2EB,d1
	move.b (a2,d1.l),d0
	move.w $48(a1),d2
	move.b $54(a1),d5
	eor.b d5,d0
	or.b #$80,d0
	move.b d0,$61(a1)
	move.b $51(a1),d4		; a = ($51); $51 += 1 (+ 1 more for bit 4)
	addq.b #1,$51(a1)
	btst #4,d0
	beq.s .n1
	addq.b #1,$51(a1)
.n1:	tst.b $52(a1)
	bne.s .s63
	ROM8 d4
.s63:	move.b d4,$63(a1)
	tst.b $5A(a1)
	bpl.s .nx1
	move.w d2,$48(a1)
	move.w $4C(a1),d2
.nx1:	ROM8 d1				; x offset
	btst #3,$54(a1)
	beq.s .nneg
	neg.b d1
.nneg:	ext.w d1
	add.w $58(a1),d1
	addq.w #7,d1
	move.w d1,d5
	lsr.w #8,d5
	beq.s .h1
	or.b #$02,$61(a1)
.h1:	not.b d1
	move.b d1,$64(a1)
	ROM8 d1				; y offset
	ext.w d1
	add.w $56(a1),d1
	subq.w #7,d1
	move.b d1,$60(a1)
	btst #4,$61(a1)
	beq.s .n8
	subq.w #8,d1
	move.b d1,$60(a1)
.n8:	move.w d1,d5
	lsr.w #8,d5
	beq.s .h0
	or.b #$01,$61(a1)
.h0:	tst.b $5A(a1)
	bpl.s .nx2
	move.w d2,$4C(a1)
	move.w $48(a1),d2
.nx2:	move.w d2,$48(a1)
	move.w $4A(a1),d1		; the entry at ($4A)
	and.w #$1FF,d1
	moveq #5-1,d5
	lea $60(a1),a1
.wr:	move.b (a1)+,(a0,d1.w)
	addq.w #1,d1
	and.w #$1FF,d1
	dbf d5,.wr
	lea mcu_ram-$40,a1
	addq.w #5,$4A(a1)
	addq.b #1,$1FD(a0)
	cmp.b #$4B,$1FD(a0)
	bhs.s .r
	subq.b #1,$53(a1)
	bne .part
.r:	rts

	section bss,bss
mcu_ram:	ds.b $100		; ($40-$13F)
mcu_done_first:	ds.b 1
	even
	section text,code
