; Double Dragon's sprite MCU (HD63701Y0) as a native routine: its NMI handler's job on the shared RAM, as
; tools/mcu.py (the model, checked against the interpreter by tools/mcu_test.py) does it step for step.
;
; mcu_job: called by main_io_w at a write to $380F; every register kept.  The shared RAM is g_mem+$2000 (the MCU's
; $8000-$81FF), the MCU's own RAM mcu_ram ($40-$13F, a1 = mcu_ram-$40 so that $nn(a1) is its byte $nn), its ROM
; mcu_rom (16 KB: a2 = mcu_rom - $C000, so a2 + an MCU address; the job reads only $C000-$FFFF).  Then $0E3E = 1, as the main CPU's IRQ handler
; would set it (the port takes no IRQ).

	section text,code
mcu_job:
	movem.l d0-d7/a0-a5,-(sp)
	lea g_mem+$2000,a0
	lea mcu_ram-$40,a1
	lea mcu_rom-$C000,a2
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
	movem.l (sp)+,d0-d7/a0-a5
	move.b #1,g_mem+$0E3E
	rts

; $C0A8: a bubble sort of the 8-byte records at $8001 (from offset 1 to the last one before ($8000)) until a pass
; swaps none: a record goes after the next one when its word at +4 is lower (unsigned).  Its result is the stable
; sort by that word, descending: done here as an insertion sort (linear on the nearly sorted lists the game keeps).
; As the MCU leaves them: $4E = the offset its passes end at, $4F = 0 (the swaps' temporary at $40 is overwritten by
; the records' loop, which always follows with two or more records).  d0-d6, a1 (restored).
mcu_sort:
	moveq #0,d0
	move.b (a0),d0			; the end
	beq .r
	moveq #1,d2			; the passes' end: the first offset 1 + 8 k whose next one is at or past the end
.e:	move.b d2,d1
	addq.b #8,d1
	cmp.b d0,d1
	bhs.s .ee
	addq.b #8,d2
	bra.s .e
.ee:	lea mcu_ram-$40,a1
	move.b d2,$4E(a1)
	clr.b $4F(a1)
	moveq #0,d4
	move.b d2,d4
	lsr.w #3,d4			; the last record's index (n - 1)
	beq .r
	moveq #1,d1			; i
.i:	move.w d1,d3
	lsl.w #3,d3
	lea 1(a0,d3.w),a1		; R[i]
	move.b 4(a1),d5
	lsl.w #8,d5
	move.b 5(a1),d5			; its key
	moveq #0,d6
	move.b 4-8(a1),d6
	lsl.w #8,d6
	move.b 5-8(a1),d6
	cmp.w d5,d6
	bhs .in			; (in place: R[i-1] >= its key)
	move.b (a1),sort_tmp
	move.b 1(a1),sort_tmp+1
	move.b 2(a1),sort_tmp+2
	move.b 3(a1),sort_tmp+3
	move.b 4(a1),sort_tmp+4
	move.b 5(a1),sort_tmp+5
	move.b 6(a1),sort_tmp+6
	move.b 7(a1),sort_tmp+7
	move.w d1,d3			; j + 1
.sh:	lea -8(a1),a1			; R[j] -> R[j + 1]
	move.b (a1),8(a1)
	move.b 1(a1),9(a1)
	move.b 2(a1),10(a1)
	move.b 3(a1),11(a1)
	move.b 4(a1),12(a1)
	move.b 5(a1),13(a1)
	move.b 6(a1),14(a1)
	move.b 7(a1),15(a1)
	subq.w #1,d3
	beq.s .put
	moveq #0,d6
	move.b 4-8(a1),d6
	lsl.w #8,d6
	move.b 5-8(a1),d6
	cmp.w d5,d6
	blo.s .sh
.put:	move.b sort_tmp,(a1)
	move.b sort_tmp+1,1(a1)
	move.b sort_tmp+2,2(a1)
	move.b sort_tmp+3,3(a1)
	move.b sort_tmp+4,4(a1)
	move.b sort_tmp+5,5(a1)
	move.b sort_tmp+6,6(a1)
	move.b sort_tmp+7,7(a1)
.in:	addq.w #1,d1
	cmp.w d4,d1
	bls .i
.r:	lea mcu_ram-$40,a1
	rts

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
	beq.s .setup
	st $5A(a1)
	ROM8 d1
	lsl.w #8,d1
	ROM8 d1
	move.w d1,$4C(a1)
; $C189: the parts, in registers: d2 X, d3 the second pointer ($4C), d6 $56 (high word) / $58, d7 the parts left
; ($53) with the record's flags above (16: $4E bit 7 the part byte is $50; 17: $5E bit 7; 18: $52 set; 19: $5A set;
; 20: $54 set, the flip), a3 the $C27F row of the code ($5F), a4 the $C2EB table, a5 the entry at ($4A) (the 75
; entries from $8081 never wrap the 512 bytes).  $48 $4A $4C $53 $60-$64 written back as the MCU leaves them.
.setup:	moveq #0,d7
	move.b $53(a1),d7
	tst.b $4E(a1)
	bpl.s .f1
	bset #16,d7
.f1:	tst.b $5E(a1)
	bpl.s .f2
	bset #17,d7
.f2:	tst.b $52(a1)
	beq.s .f3
	bset #18,d7
.f3:	tst.b $5A(a1)
	beq.s .f4
	bset #19,d7
.f4:	tst.b $54(a1)
	beq.s .f5
	bset #20,d7
.f5:	move.w $56(a1),d6
	swap d6
	move.w $58(a1),d6
	moveq #0,d3
	move.w $4C(a1),d3
	moveq #0,d1
	move.b $5F(a1),d1
	move.b d1,d5
	add.b d1,d1
	add.b d5,d1			; (3 * $5F) & $FF
	lea $C27F(a2),a3
	add.w d1,a3
	lea $C2EB(a2),a4
	move.w $4A(a1),d1
	and.w #$1FF,d1
	lea (a0,d1.w),a5
.part:	btst #16,d7
	beq.s .rd
	move.b $50(a1),d4
	bra.s .got
.rd:	ROM8 d4				; d4 = the part byte
.got:	moveq #$30,d5			; $62 = (a & $0F) | ($C27F + 3 $5F + (a & $30) >> 4)
	and.b d4,d5
	lsr.b #4,d5
	moveq #$0F,d0
	and.b d4,d0
	or.b (a3,d5.w),d0
	moveq #$F0-256,d5
	and.b d0,d5
	cmp.b #$20,d5
	bhs.s .s62
	btst #17,d7
	beq.s .s62
	eor.b #$10,d0
.s62:	move.b d0,2(a5)
	moveq #0,d1			; $61 = ($C2EB + (a >> 6)) ^ $54 | $80
	move.b d4,d1
	lsr.b #6,d1
	move.b (a4,d1.w),d0
	btst #20,d7
	beq.s .nf
	eor.b #8,d0
.nf:	or.b #$80,d0
	move.b $51(a1),d4		; a = ($51); $51 += 1 (+ 1 more for bit 4)
	addq.b #1,$51(a1)
	btst #4,d0
	beq.s .n1
	addq.b #1,$51(a1)
.n1:	btst #18,d7
	bne.s .s63
	ROM8 d4
.s63:	move.b d4,3(a5)
	btst #19,d7
	beq.s .nx1
	exg d2,d3			; (the offsets from the second pointer)
.nx1:	ROM8 d1				; x offset
	btst #20,d7
	beq.s .nneg
	neg.b d1
.nneg:	ext.w d1
	add.w d6,d1
	addq.w #7,d1
	move.w d1,d5
	lsr.w #8,d5
	beq.s .h1
	or.b #$02,d0
.h1:	not.b d1
	move.b d1,4(a5)
	ROM8 d1				; y offset
	ext.w d1
	swap d6
	add.w d6,d1
	swap d6
	subq.w #7,d1
	btst #4,d0
	beq.s .n8
	subq.w #8,d1
.n8:	move.b d1,(a5)
	lsr.w #8,d1
	beq.s .h0
	or.b #$01,d0
.h0:	btst #19,d7
	beq.s .nx2
	exg d2,d3
.nx2:	move.b d0,1(a5)
	addq.l #5,a5
	addq.b #1,$1FD(a0)
	cmp.b #$4B,$1FD(a0)
	bhs.s .done
	subq.b #1,d7
	bne .part
.done:	move.w d2,$48(a1)
	move.w d3,$4C(a1)
	move.b d7,$53(a1)
	move.l a5,d1
	sub.l a0,d1
	add.w #$8000,d1
	move.w d1,$4A(a1)
	move.b -5(a5),$60(a1)
	move.b -4(a5),$61(a1)
	move.b -3(a5),$62(a1)
	move.b -2(a5),$63(a1)
	move.b -1(a5),$64(a1)
.r:	rts

	section bss,bss
mcu_ram:	ds.b $100		; ($40-$13F)
mcu_done_first:	ds.b 1
sort_tmp:	ds.b 8
	even
	section text,code
